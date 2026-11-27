"""SHA-256 checksummed SQLite migration runner with pre-migration Online Backup & integrity check."""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


class MigrationChecksumMismatchError(RuntimeError):
    """Raised when an already-applied migration SQL file differs from its recorded SHA-256."""


class DatabaseIntegrityError(RuntimeError):
    """Raised when PRAGMA integrity_check fails."""


@dataclass(frozen=True)
class AppliedMigration:
    version: int
    filename: str
    sha256: str
    applied_at: str


def _ensure_tracking_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migration (
            version INTEGER PRIMARY KEY,
            filename TEXT NOT NULL UNIQUE,
            sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def verify_integrity(conn: sqlite3.Connection) -> None:
    """Run PRAGMA integrity_check and raise if database is corrupt."""
    rows = conn.execute("PRAGMA integrity_check").fetchall()
    results = [str(r[0]) for r in rows]
    if results != ["ok"]:
        raise DatabaseIntegrityError(f"SQLite integrity_check failed: {results}")


def online_backup_sqlite(source_conn: sqlite3.Connection, dest_path: Path) -> Path:
    """Create a WAL-consistent snapshot using SQLite Online Backup API."""
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".staging")
    if tmp_path.exists():
        tmp_path.unlink()
    dst_conn = sqlite3.connect(str(tmp_path))
    try:
        source_conn.backup(dst_conn)
        dst_conn.commit()
        verify_integrity(dst_conn)
    finally:
        dst_conn.close()
    tmp_path.replace(dest_path)
    return dest_path


def _split_sql_statements(sql_text: str) -> list[str]:
    """Split a migration SQL script into executable statements without sqlite3.executescript() implicit COMMIT."""
    statements: list[str] = []
    buf: list[str] = []
    for line in sql_text.splitlines(keepends=True):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf.append(line)
        candidate = "".join(buf)
        if sqlite3.complete_statement(candidate):
            cleaned = candidate.strip()
            if cleaned and cleaned != ";":
                statements.append(cleaned)
            buf.clear()
    leftover = "".join(buf).strip()
    if leftover and not leftover.startswith("--"):
        statements.append(leftover)
    return statements


def apply_migrations(
    conn: sqlite3.Connection,
    migrations_dir: Path,
    *,
    pre_migration_backup_dir: Path | None = None,
) -> list[AppliedMigration]:
    """Apply numbered *.sql migrations atomically inside a real SQLite transaction (B19, DEF-06)."""
    _ensure_tracking_table(conn)
    sql_files = sorted(migrations_dir.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    existing = {
        int(row[0]): (str(row[1]), str(row[2]), str(row[3]))
        for row in conn.execute("SELECT version, filename, sha256, applied_at FROM schema_migration").fetchall()
    }

    pending: list[tuple[int, str, str, str]] = []
    for path in sql_files:
        version_prefix = path.name.split("_", 1)[0]
        version = int(version_prefix)
        sql_text = path.read_text(encoding="utf-8")
        digest = hashlib.sha256(sql_text.encode("utf-8")).hexdigest()
        if version in existing:
            prev_filename, prev_sha, _ = existing[version]
            if prev_sha != digest or prev_filename != path.name:
                raise MigrationChecksumMismatchError(
                    f"Migration {version:04d} ({path.name}) checksum mismatch: expected {prev_sha}, got {digest}."
                )
        else:
            pending.append((version, path.name, digest, sql_text))

    if pending and pre_migration_backup_dir is not None and existing:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        online_backup_sqlite(conn, pre_migration_backup_dir / f"pre_migration_{ts}.db")

    newly_applied: list[AppliedMigration] = []
    for version, filename, digest, sql_text in pending:
        now_iso = datetime.now(tz=UTC).isoformat()
        stmts = _split_sql_statements(sql_text)
        # B19: execute DDL/DML + schema_migration insert inside one atomic transaction (never implicit-commit executescript!)
        prev_isolation = conn.isolation_level
        conn.commit()
        conn.isolation_level = None
        try:
            conn.execute("BEGIN IMMEDIATE")
            for stmt in stmts:
                conn.execute(stmt)
            conn.execute(
                """
                INSERT INTO schema_migration(version, filename, sha256, applied_at)
                VALUES (?, ?, ?, ?)
                """,
                (version, filename, digest, now_iso),
            )
            conn.execute("COMMIT")
        except Exception:
            if conn.in_transaction:
                conn.execute("ROLLBACK")
            raise
        finally:
            conn.isolation_level = prev_isolation
        newly_applied.append(AppliedMigration(version=version, filename=filename, sha256=digest, applied_at=now_iso))

    verify_integrity(conn)
    return newly_applied
