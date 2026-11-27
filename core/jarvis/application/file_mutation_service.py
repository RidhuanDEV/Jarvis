"""Scoped Tier-2 GUI Diff File Edit & Stage G4 Handle-Pinned Move Service (B14, Decision A2, U-S02, U-S03).

Strictly OS-independent (NFR-16): delegates containment & reparse checks to FilesystemSafetyPort.
Enforces:
- Mandatory single-use cryptographic GUI ApprovalChallenge with exact unified diff preview & target_snapshot_hash.
- TOCTOU target verification (TARGET_CHANGED if file modified on disk between preview and apply).
- Anti-overwrite (no-clobber) on file move and strict same-root scope enforcement.
- Anti-indirect-delete guard: refuses truncating/emptying existing files and rejects executable/script targets.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jarvis.application.approval_service import ApprovalError, ApprovalService
from jarvis.domain.models import (
    ApprovalChallenge,
    ErrorCode,
    GrantRecord,
    SessionContext,
)
from jarvis.domain.policy import PolicyEngine
from jarvis.domain.ports import ClockPort, FilesystemSafetyPort
from jarvis.infrastructure.dual_db import DualSqliteManager

EDITABLE_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {".txt", ".md", ".csv", ".json", ".yaml", ".yml", ".log", ".ini", ".toml"}
)


class FileMutationError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PendingFileEditSpec:
    approval_id: str
    root_id: str
    root_path: str
    relative_path: str
    canonical_path: str
    new_content: str
    target_snapshot_hash: str
    bound_hash: str
    diff_preview: str


@dataclass(frozen=True)
class PendingFileMoveSpec:
    approval_id: str
    root_id: str
    root_path: str
    source_relative_path: str
    target_relative_path: str
    source_canonical_path: str
    target_canonical_path: str
    target_snapshot_hash: str
    bound_hash: str


@dataclass(frozen=True)
class FileMutationReceipt:
    tool_id: str
    verified: bool
    canonical_path: str
    sha256: str
    summary: str


class FileMutationService:
    """Proposes diff-previewed Tier-2 file edits/moves and applies them strictly after single-use GUI approval."""

    def __init__(
        self,
        db: DualSqliteManager,
        policy_engine: PolicyEngine,
        approval_service: ApprovalService,
        fs_port: FilesystemSafetyPort,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._policy = policy_engine
        self._approvals = approval_service
        self._fs = fs_port
        self._clock = clock
        self._lock = threading.RLock()
        self._pending_edits: dict[str, PendingFileEditSpec] = {}
        self._pending_moves: dict[str, PendingFileMoveSpec] = {}

    def _resolve_active_root(self, root_id: str) -> str:
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT canonical_path FROM source_root WHERE id = ? AND enabled = 1 AND revoked_at IS NULL",
                (root_id,),
            ).fetchone()
            tomb = conn.execute(
                "SELECT 1 FROM deletion_ledger WHERE entity_type = 'source_root' AND entity_id = ?",
                (root_id,),
            ).fetchone()
        if row is None or tomb is not None:
            raise FileMutationError(
                ErrorCode.DENIED, f"Authorized root '{root_id}' is missing or has been revoked."
            )
        return str(row["canonical_path"])

    def propose_file_edit(
        self,
        *,
        root_id: str,
        relative_path: str,
        new_content: str,
        session: SessionContext,
        grants: tuple[GrantRecord, ...],
        correlation_id: str,
    ) -> tuple[ApprovalChallenge, str]:
        """Validate scope, compute exact unified diff, and create single-use R2 GUI ApprovalChallenge."""
        if not new_content.strip():
            raise FileMutationError(
                ErrorCode.DENIED,
                "Refusing empty/whitespace-only edit that would indirectly erase file contents (Tier-3 no-delete guard).",
            )
        root_path = self._resolve_active_root(root_id)
        try:
            canonical = self._fs.resolve_within_root(root_path, relative_path)
        except PermissionError as exc:
            raise FileMutationError(ErrorCode.DENIED, str(exc)) from exc

        insp = self._fs.inspect_path(canonical)
        if insp.is_reparse_point:
            raise FileMutationError(ErrorCode.DENIED, "Reparse point / symlink file edits are prohibited.")

        target_p = Path(canonical)
        if not target_p.is_file():
            raise FileMutationError(ErrorCode.NOT_FOUND, f"Target file does not exist: '{relative_path}'.")
        if target_p.suffix.lower() not in EDITABLE_TEXT_EXTENSIONS:
            raise FileMutationError(
                ErrorCode.DENIED,
                f"Extension '{target_p.suffix or '(none)'}' is not permitted for structured text editing.",
            )

        snap = self._fs.snapshot_target(canonical)
        step_args: dict[str, Any] = {
            "root_id": root_id,
            "relative_path": relative_path,
            "target_path": canonical,
            "new_content_sha256": hashlib.sha256(new_content.encode()).hexdigest(),
        }
        decision = self._policy.evaluate_step(
            tool_id="fs.file.edit",
            tool_version=1,
            args=step_args,
            session=session,
            grants=grants,
            now_utc=self._clock.now_utc(),
            target_snapshot_hash=snap.snapshot_hash,
        )
        if not decision.requires_approval and not decision.allowed:
            raise FileMutationError(decision.error_code or ErrorCode.DENIED, decision.reason)

        old_text = target_p.read_text(encoding="utf-8", errors="replace")
        diff_lines = list(
            difflib.unified_diff(
                old_text.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=f"a/{relative_path}",
                tofile=f"b/{relative_path}",
                n=3,
            )
        )
        diff_preview = "".join(diff_lines)[:3000] or "(no textual changes)"

        challenge = self._approvals.create_challenge(
            request_id=f"req_edit_{uuid.uuid4().hex[:10]}",
            correlation_id=correlation_id,
            tool_id="fs.file.edit",
            tool_version=1,
            canonical_args_hash=decision.canonical_args_hash,
            session=session,
            target_snapshot_hash=snap.snapshot_hash,
            summary=f"Edit file '{relative_path}' (Tier-2 GUI approval required)\n{diff_preview[:300]}",
        )
        with self._lock:
            self._pending_edits[challenge.approval_id] = PendingFileEditSpec(
                approval_id=challenge.approval_id,
                root_id=root_id,
                root_path=root_path,
                relative_path=relative_path,
                canonical_path=canonical,
                new_content=new_content,
                target_snapshot_hash=snap.snapshot_hash,
                bound_hash=challenge.bound_hash,
                diff_preview=diff_preview,
            )
        return (challenge, diff_preview)

    def apply_approved_file_edit(
        self,
        *,
        approval_id: str,
        session: SessionContext,
        correlation_id: str,
    ) -> FileMutationReceipt:
        """Consume approved GUI challenge, check TOCTOU snapshot, and perform atomic staged write."""
        if session.is_os_locked or session.is_suspended:
            raise FileMutationError(ErrorCode.DENIED, "Session is locked; file mutation denied.")

        with self._lock:
            spec = self._pending_edits.get(approval_id)
        if spec is None:
            raise FileMutationError(ErrorCode.NOT_FOUND, f"No pending file edit for approval '{approval_id}'.")

        # Re-verify root still authorized and target unchanged on disk (TOCTOU guard U-S03)
        self._resolve_active_root(spec.root_id)
        target_p = Path(spec.canonical_path)
        if not target_p.is_file():
            raise FileMutationError(ErrorCode.TARGET_CHANGED, "Target file vanished before apply.")
        current_snap = self._fs.snapshot_target(spec.canonical_path)
        if current_snap.snapshot_hash != spec.target_snapshot_hash:
            raise FileMutationError(
                ErrorCode.TARGET_CHANGED,
                "Target file was modified on disk after diff preview; re-approval required.",
            )

        try:
            self._approvals.consume_approved_for_execution(
                approval_id,
                expected_bound_hash=spec.bound_hash,
                session_id=session.session_id,
                actor_ref=session.actor_ref,
                expected_tool_id="fs.file.edit",
            )
        except ApprovalError as exc:
            raise FileMutationError(exc.code, str(exc)) from exc

        # Atomic staged write in same directory (never truncates target in place)
        encoded = spec.new_content.encode("utf-8")
        expected_sha = hashlib.sha256(encoded).hexdigest()
        tmp_path = target_p.with_name(f".{target_p.name}.jarvis-stage-{uuid.uuid4().hex[:8]}.tmp")
        try:
            with open(tmp_path, "wb") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target_p)
        except OSError as exc:
            if tmp_path.exists():
                tmp_path.unlink(missing_ok=True)
            raise FileMutationError(ErrorCode.INTERNAL, f"Atomic staged write failed: {exc}") from exc

        actual_sha = hashlib.sha256(target_p.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise FileMutationError(ErrorCode.INTERNAL, "Post-write SHA-256 readback mismatch.")

        with self._lock:
            self._pending_edits.pop(approval_id, None)

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'fs.file.edit', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    session.actor_ref,
                    json.dumps(
                        {
                            "approval_id": approval_id,
                            "root_id": spec.root_id,
                            "relative_path": spec.relative_path,
                            "sha256": actual_sha,
                        }
                    ),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return FileMutationReceipt(
            tool_id="fs.file.edit",
            verified=True,
            canonical_path=spec.canonical_path,
            sha256=actual_sha,
            summary=f"File '{spec.relative_path}' diperbarui secara atomik dan terverifikasi SHA-256.",
        )

    def propose_file_move(
        self,
        *,
        root_id: str,
        source_relative_path: str,
        target_relative_path: str,
        session: SessionContext,
        grants: tuple[GrantRecord, ...],
        correlation_id: str,
    ) -> ApprovalChallenge:
        """Stage G4 Decision A2: propose same-scope, no-overwrite file move requiring GUI diff approval."""
        root_path = self._resolve_active_root(root_id)
        try:
            src_canon = self._fs.resolve_within_root(root_path, source_relative_path)
            dst_canon = self._fs.resolve_within_root(root_path, target_relative_path)
        except PermissionError as exc:
            raise FileMutationError(ErrorCode.DENIED, str(exc)) from exc

        src_p = Path(src_canon)
        dst_p = Path(dst_canon)
        if not src_p.is_file():
            raise FileMutationError(ErrorCode.NOT_FOUND, f"Source file not found: '{source_relative_path}'.")
        if dst_p.exists():
            raise FileMutationError(
                ErrorCode.DENIED,
                f"Destination '{target_relative_path}' already exists; overwriting files is strictly prohibited.",
            )

        snap = self._fs.snapshot_target(src_canon)
        step_args: dict[str, Any] = {
            "root_id": root_id,
            "source_path": src_canon,
            "target_path": dst_canon,
        }
        decision = self._policy.evaluate_step(
            tool_id="fs.file.move",
            tool_version=1,
            args=step_args,
            session=session,
            grants=grants,
            now_utc=self._clock.now_utc(),
            target_snapshot_hash=snap.snapshot_hash,
        )
        if not decision.requires_approval and not decision.allowed:
            raise FileMutationError(decision.error_code or ErrorCode.DENIED, decision.reason)

        challenge = self._approvals.create_challenge(
            request_id=f"req_move_{uuid.uuid4().hex[:10]}",
            correlation_id=correlation_id,
            tool_id="fs.file.move",
            tool_version=1,
            canonical_args_hash=decision.canonical_args_hash,
            session=session,
            target_snapshot_hash=snap.snapshot_hash,
            summary=f"Move/rename '{source_relative_path}' -> '{target_relative_path}' (no-overwrite, same-scope)",
        )
        with self._lock:
            self._pending_moves[challenge.approval_id] = PendingFileMoveSpec(
                approval_id=challenge.approval_id,
                root_id=root_id,
                root_path=root_path,
                source_relative_path=source_relative_path,
                target_relative_path=target_relative_path,
                source_canonical_path=src_canon,
                target_canonical_path=dst_canon,
                target_snapshot_hash=snap.snapshot_hash,
                bound_hash=challenge.bound_hash,
            )
        return challenge

    def apply_approved_file_move(
        self,
        *,
        approval_id: str,
        session: SessionContext,
        correlation_id: str,
    ) -> FileMutationReceipt:
        """Stage G4 Decision A2: consume GUI approval, verify TOCTOU & no-overwrite, and rename atomically."""
        if session.is_os_locked or session.is_suspended:
            raise FileMutationError(ErrorCode.DENIED, "Session is locked; file move denied.")
        with self._lock:
            spec = self._pending_moves.get(approval_id)
        if spec is None:
            raise FileMutationError(ErrorCode.NOT_FOUND, f"No pending file move for approval '{approval_id}'.")

        self._resolve_active_root(spec.root_id)
        src_p = Path(spec.source_canonical_path)
        dst_p = Path(spec.target_canonical_path)
        if not src_p.is_file():
            raise FileMutationError(ErrorCode.TARGET_CHANGED, "Source file vanished before move.")
        if dst_p.exists():
            raise FileMutationError(ErrorCode.DENIED, "Destination now exists; no-overwrite guard blocked move.")
        if self._fs.snapshot_target(spec.source_canonical_path).snapshot_hash != spec.target_snapshot_hash:
            raise FileMutationError(ErrorCode.TARGET_CHANGED, "Source file changed after preview; re-approval required.")

        try:
            self._approvals.consume_approved_for_execution(
                approval_id,
                expected_bound_hash=spec.bound_hash,
                session_id=session.session_id,
                actor_ref=session.actor_ref,
                expected_tool_id="fs.file.move",
            )
        except ApprovalError as exc:
            raise FileMutationError(exc.code, str(exc)) from exc

        dst_p.parent.mkdir(parents=True, exist_ok=True)
        src_p.rename(dst_p)
        moved_sha = hashlib.sha256(dst_p.read_bytes()).hexdigest()

        with self._lock:
            self._pending_moves.pop(approval_id, None)

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'fs.file.move', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    session.actor_ref,
                    json.dumps(
                        {
                            "approval_id": approval_id,
                            "root_id": spec.root_id,
                            "from": spec.source_relative_path,
                            "to": spec.target_relative_path,
                        }
                    ),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return FileMutationReceipt(
            tool_id="fs.file.move",
            verified=True,
            canonical_path=spec.target_canonical_path,
            sha256=moved_sha,
            summary=f"File '{spec.source_relative_path}' dipindahkan aman ke '{spec.target_relative_path}'.",
        )
