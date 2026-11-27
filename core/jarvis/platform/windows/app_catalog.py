"""Windows Native Installed Application Catalog Discovery (B09, DEC-032).

Discovers non-elevated installed applications via:
1. Safe Windows Inbox / AUMID apps (Calculator, Notepad, Paint, File Explorer, Settings, Snipping Tool).
2. Start Menu .lnk shortcuts parsed cleanly with a pure-Python MS-SHLLINK binary reader.
3. Read-only HKLM/HKCU App Paths registry keys.

Enforces strict Tier-3 LOLBin, script-extension, uninstaller, and shell-argument rejection at discovery time.
"""

from __future__ import annotations

import contextlib
import os
import re
import struct
import sys
import time
from pathlib import Path

from jarvis.domain.app_catalog import (
    ApplicationCatalogEntry,
    is_prohibited_binary_target,
    normalize_app_query,
)

_LNK_HEADER_SIZE = 0x4C
_LNK_CLSID = bytes.fromhex("0114020000000000c000000000000046")
_ENV_BLOCK_SIG = 0xA0000001
_SAFE_ENV_RE = re.compile(r"%([A-Za-z0-9_()]+)%")


def _expand_windows_env(raw: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        key = match.group(1)
        val = os.environ.get(key) or os.environ.get(key.upper())
        return val if val is not None else match.group(0)

    return _SAFE_ENV_RE.sub(_sub, raw)


def _read_cstr(data: bytes, offset: int, *, unicode_mode: bool = False) -> str:
    if offset < 0 or offset >= len(data):
        return ""
    if unicode_mode:
        end = offset
        while end + 1 < len(data):
            if data[end] == 0 and data[end + 1] == 0:
                break
            end += 2
        return data[offset:end].decode("utf-16-le", errors="ignore")
    end = data.find(b"\x00", offset)
    if end == -1:
        end = len(data)
    return data[offset:end].decode("mbcs" if sys.platform == "win32" else "latin-1", errors="ignore")


def parse_windows_lnk(lnk_path: Path) -> tuple[str | None, str]:
    """Parse a Windows Shell Link (.lnk) per [MS-SHLLINK] returning (target_path, arguments)."""
    try:
        data = lnk_path.read_bytes()
    except OSError:
        return (None, "")

    if len(data) < _LNK_HEADER_SIZE:
        return (None, "")
    header_size = struct.unpack_from("<I", data, 0)[0]
    if header_size != _LNK_HEADER_SIZE or data[4:20] != _LNK_CLSID:
        return (None, "")

    flags = struct.unpack_from("<I", data, 20)[0]
    has_idlist = bool(flags & 0x01)
    has_linkinfo = bool(flags & 0x02)
    has_name = bool(flags & 0x04)
    has_rel_path = bool(flags & 0x08)
    has_working_dir = bool(flags & 0x10)
    has_arguments = bool(flags & 0x20)
    has_icon = bool(flags & 0x40)
    is_unicode = bool(flags & 0x80)

    pos = _LNK_HEADER_SIZE
    target_path: str | None = None
    relative_path = ""
    arguments = ""

    # 1. LinkTargetIDList
    if has_idlist:
        if pos + 2 > len(data):
            return (None, "")
        idlist_size = struct.unpack_from("<H", data, pos)[0]
        pos += 2 + idlist_size

    # 2. LinkInfo
    if has_linkinfo and pos + 4 <= len(data):
        info_start = pos
        info_size = struct.unpack_from("<I", data, info_start)[0]
        if info_size >= 28 and info_start + info_size <= len(data):
            info_hdr_size = struct.unpack_from("<I", data, info_start + 4)[0]
            info_flags = struct.unpack_from("<I", data, info_start + 8)[0]
            local_base_off = struct.unpack_from("<I", data, info_start + 16)[0]
            suffix_off = struct.unpack_from("<I", data, info_start + 24)[0]
            if info_flags & 0x01:
                if info_hdr_size >= 0x24 and info_start + 36 <= len(data):
                    u_base_off = struct.unpack_from("<I", data, info_start + 28)[0]
                    u_suffix_off = struct.unpack_from("<I", data, info_start + 32)[0]
                    base = _read_cstr(data, info_start + u_base_off, unicode_mode=True)
                    suffix = _read_cstr(data, info_start + u_suffix_off, unicode_mode=True)
                else:
                    base = _read_cstr(data, info_start + local_base_off, unicode_mode=False)
                    suffix = _read_cstr(data, info_start + suffix_off, unicode_mode=False)
                combined = f"{base}{suffix}".strip()
                if combined:
                    target_path = combined
        pos += info_size

    # 3. StringData
    def _read_counted_string(cursor: int) -> tuple[str, int]:
        if cursor + 2 > len(data):
            return ("", len(data))
        count = struct.unpack_from("<H", data, cursor)[0]
        cursor += 2
        byte_len = count * 2 if is_unicode else count
        chunk = data[cursor : cursor + byte_len]
        decoded = (
            chunk.decode("utf-16-le", errors="ignore")
            if is_unicode
            else chunk.decode("mbcs" if sys.platform == "win32" else "latin-1", errors="ignore")
        )
        return (decoded, cursor + byte_len)

    if has_name:
        _, pos = _read_counted_string(pos)
    if has_rel_path:
        relative_path, pos = _read_counted_string(pos)
    if has_working_dir:
        _, pos = _read_counted_string(pos)
    if has_arguments:
        arguments, pos = _read_counted_string(pos)
    if has_icon:
        _, pos = _read_counted_string(pos)

    # 4. ExtraData (EnvironmentVariableDataBlock fallback when LinkInfo omitted)
    while pos + 4 <= len(data):
        block_size = struct.unpack_from("<I", data, pos)[0]
        if block_size < 4 or pos + block_size > len(data):
            break
        if block_size >= 8:
            sig = struct.unpack_from("<I", data, pos + 4)[0]
            if sig == _ENV_BLOCK_SIG and target_path is None:
                if block_size >= 8 + 260 + 520:
                    env_uni = _read_cstr(data, pos + 8 + 260, unicode_mode=True).strip()
                    if env_uni:
                        target_path = _expand_windows_env(env_uni)
                if not target_path and block_size >= 8 + 260:
                    env_ansi = _read_cstr(data, pos + 8, unicode_mode=False).strip()
                    if env_ansi:
                        target_path = _expand_windows_env(env_ansi)
        pos += block_size

    if target_path is None and relative_path:
        with contextlib.suppress(OSError):
            target_path = str((lnk_path.parent / relative_path).resolve(strict=False))

    if target_path is not None:
        target_path = _expand_windows_env(target_path.strip().strip('"'))

    return (target_path, arguments.strip())


def _slugify_app_id(display_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", normalize_app_query(display_name)).strip("_")
    return slug or "app"


class WindowsApplicationCatalogAdapter:
    """Non-elevated Windows ApplicationCatalogPort discovering safe ordinary installed apps (B09)."""

    CACHE_TTL_SECONDS: float = 300.0

    def __init__(
        self,
        *,
        start_menu_dirs: tuple[Path, ...] | None = None,
        scan_registry: bool = True,
        include_inbox_apps: bool = True,
        extra_entries: tuple[ApplicationCatalogEntry, ...] = (),
    ) -> None:
        self._start_menu_dirs = start_menu_dirs
        self._scan_registry = scan_registry
        self._include_inbox_apps = include_inbox_apps
        self._extra_entries = extra_entries
        self._cached: tuple[ApplicationCatalogEntry, ...] | None = None
        self._cached_at: float = 0.0

    def list_apps(self) -> tuple[ApplicationCatalogEntry, ...]:
        now = time.monotonic()
        if self._cached is None or (now - self._cached_at) > self.CACHE_TTL_SECONDS:
            return self.refresh()
        return self._cached

    def find_by_id(self, app_id: str) -> ApplicationCatalogEntry | None:
        norm = normalize_app_query(app_id)
        for entry in self.list_apps():
            if normalize_app_query(entry.app_id) == norm:
                return entry
        return None

    def refresh(self) -> tuple[ApplicationCatalogEntry, ...]:
        by_id: dict[str, ApplicationCatalogEntry] = {}

        if self._include_inbox_apps:
            for entry in self._discover_inbox_apps():
                by_id[entry.app_id] = entry

        for entry in self._discover_start_menu_shortcuts():
            by_id.setdefault(entry.app_id, entry)

        if self._scan_registry and sys.platform == "win32":
            for entry in self._discover_registry_app_paths():
                by_id.setdefault(entry.app_id, entry)

        for entry in self._extra_entries:
            if entry.trust_class == "tier3_prohibited":
                continue
            if entry.activation_kind == "exe" and is_prohibited_binary_target(
                entry.target, entry.arguments
            ):
                continue
            by_id[entry.app_id] = entry

        result = tuple(sorted(by_id.values(), key=lambda e: e.display_name.casefold()))
        self._cached = result
        self._cached_at = time.monotonic()
        return result

    @staticmethod
    def _discover_inbox_apps() -> list[ApplicationCatalogEntry]:
        sys_root = Path(os.environ.get("SYSTEMROOT", "C:\\Windows"))
        sys32 = sys_root / "System32"
        candidates = [
            ApplicationCatalogEntry(
                app_id="calculator",
                display_name="Calculator",
                activation_kind="exe",
                target=str(sys32 / "calc.exe"),
                aliases=("kalkulator", "calc", "windows calculator"),
                source="windows_inbox",
                trust_class="tier1_ordinary",
                publisher="Microsoft",
            ),
            ApplicationCatalogEntry(
                app_id="notepad",
                display_name="Notepad",
                activation_kind="exe",
                target=str(sys32 / "notepad.exe"),
                aliases=("catatan", "text editor"),
                source="windows_inbox",
                trust_class="tier1_ordinary",
                publisher="Microsoft",
            ),
            ApplicationCatalogEntry(
                app_id="paint",
                display_name="Paint",
                activation_kind="exe",
                target=str(sys32 / "mspaint.exe"),
                aliases=("mspaint", "gambar"),
                source="windows_inbox",
                trust_class="tier1_ordinary",
                publisher="Microsoft",
            ),
            ApplicationCatalogEntry(
                app_id="file_explorer",
                display_name="File Explorer",
                activation_kind="exe",
                target=str(sys_root / "explorer.exe"),
                aliases=("explorer", "windows explorer", "penjelajah file"),
                source="windows_inbox",
                trust_class="tier1_ordinary",
                publisher="Microsoft",
            ),
            ApplicationCatalogEntry(
                app_id="settings",
                display_name="Settings",
                activation_kind="aumid",
                target="windows.immersivecontrolpanel_cw5n1h2txyewy!microsoft.windows.immersivecontrolpanel",
                aliases=("pengaturan", "windows settings"),
                source="windows_inbox_aumid",
                trust_class="tier1_ordinary",
                publisher="Microsoft",
            ),
        ]
        entries: list[ApplicationCatalogEntry] = []
        for entry in candidates:
            if entry.activation_kind == "aumid" or sys.platform != "win32" or Path(entry.target).is_file():
                entries.append(entry)
        return entries

    def _resolved_start_menu_dirs(self) -> tuple[Path, ...]:
        if self._start_menu_dirs is not None:
            return self._start_menu_dirs
        dirs: list[Path] = []
        for env_key in ("PROGRAMDATA", "APPDATA"):
            base = os.environ.get(env_key)
            if base:
                cand = Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
                if cand.is_dir():
                    dirs.append(cand)
        return tuple(dirs)

    def _discover_start_menu_shortcuts(self) -> list[ApplicationCatalogEntry]:
        entries: list[ApplicationCatalogEntry] = []
        seen_targets: set[str] = set()
        for root_dir in self._resolved_start_menu_dirs():
            if not root_dir.is_dir():
                continue
            for dirpath, _dirnames, filenames in os.walk(root_dir, followlinks=False):
                for fname in filenames:
                    if not fname.lower().endswith(".lnk"):
                        continue
                    lnk_path = Path(dirpath) / fname
                    display_name = lnk_path.stem.strip()
                    if not display_name or "uninstall" in display_name.casefold():
                        continue
                    target, arguments = parse_windows_lnk(lnk_path)
                    if not target:
                        continue
                    if is_prohibited_binary_target(target, arguments):
                        continue
                    target_path = Path(target)
                    if target_path.suffix.lower() != ".exe":
                        continue
                    if not target_path.is_file():
                        continue
                    canon_target = str(target_path.resolve(strict=False))
                    target_key = canon_target.casefold()
                    if target_key in seen_targets:
                        continue
                    seen_targets.add(target_key)
                    stem_alias = target_path.stem.strip()
                    aliases = tuple(
                        dict.fromkeys(
                            a
                            for a in (display_name.casefold(), stem_alias.casefold())
                            if a
                        )
                    )
                    entries.append(
                        ApplicationCatalogEntry(
                            app_id=_slugify_app_id(display_name),
                            display_name=display_name,
                            activation_kind="exe",
                            target=canon_target,
                            aliases=aliases,
                            source="windows_start_menu",
                            trust_class="tier1_ordinary",
                            arguments="",
                        )
                    )
        return entries

    @staticmethod
    def _discover_registry_app_paths() -> list[ApplicationCatalogEntry]:
        if sys.platform != "win32":
            return []
        import winreg

        entries: list[ApplicationCatalogEntry] = []
        subkey_path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"
        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                root_key = winreg.OpenKey(hive, subkey_path, 0, winreg.KEY_READ)
            except OSError:
                continue
            with root_key:
                idx = 0
                while True:
                    try:
                        sub_name = winreg.EnumKey(root_key, idx)
                        idx += 1
                    except OSError:
                        break
                    try:
                        with winreg.OpenKey(root_key, sub_name, 0, winreg.KEY_READ) as app_key:
                            raw_val, _ = winreg.QueryValueEx(app_key, "")
                    except OSError:
                        continue
                    if not isinstance(raw_val, str) or not raw_val.strip():
                        continue
                    target = _expand_windows_env(raw_val.strip().strip('"'))
                    if is_prohibited_binary_target(target):
                        continue
                    target_path = Path(target)
                    if target_path.suffix.lower() != ".exe" or not target_path.is_file():
                        continue
                    display = Path(sub_name).stem.replace("_", " ").strip()
                    if not display:
                        continue
                    entries.append(
                        ApplicationCatalogEntry(
                            app_id=_slugify_app_id(display),
                            display_name=display.title() if display.islower() else display,
                            activation_kind="exe",
                            target=str(target_path.resolve(strict=False)),
                            aliases=(display.casefold(), sub_name.casefold()),
                            source="windows_app_paths",
                            trust_class="tier1_ordinary",
                        )
                    )
        return entries
