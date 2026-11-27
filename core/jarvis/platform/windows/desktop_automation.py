"""Windows DesktopAutomationPort: safe non-elevated app launcher & WASAPI Core Audio volume control (B09)."""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from jarvis.domain.app_catalog import (
    AppLaunchReceipt,
    ApplicationCatalogEntry,
    is_prohibited_binary_target,
)

# Explicit verified Windows system binaries for legacy launch_allowlisted_app compatibility
_ALLOWLISTED_WINDOWS_APPS: dict[str, tuple[str, ...]] = {
    "calculator": ("calc.exe",),
    "notepad": ("notepad.exe",),
    "paint": ("mspaint.exe",),
}

# Win32 Core Audio (WASAPI) COM GUIDs
class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid_str(cls, raw: str) -> _GUID:
        cleaned = raw.strip("{}")
        parts = cleaned.split("-")
        d1 = int(parts[0], 16)
        d2 = int(parts[1], 16)
        d3 = int(parts[2], 16)
        tail = bytes.fromhex(parts[3] + parts[4])
        arr = (ctypes.c_ubyte * 8)(*tail)
        return cls(d1, d2, d3, arr)


_CLSID_MMDEVICE_ENUMERATOR = _GUID.from_uuid_str("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_IID_IMMDEVICE_ENUMERATOR = _GUID.from_uuid_str("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
_IID_IAUDIO_ENDPOINT_VOLUME = _GUID.from_uuid_str("{5CDF2C82-841E-4546-9722-0CF74078229A}")
_CLSCTX_ALL = 0x17
_E_RENDER = 0
_E_CONSOLE = 0
_COINIT_MULTITHREADED = 0x0


def _com_vtable_fn(obj_ptr: ctypes.c_void_p, slot: int, restype: Any, *argtypes: Any) -> Any:
    vtable = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    winfunctype: Any = ctypes.WINFUNCTYPE
    fn_type = winfunctype(restype, ctypes.c_void_p, *argtypes)
    return fn_type(vtable[slot])


def _com_release(obj_ptr: ctypes.c_void_p) -> None:
    if obj_ptr.value:
        with contextlib.suppress(Exception):
            release_fn = _com_vtable_fn(obj_ptr, 2, ctypes.c_ulong)
            release_fn(obj_ptr)


def _wasapi_volume_op(*, set_percent: int | None = None) -> int | None:
    """Read or set real Windows master audio endpoint volume via WASAPI IAudioEndpointVolume COM."""
    if sys.platform != "win32":
        return None
    ole32 = ctypes.windll.ole32
    hr_init = ole32.CoInitializeEx(None, _COINIT_MULTITHREADED)
    should_uninit = hr_init in (0, 1)  # S_OK or S_FALSE
    enumerator = ctypes.c_void_p()
    device = ctypes.c_void_p()
    endpoint_vol = ctypes.c_void_p()
    try:
        hr = ole32.CoCreateInstance(
            ctypes.byref(_CLSID_MMDEVICE_ENUMERATOR),
            None,
            _CLSCTX_ALL,
            ctypes.byref(_IID_IMMDEVICE_ENUMERATOR),
            ctypes.byref(enumerator),
        )
        if hr != 0 or not enumerator.value:
            return None

        # IMMDeviceEnumerator::GetDefaultAudioEndpoint (vtable slot 4)
        get_default = _com_vtable_fn(
            enumerator,
            4,
            ctypes.c_long,
            ctypes.c_uint,
            ctypes.c_uint,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = get_default(enumerator, _E_RENDER, _E_CONSOLE, ctypes.byref(device))
        if hr != 0 or not device.value:
            return None

        # IMMDevice::Activate (vtable slot 3)
        activate = _com_vtable_fn(
            device,
            3,
            ctypes.c_long,
            ctypes.POINTER(_GUID),
            ctypes.c_uint32,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        )
        hr = activate(
            device,
            ctypes.byref(_IID_IAUDIO_ENDPOINT_VOLUME),
            _CLSCTX_ALL,
            None,
            ctypes.byref(endpoint_vol),
        )
        if hr != 0 or not endpoint_vol.value:
            return None

        if set_percent is not None:
            # IAudioEndpointVolume::SetMasterVolumeLevelScalar (vtable slot 7)
            set_scalar = _com_vtable_fn(
                endpoint_vol, 7, ctypes.c_long, ctypes.c_float, ctypes.c_void_p
            )
            hr = set_scalar(endpoint_vol, ctypes.c_float(set_percent / 100.0), None)
            if hr != 0:
                return None

        # IAudioEndpointVolume::GetMasterVolumeLevelScalar (vtable slot 9)
        get_scalar = _com_vtable_fn(
            endpoint_vol, 9, ctypes.c_long, ctypes.POINTER(ctypes.c_float)
        )
        level = ctypes.c_float(0.0)
        hr = get_scalar(endpoint_vol, ctypes.byref(level))
        if hr != 0:
            return None
        return max(0, min(100, int(round(level.value * 100.0))))
    except Exception:
        return None
    finally:
        _com_release(endpoint_vol)
        _com_release(device)
        _com_release(enumerator)
        if should_uninit:
            with contextlib.suppress(Exception):
                ole32.CoUninitialize()


class WindowsDesktopAutomationAdapter:
    """Safe non-shell DesktopAutomationPort with dynamic catalog launch and WASAPI volume readback (B09)."""

    def __init__(self, *, allow_live_launch: bool = False) -> None:
        self._allow_live_launch = allow_live_launch

    def launch_catalog_entry(self, entry: ApplicationCatalogEntry) -> AppLaunchReceipt:
        if entry.trust_class == "tier3_prohibited":
            raise PermissionError(
                f"Application '{entry.display_name}' is prohibited by Tier-3 safety policy."
            )
        if entry.activation_kind == "exe" and is_prohibited_binary_target(
            entry.target, entry.arguments
        ):
            raise PermissionError(
                f"Target executable '{entry.target}' violates Tier-3 LOLBin/shell prohibition."
            )
        if sys.platform != "win32":
            return AppLaunchReceipt(
                accepted=False,
                app_id=entry.app_id,
                display_name=entry.display_name,
                activation_kind=entry.activation_kind,
                pid=None,
                verification_kind="disabled",
                detail="Windows native app launch is unavailable on non-Windows hosts.",
            )
        if not self._allow_live_launch:
            return AppLaunchReceipt(
                accepted=False,
                app_id=entry.app_id,
                display_name=entry.display_name,
                activation_kind=entry.activation_kind,
                pid=None,
                verification_kind="disabled",
                detail="Live desktop app launch is disabled in this environment.",
            )

        creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        if entry.activation_kind == "aumid":
            explorer = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "explorer.exe"
            if not explorer.is_file():
                return AppLaunchReceipt(
                    accepted=False,
                    app_id=entry.app_id,
                    display_name=entry.display_name,
                    activation_kind="aumid",
                    pid=None,
                    verification_kind="not_found",
                    detail="Windows explorer.exe not found for AUMID activation.",
                )
            proc = subprocess.Popen(  # noqa: S603
                [str(explorer), f"shell:AppsFolder\\{entry.target}"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                shell=False,
                creationflags=creation_flags,
            )
            return AppLaunchReceipt(
                accepted=True,
                app_id=entry.app_id,
                display_name=entry.display_name,
                activation_kind="aumid",
                pid=proc.pid,
                verification_kind="os_activation_ack",
                detail=f"Activated packaged Windows app '{entry.display_name}' via shell:AppsFolder.",
            )

        exe_path = Path(entry.target)
        if not exe_path.is_file():
            return AppLaunchReceipt(
                accepted=False,
                app_id=entry.app_id,
                display_name=entry.display_name,
                activation_kind="exe",
                pid=None,
                verification_kind="not_found",
                detail=f"Executable not found: {exe_path}",
            )
        canonical_exe = str(exe_path.resolve(strict=True))
        if is_prohibited_binary_target(canonical_exe):
            raise PermissionError(
                f"Resolved executable '{canonical_exe}' violates Tier-3 LOLBin/shell prohibition."
            )
        proc = subprocess.Popen(  # noqa: S603
            [canonical_exe],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
            creationflags=creation_flags,
        )
        return AppLaunchReceipt(
            accepted=True,
            app_id=entry.app_id,
            display_name=entry.display_name,
            activation_kind="exe",
            pid=proc.pid,
            verification_kind="os_activation_ack",
            detail=f"Launched non-elevated Windows executable '{entry.display_name}' (PID {proc.pid}).",
        )

    def launch_allowlisted_app(self, app_id: str) -> bool:
        key = app_id.strip().lower()
        candidates = _ALLOWLISTED_WINDOWS_APPS.get(key)
        if candidates is None:
            raise PermissionError(f"Application '{app_id}' is not in the explicit desktop allowlist.")
        system32 = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "System32"
        exe_path = system32 / candidates[0]
        if sys.platform == "win32" and not exe_path.is_file():
            raise FileNotFoundError(f"Allowlisted binary not found: {exe_path}")
        entry = ApplicationCatalogEntry(
            app_id=key,
            display_name=key.title(),
            activation_kind="exe",
            target=str(exe_path),
            source="windows_inbox",
            trust_class="tier1_ordinary",
        )
        receipt = self.launch_catalog_entry(entry)
        return receipt.accepted

    def get_volume_percent(self) -> int:
        level = _wasapi_volume_op(set_percent=None)
        if level is None:
            raise RuntimeError("Windows WASAPI master audio endpoint is unavailable.")
        return level

    def set_volume_percent(self, percent: int) -> int:
        if percent < 0 or percent > 100:
            raise ValueError("Volume percent must be between 0 and 100.")
        readback = _wasapi_volume_op(set_percent=percent)
        if readback is None:
            raise RuntimeError("Windows WASAPI master audio endpoint is unavailable for volume control.")
        return readback
