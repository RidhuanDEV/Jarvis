"""11-Root Dynamic Storage Manager, Cache Quota LRU & Safe Staged Migration (DEC-003, DEC-019, BR-SYS-02)."""

from __future__ import annotations

import hashlib
import json
import os
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

CACHE_OWNERSHIP_SENTINEL = ".jarvis-cache-owned"

_FORBIDDEN_STORAGE_SEGMENTS: frozenset[str] = frozenset(
    {
        "windows",
        "system32",
        "syswow64",
        "programdata",
        "program files",
        "program files (x86)",
        "$recycle.bin",
        "system volume information",
        ".ssh",
        ".gnupg",
        ".aws",
        ".azure",
        ".kube",
    }
)


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

    def _has_forbidden_segment(self, path: Path) -> bool:
        return any(part.lower() in _FORBIDDEN_STORAGE_SEGMENTS for part in path.parts)

    def _has_valid_cache_sentinel(self, root_dir: Path, expected_category: StorageCategory) -> bool:
        sentinel = root_dir / CACHE_OWNERSHIP_SENTINEL
        if not sentinel.exists() or sentinel.is_symlink():
            return False
        if self._fs.inspect_path(str(sentinel)).is_reparse_point:
            return False
        try:
            payload = json.loads(sentinel.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        return (
            isinstance(payload, dict)
            and payload.get("owner") == "jarvis"
            and payload.get("category") == expected_category.value
        )

    def _ensure_owned_cache_sentinel(self, root_dir: Path, category: StorageCategory) -> None:
        """Stamp ownership sentinel ONLY on freshly created or empty directories (never user folders)."""
        if self._fs.inspect_path(str(root_dir)).is_reparse_point or root_dir.is_symlink():
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Refusing to adopt reparse point/symlink as cache root: '{root_dir}'.",
            )
        if root_dir.exists():
            if self._has_valid_cache_sentinel(root_dir, category):
                return
            try:
                existing_entries = list(root_dir.iterdir())
            except OSError as exc:
                raise StorageServiceError(ErrorCode.DENIED, f"Cannot inspect directory '{root_dir}': {exc}") from exc
            if existing_entries:
                raise StorageServiceError(
                    ErrorCode.DENIED,
                    f"Refusing to assign evictable '{category.value}' root to non-empty directory without JARVIS ownership sentinel.",
                )
        else:
            root_dir.mkdir(parents=True, exist_ok=True)
        sentinel = root_dir / CACHE_OWNERSHIP_SENTINEL
        sentinel.write_text(
            json.dumps(
                {
                    "owner": "jarvis",
                    "category": category.value,
                    "created_at": self._clock.now_utc().isoformat(),
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )

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
                if category in EVICTABLE_CACHE_CATEGORIES and inspection.writable and not inspection.is_reparse_point:
                    cand_dir = Path(inspection.canonical_path)
                    # Only stamp sentinel on newly created or empty default cache/temp directories
                    if not self._has_forbidden_segment(cand_dir) and (
                        not cand_dir.exists() or not any(cand_dir.iterdir())
                    ):
                        self._ensure_owned_cache_sentinel(cand_dir, category)
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
        if inspection.is_reparse_point:
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' is a reparse point/symlink and cannot be registered.",
            )
        if self._has_forbidden_segment(Path(inspection.canonical_path)):
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' lies inside a protected OS or credential directory.",
            )
        if not inspection.writable:
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' is not writable.",
            )
        if category in EVICTABLE_CACHE_CATEGORIES:
            # IR-01 / B03: prevent 2-step user-file deletion by refusing non-empty user directories as cache/temp
            self._ensure_owned_cache_sentinel(Path(inspection.canonical_path), category)

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
        if inspection.is_reparse_point:
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' is a reparse point/symlink and cannot be a migration target.",
            )
        if self._has_forbidden_segment(Path(inspection.canonical_path)):
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Target path '{inspection.canonical_path}' lies inside a protected OS or credential directory.",
            )
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

        # Preflight disk space check (exclude live WAL/SHM sidecars when using Online Backup API!)
        is_wal_db = category in WAL_DATABASE_CATEGORIES
        source_files: list[Path] = []
        total_bytes = 0
        if source_dir.exists():
            for item in source_dir.rglob("*"):
                if item.is_file() and not item.is_symlink():
                    if is_wal_db and item.name.endswith((".db-wal", ".db-shm")):
                        continue
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
            if category == StorageCategory.CORE_DB:
                # B19 / DEF-14: quiesced SQLite Online Backup API snapshot (never raw shutil.copy2 on live WAL DB!)
                snap_dst = staging_dir / self._db.core_db_path.name
                self._db.snapshot_core(snap_dst)
                total_bytes = snap_dst.stat().st_size
                verified_count = 1
            elif category == StorageCategory.KNOWLEDGE_DB:
                snap_dst = staging_dir / self._db.knowledge_db_path.name
                self._db.snapshot_knowledge(snap_dst)
                total_bytes = snap_dst.stat().st_size
                verified_count = 1
            else:
                for src_file in source_files:
                    if self._fs.inspect_path(str(src_file)).is_reparse_point:
                        continue
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

        # IR-01 / B03: ownership sentinel + anti-reparse boundary prevents deleting any non-JARVIS user directory
        if self._fs.inspect_path(str(root_dir)).is_reparse_point or root_dir.is_symlink():
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Cache cleanup refused: '{category.value}' root is a reparse point or symlink.",
            )
        if self._has_forbidden_segment(root_dir):
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Cache cleanup refused: '{category.value}' root points inside a protected directory.",
            )
        if not self._has_valid_cache_sentinel(root_dir, category):
            raise StorageServiceError(
                ErrorCode.DENIED,
                f"Cache cleanup refused: '{category.value}' directory lacks verified JARVIS ownership sentinel.",
            )

        root_resolved = root_dir.resolve(strict=True)
        files: list[tuple[float, int, Path]] = []
        total_size = 0
        for dirpath, dirnames, filenames in os.walk(root_resolved, topdown=True, followlinks=False):
            current_dir = Path(dirpath)
            # Prune symlinks and Windows junctions before descending
            safe_subdirs: list[str] = []
            for dname in dirnames:
                sub = current_dir / dname
                if sub.is_symlink() or self._fs.inspect_path(str(sub)).is_reparse_point:
                    continue
                if sub.resolve(strict=False).is_relative_to(root_resolved):
                    safe_subdirs.append(dname)
            dirnames[:] = safe_subdirs

            for fname in filenames:
                if current_dir == root_resolved and fname == CACHE_OWNERSHIP_SENTINEL:
                    continue
                item = current_dir / fname
                if item.is_symlink() or self._fs.inspect_path(str(item)).is_reparse_point:
                    continue
                resolved_item = item.resolve(strict=False)
                if not resolved_item.is_relative_to(root_resolved):
                    continue
                try:
                    st = item.stat(follow_symlinks=False)
                except OSError:
                    continue
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
            if path.is_symlink() or self._fs.inspect_path(str(path)).is_reparse_point:
                continue
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
