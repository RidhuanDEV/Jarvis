"""Explicit Encrypted Memory Vault with Optimistic Locking & deletion_ledger Tombstones (B08, BR-14, T13)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal, Protocol

from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort, SecretVaultAndCryptoPort
from jarvis.infrastructure.crypto import decrypt_field, encrypt_field
from jarvis.infrastructure.dual_db import DualSqliteManager

MEMORY_DEK_REF = "jarvis.memory.master_dek.v1"


class _RowLike(Protocol):
    def __getitem__(self, key: str) -> Any: ...


class MemoryServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class MemoryRecord(StrictModel):
    id: str
    kind: Literal["fact", "preference", "instruction", "note"]
    content: str
    is_encrypted: bool
    sensitivity: Literal["normal", "sensitive"]
    source_ref: str
    status: Literal["active", "proposal", "superseded"]
    revision: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None


class MemoryVaultService:
    """Manages explicit personal memories with AES-256-GCM encryption for sensitive records."""

    def __init__(
        self,
        db: DualSqliteManager,
        vault: SecretVaultAndCryptoPort,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._vault = vault
        self._clock = clock

    def _dek(self) -> bytes:
        return self._vault.get_or_create_master_dek(MEMORY_DEK_REF)

    @staticmethod
    def _aad(memory_id: str) -> bytes:
        return f"memory:{memory_id}:content".encode()

    def create_memory(
        self,
        *,
        kind: Literal["fact", "preference", "instruction", "note"],
        content: str,
        sensitivity: Literal["normal", "sensitive"] = "normal",
        source_ref: str = "local_owner",
        status: Literal["active", "proposal"] = "active",
        expires_at: datetime | None = None,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> MemoryRecord:
        cleaned = content.strip()
        if not cleaned:
            raise MemoryServiceError(ErrorCode.INVALID_ARGS, "Memory content cannot be empty.")

        memory_id = str(uuid.uuid4())
        now = self._clock.now_utc()
        now_iso = now.isoformat()
        encrypt = sensitivity == "sensitive"
        stored_content = encrypt_field(self._dek(), cleaned, self._aad(memory_id)) if encrypt else cleaned

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO memory(
                    id, kind, content, is_encrypted, sensitivity, source_ref, status,
                    revision, created_at, updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    memory_id,
                    kind,
                    stored_content,
                    1 if encrypt else 0,
                    sensitivity,
                    source_ref,
                    status,
                    now_iso,
                    now_iso,
                    expires_at.isoformat() if expires_at else None,
                ),
            )
            conn.execute(
                """
                INSERT INTO memory_revision(id, memory_id, revision, change_reason, timestamp)
                VALUES (?, ?, 1, 'created', ?)
                """,
                (str(uuid.uuid4()), memory_id, now_iso),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'memory.created', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps(
                        {"memory_id": memory_id, "kind": kind, "sensitivity": sensitivity, "status": status}
                    ),
                    now_iso,
                ),
            )

        return MemoryRecord(
            id=memory_id,
            kind=kind,
            content=cleaned,
            is_encrypted=encrypt,
            sensitivity=sensitivity,
            source_ref=source_ref,
            status=status,
            revision=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

    def _hydrate_row(self, r: _RowLike) -> MemoryRecord:
        mem_id = str(r["id"])
        is_enc = bool(r["is_encrypted"])
        raw_content = str(r["content"])
        plain = decrypt_field(self._dek(), raw_content, self._aad(mem_id)) if is_enc else raw_content
        return MemoryRecord(
            id=mem_id,
            kind=str(r["kind"]),  # type: ignore[arg-type]
            content=plain,
            is_encrypted=is_enc,
            sensitivity=str(r["sensitivity"]),  # type: ignore[arg-type]
            source_ref=str(r["source_ref"]),
            status=str(r["status"]),  # type: ignore[arg-type]
            revision=int(r["revision"]),
            created_at=datetime.fromisoformat(str(r["created_at"])),
            updated_at=datetime.fromisoformat(str(r["updated_at"])),
            expires_at=datetime.fromisoformat(str(r["expires_at"])) if r["expires_at"] else None,
        )

    def list_memories(
        self,
        *,
        include_proposals: bool = False,
        query: str | None = None,
    ) -> list[MemoryRecord]:
        """List non-expired memories. Proposals are excluded by default so they never act as facts (BR-14)."""
        now = self._clock.now_utc()
        statuses = ("active", "proposal") if include_proposals else ("active",)
        placeholders = ",".join("?" for _ in statuses)
        with self._db.core_read() as conn:
            rows = conn.execute(
                f"SELECT * FROM memory WHERE status IN ({placeholders}) ORDER BY updated_at DESC",  # noqa: S608
                list(statuses),
            ).fetchall()

        q = query.strip().lower() if query else ""
        items: list[MemoryRecord] = []
        for row in rows:
            rec = self._hydrate_row(row)
            if rec.expires_at is not None and rec.expires_at <= now:
                continue
            if q and q not in rec.content.lower() and q not in rec.kind.lower():
                continue
            items.append(rec)
        return items

    def approve_proposal(
        self,
        memory_id: str,
        *,
        expected_revision: int,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> MemoryRecord:
        """Explicitly promote a pending preference proposal to active memory (BR-14)."""
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute(
                """
                UPDATE memory
                SET status = 'active', revision = revision + 1, updated_at = ?
                WHERE id = ? AND status = 'proposal' AND revision = ?
                """,
                (now_iso, memory_id, expected_revision),
            )
            if cur.rowcount != 1:
                raise MemoryServiceError(
                    ErrorCode.INVALID_ARGS,
                    f"Proposal '{memory_id}' not found or revision conflict (expected {expected_revision}).",
                )
            conn.execute(
                """
                INSERT INTO memory_revision(id, memory_id, revision, change_reason, timestamp)
                VALUES (?, ?, ?, 'owner_approved_proposal', ?)
                """,
                (str(uuid.uuid4()), memory_id, expected_revision + 1, now_iso),
            )
            row = conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        assert row is not None
        return self._hydrate_row(row)

    def update_memory(
        self,
        memory_id: str,
        *,
        expected_revision: int,
        new_content: str,
        change_reason: str = "user_edit",
        correlation_id: str,
        actor: str = "local_owner",
    ) -> MemoryRecord:
        cleaned = new_content.strip()
        if not cleaned:
            raise MemoryServiceError(ErrorCode.INVALID_ARGS, "Updated memory content cannot be empty.")
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            existing = conn.execute("SELECT sensitivity, revision FROM memory WHERE id = ?", (memory_id,)).fetchone()
            if existing is None:
                raise MemoryServiceError(ErrorCode.NOT_FOUND, f"Memory '{memory_id}' not found.")
            if int(existing["revision"]) != expected_revision:
                raise MemoryServiceError(
                    ErrorCode.INVALID_ARGS,
                    f"Optimistic lock mismatch: expected revision {expected_revision}, actual {existing['revision']}.",
                )
            encrypt = str(existing["sensitivity"]) == "sensitive"
            stored = encrypt_field(self._dek(), cleaned, self._aad(memory_id)) if encrypt else cleaned
            conn.execute(
                """
                UPDATE memory
                SET content = ?, is_encrypted = ?, revision = revision + 1, updated_at = ?
                WHERE id = ? AND revision = ?
                """,
                (stored, 1 if encrypt else 0, now_iso, memory_id, expected_revision),
            )
            # Metadata-only revision history — never duplicates old sensitive plaintext!
            conn.execute(
                """
                INSERT INTO memory_revision(id, memory_id, revision, change_reason, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid.uuid4()), memory_id, expected_revision + 1, change_reason, now_iso),
            )
            row = conn.execute("SELECT * FROM memory WHERE id = ?", (memory_id,)).fetchone()
        assert row is not None
        return self._hydrate_row(row)

    def delete_memory(
        self, memory_id: str, *, correlation_id: str, actor: str = "local_owner"
    ) -> bool:
        """Hard-delete memory and record mandatory deletion_ledger tombstone (FR-MEM-05, T13)."""
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute("DELETE FROM memory WHERE id = ?", (memory_id,))
            if cur.rowcount == 0:
                return False
            conn.execute(
                """
                INSERT INTO deletion_ledger(entity_type, entity_id, deleted_at)
                VALUES ('memory', ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET deleted_at = excluded.deleted_at
                """,
                (memory_id, now_iso),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'memory.deleted', 'completed', ?, ?)
                """,
                (str(uuid.uuid4()), correlation_id, actor, json.dumps({"memory_id": memory_id}), now_iso),
            )
        return True
