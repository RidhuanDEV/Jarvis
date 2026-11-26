"""11-Root Dynamic Storage Manager, Cache Quota LRU & Safe Staged Migration (DEC-003, DEC-019, BR-SYS-02)."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jarvis.application.config_service import ConfigService
from jarvis.domain.models import (
    EVICTABLE_CACHE_CATEGORIES,
    WAL_DATABASE_CATEGORIES,
    ErrorCode,
    StorageCategory,
    StorageLocationRecord,
    StorageVolumeInfo,
)
from jarvis.domain.ports import ClockPort, FilesystemSafetyPort
from jarvis.infrastructure.dual_db import DualSqliteManager


class StorageServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class CacheCleanupResult:
    category: StorageCategory
    deleted_files: int
    freed_bytes: int
    remaining_bytes: int


@dataclass(frozen=True)
class MigrationResult:
    category: StorageCategory
    source_path: str
    target_path: str
    files_verified: int
    total_bytes: int
    rolled_back: bool


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


class StorageService:
    """Manages all 11 independent storage roots, WAL FS guards, LRU cache eviction, and staged migration."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        fs_port: FilesystemSafetyPort,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._config = config_service
        self._fs = fs_port
        self._clock = clock

    def sync_locations_from_config(self) -> list[StorageLocationRecord]:
        """Materialize all 11 configured storage roots into storage_location table."""
        active = self._config.get_active().document
        cat_map = active.storage.roots.as_category_map()
        now = self._clock.now_utc()
        now_iso = now.isoformat()
        records: list[StorageLocationRecord] = []

        with self._db.core_tx() as conn:
            for category, raw_path in cat_map.items():
                inspection = self._fs.inspect_path(raw_path)
                quota = active.storage.cache_quota_bytes if category == StorageCategory.CACHE else None
                status = "healthy"
                if category in WAL_DATABASE_CATEGORIES:
                    wal_ok, _ = self._fs.is_wal_supported_path(raw_path)
                    if not wal_ok:
                        status = "blocked"
                elif not inspection.exists and inspection.is_removable:
                    status = "offline"

                conn.execute(
                    """
                    INSERT INTO storage_location(
                        category, resolved_path, quota_bytes, is_removable, filesystem_kind, status, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(category) DO UPDATE SET
                        resolved_path = excluded.resolved_path,
                        quota_bytes = excluded.quota_bytes,
                        is_removable = excluded.is_removable,
                        filesystem_kind = excluded.filesystem_kind,
                        status = excluded.status,
                        updated_at = excluded.updated_at
                    """,
                    (
                        category.value,
                        inspection.canonical_path,
                        quota,
                        1 if inspection.is_removable else 0,
                        inspection.filesystem_kind,
                        status,
                        now_iso,
                    ),
                )
                records.append(
                    StorageLocationRecord(
                        category=category,
                        resolved_path=inspection.canonical_path,
                        quota_bytes=quota,
                        is_removable=inspection.is_removable,
                        filesystem_kind=inspection.filesystem_kind,
                        status=status,  # type: ignore[arg-type]
                        updated_at=now,
                    )
                )
        return records

    def list_volumes(self) -> tuple[StorageVolumeInfo, ...]:
        return self._fs.list_volumes()

    def list_locations(self) -> list[StorageLocationRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT category, resolved_path, quota_bytes, is_removable, filesystem_kind, status, updated_at
                FROM storage_location
                ORDER BY category ASC
                """
            ).fetchall()
        if not rows:
            return self.sync_locations_from_config()
        return [
            StorageLocationRecord(
                category=StorageCategory(str(r["category"])),
                resolved_path=str(r["resolved_path"]),
                quota_bytes=int(r["quota_bytes"]) if r["quota_bytes"] is not None else None,
                is_removable=bool(r["is_removable"]),
                filesystem_kind=str(r["filesystem_kind"]),
                status=str(r["status"]),  # type: ignore[arg-type]
                updated_at=(
                    self._clock.now_utc() if not r["updated_at"] else datetime.fromisoformat(str(r["updated_at"]))
                ),
            )
            for r in rows
        ]

    def set_location(
        self,
        category: StorageCategory,
        new_path: str,
        *,
        quota_bytes: int | None = None,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> StorageLocationRecord:
        """Update one storage root with WAL filesystem enforcement (DEC-003, DEC-019, BR-SYS-01)."""
        if category in WAL_DATABASE_CATEGORIES:
            wal_ok, reason = self._fs.is_wal_supported_path(new_path)
            if not wal_ok:
                raise StorageServiceError(
                    ErrorCode.UNSUPPORTED_FILESYSTEM,
                    f"Cannot place WAL database '{category.value}' on '{new_path}': {reason}",
                )

        inspection = self._fs.inspect_path(new_path)
        if not inspection.writable:
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' is not writable.",
            )

        active_doc = self._config.get_active().document
        updated_roots = active_doc.storage.roots.model_copy(update={category.value: inspection.canonical_path})
        updated_storage = active_doc.storage.model_copy(
            update={
                "roots": updated_roots,
                "cache_quota_bytes": (
                    quota_bytes if category == StorageCategory.CACHE else active_doc.storage.cache_quota_bytes
                ),
            }
        )
        updated_doc = active_doc.model_copy(update={"storage": updated_storage})
        self._config.save_revision(updated_doc, source="user", correlation_id=correlation_id, actor=actor)
        records = self.sync_locations_from_config()
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'storage.location_updated', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps(
                        {
                            "category": category.value,
                            "filesystem_kind": inspection.filesystem_kind,
                            "is_removable": inspection.is_removable,
                        }
                    ),
                    now_iso,
                ),
            )
        return next(r for r in records if r.category == category)

    def add_shared_model_directory(
        self, directory_path: str, *, correlation_id: str, actor: str = "local_owner"
    ) -> tuple[str, ...]:
        """Register an external shared model directory without copying multi-GB weights (DEC-019)."""
        inspection = self._fs.inspect_path(directory_path)
        if not inspection.exists:
            raise StorageServiceError(
                ErrorCode.NOT_FOUND,
                f"Shared model directory does not exist: '{inspection.canonical_path}'.",
            )
        active_doc = self._config.get_active().document
        dirs = tuple(dict.fromkeys((*active_doc.storage.shared_model_directories, inspection.canonical_path)))
        updated_storage = active_doc.storage.model_copy(update={"shared_model_directories": dirs})
        updated_doc = active_doc.model_copy(update={"storage": updated_storage})
        self._config.save_revision(updated_doc, source="user", correlation_id=correlation_id, actor=actor)
        return dirs

    def migrate_location(
        self,
        category: StorageCategory,
        target_path: str,
        *,
        correlation_id: str,
        actor: str = "local_owner",
        simulate_failure_before_commit: bool = False,
    ) -> MigrationResult:
        """6-stage checksum-verified migration with atomic pointer commit & rollback (FR-SYS-04, T10)."""
        if category in WAL_DATABASE_CATEGORIES:
            wal_ok, reason = self._fs.is_wal_supported_path(target_path)
            if not wal_ok:
                raise StorageServiceError(
                    ErrorCode.UNSUPPORTED_FILESYSTEM,
                    f"WAL database migration rejected: {reason}",
                )

        active_doc = self._config.get_active().document
        source_dir = Path(active_doc.storage.roots.as_category_map()[category])
        inspection = self._fs.inspect_path(target_path)
        if not inspection.writable:
            raise StorageServiceError(ErrorCode.DENIED, f"Target path not writable: {target_path}")

        target_dir = Path(inspection.canonical_path)
        if source_dir.resolve() == target_dir.resolve():
            return MigrationResult(
                category=category,
                source_path=str(source_dir),
                target_path=str(target_dir),
                files_verified=0,
                total_bytes=0,
                rolled_back=False,
            )

        # Preflight disk space check
        source_files: list[Path] = []
        total_bytes = 0
        if source_dir.exists():
            for item in source_dir.rglob("*"):
                if item.is_file():
                    source_files.append(item)
                    total_bytes += item.stat().st_size

        if inspection.free_bytes < total_bytes + (16 * 1024 * 1024):
            raise StorageServiceError(
                ErrorCode.INSUFFICIENT_DISK,
                f"Insufficient free space at target ({inspection.free_bytes} bytes available, need {total_bytes}).",
            )

        staging_dir = target_dir.parent / f".staging-{target_dir.name}-{uuid.uuid4().hex[:8]}"
        try:
            staging_dir.mkdir(parents=True, exist_ok=True)
            verified_count = 0
            for src_file in source_files:
                rel = src_file.relative_to(source_dir)
                dst_file = staging_dir / rel
                dst_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src_file, dst_file)
                if _sha256_file(src_file) != _sha256_file(dst_file):
                    raise StorageServiceError(
                        ErrorCode.INTERNAL,
                        f"Checksum verification failed during migration for '{rel}'.",
                    )
                verified_count += 1

            if simulate_failure_before_commit:
                raise RuntimeError("Simulated mid-migration interruption before pointer commit.")

            # Move staged contents into final target_dir
            target_dir.mkdir(parents=True, exist_ok=True)
            for staged_file in staging_dir.rglob("*"):
                if staged_file.is_file():
                    rel = staged_file.relative_to(staging_dir)
                    final_file = target_dir / rel
                    final_file.parent.mkdir(parents=True, exist_ok=True)
                    staged_file.replace(final_file)

            # Atomic pointer update in config_revision & storage_location
            self.set_location(category, str(target_dir), correlation_id=correlation_id, actor=actor)
            return MigrationResult(
                category=category,
                source_path=str(source_dir),
                target_path=str(target_dir),
                files_verified=verified_count,
                total_bytes=total_bytes,
                rolled_back=False,
            )
        except Exception as exc:
            # Clean rollback: remove staging and keep source intact
            shutil.rmtree(staging_dir, ignore_errors=True)
            if isinstance(exc, StorageServiceError):
                raise
            raise StorageServiceError(
                ErrorCode.INTERNAL, f"Migration interrupted and rolled back cleanly: {exc}"
            ) from exc
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir, ignore_errors=True)

    def cleanup_cache_lru(
        self,
        category: StorageCategory,
        max_bytes: int,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> CacheCleanupResult:
        """LRU eviction strictly restricted to evictable cache/temp categories (BR-SYS-02)."""
        if category not in EVICTABLE_CACHE_CATEGORIES:
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"BR-SYS-02 prohibits automatic eviction on protected category '{category.value}'.",
            )
        if max_bytes < 0:
            raise StorageServiceError(ErrorCode.INVALID_ARGS, "max_bytes must be >= 0.")

        active_doc = self._config.get_active().document
        root_dir = Path(active_doc.storage.roots.as_category_map()[category])
        if not root_dir.exists():
            return CacheCleanupResult(category=category, deleted_files=0, freed_bytes=0, remaining_bytes=0)

        files: list[tuple[float, int, Path]] = []
        total_size = 0
        for item in root_dir.rglob("*"):
            if item.is_file():
                st = item.stat()
                total_size += st.st_size
                files.append((st.st_mtime, st.st_size, item))

        # Oldest modified/accessed first
        files.sort(key=lambda t: t[0])
        deleted_files = 0
        freed_bytes = 0
        remaining = total_size
        for _mtime, size, path in files:
            if remaining <= max_bytes:
                break
            path.unlink(missing_ok=True)
            deleted_files += 1
            freed_bytes += size
            remaining -= size

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'storage.cache_cleanup', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps(
                        {
                            "category": category.value,
                            "deleted_files": deleted_files,
                            "freed_bytes": freed_bytes,
                            "remaining_bytes": remaining,
                        }
                    ),
                    now_iso,
                ),
            )

        return CacheCleanupResult(
            category=category,
            deleted_files=deleted_files,
            freed_bytes=freed_bytes,
            remaining_bytes=remaining,
        )
