"""Transactional R2 Single-Use Approval Lifecycle Service (BR-03, BR-21, T06)."""

from __future__ import annotations

import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta

from jarvis.domain.models import (
    ApprovalChallenge,
    ApprovalDecisionRequest,
    ApprovalState,
    ChannelKind,
    ErrorCode,
    InputModality,
    SessionContext,
)
from jarvis.domain.policy import (
    APPROVAL_TTL_SECONDS,
    compute_approval_bound_hash,
    hash_approval_nonce,
)
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class ApprovalError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ApprovalService:
    """Issues, validates, atomically consumes, and lock-cancels R2 approval challenges."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        event_bus: SequencedEventBus,
    ) -> None:
        self._db = db
        self._clock = clock
        self._bus = event_bus

    def create_challenge(
        self,
        *,
        request_id: str,
        correlation_id: str,
        tool_id: str,
        tool_version: int,
        canonical_args_hash: str,
        session: SessionContext,
        target_snapshot_hash: str | None = None,
        summary: str = "",
        ttl_seconds: int = APPROVAL_TTL_SECONDS,
    ) -> ApprovalChallenge:
        if session.channel != ChannelKind.LOCAL:
            raise ApprovalError(ErrorCode.DENIED, "R2 approval challenges can only be issued on local sessions.")
        if session.is_os_locked or session.is_suspended:
            raise ApprovalError(ErrorCode.DENIED, "Cannot issue approval while session is locked/suspended.")

        now = self._clock.now_utc()
        expires_at = now + timedelta(seconds=ttl_seconds)
        now_iso = now.isoformat()
        expires_iso = expires_at.isoformat()

        raw_nonce = secrets.token_hex(32)  # 256-bit single-use nonce
        nonce_hash = hash_approval_nonce(raw_nonce)
        bound_hash = compute_approval_bound_hash(
            tool_id=tool_id,
            tool_version=tool_version,
            canonical_args_hash=canonical_args_hash,
            session_id=session.session_id,
            actor_ref=session.actor_ref,
            target_snapshot_hash=target_snapshot_hash,
        )

        action_run_id = str(uuid.uuid4())
        approval_id = str(uuid.uuid4())
        idempotency_key = f"{request_id}:{tool_id}:{tool_version}:{uuid.uuid4().hex[:12]}"

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO request(
                    id, correlation_id, actor_ref, channel, state, created_at, deadline_at
                ) VALUES (?, ?, ?, ?, 'awaiting_approval', ?, ?)
                """,
                (request_id, correlation_id, session.actor_ref, session.channel.value, now_iso, expires_iso),
            )
            conn.execute(
                """
                INSERT INTO action_run(
                    id, request_id, tool_id, tool_version, canonical_args_hash, state,
                    idempotency_key, attempt_count, outcome_code, verified, redacted_summary, started_at
                ) VALUES (?, ?, ?, ?, ?, 'awaiting_approval', ?, 0, 'APPROVAL_REQUIRED', 0, ?, ?)
                """,
                (
                    action_run_id,
                    request_id,
                    tool_id,
                    tool_version,
                    canonical_args_hash,
                    idempotency_key,
                    summary,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO approval(
                    id, action_run_id, nonce_hash, bound_hash, actor_ref, session_ref, expires_at, consumed_at, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'pending')
                """,
                (
                    approval_id,
                    action_run_id,
                    nonce_hash,
                    bound_hash,
                    session.actor_ref,
                    session.session_id,
                    expires_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, ?, ?, 'approval.created', 'awaiting_approval', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    action_run_id,
                    session.actor_ref,
                    json.dumps({"approval_id": approval_id, "tool_id": tool_id, "expires_at": expires_iso}),
                    now_iso,
                ),
            )

        self._bus.publish(
            event_type="approval.required",
            correlation_id=correlation_id,
            request_id=request_id,
            payload={
                "approval_id": approval_id,
                "action_run_id": action_run_id,
                "tool_id": tool_id,
                "tool_version": tool_version,
                "bound_hash": bound_hash,
                "expires_at": expires_iso,
                "summary": summary,
            },
        )
        return ApprovalChallenge(
            approval_id=approval_id,
            action_run_id=action_run_id,
            tool_id=tool_id,
            tool_version=tool_version,
            bound_hash=bound_hash,
            nonce=raw_nonce,
            expires_at=expires_at,
            state=ApprovalState.PENDING,
        )

    def decide(
        self,
        approval_id: str,
        decision_req: ApprovalDecisionRequest,
        *,
        session: SessionContext,
        correlation_id: str,
    ) -> ApprovalState:
        """Validate and atomically consume an R2 approval challenge (BR-03, T06)."""
        # Voice and remote approvals are strictly prohibited for R2
        if decision_req.modality != InputModality.TRUSTED_UI or decision_req.channel != ChannelKind.LOCAL:
            raise ApprovalError(
                ErrorCode.DENIED,
                "R2 approvals MUST come from local trusted UI interaction (never voice or remote).",
            )
        if session.channel != ChannelKind.LOCAL or session.is_os_locked or session.is_suspended:
            self.cancel_all_pending_on_lock(reason="session_locked_or_suspended", correlation_id=correlation_id)
            raise ApprovalError(
                ErrorCode.DENIED,
                "Session is locked, suspended, or non-local; approval rejected.",
            )

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        pending_error: ApprovalError | None = None
        target_state: ApprovalState | None = None
        request_id = ""

        with self._db.core_tx() as conn:
            row = conn.execute(
                """
                SELECT a.id, a.action_run_id, a.nonce_hash, a.bound_hash, a.actor_ref,
                       a.session_ref, a.expires_at, a.consumed_at, a.state,
                       ar.request_id, ar.tool_id, ar.tool_version, ar.canonical_args_hash
                FROM approval a
                JOIN action_run ar ON ar.id = a.action_run_id
                WHERE a.id = ?
                """,
                (approval_id,),
            ).fetchone()

            if row is None:
                raise ApprovalError(ErrorCode.NOT_FOUND, f"Approval '{approval_id}' not found.")

            current_state = str(row["state"])
            if current_state != ApprovalState.PENDING.value or row["consumed_at"] is not None:
                raise ApprovalError(
                    ErrorCode.DENIED,
                    f"Approval '{approval_id}' is already finalized ('{current_state}') and cannot be replayed.",
                )

            expires_at = datetime.fromisoformat(str(row["expires_at"]))
            if now >= expires_at:
                conn.execute(
                    "UPDATE approval SET state = 'expired', consumed_at = ? WHERE id = ? AND state = 'pending'",
                    (now_iso, approval_id),
                )
                conn.execute(
                    "UPDATE action_run SET state = 'canceled', outcome_code = 'APPROVAL_EXPIRED', finished_at = ? WHERE id = ?",
                    (now_iso, str(row["action_run_id"])),
                )
                pending_error = ApprovalError(ErrorCode.APPROVAL_EXPIRED, "Approval challenge expired (60s TTL).")
            elif str(row["session_ref"]) != session.session_id or str(row["actor_ref"]) != session.actor_ref:
                raise ApprovalError(ErrorCode.DENIED, "Approval does not belong to the active local session.")
            elif not hmac.compare_digest(hash_approval_nonce(decision_req.nonce), str(row["nonce_hash"])):
                raise ApprovalError(ErrorCode.DENIED, "Invalid single-use approval nonce.")
            elif not hmac.compare_digest(decision_req.bound_hash, str(row["bound_hash"])):
                raise ApprovalError(ErrorCode.DENIED, "Approval bound_hash mismatch.")
            else:
                # Verify target has not changed since preview (TOCTOU guard T04/T06)
                if decision_req.current_target_snapshot_hash is not None:
                    recomputed = compute_approval_bound_hash(
                        tool_id=str(row["tool_id"]),
                        tool_version=int(row["tool_version"]),
                        canonical_args_hash=str(row["canonical_args_hash"]),
                        session_id=str(row["session_ref"]),
                        actor_ref=str(row["actor_ref"]),
                        target_snapshot_hash=decision_req.current_target_snapshot_hash,
                    )
                    if not hmac.compare_digest(recomputed, str(row["bound_hash"])):
                        conn.execute(
                            "UPDATE approval SET state = 'canceled', consumed_at = ? WHERE id = ? AND state = 'pending'",
                            (now_iso, approval_id),
                        )
                        conn.execute(
                            "UPDATE action_run SET state = 'canceled', outcome_code = 'TARGET_CHANGED', finished_at = ? WHERE id = ?",
                            (now_iso, str(row["action_run_id"])),
                        )
                        pending_error = ApprovalError(
                            ErrorCode.TARGET_CHANGED,
                            "Target snapshot changed after preview; approval automatically invalidated.",
                        )

                if pending_error is None:
                    target_state = (
                        ApprovalState.APPROVED if decision_req.decision == "approve" else ApprovalState.REJECTED
                    )
                    cur = conn.execute(
                        """
                        UPDATE approval
                        SET state = ?, consumed_at = ?
                        WHERE id = ? AND state = 'pending' AND consumed_at IS NULL
                        """,
                        (target_state.value, now_iso, approval_id),
                    )
                    if cur.rowcount != 1:
                        raise ApprovalError(ErrorCode.DENIED, "Concurrent replay detected; approval already consumed.")

                    if target_state == ApprovalState.REJECTED:
                        conn.execute(
                            "UPDATE action_run SET state = 'canceled', outcome_code = 'CANCELED', finished_at = ? WHERE id = ?",
                            (now_iso, str(row["action_run_id"])),
                        )
                    else:
                        conn.execute(
                            "UPDATE action_run SET state = 'pending', outcome_code = NULL WHERE id = ?",
                            (str(row["action_run_id"]),),
                        )

                    conn.execute(
                        """
                        INSERT INTO audit_event(
                            id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                        ) VALUES (?, ?, ?, ?, 'approval.decided', ?, ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            correlation_id,
                            str(row["action_run_id"]),
                            session.actor_ref,
                            target_state.value,
                            json.dumps({"approval_id": approval_id, "decision": decision_req.decision}),
                            now_iso,
                        ),
                    )
                    request_id = str(row["request_id"])

        if pending_error is not None:
            raise pending_error
        assert target_state is not None

        self._bus.publish(
            event_type="approval.resolved",
            correlation_id=correlation_id,
            request_id=request_id,
            payload={"approval_id": approval_id, "state": target_state.value},
        )
        return target_state

    def cancel_all_pending_on_lock(self, *, reason: str, correlation_id: str) -> int:
        """Immediately cancel all pending R2 approvals on OS lock or system suspend (BR-21)."""
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            rows = conn.execute("SELECT id, action_run_id FROM approval WHERE state = 'pending'").fetchall()
            if not rows:
                return 0
            conn.execute(
                "UPDATE approval SET state = 'canceled', consumed_at = ? WHERE state = 'pending'",
                (now_iso,),
            )
            for row in rows:
                conn.execute(
                    "UPDATE action_run SET state = 'canceled', outcome_code = 'CANCELED', finished_at = ? WHERE id = ?",
                    (now_iso, str(row["action_run_id"])),
                )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'system', 'approval.mass_canceled', 'canceled', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"reason": reason, "canceled_count": len(rows)}),
                    now_iso,
                ),
            )
        self._bus.publish(
            event_type="session.locked",
            correlation_id=correlation_id,
            payload={"reason": reason, "canceled_approvals": len(rows)},
        )
        return len(rows)
