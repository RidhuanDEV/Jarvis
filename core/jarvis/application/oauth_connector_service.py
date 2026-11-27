"""Opt-In Read-Only OAuth 2.0 PKCE Calendar & Email Connector Service (Stage G7, B26, FR-LIF-04).

Strict invariants:
- Disabled by default; requires explicit per-connector owner consent (`consent_acknowledged=True`).
- RFC 7636 PKCE (`S256`) + RFC 8252 loopback redirect URI (`http://127.0.0.1:<port>/callback`) + single-use CSRF state (300s TTL).
- Strictly read-only scopes verified BOTH before authorization redirect AND on the token-endpoint response
  (prevents silent provider scope escalation to write/send/delete).
- OAuth access/refresh tokens stored ONLY in `SecretVaultAndCryptoPort` (`vault_ref`); NEVER stored in SQLite or logs.
- All external HTTP requests validated against upfront DNS anti-SSRF (`SafeWebFetchClient`), `follow_redirects=False`, `trust_env=False`.
- Offline degradation honors `offline_mode=True` (serves labeled stale read-only cache or returns `ErrorCode.OFFLINE`).
- Imported external content marks the session untrusted (`BR-15`) and sanitizes HTML/injection boundary tags.
"""

from __future__ import annotations

import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal
from urllib.parse import urlencode

import httpx

from jarvis.application.config_service import ConfigService
from jarvis.application.context_service import ContextAssemblerService
from jarvis.application.personal_life_service import CalendarEventRecord, PersonalLifeService
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.oauth_pkce import (
    compute_pkce_s256_challenge,
    generate_pkce_verifier,
    hash_pkce_verifier,
    validate_oauth_https_endpoint,
    validate_oauth_loopback_redirect_uri,
    validate_readonly_oauth_scopes,
)
from jarvis.domain.ports import ClockPort, SecretVaultAndCryptoPort
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.web_fetch import DnsResolverFn, SafeWebFetchClient, WebFetchSecurityError
from jarvis.infrastructure.web_search_provider import sanitize_untrusted_web_text

PKCE_STATE_TTL_SECONDS = 300
OAUTH_HTTP_TIMEOUT_SECONDS = 10.0


class OAuthConnectorError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class OAuthStartResult(StrictModel):
    connector_id: str
    kind: Literal["oauth_calendar", "oauth_mail"]
    state_nonce: str
    authorization_url: str
    code_challenge: str
    code_challenge_method: Literal["S256"] = "S256"
    code_verifier: str
    scopes: tuple[str, ...]
    expires_at: datetime


class OAuthConnectorView(StrictModel):
    id: str
    kind: Literal["oauth_calendar", "oauth_mail"]
    display_name: str
    endpoint_url: str
    allowed_scopes: tuple[str, ...]
    consent_acknowledged: bool
    enabled: bool
    revoked_at: datetime | None = None
    updated_at: datetime


class ReadOnlyMailHeader(StrictModel):
    external_id: str
    sender: str
    subject: str
    received_at: str
    snippet: str
    is_stale: bool = False


