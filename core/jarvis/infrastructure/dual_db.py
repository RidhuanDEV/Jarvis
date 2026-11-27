"""Dual SQLite WAL Persistence Manager & Cross-DB Consistency Guard (DEC-007, NFR-05).

- jarvis_core.db: authoritative ACID store (synchronous=FULL, single-writer lock).
- jarvis_knowledge.db: derived rebuildable index store (synchronous=NORMAL, FTS5 + optional sqlite-vec).
- Never ATTACH-joins writes; every knowledge read filters strictly against active source_root
  and deletion_ledger from jarvis_core.db.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from jarvis.infrastructure.migrations import apply_migrations, online_backup_sqlite, verify_integrity

MIGRATIONS_BASE = Path(__file__).resolve().parents[2] / "migrations"


def resolve_migrations_base() -> Path:
    """Resolve bundled migrations directory cleanly for both standalone installers (B18) and repo runs."""
    override = os.environ.get("JARVIS_MIGRATIONS_DIR", "").strip()
    if override:
        cand = Path(override)
        if cand.is_dir():
            return cand
    return MIGRATIONS_BASE


@dataclass(frozen=True)
class KnowledgeSearchHit:
    chunk_id: str
    document_id: str
    root_id: str
    relative_path: str
    ordinal: int
    locator_json: str
    text: str


class DualSqliteManager:
    """Manages isolated core and knowledge SQLite WAL databases with cross-DB invariants."""

    def __init__(
        self,
        core_db_path: Path,
        knowledge_db_path: Path,
        *,
        pre_migration_backup_dir: Path | None = None,
        load_sqlite_vec: bool = True,
    ) -> None:
        self.core_db_path = core_db_path
        self.knowledge_db_path = knowledge_db_path
        self.pre_migration_backup_dir = pre_migration_backup_dir
        self._load_sqlite_vec = load_sqlite_vec
        self._core_lock = threading.RLock()
        self._knowledge_lock = threading.RLock()
        self._vec_loaded = False

        self.core_db_path.parent.mkdir(parents=True, exist_ok=True)
        self.knowledge_db_path.parent.mkdir(parents=True, exist_ok=True)

        self._core_conn = self._open_connection(self.core_db_path, synchronous="FULL", load_vec=False)
        self._knowledge_conn = self._open_connection(
            self.knowledge_db_path, synchronous="NORMAL", load_vec=load_sqlite_vec
        )

    @property
    def sqlite_vec_loaded(self) -> bool:
        return self._vec_loaded

    def _open_connection(self, db_path: Path, *, synchronous: str, load_vec: bool) -> sqlite3.Connection:
        conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute(f"PRAGMA synchronous = {synchronous}")
        conn.execute("PRAGMA busy_timeout = 5000")
        if load_vec:
            try:
                import sqlite_vec

                conn.enable_load_extension(True)
                sqlite_vec.load(conn)
                conn.enable_load_extension(False)
                self._vec_loaded = True
            except Exception:
                self._vec_loaded = False
        return conn

    def initialize(self) -> None:
        """Apply checksummed migrations on both DBs and run startup orphan GC (DEC-007)."""
        mig_base = resolve_migrations_base()
        with self._core_lock:
            apply_migrations(
                self._core_conn,
                mig_base / "core",
                pre_migration_backup_dir=self.pre_migration_backup_dir,
            )
        with self._knowledge_lock:
            apply_migrations(self._knowledge_conn, mig_base / "knowledge")
        self.gc_revoked_knowledge()

    def snapshot_knowledge(self, dest_path: Path) -> Path:
        """Create a WAL-consistent Online Backup snapshot of jarvis_knowledge.db (B19)."""
        with self._knowledge_lock:
            return online_backup_sqlite(self._knowledge_conn, dest_path)

    @contextmanager
    def core_tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized ACID transaction context on jarvis_core.db."""
        with self._core_lock, self._core_conn:
            yield self._core_conn

    @contextmanager
    def core_read(self) -> Iterator[sqlite3.Connection]:
        with self._core_lock:
            yield self._core_conn

    @contextmanager
    def knowledge_tx(self) -> Iterator[sqlite3.Connection]:
        """Serialized write transaction context on jarvis_knowledge.db."""
        with self._knowledge_lock, self._knowledge_conn:
            yield self._knowledge_conn

    @contextmanager
    def knowledge_read(self) -> Iterator[sqlite3.Connection]:
        with self._knowledge_lock:
            yield self._knowledge_conn

    def check_health_fast(self) -> dict[str, bool]:
        """Lightweight liveness/readiness check (SELECT 1) safe for high-frequency health polling (IR-17, B07)."""
        with self._core_lock:
            core_ok = self._core_conn.execute("SELECT 1").fetchone() is not None
        with self._knowledge_lock:
            know_ok = self._knowledge_conn.execute("SELECT 1").fetchone() is not None
        return {"core_db_ok": core_ok, "knowledge_db_ok": know_ok, "sqlite_vec_loaded": self._vec_loaded}

    def check_health(self) -> dict[str, bool]:
        """Deep SQLite PRAGMA integrity_check across both databases (use off event loop or explicit diagnostics)."""
        with self._core_lock:
            verify_integrity(self._core_conn)
        with self._knowledge_lock:
            verify_integrity(self._knowledge_conn)
        return {"core_db_ok": True, "knowledge_db_ok": True, "sqlite_vec_loaded": self._vec_loaded}

    def snapshot_core(self, dest_path: Path) -> Path:
        with self._core_lock:
            return online_backup_sqlite(self._core_conn, dest_path)

    def _get_authorized_roots_and_tombstones(
        self,
    ) -> tuple[dict[str, int], set[str], set[str], set[str]]:
        """Read authoritative source_root permissions and deletion_ledger from jarvis_core.db."""
        with self._core_lock:
            root_rows = self._core_conn.execute(
                "SELECT id, revision FROM source_root WHERE enabled = 1 AND revoked_at IS NULL"
            ).fetchall()
            active_roots = {str(r["id"]): int(r["revision"]) for r in root_rows}

            tomb_rows = self._core_conn.execute("SELECT entity_type, entity_id FROM deletion_ledger").fetchall()
            deleted_roots = {str(r["entity_id"]) for r in tomb_rows if r["entity_type"] == "source_root"}
            deleted_docs = {str(r["entity_id"]) for r in tomb_rows if r["entity_type"] == "document"}
            deleted_chunks = {str(r["entity_id"]) for r in tomb_rows if r["entity_type"] == "chunk"}
        for rid in deleted_roots:
            active_roots.pop(rid, None)
        return active_roots, deleted_roots, deleted_docs, deleted_chunks

    def query_knowledge_fts(self, query_text: str, *, limit: int = 10) -> list[KnowledgeSearchHit]:
        """Query knowledge FTS5 strictly filtered by core.db active source_root & deletion_ledger."""
        cleaned = query_text.strip()
        if not cleaned:
            return []

        active_roots, _deleted_roots, deleted_docs, deleted_chunks = self._get_authorized_roots_and_tombstones()
        if not active_roots:
            return []

        placeholders = ",".join("?" for _ in active_roots)
        params: list[object] = [cleaned, *active_roots.keys(), max(1, min(limit * 3, 100))]

        with self._knowledge_lock:
            rows = self._knowledge_conn.execute(
                f"""
                SELECT c.id AS chunk_id, c.document_id, c.root_id, d.root_revision,
                       d.relative_path, c.ordinal, c.locator_json, c.text
                FROM chunk_fts f
                JOIN chunk c ON c.id = f.chunk_id
                JOIN document d ON d.id = c.document_id
                WHERE chunk_fts MATCH ?
                  AND c.root_id IN ({placeholders})
                LIMIT ?
                """,  # noqa: S608
                params,
            ).fetchall()

        hits: list[KnowledgeSearchHit] = []
        for row in rows:
            root_id = str(row["root_id"])
            doc_id = str(row["document_id"])
            chunk_id = str(row["chunk_id"])
            if active_roots.get(root_id) != int(row["root_revision"]):
                continue
            if doc_id in deleted_docs or chunk_id in deleted_chunks:
                continue
            hits.append(
                KnowledgeSearchHit(
                    chunk_id=chunk_id,
                    document_id=doc_id,
                    root_id=root_id,
                    relative_path=str(row["relative_path"]),
                    ordinal=int(row["ordinal"]),
                    locator_json=str(row["locator_json"]),
                    text=str(row["text"]),
                )
            )
            if len(hits) >= limit:
                break
        return hits

    def gc_revoked_knowledge(self) -> int:
        """Idempotently purge documents/chunks/file_metadata for revoked or tombstoned source roots."""
        active_roots, _deleted_roots, deleted_docs, deleted_chunks = self._get_authorized_roots_and_tombstones()
        removed = 0
        with self._knowledge_lock, self._knowledge_conn:
            has_file_meta = (
                self._knowledge_conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'file_metadata'"
                ).fetchone()
                is not None
            )
            if not active_roots:
                cur = self._knowledge_conn.execute("DELETE FROM document")
                removed += cur.rowcount
                if has_file_meta:
                    cur = self._knowledge_conn.execute("DELETE FROM file_metadata")
                    removed += cur.rowcount
            else:
                placeholders = ",".join("?" for _ in active_roots)
                cur = self._knowledge_conn.execute(
                    f"DELETE FROM document WHERE root_id NOT IN ({placeholders})",  # noqa: S608
                    list(active_roots.keys()),
                )
                removed += cur.rowcount
                if has_file_meta:
                    cur = self._knowledge_conn.execute(
                        f"DELETE FROM file_metadata WHERE root_id NOT IN ({placeholders})",  # noqa: S608
                        list(active_roots.keys()),
                    )
                    removed += cur.rowcount
                for root_id, revision in active_roots.items():
                    cur = self._knowledge_conn.execute(
                        "DELETE FROM document WHERE root_id = ? AND root_revision != ?",
                        (root_id, revision),
                    )
                    removed += cur.rowcount
                    if has_file_meta:
                        cur = self._knowledge_conn.execute(
                            "DELETE FROM file_metadata WHERE root_id = ? AND root_revision != ?",
                            (root_id, revision),
                        )
                        removed += cur.rowcount
            for doc_id in deleted_docs:
                cur = self._knowledge_conn.execute("DELETE FROM document WHERE id = ?", (doc_id,))
                removed += cur.rowcount
            for chunk_id in deleted_chunks:
                cur = self._knowledge_conn.execute("DELETE FROM chunk WHERE id = ?", (chunk_id,))
                removed += cur.rowcount
        return removed

    def record_deletion_tombstone(self, entity_type: str, entity_id: str) -> None:
        """Record an entity deletion in deletion_ledger for backup restore replay (T13)."""
        now_iso = datetime.now(tz=UTC).isoformat()
        with self.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO deletion_ledger(entity_type, entity_id, deleted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(entity_type, entity_id) DO UPDATE SET deleted_at = excluded.deleted_at
                """,
                (entity_type, entity_id, now_iso),
            )

    def replay_deletion_ledger(self) -> int:
        """Replay deletion_ledger against active core and knowledge tables before reopening (T13)."""
        entity_table_map = {
            "memory": "memory",
            "reminder": "reminder",
            "task": "task",
            "source_root": "source_root",
            "workflow": "workflow",
            "calendar_event": "calendar_event",
            "expense": "expense",
        }
        purged = 0
        with self.core_tx() as conn:
            tombstones = conn.execute("SELECT entity_type, entity_id FROM deletion_ledger").fetchall()
            for row in tombstones:
                etype = str(row["entity_type"])
                eid = str(row["entity_id"])
                table = entity_table_map.get(etype)
                if table is not None:
                    cur = conn.execute(f"DELETE FROM {table} WHERE id = ?", (eid,))  # noqa: S608
                    purged += cur.rowcount
        purged += self.gc_revoked_knowledge()
        return purged

    def close(self) -> None:
        with self._core_lock:
            self._core_conn.close()
        with self._knowledge_lock:
            self._knowledge_conn.close()
