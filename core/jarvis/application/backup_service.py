"""Cross-Machine Portable Backup & Restore Service with deletion_ledger Replay (FR-ADM-08, DEC-007, T13)."""

from __future__ import annotations

import hashlib
import io
import json
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jarvis.domain.models import ErrorCode, StorageRootsConfig
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.crypto import (
    Argon2Params,
    CryptoIntegrityError,
    decrypt_portable_backup,
    encrypt_portable_backup,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.migrations import verify_integrity


class BackupServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BackupMetadata:
    backup_id: str
    created_at: str
    core_db_sha256: str
    core_db_bytes: int
    deletion_tombstone_count: int
    archive_path: str


@dataclass(frozen=True)
class RestoreSummary:
    backup_id: str
    restored_core_db_path: str
    replayed_tombstones: int
    remapped_roots: bool


class BackupService:
    """Creates, verifies, and restores Argon2id+AES-256-GCM encrypted portable backups."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        *,
        argon2_params: Argon2Params | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._argon2_params = argon2_params or Argon2Params()

    def create_backup(
        self,
        dest_archive_path: Path,
        recovery_passphrase: str,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> BackupMetadata:
        backup_id = str(uuid.uuid4())
        now_iso = self._clock.now_utc().isoformat()

        with tempfile.TemporaryDirectory(prefix="jarvis-bk-") as tmpdir:
            snap_path = Path(tmpdir) / "jarvis_core.db"
            self._db.snapshot_core(snap_path)
            db_bytes = snap_path.read_bytes()
            db_sha = hashlib.sha256(db_bytes).hexdigest()

            with self._db.core_read() as conn:
                tomb_count = int(conn.execute("SELECT COUNT(*) FROM deletion_ledger").fetchone()[0])

            manifest = {
                "schema_version": 1,
                "backup_id": backup_id,
                "created_at": now_iso,
                "core_db_sha256": db_sha,
                "core_db_bytes": len(db_bytes),
                "deletion_tombstone_count": tomb_count,
            }

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
                zf.writestr("jarvis_core.db", db_bytes)

            encrypted = encrypt_portable_backup(buf.getvalue(), recovery_passphrase, params=self._argon2_params)

        dest_archive_path.parent.mkdir(parents=True, exist_ok=True)
        staging = dest_archive_path.with_suffix(dest_archive_path.suffix + ".staging")
        staging.write_bytes(encrypted)
        staging.replace(dest_archive_path)

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'backup.created', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"backup_id": backup_id, "core_db_sha256": db_sha}),
                    now_iso,
                ),
            )

        return BackupMetadata(
            backup_id=backup_id,
            created_at=now_iso,
            core_db_sha256=db_sha,
            core_db_bytes=len(db_bytes),
            deletion_tombstone_count=tomb_count,
            archive_path=str(dest_archive_path),
        )

    def verify_backup(self, archive_path: Path, recovery_passphrase: str) -> BackupMetadata:
        if not archive_path.exists():
            raise BackupServiceError(ErrorCode.NOT_FOUND, f"Backup archive not found: {archive_path}")
        try:
            plain_zip = decrypt_portable_backup(archive_path.read_bytes(), recovery_passphrase)
        except CryptoIntegrityError as exc:
            raise BackupServiceError(ErrorCode.DENIED, str(exc)) from exc

        with zipfile.ZipFile(io.BytesIO(plain_zip), mode="r") as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            db_bytes = zf.read("jarvis_core.db")

        actual_sha = hashlib.sha256(db_bytes).hexdigest()
        if actual_sha != str(manifest["core_db_sha256"]):
            raise BackupServiceError(ErrorCode.INTERNAL, "Backup archive core_db SHA-256 mismatch.")

        with tempfile.TemporaryDirectory(prefix="jarvis-bk-verify-") as tmpdir:
            check_db = Path(tmpdir) / "verify.db"
            check_db.write_bytes(db_bytes)
            conn = sqlite3.connect(str(check_db))
            try:
                verify_integrity(conn)
            finally:
                conn.close()

        return BackupMetadata(
            backup_id=str(manifest["backup_id"]),
            created_at=str(manifest["created_at"]),
            core_db_sha256=actual_sha,
            core_db_bytes=len(db_bytes),
            deletion_tombstone_count=int(manifest.get("deletion_tombstone_count", 0)),
            archive_path=str(archive_path),
        )

    def restore_into_directory(
        self,
        archive_path: Path,
        recovery_passphrase: str,
        *,
        target_core_db_path: Path,
        target_knowledge_db_path: Path,
        preserve_local_tombstones: list[tuple[str, str, str]] | None = None,
        remapped_storage_roots: StorageRootsConfig | None = None,
    ) -> RestoreSummary:
        """Restore encrypted portable backup onto target paths & replay deletion_ledger (T13)."""
        meta = self.verify_backup(archive_path, recovery_passphrase)
        plain_zip = decrypt_portable_backup(archive_path.read_bytes(), recovery_passphrase)
        with zipfile.ZipFile(io.BytesIO(plain_zip), mode="r") as zf:
            db_bytes = zf.read("jarvis_core.db")

        target_core_db_path.parent.mkdir(parents=True, exist_ok=True)
        staging_db = target_core_db_path.with_suffix(".db.staging")
        staging_db.write_bytes(db_bytes)
        staging_db.replace(target_core_db_path)

        # Open restored DualSqliteManager, merge any newer local tombstones, and replay deletion_ledger
        restored_db = DualSqliteManager(target_core_db_path, target_knowledge_db_path, load_sqlite_vec=False)
        try:
            restored_db.initialize()
            if preserve_local_tombstones:
                with restored_db.core_tx() as conn:
                    for etype, eid, deleted_at in preserve_local_tombstones:
                        conn.execute(
                            """
                            INSERT INTO deletion_ledger(entity_type, entity_id, deleted_at)
                            VALUES (?, ?, ?)
                            ON CONFLICT(entity_type, entity_id) DO NOTHING
                            """,
                            (etype, eid, deleted_at),
                        )

            remapped = False
            if remapped_storage_roots is not None:
                with restored_db.core_tx() as conn:
                    row = conn.execute(
                        "SELECT revision, config_json FROM config_revision WHERE is_active = 1 LIMIT 1"
                    ).fetchone()
                    if row is not None:
                        cfg = json.loads(str(row["config_json"]))
                        cfg["storage"]["roots"] = remapped_storage_roots.model_dump(mode="json")
                        conn.execute(
                            "UPDATE config_revision SET config_json = ? WHERE revision = ?",
                            (json.dumps(cfg, sort_keys=True, separators=(",", ":")), int(row["revision"])),
                        )
                        remapped = True

            replayed = restored_db.replay_deletion_ledger()
        finally:
            restored_db.close()

        return RestoreSummary(
            backup_id=meta.backup_id,
            restored_core_db_path=str(target_core_db_path),
            replayed_tombstones=replayed,
            remapped_roots=remapped,
        )
