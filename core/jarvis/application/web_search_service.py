"""Pluggable Web Search Service with Offline Gate, Private-Query Guard & Stale Cache Labeling (B12, DEC-011, FR-WEB-01..03)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Protocol

from jarvis.application.config_service import ConfigService
from jarvis.application.context_service import ContextAssemblerService
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.domain.security_guards import detect_private_indicators_in_query
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.web_fetch import FetchedWebPage, SafeWebFetchClient, WebFetchSecurityError


class WebSearchError(ValueError):
    def __init__(self, code: ErrorCode, message: str, *, indicators: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.indicators = indicators


class WebSearchResultItem(StrictModel):
    title: str
    url: str
    snippet: str
    published_at: str | None = None
    fetched_at: datetime
    is_stale: bool = False


class WebSearchProviderPort(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def search(self, query: str, *, limit: int = 5) -> list[WebSearchResultItem]: ...


class WebProviderConsentState(StrictModel):
    configured: bool
    enabled: bool
    provider_name: str | None = None
    endpoint_url: str | None = None
    consent_acknowledged: bool = False
    allow_loopback_searxng: bool = False


class WebIntelligenceService:
    """Orchestrates pluggable read-only web search & anti-SSRF fetching with consent, BR-15 taint & offline fallback."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        fetch_client: SafeWebFetchClient,
        clock: ClockPort,
        *,
        search_provider: WebSearchProviderPort | None = None,
        context_service: ContextAssemblerService | None = None,
    ) -> None:
        self._db = db
        self._config = config_service
        self._fetch = fetch_client
        self._clock = clock
        self._provider = search_provider
        self._context_service = context_service

    def bind_search_provider(self, provider: WebSearchProviderPort | None) -> None:
        self._provider = provider

    def get_provider_consent_state(self) -> WebProviderConsentState:
        with self._db.core_read() as conn:
            row = conn.execute(
                """
                SELECT display_name, endpoint_url, consent_acknowledged, enabled, metadata_json
                FROM ecosystem_connector
                WHERE id = 'web_search_default' AND kind = 'web_search'
                """
            ).fetchone()
        if row is None:
            return WebProviderConsentState(
                configured=self._provider is not None,
                enabled=self._provider is not None,
                provider_name=self._provider.provider_name if self._provider is not None else None,
            )
        meta = json.loads(str(row["metadata_json"] or "{}"))
        return WebProviderConsentState(
            configured=True,
            enabled=bool(row["enabled"]) and self._provider is not None,
            provider_name=str(row["display_name"]),
            endpoint_url=str(row["endpoint_url"]),
            consent_acknowledged=bool(row["consent_acknowledged"]),
            allow_loopback_searxng=bool(meta.get("allow_loopback_searxng", False)),
        )

    def configure_search_provider(
        self,
        *,
        provider: WebSearchProviderPort,
        endpoint_url: str,
        consent_acknowledged: bool,
        allow_loopback_searxng: bool = False,
        correlation_id: str,
    ) -> WebProviderConsentState:
        if not consent_acknowledged:
            raise WebSearchError(
                ErrorCode.APPROVAL_REQUIRED,
                "Explicit per-connector owner consent is required before enabling Web Search (FR-WEB-01).",
            )
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO ecosystem_connector(
                    id, kind, display_name, endpoint_url, allowed_scopes_json, vault_ref,
                    tls_fingerprint_sha256, consent_acknowledged, enabled, revoked_at, metadata_json, updated_at
                ) VALUES ('web_search_default', 'web_search', ?, ?, '["web.search.readonly"]', NULL, '', 1, 1, NULL, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    endpoint_url = excluded.endpoint_url,
                    consent_acknowledged = 1,
                    enabled = 1,
                    revoked_at = NULL,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    provider.provider_name,
                    endpoint_url,
                    json.dumps({"allow_loopback_searxng": allow_loopback_searxng}),
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.provider.configured', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps(
                        {
                            "provider": provider.provider_name,
                            "allow_loopback_searxng": allow_loopback_searxng,
                        }
                    ),
                    now_iso,
                ),
            )
        self._provider = provider
        return self.get_provider_consent_state()

    def revoke_search_provider(self, *, correlation_id: str) -> WebProviderConsentState:
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                UPDATE ecosystem_connector
                SET enabled = 0, consent_acknowledged = 0, revoked_at = ?, updated_at = ?
                WHERE id = 'web_search_default' AND kind = 'web_search'
                """,
                (now_iso, now_iso),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.provider.revoked', 'completed', '{}', ?)
                """,
                (str(uuid.uuid4()), correlation_id, now_iso),
            )
        self._provider = None
        return self.get_provider_consent_state()

    async def query_web(
        self,
        query: str,
        *,
        limit: int = 5,
        private_query_approved: bool = False,
        allow_stale_cache_when_offline: bool = False,
        session_id: str | None = None,
        correlation_id: str,
    ) -> dict[str, object]:
        cfg = self._config.get_active().document
        cleaned = query.strip()
        if not cleaned:
            raise WebSearchError(ErrorCode.INVALID_ARGS, "Query pencarian web tidak boleh kosong.")

        if cfg.ai.offline_mode:
            if allow_stale_cache_when_offline and self._provider is not None:
                cache_getter = getattr(self._provider, "get_cached_results", None)
                if callable(cache_getter):
                    cached = cache_getter(cleaned)
                    if cached is not None:
                        cached_items = [
                            item.model_copy(update={"is_stale": True})
                            for item in cached[0][: max(1, min(limit, 10))]
                        ]
                        if self._context_service is not None and session_id:
                            self._context_service.mark_session_untrusted_taint(session_id)
                        return {
                            "provider": self._provider.provider_name,
                            "fetched_at": self._clock.now_utc().isoformat(),
                            "is_stale": True,
                            "from_cache": True,
                            "untrusted_data_notice": "Web results are untrusted passive data (BR-15).",
                            "results": [r.model_dump(mode="json") for r in cached_items],
                        }
            raise WebSearchError(
                ErrorCode.OFFLINE, "Mode offline aktif; pencarian web diblokir (BR-16)."
            )

        # FR-WEB-01: inspect query for private/PII/token indicators before sending outbound
        indicators = detect_private_indicators_in_query(cleaned)
        if indicators and not private_query_approved:
            raise WebSearchError(
                ErrorCode.APPROVAL_REQUIRED,
                f"Query memuat indikasi data privat ({', '.join(indicators)}); diperlukan pratinjau/persetujuan R2 atau redaksi.",
                indicators=indicators,
            )

        if self._provider is None:
            raise WebSearchError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                "Tidak ada provider pencarian web (mis. SearXNG lokal) yang dikonfigurasi.",
            )

        results = await self._provider.search(cleaned, limit=max(1, min(limit, 10)))
        if self._context_service is not None and session_id:
            self._context_service.mark_session_untrusted_taint(session_id)
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.search.executed', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"provider": self._provider.provider_name, "result_count": len(results)}),
                    now_iso,
                ),
            )
        return {
            "provider": self._provider.provider_name,
            "fetched_at": now_iso,
            "is_stale": any(r.is_stale for r in results),
            "from_cache": False,
            "untrusted_data_notice": "Web results are untrusted passive data (BR-15).",
            "results": [r.model_dump(mode="json") for r in results],
        }

    async def fetch_page(
        self,
        url: str,
        *,
        require_https: bool = False,
        session_id: str | None = None,
        correlation_id: str,
    ) -> FetchedWebPage:
        cfg = self._config.get_active().document
        try:
            page = await self._fetch.fetch_read_only(
                url, offline_mode=cfg.ai.offline_mode, require_https=require_https
            )
        except WebFetchSecurityError as exc:
            raise WebSearchError(exc.code, str(exc)) from exc

        if self._context_service is not None and session_id:
            self._context_service.mark_session_untrusted_taint(session_id)

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.page.fetched', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"status_code": page.status_code, "is_stale": page.is_stale}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return page
