"""Local Adaptive Preference Proposal Service (B20, FR-REM-03).

Strict invariants:
- Generates proposals strictly from local explicit user corrections.
- Never mutates active configuration, AI models, permissions, or security policy silently!
- Rejecting or ignoring a proposal leaves active configuration completely untouched.
- Proposals targeting security/policy/permissions/trust-zone keys are hard-rejected (`DENIED`).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from jarvis.application.config_service import ConfigService
from jarvis.domain.iot_and_remote import validate_adaptive_preference_proposal
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager


class PreferenceProposalError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class PreferenceProposalRecord(StrictModel):
    id: str
    preference_key: str
    proposed_value: str
    rationale: str
    evidence_count: int = Field(ge=1)
    status: Literal["pending", "approved", "rejected", "dismissed"]
    created_at: datetime
    decided_at: datetime | None = None


class PreferenceProposalService:
    """Manages local non-privilege preference proposals requiring explicit owner approval (FR-REM-03)."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._config_service = config_service
        self._clock = clock

    def create_proposal(
        self,
        *,
        preference_key: str,
        proposed_value: str,
        rationale: str,
        evidence_count: int = 2,
        correlation_id: str,
    ) -> PreferenceProposalRecord:
        check = validate_adaptive_preference_proposal(preference_key, proposed_value)
        if not check.allowed:
            raise PreferenceProposalError(check.error_code or ErrorCode.DENIED, check.reason)

        if evidence_count < 1:
            raise PreferenceProposalError(ErrorCode.INVALID_ARGS, "evidence_count must be >= 1.")

        clean_rationale = rationale.strip()
        if not clean_rationale:
            raise PreferenceProposalError(ErrorCode.INVALID_ARGS, "Proposal rationale cannot be empty.")

        prop_id = f"prop_{uuid.uuid4().hex[:16]}"
        now = self._clock.now_utc()
        now_iso = now.isoformat()

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO preference_proposal(
                    id, preference_key, proposed_value_json, rationale, evidence_count, status, created_at, decided_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', ?, NULL)
                """,
                (
                    prop_id,
                    preference_key.strip(),
                    json.dumps(proposed_value.strip()),
                    clean_rationale,
                    evidence_count,
                    now_iso,
                ),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type="preference.proposal_created",
                outcome="completed",
                meta={
                    "proposal_id": prop_id,
                    "preference_key": preference_key.strip(),
                    "evidence_count": evidence_count,
                },
                now_iso=now_iso,
            )

        return PreferenceProposalRecord(
            id=prop_id,
            preference_key=preference_key.strip(),
            proposed_value=proposed_value.strip(),
            rationale=clean_rationale,
            evidence_count=evidence_count,
            status="pending",
            created_at=now,
            decided_at=None,
        )

    def list_proposals(self, *, status_filter: str | None = None) -> list[PreferenceProposalRecord]:
        with self._db.core_read() as conn:
            if status_filter is not None:
                rows = conn.execute(
                    "SELECT * FROM preference_proposal WHERE status = ? ORDER BY created_at DESC",
                    (status_filter,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM preference_proposal ORDER BY created_at DESC").fetchall()
        return [self._row_to_record(r) for r in rows]

    def decide_proposal(
        self,
        proposal_id: str,
        *,
        decision: Literal["approve", "reject", "dismiss"],
        channel: str = "local",
        is_os_locked: bool = False,
        correlation_id: str,
    ) -> PreferenceProposalRecord:
        """Apply safe UX preference ONLY on explicit local 'approve'; reject/dismiss leaves active config untouched."""
        if channel != "local":
            raise PreferenceProposalError(
                ErrorCode.DENIED, "Preference proposals may only be decided from the local desktop (FR-REM-02)."
            )
        if is_os_locked:
            raise PreferenceProposalError(
                ErrorCode.DENIED, "Cannot decide preference proposals while OS session is locked."
            )

        with self._db.core_read() as conn:
            row = conn.execute("SELECT * FROM preference_proposal WHERE id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise PreferenceProposalError(ErrorCode.NOT_FOUND, f"Preference proposal '{proposal_id}' not found.")

        record = self._row_to_record(row)
        if record.status != "pending":
            raise PreferenceProposalError(
                ErrorCode.APPROVAL_EXPIRED, f"Preference proposal '{proposal_id}' is already '{record.status}'."
            )

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        target_status: Literal["approved", "rejected", "dismissed"] = (
            "approved" if decision == "approve" else ("rejected" if decision == "reject" else "dismissed")
        )

        # Apply ONLY on explicit approval, re-validating safety ceiling before mutating config
        if decision == "approve":
            check = validate_adaptive_preference_proposal(record.preference_key, record.proposed_value)
            if not check.allowed:
                raise PreferenceProposalError(check.error_code or ErrorCode.DENIED, check.reason)
            self._apply_safe_config_preference(
                record.preference_key, record.proposed_value, correlation_id=correlation_id
            )

        with self._db.core_tx() as conn:
            conn.execute(
                "UPDATE preference_proposal SET status = ?, decided_at = ? WHERE id = ?",
                (target_status, now_iso, proposal_id),
            )
            self._write_audit(
                conn,
                correlation_id=correlation_id,
                event_type=f"preference.proposal_{target_status}",
                outcome="completed",
                meta={"proposal_id": proposal_id, "preference_key": record.preference_key},
                now_iso=now_iso,
            )

        return record.model_copy(update={"status": target_status, "decided_at": now})

    def _apply_safe_config_preference(self, key: str, value: str, *, correlation_id: str) -> None:
        active = self._config_service.get_active().document
        data = active.model_dump(mode="json")
        if key == "persona.verbosity":
            data["persona"]["verbosity"] = value
        elif key == "persona.style":
            data["persona"]["style"] = value
        elif key == "locale.primary_language":
            data["locale"]["primary_language"] = value
        elif key == "persona.quiet_hours.start_local":
            data["persona"]["quiet_hours"]["start_local"] = value
        elif key == "persona.quiet_hours.end_local":
            data["persona"]["quiet_hours"]["end_local"] = value
        elif key == "visual.quality_tier":
            data["visual"]["quality_tier"] = value
        else:
            raise PreferenceProposalError(ErrorCode.DENIED, f"Preference key '{key}' is not writable via proposals.")

        validated = self._config_service.validate_payload(data)
        self._config_service.save_revision(validated, source="user", correlation_id=correlation_id)

    @staticmethod
    def _row_to_record(row: Any) -> PreferenceProposalRecord:
        return PreferenceProposalRecord(
            id=str(row["id"]),
            preference_key=str(row["preference_key"]),
            proposed_value=str(json.loads(str(row["proposed_value_json"]))),
            rationale=str(row["rationale"]),
            evidence_count=int(row["evidence_count"]),
            status=str(row["status"]),  # type: ignore[arg-type]
            created_at=datetime.fromisoformat(str(row["created_at"])),
            decided_at=datetime.fromisoformat(str(row["decided_at"])) if row["decided_at"] else None,
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
