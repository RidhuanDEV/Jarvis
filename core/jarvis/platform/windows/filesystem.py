"""Windows FilesystemSafetyPort: UNC/SMB WAL rejection, reparse point guard, handle snapshot (T04, DEC-019)."""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import sys
from pathlib import Path

import psutil

from jarvis.domain.models import StorageVolumeInfo
from jarvis.domain.ports import PathSafetyInspection, TargetHandleSnapshot

FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
DRIVE_REMOVABLE = 2
DRIVE_FIXED = 3
DRIVE_REMOTE = 4
DRIVE_CDROM = 5
DRIVE_RAMDISK = 6

UNSUPPORTED_WAL_FS = frozenset({"smb", "cifs", "nfs", "webdav", "davfs", "fuse.sshfs", "network"})


def _is_unc_or_network_syntax(raw_path: str) -> bool:
    stripped = raw_path.strip()
    return stripped.startswith("\\\\") or stripped.startswith("//") or stripped.lower().startswith("\\\\?\\unc\\")


def _win_drive_type(root_drive: str) -> int:
    if sys.platform != "win32":
        return DRIVE_FIXED
    kernel32 = ctypes.windll.kernel32
    drive = root_drive if root_drive.endswith("\\") else f"{root_drive}\\"
    return int(kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)))


def _win_volume_filesystem(root_drive: str) -> str:
    if sys.platform != "win32":
        return "local"
    kernel32 = ctypes.windll.kernel32
    drive = root_drive if root_drive.endswith("\\") else f"{root_drive}\\"
    fs_buf = ctypes.create_unicode_buffer(64)
    ok = kernel32.GetVolumeInformationW(
        ctypes.c_wchar_p(drive),
        None,
        0,
        None,
        None,
        None,
        fs_buf,
        len(fs_buf),
    )
    return str(fs_buf.value) if ok else "unknown"


def _win_is_reparse_point(path: Path) -> bool:
    if sys.platform != "win32":
        return path.is_symlink()
    kernel32 = ctypes.windll.kernel32
    attrs = int(kernel32.GetFileAttributesW(ctypes.c_wchar_p(str(path))))
    if attrs == INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


class WindowsFilesystemSafetyAdapter:
    """Windows implementation of FilesystemSafetyPort with anti-TOCTOU & WAL FS checks."""

    def inspect_path(self, raw_path: str) -> PathSafetyInspection:
        if _is_unc_or_network_syntax(raw_path):
            return PathSafetyInspection(
                canonical_path=raw_path.strip(),
                exists=False,
                is_reparse_point=False,
                filesystem_kind="SMB/UNC",
                is_network=True,
                is_removable=False,
                free_bytes=0,
                writable=False,
            )

        path = Path(raw_path).expanduser()
        exists = path.exists()
        is_reparse = _win_is_reparse_point(path) if exists else False
        canonical = str(path.resolve(strict=False))

        drive_anchor = Path(canonical).anchor or (f"{Path(canonical).drive}\\" if Path(canonical).drive else "")
        drive_type = _win_drive_type(drive_anchor) if drive_anchor else DRIVE_FIXED
        is_network = drive_type == DRIVE_REMOTE
        is_removable = drive_type == DRIVE_REMOVABLE
        fs_kind = "SMB/UNC" if is_network else (_win_volume_filesystem(drive_anchor) if drive_anchor else "unknown")

        probe_target = Path(canonical)
        while not probe_target.exists() and probe_target.parent != probe_target:
            probe_target = probe_target.parent

        free_bytes = 0
        writable = False
        if probe_target.exists() and not is_network:
            try:
                usage = shutil.disk_usage(probe_target)
                free_bytes = int(usage.free)
                writable = os.access(probe_target, os.W_OK)
            except OSError:
                free_bytes = 0
                writable = False

        return PathSafetyInspection(
            canonical_path=canonical,
            exists=exists,
            is_reparse_point=is_reparse,
            filesystem_kind=fs_kind,
            is_network=is_network,
            is_removable=is_removable,
            free_bytes=free_bytes,
            writable=writable,
        )

    def is_wal_supported_path(self, raw_path: str) -> tuple[bool, str]:
        if _is_unc_or_network_syntax(raw_path):
            return (False, "UNC/SMB network shares are prohibited for SQLite WAL databases.")
        inspection = self.inspect_path(raw_path)
        if inspection.is_network:
            return (False, "Mapped network drives do not support safe SQLite WAL shared-memory locking.")
        if inspection.filesystem_kind.lower() in UNSUPPORTED_WAL_FS:
            return (False, f"Filesystem '{inspection.filesystem_kind}' does not support SQLite WAL.")
        return (True, "Local filesystem verified for SQLite WAL.")

    def resolve_within_root(self, root_path: str, relative_path: str) -> str:
        """Resolve relative_path strictly inside root_path, rejecting traversal and reparse escapes (T04)."""
        root = Path(root_path).resolve(strict=True)
        if _win_is_reparse_point(root):
            raise PermissionError("Root directory itself must not be an untrusted reparse point.")

        candidate = root / relative_path
        # Check every intermediate component inside root for reparse points / junctions
        current = root
        for part in Path(relative_path).parts:
            if part in ("..", "/", "\\"):
                raise PermissionError(f"Path traversal component '{part}' rejected.")
            current = current / part
            if current.exists() and _win_is_reparse_point(current):
                resolved_part = current.resolve(strict=True)
                if not resolved_part.is_relative_to(root):
                    raise PermissionError(f"Reparse point/junction '{current}' escapes authorized root '{root}'.")

        resolved = candidate.resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise PermissionError(f"Resolved path '{resolved}' escapes authorized root '{root}'.")
        return str(resolved)

    def snapshot_target(self, canonical_path: str) -> TargetHandleSnapshot:
        path = Path(canonical_path)
        st = path.stat()
        file_index = f"{st.st_dev}:{st.st_ino}"
        digest = hashlib.sha256(f"{path.resolve()}|{st.st_size}|{st.st_mtime_ns}|{file_index}".encode()).hexdigest()
        return TargetHandleSnapshot(
            canonical_path=str(path.resolve()),
            size_bytes=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            file_index_id=file_index,
            snapshot_hash=digest,
        )

    def list_volumes(self) -> tuple[StorageVolumeInfo, ...]:
        volumes: list[StorageVolumeInfo] = []
        for part in psutil.disk_partitions(all=False):
            mount = part.mountpoint
            drive_type = _win_drive_type(mount)
            is_network = drive_type == DRIVE_REMOTE or part.fstype.lower() in UNSUPPORTED_WAL_FS
            is_removable = drive_type == DRIVE_REMOVABLE
            try:
                usage = shutil.disk_usage(mount)
                total_b, free_b = int(usage.total), int(usage.free)
            except OSError:
                total_b, free_b = 0, 0
            volumes.append(
                StorageVolumeInfo(
                    mount_point=mount,
                    filesystem_kind=part.fstype or "unknown",
                    total_bytes=total_b,
                    free_bytes=free_b,
                    is_removable=is_removable,
                    is_network=is_network,
                )
            )
        return tuple(volumes)
