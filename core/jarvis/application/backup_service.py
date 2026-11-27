"""Cross-Machine Portable Backup & Restore Service with deletion_ledger Replay (FR-ADM-08, DEC-007, T13)."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from jarvis.domain.models import ErrorCode, StorageRootsConfig
from jarvis.domain.ports import ClockPort, FilesystemSafetyPort, SecretVaultAndCryptoPort
from jarvis.infrastructure.crypto import (
    AES_KEY_LEN,
    Argon2Params,
    CryptoIntegrityError,
    decrypt_field,
    decrypt_portable_backup,
    encrypt_field,
    encrypt_portable_backup,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.migrations import verify_integrity

MAX_RESTORE_CORE_DB_BYTES = 256 * 1024 * 1024  # 256 MiB archive extraction safety ceiling
MEMORY_DEK_REF = "jarvis.memory.master_dek.v1"


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
    has_wrapped_dek: bool = False


@dataclass(frozen=True)
class RestoreSummary:
    backup_id: str
    restored_core_db_path: str
    replayed_tombstones: int
    remapped_roots: bool
    reencrypted_sensitive_memories: int = 0


class BackupService:
    """Creates, verifies, and restores Argon2id+AES-256-GCM encrypted portable backups with wrapped DEK (B19)."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        *,
        argon2_params: Argon2Params | None = None,
        allowed_backup_root: Path | None = None,
        fs_port: FilesystemSafetyPort | None = None,
        vault: SecretVaultAndCryptoPort | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._argon2_params = argon2_params or Argon2Params()
        self._allowed_backup_root = allowed_backup_root
        self._fs = fs_port
        self._vault = vault

    def _validate_archive_target(self, dest_archive_path: Path) -> Path:
        """Enforce managed backup root containment, anti-symlink, and strict no-clobber (IR-02, B03)."""
        if dest_archive_path.is_symlink():
            raise BackupServiceError(ErrorCode.DENIED, "Backup destination must not be a symlink.")
        if self._fs is not None and self._fs.inspect_path(str(dest_archive_path)).is_reparse_point:
            raise BackupServiceError(ErrorCode.DENIED, "Backup destination must not be a reparse point.")

        if self._allowed_backup_root is not None:
            allowed_root = self._allowed_backup_root.resolve(strict=False)
            allowed_root.mkdir(parents=True, exist_ok=True)
            resolved_dest = dest_archive_path.resolve(strict=False)
            if not resolved_dest.is_relative_to(allowed_root) or resolved_dest == allowed_root:
                raise BackupServiceError(
                    ErrorCode.DENIED,
                    "Backup destination must reside inside the configured managed backups root.",
                )
            if ".." in dest_archive_path.parts:
                raise BackupServiceError(ErrorCode.DENIED, "Path traversal components are prohibited in backup path.")
            # Verify parent chain inside allowed root has no reparse points
            for parent in resolved_dest.parents:
                if parent == allowed_root:
                    break
                if parent.is_symlink() or (
                    self._fs is not None and parent.exists() and self._fs.inspect_path(str(parent)).is_reparse_point
                ):
                    raise BackupServiceError(ErrorCode.DENIED, "Backup destination traverses a symlink/reparse point.")
            dest_archive_path = resolved_dest

        if dest_archive_path.exists():
            raise BackupServiceError(
                ErrorCode.DENIED,
                f"Backup destination '{dest_archive_path.name}' already exists; overwriting files is strictly prohibited (no-clobber).",
            )
        return dest_archive_path

    def create_backup(
        self,
        dest_archive_path: Path,
        recovery_passphrase: str,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> BackupMetadata:
        dest_archive_path = self._validate_archive_target(dest_archive_path)
        backup_id = str(uuid.uuid4())
        now_iso = self._clock.now_utc().isoformat()

        with tempfile.TemporaryDirectory(prefix="jarvis-bk-") as tmpdir:
            snap_path = Path(tmpdir) / "jarvis_core.db"
            self._db.snapshot_core(snap_path)
            db_bytes = snap_path.read_bytes()
            db_sha = hashlib.sha256(db_bytes).hexdigest()

            with self._db.core_read() as conn:
                tomb_count = int(conn.execute("SELECT COUNT(*) FROM deletion_ledger").fetchone()[0])

            has_wrapped_dek = self._vault is not None
            wrapped_keys_payload: dict[str, str] | None = None
            if self._vault is not None:
                dek = self._vault.get_or_create_master_dek(MEMORY_DEK_REF)
                if len(dek) != AES_KEY_LEN:
                    raise BackupServiceError(ErrorCode.INTERNAL, "Master memory DEK must be 32 bytes.")
                wrapped_keys_payload = {
                    MEMORY_DEK_REF: base64.b64encode(dek).decode("ascii"),
                }

            manifest = {
                "schema_version": 2 if has_wrapped_dek else 1,
                "backup_id": backup_id,
                "created_at": now_iso,
                "core_db_sha256": db_sha,
                "core_db_bytes": len(db_bytes),
                "deletion_tombstone_count": tomb_count,
                "has_wrapped_dek": has_wrapped_dek,
            }

            buf = io.BytesIO()
            with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
                zf.writestr("jarvis_core.db", db_bytes)
                if wrapped_keys_payload is not None:
                    # Strictly inside the Argon2id + AES-256-GCM encrypted archive envelope (B19, U-D02)
                    zf.writestr("wrapped_keys.json", json.dumps(wrapped_keys_payload, sort_keys=True))

            encrypted = encrypt_portable_backup(buf.getvalue(), recovery_passphrase, params=self._argon2_params)

        dest_archive_path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation (O_CREAT | O_EXCL) guarantees atomic no-clobber against race conditions
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_BINARY"):
            flags |= os.O_BINARY
        try:
            fd = os.open(str(dest_archive_path), flags, 0o600)
        except FileExistsError as exc:
            raise BackupServiceError(
                ErrorCode.DENIED,
                "Backup destination already exists; no-clobber protection blocked overwrite.",
            ) from exc
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(encrypted)
                fh.flush()
                os.fsync(fh.fileno())
        except Exception:
            dest_archive_path.unlink(missing_ok=True)
            raise

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
            has_wrapped_dek=has_wrapped_dek,
        )

    def verify_backup(self, archive_path: Path, recovery_passphrase: str) -> BackupMetadata:
        if not archive_path.exists():
            raise BackupServiceError(ErrorCode.NOT_FOUND, f"Backup archive not found: {archive_path}")
        try:
            plain_zip = decrypt_portable_backup(archive_path.read_bytes(), recovery_passphrase)
        except CryptoIntegrityError as exc:
            raise BackupServiceError(ErrorCode.DENIED, str(exc)) from exc

        with zipfile.ZipFile(io.BytesIO(plain_zip), mode="r") as zf:
            names = set(zf.namelist())
            if not {"manifest.json", "jarvis_core.db"}.issubset(names):
                raise BackupServiceError(ErrorCode.INVALID_ARGS, "Backup archive missing required entries.")
            for info in zf.infolist():
                if info.filename.startswith(("/", "\\")) or ".." in Path(info.filename).parts:
                    raise BackupServiceError(ErrorCode.DENIED, "Backup archive contains unsafe entry path.")
                if info.file_size > MAX_RESTORE_CORE_DB_BYTES:
                    raise BackupServiceError(ErrorCode.INVALID_ARGS, "Backup entry exceeds safe extraction limit.")
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
            has_wrapped_dek=bool(manifest.get("has_wrapped_dek", False)),
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
        target_vault: SecretVaultAndCryptoPort | None = None,
    ) -> RestoreSummary:
        """Restore encrypted portable backup onto target paths, re-key encrypted memories & replay tombstones (B19, U-D02)."""
        meta = self.verify_backup(archive_path, recovery_passphrase)
        plain_zip = decrypt_portable_backup(archive_path.read_bytes(), recovery_passphrase)
        backup_dek: bytes | None = None
        with zipfile.ZipFile(io.BytesIO(plain_zip), mode="r") as zf:
            db_bytes = zf.read("jarvis_core.db")
            if "wrapped_keys.json" in zf.namelist():
                try:
                    wk = json.loads(zf.read("wrapped_keys.json").decode("utf-8"))
                    raw_b64 = str(wk.get(MEMORY_DEK_REF, ""))
                    decoded = base64.b64decode(raw_b64, validate=True)
                    if len(decoded) != AES_KEY_LEN:
                        raise ValueError("Invalid DEK length")
                    backup_dek = decoded
                except Exception as exc:
                    raise BackupServiceError(
                        ErrorCode.DENIED, "Wrapped recovery DEK in backup archive is corrupted (fail closed)."
                    ) from exc

        target_core_db_path.parent.mkdir(parents=True, exist_ok=True)
        staging_db = target_core_db_path.with_suffix(".db.staging")
        staging_db.write_bytes(db_bytes)
        staging_db.replace(target_core_db_path)

        # Open restored DualSqliteManager, merge any newer local tombstones, replay deletion_ledger & re-key sensitive rows
        restored_db = DualSqliteManager(target_core_db_path, target_knowledge_db_path, load_sqlite_vec=False)
        reencrypted_count = 0
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

            # B19 / U-D02: cross-machine portability — re-encrypt surviving is_encrypted=1 memories onto target machine DEK!
            if target_vault is not None:
                with restored_db.core_read() as conn:
                    enc_rows = conn.execute(
                        "SELECT id, content FROM memory WHERE is_encrypted = 1"
                    ).fetchall()
                if enc_rows:
                    if backup_dek is None:
                        raise BackupServiceError(
                            ErrorCode.DENIED,
                            "Backup contains encrypted sensitive memories but lacks wrapped recovery DEK (fail closed).",
                        )
                    target_dek = target_vault.get_or_create_master_dek(MEMORY_DEK_REF)
                    with restored_db.core_tx() as conn:
                        for erow in enc_rows:
                            mem_id = str(erow["id"])
                            aad = f"memory:{mem_id}:content".encode()
                            try:
                                plaintext = decrypt_field(backup_dek, str(erow["content"]), aad)
                            except CryptoIntegrityError as exc:
                                raise BackupServiceError(
                                    ErrorCode.DENIED,
                                    f"Failed authenticating restored sensitive memory '{mem_id}' with wrapped DEK.",
                                ) from exc
                            new_cipher = encrypt_field(target_dek, plaintext, aad)
                            conn.execute(
                                "UPDATE memory SET content = ? WHERE id = ?",
                                (new_cipher, mem_id),
                            )
                            reencrypted_count += 1
        finally:
            restored_db.close()

        return RestoreSummary(
            backup_id=meta.backup_id,
            restored_core_db_path=str(target_core_db_path),
            replayed_tombstones=replayed,
            remapped_roots=remapped,
            reencrypted_sensitive_memories=reencrypted_count,
        )