class OAuthReadOnlyConnectorService:
    """Manages opt-in read-only OAuth 2.0 PKCE calendar/email connectors with vault token isolation & offline fallback."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        vault: SecretVaultAndCryptoPort,
        life_service: PersonalLifeService,
        clock: ClockPort,
        *,
        context_service: ContextAssemblerService | None = None,
        dns_resolver: DnsResolverFn | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._db = db
        self._config = config_service
        self._vault = vault
        self._life = life_service
        self._clock = clock
        self._context_service = context_service
        self._transport = transport
        self._ssrf = SafeWebFetchClient(clock, dns_resolver=dns_resolver, transport=transport)
        self._mail_cache: dict[str, list[ReadOnlyMailHeader]] = {}

    def start_pkce_authorization(
        self,
        *,
        connector_id: str,
        kind: Literal["oauth_calendar", "oauth_mail"],
        provider_name: str,
        authorize_url: str,
        token_url: str,
        api_base_url: str,
        redirect_uri: str,
        client_id: str,
        scopes: tuple[str, ...],
        consent_acknowledged: bool,
        correlation_id: str,
    ) -> OAuthStartResult:
        if not consent_acknowledged:
            raise OAuthConnectorError(
                ErrorCode.APPROVAL_REQUIRED,
                "Explicit per-connector consent acknowledging read-only cloud data access is required (FR-LIF-04).",
            )
        clean_id = connector_id.strip().lower()
        if len(clean_id) < 3 or len(clean_id) > 64:
            raise OAuthConnectorError(ErrorCode.INVALID_ARGS, "connector_id must be 3..64 characters.")

        scope_verdict = validate_readonly_oauth_scopes(scopes, connector_kind=kind)
        if not scope_verdict.allowed:
            raise OAuthConnectorError(scope_verdict.error_code or ErrorCode.DENIED, scope_verdict.reason)

        redir_ok, redir_reason = validate_oauth_loopback_redirect_uri(redirect_uri)
        if not redir_ok:
            raise OAuthConnectorError(ErrorCode.DENIED, redir_reason)

        for label, url in (
            ("authorize_url", authorize_url),
            ("token_url", token_url),
            ("api_base_url", api_base_url),
        ):
            ok, reason = validate_oauth_https_endpoint(url)
            if not ok:
                raise OAuthConnectorError(ErrorCode.DENIED, f"{label}: {reason}")

        verifier = generate_pkce_verifier(64)
        challenge = compute_pkce_s256_challenge(verifier)
        state_nonce = secrets.token_urlsafe(24)
        now = self._clock.now_utc()
        expires = now + timedelta(seconds=PKCE_STATE_TTL_SECONDS)

        query = urlencode(
            {
                "response_type": "code",
                "client_id": client_id.strip(),
                "redirect_uri": redirect_uri.strip(),
                "scope": " ".join(scope_verdict.normalized_scopes),
                "state": state_nonce,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        sep = "&" if "?" in authorize_url else "?"
        auth_url = f"{authorize_url.strip()}{sep}{query}"

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO oauth_pkce_state(
                    state_nonce, connector_id, kind, provider_name, authorize_url, token_url, api_base_url,
                    redirect_uri, client_id, requested_scopes_json, code_verifier_hash, expires_at, consumed_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    state_nonce,
                    clean_id,
                    kind,
                    provider_name.strip(),
                    authorize_url.strip(),
                    token_url.strip(),
                    api_base_url.strip().rstrip("/"),
                    redirect_uri.strip(),
                    client_id.strip(),
                    json.dumps(list(scope_verdict.normalized_scopes)),
                    hash_pkce_verifier(verifier),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="oauth.pkce.started",
                outcome="completed",
                meta={
                    "connector_id": clean_id,
                    "kind": kind,
                    "provider_name": provider_name.strip(),
                    "scopes": list(scope_verdict.normalized_scopes),
                },
                now_iso=now.isoformat(),
            )

        return OAuthStartResult(
            connector_id=clean_id,
            kind=kind,
            state_nonce=state_nonce,
            authorization_url=auth_url,
            code_challenge=challenge,
            code_verifier=verifier,
            scopes=scope_verdict.normalized_scopes,
            expires_at=expires,
        )

    async def complete_pkce_callback(
        self,
        *,
        state_nonce: str,
        authorization_code: str,
        code_verifier: str,
        correlation_id: str,
    ) -> OAuthConnectorView:
        cfg = self._config.get_active().document
        if cfg.ai.offline_mode:
            raise OAuthConnectorError(
                ErrorCode.OFFLINE,
                "Offline mode is active; OAuth PKCE token exchange is blocked (BR-16).",
            )
        clean_code = authorization_code.strip()
        if not clean_code:
            raise OAuthConnectorError(ErrorCode.INVALID_ARGS, "authorization_code cannot be empty.")

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT * FROM oauth_pkce_state WHERE state_nonce = ?",
                (state_nonce.strip(),),
            ).fetchone()

        if row is None:
            raise OAuthConnectorError(ErrorCode.DENIED, "Unknown or forged OAuth CSRF state nonce.")
        if row["consumed_at"] is not None:
            raise OAuthConnectorError(ErrorCode.APPROVAL_EXPIRED, "OAuth PKCE state nonce was already consumed (replay blocked).")
        if now >= datetime.fromisoformat(str(row["expires_at"])):
            raise OAuthConnectorError(ErrorCode.APPROVAL_EXPIRED, "OAuth PKCE authorization state expired.")
        if not hmac.compare_digest(str(row["code_verifier_hash"]), hash_pkce_verifier(code_verifier.strip())):
            raise OAuthConnectorError(ErrorCode.DENIED, "PKCE code_verifier does not match initiated challenge.")

        token_url = str(row["token_url"])
        kind = str(row["kind"])
        connector_id = str(row["connector_id"])
        requested_scopes = tuple(str(s) for s in json.loads(str(row["requested_scopes_json"])))

        # Upfront DNS-resolved anti-SSRF validation before calling token endpoint
        try:
            pinned_ip = self._ssrf.validate_and_resolve_url(token_url, require_https=True)
        except WebFetchSecurityError as exc:
            raise OAuthConnectorError(exc.code, str(exc)) from exc

        use_pinned = self._transport is None
        req_url, headers, extensions = SafeWebFetchClient._build_pinned_request_params(
            token_url, pinned_ip, use_pinned_socket=use_pinned
        )
        headers["Accept"] = "application/json"

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=OAUTH_HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = await client.post(
                    req_url,
                    data={
                        "grant_type": "authorization_code",
                        "code": clean_code,
                        "redirect_uri": str(row["redirect_uri"]),
                        "client_id": str(row["client_id"]),
                        "code_verifier": code_verifier.strip(),
                    },
                    headers=headers,
                    extensions=extensions,
                )
        except httpx.HTTPError as exc:
            raise OAuthConnectorError(
                ErrorCode.RUNTIME_UNAVAILABLE, f"OAuth token endpoint unreachable: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise OAuthConnectorError(
                ErrorCode.DENIED, f"OAuth token exchange rejected with HTTP {resp.status_code}."
            )
        token_payload = resp.json()
        if not isinstance(token_payload, dict) or not str(token_payload.get("access_token", "")).strip():
            raise OAuthConnectorError(ErrorCode.DENIED, "OAuth token endpoint response missing access_token.")

        # Re-verify granted scopes returned by provider: refuse any silent write/send scope escalation!
        granted_raw = str(token_payload.get("scope", "")).strip()
        granted_scopes = tuple(granted_raw.split()) if granted_raw else requested_scopes
        granted_verdict = validate_readonly_oauth_scopes(granted_scopes, connector_kind=kind)
        if not granted_verdict.allowed:
            raise OAuthConnectorError(
                ErrorCode.DENIED,
                f"OAuth provider attempted scope escalation beyond read-only ceiling: {granted_verdict.reason}",
            )

        # Store token payload strictly in OS Credential Vault, NEVER in SQLite!
        vault_ref = f"jarvis.oauth.{connector_id}"
        self._vault.set_secret(
            vault_ref,
            json.dumps(
                {
                    "access_token": str(token_payload["access_token"]).strip(),
                    "refresh_token": str(token_payload.get("refresh_token", "")).strip() or None,
                    "token_type": str(token_payload.get("token_type", "Bearer")),
                }
            ),
        )

        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE oauth_pkce_state SET consumed_at = ? WHERE state_nonce = ? AND consumed_at IS NULL",
                (now_iso, state_nonce.strip()),
            )
            if cur.rowcount != 1:
                self._vault.delete_secret(vault_ref)
                raise OAuthConnectorError(ErrorCode.APPROVAL_EXPIRED, "OAuth PKCE state already consumed.")

            conn.execute(
                """
                INSERT INTO ecosystem_connector(
                    id, kind, display_name, endpoint_url, allowed_scopes_json, vault_ref,
                    tls_fingerprint_sha256, consent_acknowledged, enabled, revoked_at, metadata_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, '', 1, 1, NULL, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    endpoint_url = excluded.endpoint_url,
                    allowed_scopes_json = excluded.allowed_scopes_json,
                    vault_ref = excluded.vault_ref,
                    consent_acknowledged = 1,
                    enabled = 1,
                    revoked_at = NULL,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    connector_id,
                    kind,
                    str(row["provider_name"]),
                    str(row["api_base_url"]),
                    json.dumps(list(granted_verdict.normalized_scopes)),
                    vault_ref,
                    json.dumps({"client_id": str(row["client_id"])}),
                    now_iso,
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="oauth.pkce.connected",
                outcome="completed",
                meta={
                    "connector_id": connector_id,
                    "kind": kind,
                    "scopes": list(granted_verdict.normalized_scopes),
                    "vault_ref": vault_ref,
                },
                now_iso=now_iso,
            )

        return self.get_connector(connector_id)

    def list_connectors(self) -> list[OAuthConnectorView]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ecosystem_connector
                WHERE kind IN ('oauth_calendar', 'oauth_mail')
                ORDER BY id ASC
                """
            ).fetchall()
        return [self._row_to_view(r) for r in rows]

    def get_connector(self, connector_id: str) -> OAuthConnectorView:
        with self._db.core_read() as conn:
            row = conn.execute(
                """
                SELECT * FROM ecosystem_connector
                WHERE id = ? AND kind IN ('oauth_calendar', 'oauth_mail')
                """,
                (connector_id.strip().lower(),),
            ).fetchone()
        if row is None:
            raise OAuthConnectorError(ErrorCode.NOT_FOUND, f"OAuth connector '{connector_id}' not found.")
        return self._row_to_view(row)

    def revoke_connector(self, connector_id: str, *, correlation_id: str) -> bool:
        clean_id = connector_id.strip().lower()
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            row = conn.execute(
                "SELECT vault_ref FROM ecosystem_connector WHERE id = ? AND kind IN ('oauth_calendar', 'oauth_mail')",
                (clean_id,),
            ).fetchone()
            if row is None:
                return False
            vault_ref = str(row["vault_ref"]) if row["vault_ref"] else None
            conn.execute(
                """
                UPDATE ecosystem_connector
                SET enabled = 0, consent_acknowledged = 0, revoked_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (now_iso, now_iso, clean_id),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="oauth.connector.revoked",
                outcome="completed",
                meta={"connector_id": clean_id},
                now_iso=now_iso,
            )
        if vault_ref:
            self._vault.delete_secret(vault_ref)
        self._mail_cache.pop(clean_id, None)
        return True

    async def sync_readonly_calendar(
        self,
        connector_id: str,
        *,
        session_id: str | None = None,
        correlation_id: str,
    ) -> dict[str, object]:
        """Fetch read-only calendar events into PersonalLifeService (`external_read`) with offline degradation."""
        conn_view, vault_ref = self._require_active_connector(connector_id, expected_kind="oauth_calendar")
        cfg = self._config.get_active().document
        if cfg.ai.offline_mode:
            cached = [
                e for e in self._life.list_calendar_events()
                if e.source_kind == "external_read" and (e.external_ref or "").startswith(f"{conn_view.id}:")
            ]
            return {
                "connector_id": conn_view.id,
                "mode": "offline_cached",
                "is_stale": True,
                "imported_count": 0,
                "events": [e.model_dump(mode="json") for e in cached],
            }

        access_token = self._read_access_token(vault_ref)
        events_url = f"{conn_view.endpoint_url.rstrip('/')}/calendar/events"
        payload = await self._fetch_authorized_json(events_url, access_token)
        raw_items = payload.get("items", []) if isinstance(payload, dict) else []
        if not isinstance(raw_items, list):
            raise OAuthConnectorError(ErrorCode.RUNTIME_UNAVAILABLE, "Calendar API returned invalid items list.")

        existing_refs = {
            e.external_ref for e in self._life.list_calendar_events() if e.external_ref is not None
        }
        imported: list[CalendarEventRecord] = []
        for item in raw_items[:50]:
            if not isinstance(item, dict):
                continue
            raw_id = str(item.get("id", "")).strip()
            ext_ref = f"{conn_view.id}:{raw_id}" if raw_id else None
            if ext_ref is not None and ext_ref in existing_refs:
                continue
            title = sanitize_untrusted_web_text(str(item.get("summary") or item.get("title") or ""), max_chars=200)
            start_raw = str(item.get("start_at_utc") or item.get("start") or "").strip()
            end_raw = str(item.get("end_at_utc") or item.get("end") or "").strip()
            tz = str(item.get("timezone_iana") or "UTC").strip()
            if not title or not start_raw or not end_raw:
                continue
            rec = self._life.create_calendar_event(
                title=title,
                start_at_utc=datetime.fromisoformat(start_raw),
                end_at_utc=datetime.fromisoformat(end_raw),
                timezone_iana=tz,
                source_kind="external_read",
                external_ref=ext_ref,
            )
            imported.append(rec)
            if ext_ref is not None:
                existing_refs.add(ext_ref)

        if self._context_service is not None and session_id:
            self._context_service.mark_session_untrusted_taint(session_id)

        return {
            "connector_id": conn_view.id,
            "mode": "live_readonly",
            "is_stale": False,
            "imported_count": len(imported),
            "untrusted_data_notice": "External calendar titles are untrusted passive data (BR-15).",
            "events": [e.model_dump(mode="json") for e in imported],
        }

    async def list_readonly_mail_headers(
        self,
        connector_id: str,
        *,
        session_id: str | None = None,
        correlation_id: str,
    ) -> dict[str, object]:
        """Fetch read-only email headers (strictly no send/delete) with offline stale-cache degradation."""
        _ = correlation_id
        conn_view, vault_ref = self._require_active_connector(connector_id, expected_kind="oauth_mail")
        cfg = self._config.get_active().document
        if cfg.ai.offline_mode:
            cached = [m.model_copy(update={"is_stale": True}) for m in self._mail_cache.get(conn_view.id, [])]
            return {
                "connector_id": conn_view.id,
                "mode": "offline_cached",
                "is_stale": True,
                "messages": [m.model_dump(mode="json") for m in cached],
            }

        access_token = self._read_access_token(vault_ref)
        mail_url = f"{conn_view.endpoint_url.rstrip('/')}/mail/messages"
        payload = await self._fetch_authorized_json(mail_url, access_token)
        raw_items = payload.get("messages", []) if isinstance(payload, dict) else []
        if not isinstance(raw_items, list):
            raise OAuthConnectorError(ErrorCode.RUNTIME_UNAVAILABLE, "Mail API returned invalid messages list.")

        headers: list[ReadOnlyMailHeader] = []
        for item in raw_items[:25]:
            if not isinstance(item, dict):
                continue
            headers.append(
                ReadOnlyMailHeader(
                    external_id=str(item.get("id", "")).strip() or str(uuid.uuid4()),
                    sender=sanitize_untrusted_web_text(str(item.get("from", "unknown")), max_chars=160),
                    subject=sanitize_untrusted_web_text(str(item.get("subject", "(no subject)")), max_chars=200),
                    received_at=str(item.get("received_at", "")).strip(),
                    snippet=sanitize_untrusted_web_text(str(item.get("snippet", "")), max_chars=300),
                    is_stale=False,
                )
            )
        self._mail_cache[conn_view.id] = headers
        if self._context_service is not None and session_id:
            self._context_service.mark_session_untrusted_taint(session_id)
        return {
            "connector_id": conn_view.id,
            "mode": "live_readonly",
            "is_stale": False,
            "untrusted_data_notice": "External email headers are untrusted passive data (BR-15).",
            "messages": [m.model_dump(mode="json") for m in headers],
        }

    def _require_active_connector(
        self, connector_id: str, *, expected_kind: Literal["oauth_calendar", "oauth_mail"]
    ) -> tuple[OAuthConnectorView, str]:
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT * FROM ecosystem_connector WHERE id = ? AND kind = ?",
                (connector_id.strip().lower(), expected_kind),
            ).fetchone()
        if row is None:
            raise OAuthConnectorError(ErrorCode.NOT_FOUND, f"OAuth connector '{connector_id}' not found.")
        if not bool(row["enabled"]) or not bool(row["consent_acknowledged"]) or row["revoked_at"] is not None:
            raise OAuthConnectorError(
                ErrorCode.DENIED,
                f"OAuth connector '{connector_id}' is disabled or revoked (FR-LIF-04).",
            )
        vault_ref = str(row["vault_ref"] or "").strip()
        if not vault_ref:
            raise OAuthConnectorError(ErrorCode.DENIED, f"OAuth connector '{connector_id}' lacks vault_ref.")
        return (self._row_to_view(row), vault_ref)

    def _read_access_token(self, vault_ref: str) -> str:
        secret_raw = self._vault.get_secret(vault_ref)
        if not secret_raw:
            raise OAuthConnectorError(
                ErrorCode.DENIED,
                f"OAuth credentials for '{vault_ref}' were revoked or missing from OS Credential Vault.",
            )
        parsed = json.loads(secret_raw)
        tok = str(parsed.get("access_token", "")).strip()
        if not tok:
            raise OAuthConnectorError(ErrorCode.DENIED, "Stored OAuth vault record missing access_token.")
        return tok

    async def _fetch_authorized_json(self, url: str, access_token: str) -> dict[str, Any]:
        try:
            pinned_ip = self._ssrf.validate_and_resolve_url(url, require_https=True)
        except WebFetchSecurityError as exc:
            raise OAuthConnectorError(exc.code, str(exc)) from exc

        use_pinned = self._transport is None
        req_url, headers, extensions = SafeWebFetchClient._build_pinned_request_params(
            url, pinned_ip, use_pinned_socket=use_pinned
        )
        headers["Authorization"] = f"Bearer {access_token}"
        headers["Accept"] = "application/json"

        try:
            async with httpx.AsyncClient(
                transport=self._transport,
                timeout=OAUTH_HTTP_TIMEOUT_SECONDS,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = await client.get(req_url, headers=headers, extensions=extensions)
        except httpx.HTTPError as exc:
            raise OAuthConnectorError(
                ErrorCode.RUNTIME_UNAVAILABLE, f"External OAuth API unreachable: {exc}"
            ) from exc

        if resp.status_code != 200:
            raise OAuthConnectorError(
                ErrorCode.RUNTIME_UNAVAILABLE, f"External OAuth API returned HTTP {resp.status_code}."
            )
        data = resp.json()
        if not isinstance(data, dict):
            raise OAuthConnectorError(ErrorCode.RUNTIME_UNAVAILABLE, "External OAuth API returned non-object JSON.")
        return data

    @staticmethod
    def _row_to_view(row: Any) -> OAuthConnectorView:
        return OAuthConnectorView(
            id=str(row["id"]),
            kind=str(row["kind"]),  # type: ignore[arg-type]
            display_name=str(row["display_name"]),
            endpoint_url=str(row["endpoint_url"]),
            allowed_scopes=tuple(str(s) for s in json.loads(str(row["allowed_scopes_json"]))),
            consent_acknowledged=bool(row["consent_acknowledged"]),
            enabled=bool(row["enabled"]),
            revoked_at=datetime.fromisoformat(str(row["revoked_at"])) if row["revoked_at"] else None,
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    @staticmethod
    def _write_audit(
        conn: Any,
        *,
        correlation_id: str,
        event_type: str,
        outcome: str,
        meta: dict[str, object],
        now_iso: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_event(
                id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
            ) VALUES (?, ?, NULL, 'local_owner', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                correlation_id,
                event_type,
                outcome,
                json.dumps(meta, sort_keys=True),
                now_iso,
            ),
        )
