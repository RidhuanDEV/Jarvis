"""Windows DesktopAutomationPort: allowlisted no-shell app launcher & volume control with readback (B07)."""

from __future__ import annotations

import contextlib
import ctypes
import os
import subprocess
import sys
from pathlib import Path

# Explicit verified Windows system binaries (zero cmd.exe / powershell.exe shell invocation!)
_ALLOWLISTED_WINDOWS_APPS: dict[str, tuple[str, ...]] = {
    "calculator": ("calc.exe",),
    "notepad": ("notepad.exe",),
    "paint": ("mspaint.exe",),
}


class WindowsDesktopAutomationAdapter:
    """Safe non-shell DesktopAutomationPort with explicit allowlist and volume readback."""

    def __init__(self, *, allow_live_launch: bool = False) -> None:
        self._allow_live_launch = allow_live_launch
        self._software_volume_fallback = 50

    def launch_allowlisted_app(self, app_id: str) -> bool:
        key = app_id.strip().lower()
        candidates = _ALLOWLISTED_WINDOWS_APPS.get(key)
        if candidates is None:
            raise PermissionError(f"Application '{app_id}' is not in the explicit desktop allowlist.")
        if sys.platform != "win32":
            return False
        system32 = Path(os.environ.get("SYSTEMROOT", "C:\\Windows")) / "System32"
        exe_path = system32 / candidates[0]
        if not exe_path.is_file():
            raise FileNotFoundError(f"Allowlisted binary not found: {exe_path}")
        if not self._allow_live_launch:
            return True
        subprocess.Popen(  # noqa: S603
            [str(exe_path)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            shell=False,
        )
        return True

    def get_volume_percent(self) -> int:
        if sys.platform != "win32":
            return self._software_volume_fallback
        with contextlib.suppress(Exception):
            winmm = ctypes.windll.winmm
            vol = ctypes.c_uint32(0)
            res = winmm.waveOutGetVolume(0, ctypes.byref(vol))
            if res == 0:
                left = vol.value & 0xFFFF
                return int(round((left / 0xFFFF) * 100))
        return self._software_volume_fallback

    def set_volume_percent(self, percent: int) -> int:
        if percent < 0 or percent > 100:
            raise ValueError("Volume percent must be between 0 and 100.")
        self._software_volume_fallback = percent
        if sys.platform == "win32":
            with contextlib.suppress(Exception):
                winmm = ctypes.windll.winmm
                channel = int(round((percent / 100.0) * 0xFFFF))
                packed = (channel << 16) | channel
                res = winmm.waveOutSetVolume(0, ctypes.c_uint32(packed))
                if res == 0:
                    return self.get_volume_percent()
        return self._software_volume_fallback
