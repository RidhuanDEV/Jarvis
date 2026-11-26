"""Separate Private Scoped Remote Mobile Gateway Service (B19, FR-REM-01/02/04, NFR-11, T11).

Strict invariants:
- Disabled by default; never binds to 0.0.0.0 / :: / public IPs; requires private/VPN bind IP + TLS pin.
- Local desktop pairing challenge with short TTL (120s); raw pairing code & bearer token are SHA-256 hashed at rest.
- Strict narrow remote capability ceiling (status, scoped chat, reminder read/create ONLY);
  hard 403 block on R2 approvals, files, screen, camera, policy/config/grants, and IoT actuation.
- Per-device sliding-window rate limiter (~30 req/min default) and instant revocation across active queues.
- Honest `host_unreachable` (503) when desktop host is sleeping, offline, or OS-locked; zero silent mutation queueing.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import Field

from jarvis.domain.iot_and_remote import (
    REMOTE_ALLOWED_SCOPES,
    SlidingWindowRateLimiter,
    is_remote_action_permitted,
    validate_private_gateway_bind_address,
)
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager

PAIRING_TTL_SECONDS = 120
DEFAULT_TOKEN_TTL_HOURS = 24
MAX_TOKEN_TTL_HOURS = 168


class RemoteGatewayError(ValueError):
    def __init__(self, code: ErrorCode, message: str, *, http_status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.http_status = http_status


class RemoteGatewayConfigState(StrictModel):
    enabled: bool = False
    bind_address: str = "127.0.0.1"
    bind_port: int = 47443
    tls_cert_fingerprint_sha256: str = ""
    rate_limit_per_minute: int = 30
    host_available: bool = True
    is_os_locked: bool = False
    updated_at: datetime


class PairingChallengeView(StrictModel):
    challenge_id: str
    device_label: str
    device_fingerprint: str
    pairing_code: str
    expires_at: datetime


class PairedDeviceView(StrictModel):
    id: str
    fingerprint: str
    label: str
    scopes: tuple[str, ...]
    paired_at: datetime
    expires_at: datetime
    revoked_at: datetime | None = None


class PairingApprovalReceipt(StrictModel):
    device: PairedDeviceView
    access_token: str = Field(min_length=32)


class AuthorizedRemoteContext(StrictModel):
    device_id: str
    device_label: str
    granted_scopes: tuple[str, ...]
    remaining_rate_quota: int


def _sha256_hex(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class RemoteGatewayService:
    """Manages private remote mobile gateway configuration, local pairing, rate limiting, and revocation."""

    def __init__(self, db: DualSqliteManager, clock: ClockPort) -> None:
        self._db = db
        self._clock = clock
        self._limiter = SlidingWindowRateLimiter(max_requests=30, window_seconds=60.0)
        self._os_locked = False
        self._ensure_default_config()

    def _ensure_default_config(self) -> None:
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            row = conn.execute("SELECT singleton_id FROM remote_gateway_config WHERE singleton_id = 1").fetchone()
            if row is None:
                conn.execute(
                    """
                    INSERT INTO remote_gateway_config(
                        singleton_id, enabled, bind_address, bind_port, tls_cert_fingerprint_sha256,
                        rate_limit_per_minute, host_available, updated_at
                    ) VALUES (1, 0, '127.0.0.1', 47443, '', 30, 1, ?)
                    """,
                    (now_iso,),
                )

    def get_config(self) -> RemoteGatewayConfigState:
        with self._db.core_read() as conn:
            row = conn.execute("SELECT * FROM remote_gateway_config WHERE singleton_id = 1").fetchone()
        assert row is not None
        return RemoteGatewayConfigState(
            enabled=bool(row["enabled"]),
            bind_address=str(row["bind_address"]),
            bind_port=int(row["bind_port"]),
            tls_cert_fingerprint_sha256=str(row["tls_cert_fingerprint_sha256"]),
            rate_limit_per_minute=int(row["rate_limit_per_minute"]),
            host_available=bool(row["host_available"]),
            is_os_locked=self._os_locked,
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def configure_gateway(
        self,
        *,
        enabled: bool,
        bind_address: str,
        bind_port: int,
        tls_cert_fingerprint_sha256: str,
        rate_limit_per_minute: int = 30,
        correlation_id: str,
    ) -> RemoteGatewayConfigState:
        bind_verdict = validate_private_gateway_bind_address(bind_address)
        if not bind_verdict.allowed:
            raise RemoteGatewayError(bind_verdict.error_code or ErrorCode.DENIED, bind_verdict.reason)

        if not (1024 <= bind_port <= 65535):
            raise RemoteGatewayError(ErrorCode.INVALID_ARGS, "Remote gateway bind port must be 1024..65535.")

        if not (1 <= rate_limit_per_minute <= 120):
            raise RemoteGatewayError(ErrorCode.INVALID_ARGS, "Rate limit must be between 1 and 120 req/min.")

        clean_fp = tls_cert_fingerprint_sha256.strip().lower()
        if enabled and (len(clean_fp) != 64 or any(c not in "0123456789abcdef" for c in clean_fp)):
            raise RemoteGatewayError(
                ErrorCode.INVALID_ARGS,
                "Enabling Remote Gateway requires a valid 64-hex SHA-256 TLS certificate fingerprint (FR-REM-01).",
            )

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                UPDATE remote_gateway_config
                SET enabled = ?, bind_address = ?, bind_port = ?, tls_cert_fingerprint_sha256 = ?,
                    rate_limit_per_minute = ?, updated_at = ?
                WHERE singleton_id = 1
                """,
                (
                    1 if enabled else 0,
                    bind_address.strip(),
                    bind_port,
                    clean_fp,
                    rate_limit_per_minute,
                    now_iso,
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                actor="local_owner",
                event_type="remote_gateway.configured",
                outcome="completed",
                meta={
                    "enabled": enabled,
                    "bind_address": bind_address.strip(),
                    "bind_port": bind_port,
                    "rate_limit_per_minute": rate_limit_per_minute,
                },
                now_iso=now_iso,
            )
        self._limiter = SlidingWindowRateLimiter(max_requests=rate_limit_per_minute, window_seconds=60.0)
        return self.get_config()

    def set_host_availability(self, *, available: bool, reason: str, correlation_id: str) -> RemoteGatewayConfigState:
        """Toggle host sleep/offline availability so mobile clients see honest `host_unreachable` (FR-REM-04)."""
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                "UPDATE remote_gateway_config SET host_available = ?, updated_at = ? WHERE singleton_id = 1",
                (1 if available else 0, now_iso),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                actor="system",
                event_type="remote_gateway.availability_changed",
                outcome="completed",
                meta={"host_available": available, "reason": reason},
                now_iso=now_iso,
            )
        return self.get_config()

    def set_os_lock_state(self, locked: bool) -> None:
        self._os_locked = locked

    def initiate_pairing(
        self,
        *,
        device_label: str,
        device_fingerprint: str,
        correlation_id: str,
    ) -> PairingChallengeView:
        cfg = self.get_config()
        if not cfg.enabled:
            raise RemoteGatewayError(
                ErrorCode.DENIED,
                "Remote gateway is disabled by default; enable it on a private/VPN TLS interface first (FR-REM-01).",
            )
        clean_label = device_label.strip()
        clean_fp = device_fingerprint.strip()
        if len(clean_label) < 2 or len(clean_fp) < 8:
            raise RemoteGatewayError(ErrorCode.INVALID_ARGS, "Device label and fingerprint are required for pairing.")

        now = self._clock.now_utc()
        expires = now + timedelta(seconds=PAIRING_TTL_SECONDS)
        challenge_id = f"pair_{uuid.uuid4().hex[:16]}"
        pairing_code = f"{secrets.randbelow(1_000_000):06d}"

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO remote_pairing_challenge(
                    id, device_label, device_fingerprint, code_hash, expires_at, state, created_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?)
                """,
                (
                    challenge_id,
                    clean_label,
                    clean_fp,
                    _sha256_hex(pairing_code),
                    expires.isoformat(),
                    now.isoformat(),
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                actor="local_owner",
                event_type="remote_gateway.pairing_initiated",
                outcome="completed",
                meta={"challenge_id": challenge_id, "device_label": clean_label},
                now_iso=now.isoformat(),
            )
        return PairingChallengeView(
            challenge_id=challenge_id,
            device_label=clean_label,
            device_fingerprint=clean_fp,
            pairing_code=pairing_code,
            expires_at=expires,
        )

    def approve_pairing_locally(
        self,
        *,
        challenge_id: str,
        pairing_code: str,
        scopes: tuple[str, ...] = ("remote.status.read", "remote.chat.send", "remote.reminder.read"),
        token_ttl_hours: int = DEFAULT_TOKEN_TTL_HOURS,
        channel: str = "local",
        is_os_locked: bool = False,
        correlation_id: str,
    ) -> PairingApprovalReceipt:
        """Approve a pairing challenge strictly on the unlocked local desktop (FR-REM-01)."""
        if channel != "local":
            raise RemoteGatewayError(ErrorCode.DENIED, "Device pairing approval is allowed strictly locally.")
        if is_os_locked or self._os_locked:
            raise RemoteGatewayError(ErrorCode.DENIED, "Cannot pair remote devices while OS session is locked.")
        if not scopes:
            raise RemoteGatewayError(ErrorCode.INVALID_ARGS, "At least one narrow remote scope is required.")
        for sc in scopes:
            if sc not in REMOTE_ALLOWED_SCOPES:
                raise RemoteGatewayError(
                    ErrorCode.DENIED,
                    f"Scope '{sc}' is prohibited for remote mobile pairing (FR-REM-02).",
                )
        if not (1 <= token_ttl_hours <= MAX_TOKEN_TTL_HOURS):
            raise RemoteGatewayError(
                ErrorCode.INVALID_ARGS, f"Remote token TTL must be 1..{MAX_TOKEN_TTL_HOURS} hours."
            )

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT * FROM remote_pairing_challenge WHERE id = ?", (challenge_id,)
            ).fetchone()
        if row is None:
            raise RemoteGatewayError(ErrorCode.NOT_FOUND, f"Pairing challenge '{challenge_id}' not found.")
        if str(row["state"]) != "pending":
            raise RemoteGatewayError(ErrorCode.APPROVAL_EXPIRED, "Pairing challenge is no longer pending.")

        expires_at = datetime.fromisoformat(str(row["expires_at"]))
        if now >= expires_at:
            with self._db.core_tx() as conn:
                conn.execute("UPDATE remote_pairing_challenge SET state = 'expired' WHERE id = ?", (challenge_id,))
            raise RemoteGatewayError(ErrorCode.APPROVAL_EXPIRED, "Pairing challenge expired.")

        presented_hash = _sha256_hex(pairing_code.strip())
        if not hmac.compare_digest(str(row["code_hash"]), presented_hash):
            raise RemoteGatewayError(ErrorCode.DENIED, "Invalid local pairing challenge code.")

        device_id = f"dev_{uuid.uuid4().hex[:16]}"
        token_id = f"rtok_{uuid.uuid4().hex[:16]}"
        raw_token = secrets.token_hex(32)
        token_hash = _sha256_hex(raw_token)
        token_expires = now + timedelta(hours=token_ttl_hours)
        norm_scopes = tuple(dict.fromkeys(scopes))

        with self._db.core_tx() as conn:
            conn.execute("UPDATE remote_pairing_challenge SET state = 'approved' WHERE id = ?", (challenge_id,))
            conn.execute(
                """
                INSERT INTO device(id, fingerprint, label, paired_at, expires_at, revoked_at)
                VALUES (?, ?, ?, ?, ?, NULL)
                ON CONFLICT(fingerprint) DO UPDATE SET
                    label = excluded.label,
                    paired_at = excluded.paired_at,
                    expires_at = excluded.expires_at,
                    revoked_at = NULL
                """,
                (
                    device_id,
                    str(row["device_fingerprint"]),
                    str(row["device_label"]),
                    now_iso,
                    token_expires.isoformat(),
                ),
            )
            dev_row = conn.execute(
                "SELECT id FROM device WHERE fingerprint = ?", (str(row["device_fingerprint"]),)
            ).fetchone()
            assert dev_row is not None
            resolved_device_id = str(dev_row["id"])
            conn.execute(
                """
                INSERT INTO remote_device_token(id, device_id, token_hash, scopes_json, expires_at, revoked_at, created_at)
                VALUES (?, ?, ?, ?, ?, NULL, ?)
                """,
                (
                    token_id,
                    resolved_device_id,
                    token_hash,
                    json.dumps(list(norm_scopes)),
                    token_expires.isoformat(),
                    now_iso,
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                actor="local_owner",
                event_type="remote_gateway.device_paired",
                outcome="completed",
                meta={"device_id": resolved_device_id, "scopes": list(norm_scopes)},
                now_iso=now_iso,
            )

        return PairingApprovalReceipt(
            device=PairedDeviceView(
                id=resolved_device_id,
                fingerprint=str(row["device_fingerprint"]),
                label=str(row["device_label"]),
                scopes=norm_scopes,
                paired_at=now,
                expires_at=token_expires,
                revoked_at=None,
            ),
            access_token=raw_token,
        )

    def revoke_device(self, device_id: str, *, correlation_id: str) -> bool:
        """Instantly revoke a paired mobile device and all its tokens (FR-REM-01, NFR-11)."""
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE device SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
                (now_iso, device_id),
            )
            conn.execute(
                "UPDATE remote_device_token SET revoked_at = ? WHERE device_id = ? AND revoked_at IS NULL",
                (now_iso, device_id),
            )
            if cur.rowcount == 0:
                return False
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                actor="local_owner",
                event_type="remote_gateway.device_revoked",
                outcome="completed",
                meta={"device_id": device_id},
                now_iso=now_iso,
            )
        self._limiter.reset_key(device_id)
        return True

    def list_devices(self) -> list[PairedDeviceView]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT d.id, d.fingerprint, d.label, d.paired_at, d.expires_at, d.revoked_at,
                       (SELECT t.scopes_json FROM remote_device_token t
                        WHERE t.device_id = d.id ORDER BY t.created_at DESC LIMIT 1) AS scopes_json
                FROM device d
                ORDER BY d.paired_at DESC
                """
            ).fetchall()
        out: list[PairedDeviceView] = []
        for r in rows:
            scopes_raw = json.loads(str(r["scopes_json"])) if r["scopes_json"] else []
            out.append(
                PairedDeviceView(
                    id=str(r["id"]),
                    fingerprint=str(r["fingerprint"]),
                    label=str(r["label"]),
                    scopes=tuple(str(s) for s in scopes_raw),
                    paired_at=datetime.fromisoformat(str(r["paired_at"])),
                    expires_at=datetime.fromisoformat(str(r["expires_at"])),
                    revoked_at=datetime.fromisoformat(str(r["revoked_at"])) if r["revoked_at"] else None,
                )
            )
        return out

    def authorize_remote_request(
        self,
        *,
        bearer_token: str,
        scope_requested: str,
        is_mutating: bool = False,
        correlation_id: str,
    ) -> AuthorizedRemoteContext:
        """Enforce gateway availability, token validity/revocation, rate limits, and FR-REM-02 scope ceiling."""
        cfg = self.get_config()
        if not cfg.enabled:
            raise RemoteGatewayError(
                ErrorCode.OFFLINE,
                "Remote gateway is disabled.",
                http_status=503,
            )
        if not cfg.host_available:
            raise RemoteGatewayError(
                ErrorCode.OFFLINE,
                "Desktop host is unreachable (sleeping or offline); mutation was NOT queued (FR-REM-04).",
                http_status=503,
            )
        if self._os_locked and is_mutating:
            raise RemoteGatewayError(
                ErrorCode.DENIED,
                "Desktop host OS session is locked; remote mutations are blocked (FR-ADM-03).",
                http_status=403,
            )

        clean_tok = bearer_token.strip()
        if not clean_tok:
            raise RemoteGatewayError(ErrorCode.DENIED, "Missing remote bearer token.", http_status=401)

        tok_hash = _sha256_hex(clean_tok)
        with self._db.core_read() as conn:
            row = conn.execute(
                """
                SELECT t.device_id, t.scopes_json, t.expires_at, t.revoked_at AS token_revoked_at,
                       d.label, d.revoked_at AS device_revoked_at
                FROM remote_device_token t
                JOIN device d ON d.id = t.device_id
                WHERE t.token_hash = ?
                """,
                (tok_hash,),
            ).fetchone()

        if row is None:
            raise RemoteGatewayError(ErrorCode.DENIED, "Unknown remote device token.", http_status=401)
        if row["token_revoked_at"] is not None or row["device_revoked_at"] is not None:
            raise RemoteGatewayError(
                ErrorCode.DENIED, "Remote device token has been revoked (FR-REM-01).", http_status=401
            )

        now = self._clock.now_utc()
        if now >= datetime.fromisoformat(str(row["expires_at"])):
            raise RemoteGatewayError(ErrorCode.DENIED, "Remote device token expired.", http_status=401)

        device_id = str(row["device_id"])
        allowed_rate, remaining = self._limiter.allow(device_id, now.timestamp())
        if not allowed_rate:
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    actor=f"remote:{device_id}",
                    event_type="remote_gateway.rate_limited",
                    outcome="denied",
                    meta={"device_id": device_id, "scope_requested": scope_requested},
                    now_iso=now.isoformat(),
                )
            raise RemoteGatewayError(
                ErrorCode.QUEUE_FULL,
                f"Remote device '{device_id}' exceeded rate limit ({cfg.rate_limit_per_minute} req/min, NFR-11).",
                http_status=429,
            )

        granted_scopes = frozenset(str(s) for s in json.loads(str(row["scopes_json"])))
        permitted, reason = is_remote_action_permitted(scope_requested, granted_scopes)
        if not permitted:
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    actor=f"remote:{device_id}",
                    event_type="remote_gateway.scope_denied",
                    outcome="denied",
                    meta={"device_id": device_id, "scope_requested": scope_requested},
                    now_iso=now.isoformat(),
                )
            raise RemoteGatewayError(ErrorCode.DENIED, reason, http_status=403)

        return AuthorizedRemoteContext(
            device_id=device_id,
            device_label=str(row["label"]),
            granted_scopes=tuple(sorted(granted_scopes)),
            remaining_rate_quota=remaining,
        )

    @staticmethod
    def _write_audit(
        conn: Any,
        *,
        correlation_id: str,
        actor: str,
        event_type: str,
        outcome: str,
        meta: dict[str, object],
        now_iso: str,
    ) -> None:
        conn.execute(
            """
            INSERT INTO audit_event(
                id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
            ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                correlation_id,
                actor,
                event_type,
                outcome,
                json.dumps(meta, sort_keys=True),
                now_iso,
            ),
        )
