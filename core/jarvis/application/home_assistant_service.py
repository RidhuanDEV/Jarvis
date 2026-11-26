"""Home Assistant Allowlist Integration & Safety-Actuation Hard Ban Service (B18, FR-IOT-02..04, T12).

Strict invariants:
- Deny-by-default: only entities explicitly registered & enabled in `ha_entity_allowlist` can be read/actuated.
- Safety-critical devices (locks, alarms, heaters, valves, garages, medical, security) are hard-banned (R3)
  at both allowlist registration time and invocation time, before any network call is attempted.
- Explicit target states only (`turn_on`, `turn_off`, etc.) — NEVER blind `toggle` retries.
- Mandatory post-action readback verification; disconnect or readback timeout reports `unavailable` or `unknown`
  honestly instead of claiming success (FR-IOT-04).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from jarvis.domain.iot_and_remote import evaluate_ha_entity_safety
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager


class HomeAssistantError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class HaClientDisconnectedError(RuntimeError):
    """Raised when the Home Assistant bridge is unreachable before actuation."""


class HaReadbackTimeoutError(RuntimeError):
    """Raised when an actuation command was dispatched but post-action readback timed out."""


@dataclass(frozen=True)
class HaEntityState:
    entity_id: str
    state: str
    attributes: dict[str, Any]
    observed_at: datetime


class HomeAssistantClientPort(Protocol):
    """Transport-abstracted private-LAN/TLS Home Assistant client."""

    def read_entity_state(self, entity_id: str) -> HaEntityState: ...

    def call_service(self, domain: str, service: str, entity_id: str, params: dict[str, Any]) -> None: ...


class OfflineHomeAssistantClient:
    """Default safe client when no Home Assistant instance is connected."""

    def read_entity_state(self, entity_id: str) -> HaEntityState:
        raise HaClientDisconnectedError(f"Home Assistant endpoint not configured for '{entity_id}'.")

    def call_service(self, domain: str, service: str, entity_id: str, params: dict[str, Any]) -> None:
        _ = (domain, service, params)
        raise HaClientDisconnectedError(f"Home Assistant endpoint not configured for '{entity_id}'.")


class AllowlistedHaEntity(StrictModel):
    entity_id: str
    domain: str
    friendly_name: str
    allowed_actions: tuple[str, ...]
    enabled: bool
    added_at: datetime


class HaActionResult(StrictModel):
    entity_id: str
    action: str
    status: Literal["verified", "unavailable", "unknown", "mismatch"]
    expected_state: str | None = None
    observed_state: str | None = None
    verified_readback: bool = False
    message: str = Field(default="")


_ACTION_EXPECTED_STATE: dict[str, str] = {
    "turn_on": "on",
    "turn_off": "off",
    "media_play": "playing",
    "media_pause": "paused",
    "media_stop": "idle",
}


class HomeAssistantService:
    """Enforces FR-IOT-02..04 allowlist, R3 safety bans, explicit target state, and honest readback."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        client: HomeAssistantClientPort | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._client: HomeAssistantClientPort = client or OfflineHomeAssistantClient()

    def register_allowlisted_entity(
        self,
        *,
        entity_id: str,
        friendly_name: str,
        allowed_actions: tuple[str, ...],
        correlation_id: str,
    ) -> AllowlistedHaEntity:
        if not allowed_actions:
            raise HomeAssistantError(ErrorCode.INVALID_ARGS, "At least one explicit allowed action is required.")

        cleaned_id = entity_id.strip().lower()
        for act in allowed_actions:
            verdict = evaluate_ha_entity_safety(cleaned_id, act)
            if not verdict.allowed:
                raise HomeAssistantError(verdict.error_code or ErrorCode.DENIED, verdict.reason)

        domain = cleaned_id.split(".", 1)[0]
        now = self._clock.now_utc()
        now_iso = now.isoformat()
        actions_norm = tuple(dict.fromkeys(a.strip().lower() for a in allowed_actions))

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO ha_entity_allowlist(
                    entity_id, domain, friendly_name, allowed_actions_json, enabled, added_at, revoked_at
                ) VALUES (?, ?, ?, ?, 1, ?, NULL)
                ON CONFLICT(entity_id) DO UPDATE SET
                    friendly_name = excluded.friendly_name,
                    allowed_actions_json = excluded.allowed_actions_json,
                    enabled = 1,
                    revoked_at = NULL
                """,
                (cleaned_id, domain, friendly_name.strip(), json.dumps(list(actions_norm)), now_iso),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="iot.ha_entity_allowlisted",
                outcome="completed",
                meta={"entity_id": cleaned_id, "allowed_actions": list(actions_norm)},
                now_iso=now_iso,
            )

        return AllowlistedHaEntity(
            entity_id=cleaned_id,
            domain=domain,
            friendly_name=friendly_name.strip(),
            allowed_actions=actions_norm,
            enabled=True,
            added_at=now,
        )

    def revoke_entity(self, entity_id: str, *, correlation_id: str) -> bool:
        cleaned_id = entity_id.strip().lower()
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE ha_entity_allowlist SET enabled = 0, revoked_at = ? WHERE entity_id = ?",
                (now_iso, cleaned_id),
            )
            if cur.rowcount == 0:
                return False
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="iot.ha_entity_revoked",
                outcome="completed",
                meta={"entity_id": cleaned_id},
                now_iso=now_iso,
            )
        return True

    def list_allowlisted_entities(self) -> list[AllowlistedHaEntity]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                "SELECT entity_id, domain, friendly_name, allowed_actions_json, enabled, added_at "
                "FROM ha_entity_allowlist ORDER BY entity_id ASC"
            ).fetchall()
        return [
            AllowlistedHaEntity(
                entity_id=str(r["entity_id"]),
                domain=str(r["domain"]),
                friendly_name=str(r["friendly_name"]),
                allowed_actions=tuple(json.loads(str(r["allowed_actions_json"]))),
                enabled=bool(r["enabled"]),
                added_at=datetime.fromisoformat(str(r["added_at"])),
            )
            for r in rows
        ]

    def execute_entity_action(
        self,
        *,
        entity_id: str,
        action: str,
        params: dict[str, Any] | None = None,
        offline_mode: bool = False,
        channel: str = "local",
        is_os_locked: bool = False,
        correlation_id: str,
    ) -> HaActionResult:
        """Actuate or read an allowlisted Home Assistant entity with hard safety bans and mandatory readback."""
        cleaned_id = entity_id.strip().lower()
        cleaned_action = action.strip().lower()
        now_iso = self._clock.now_utc().isoformat()

        # 1. Hard R3 safety ban & explicit action check BEFORE checking network or allowlist (FR-IOT-03)
        verdict = evaluate_ha_entity_safety(cleaned_id, cleaned_action)
        if not verdict.allowed:
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    event_type="iot.ha_action_blocked_safety",
                    outcome="denied",
                    meta={"entity_id": cleaned_id, "action": cleaned_action, "r3": verdict.is_r3_prohibited},
                    now_iso=now_iso,
                )
            raise HomeAssistantError(verdict.error_code or ErrorCode.DENIED, verdict.reason)

        # 2. Channel / OS lock / offline checks
        if channel != "local":
            raise HomeAssistantError(
                ErrorCode.DENIED, "Home Assistant actuation is prohibited over remote channels (FR-REM-02)."
            )
        if is_os_locked:
            raise HomeAssistantError(
                ErrorCode.DENIED, "Home Assistant actuation blocked while OS session is locked (FR-ADM-03)."
            )
        if offline_mode:
            return HaActionResult(
                entity_id=cleaned_id,
                action=cleaned_action,
                status="unavailable",
                verified_readback=False,
                message="Offline mode is active; Home Assistant LAN endpoint is unavailable.",
            )

        # 3. Allowlist membership & per-entity action check BEFORE network call (FR-IOT-02)
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT domain, allowed_actions_json, enabled FROM ha_entity_allowlist WHERE entity_id = ?",
                (cleaned_id,),
            ).fetchone()
        if row is None or not bool(row["enabled"]):
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    event_type="iot.ha_action_denied_not_allowlisted",
                    outcome="denied",
                    meta={"entity_id": cleaned_id, "action": cleaned_action},
                    now_iso=now_iso,
                )
            raise HomeAssistantError(
                ErrorCode.DENIED,
                f"Home Assistant entity '{cleaned_id}' is not in the active allowlist (FR-IOT-02).",
            )

        allowed_actions = set(json.loads(str(row["allowed_actions_json"])))
        if cleaned_action not in allowed_actions:
            raise HomeAssistantError(
                ErrorCode.DENIED,
                f"Action '{cleaned_action}' is not allowlisted for entity '{cleaned_id}' (FR-IOT-02).",
            )

        domain = str(row["domain"])

        # 4. Pure state read
        if cleaned_action == "read_state":
            try:
                observed = self._client.read_entity_state(cleaned_id)
                return HaActionResult(
                    entity_id=cleaned_id,
                    action=cleaned_action,
                    status="verified",
                    observed_state=observed.state,
                    verified_readback=True,
                    message=f"Observed state '{observed.state}'.",
                )
            except (HaClientDisconnectedError, HaReadbackTimeoutError) as exc:
                return HaActionResult(
                    entity_id=cleaned_id,
                    action=cleaned_action,
                    status="unavailable",
                    verified_readback=False,
                    message=f"Home Assistant unreachable: {exc}",
                )

        # 5. Dispatch explicit target state — NEVER blindly retry on post-dispatch error (FR-IOT-04)
        dispatched = False
        try:
            self._client.call_service(domain, cleaned_action, cleaned_id, dict(params or {}))
            dispatched = True
        except HaClientDisconnectedError as exc:
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    event_type="iot.ha_action_unavailable",
                    outcome="failed",
                    meta={"entity_id": cleaned_id, "action": cleaned_action},
                    now_iso=now_iso,
                )
            return HaActionResult(
                entity_id=cleaned_id,
                action=cleaned_action,
                status="unavailable",
                expected_state=_ACTION_EXPECTED_STATE.get(cleaned_action),
                verified_readback=False,
                message=f"Home Assistant unreachable before dispatch: {exc}",
            )
        except Exception as exc:
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    event_type="iot.ha_action_unknown",
                    outcome="unknown",
                    meta={"entity_id": cleaned_id, "action": cleaned_action},
                    now_iso=now_iso,
                )
            return HaActionResult(
                entity_id=cleaned_id,
                action=cleaned_action,
                status="unknown",
                expected_state=_ACTION_EXPECTED_STATE.get(cleaned_action),
                verified_readback=False,
                message=f"Dispatch outcome uncertain (no blind retry): {exc}",
            )

        # 6. Mandatory post-actuation readback verification (FR-IOT-02, FR-IOT-04)
        expected = _ACTION_EXPECTED_STATE.get(cleaned_action)
        try:
            observed = self._client.read_entity_state(cleaned_id)
        except (HaClientDisconnectedError, HaReadbackTimeoutError) as exc:
            assert dispatched
            with self._db.core_tx() as conn:
                self._write_audit(
                    conn,
                    correlation_id=correlation_id,
                    event_type="iot.ha_readback_unknown",
                    outcome="unknown",
                    meta={"entity_id": cleaned_id, "action": cleaned_action},
                    now_iso=now_iso,
                )
            return HaActionResult(
                entity_id=cleaned_id,
                action=cleaned_action,
                status="unknown",
                expected_state=expected,
                verified_readback=False,
                message=f"Command sent but readback timed out/disconnected; actual device state is unknown: {exc}",
            )

        matched = expected is None or observed.state.strip().lower() == expected
        final_status: Literal["verified", "mismatch"] = "verified" if matched else "mismatch"
        with self._db.core_tx() as conn:
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="iot.ha_action_completed" if matched else "iot.ha_readback_mismatch",
                outcome="completed" if matched else "failed",
                meta={
                    "entity_id": cleaned_id,
                    "action": cleaned_action,
                    "expected": expected,
                    "observed": observed.state,
                },
                now_iso=now_iso,
            )
        return HaActionResult(
            entity_id=cleaned_id,
            action=cleaned_action,
            status=final_status,
            expected_state=expected,
            observed_state=observed.state,
            verified_readback=matched,
            message=(
                f"Verified readback state '{observed.state}'."
                if matched
                else f"Readback mismatch: expected '{expected}', observed '{observed.state}'."
            ),
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
