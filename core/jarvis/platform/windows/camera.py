"""Verified On-Demand Local Windows Camera Discovery & RAM-Only Single-Frame Adapter (Stage G7, B26, FR-IOT-01).

Strictly lives in `jarvis.platform.windows` (preserving NFR-16 zero OS imports in domain/application).
Invariants:
- Discovery inspects PnP camera metadata without opening any video stream or lighting the camera LED.
- Capture opens the requested camera index ONLY during an explicit user snapshot, writes ZERO temp files,
  stores pixels strictly inside a mutable RAM `bytearray` (wiped in caller's finally), and closes the device
  immediately in `finally`.
- Fails honestly with `ErrorCode.UNSUPPORTED` / `RUNTIME_UNAVAILABLE` if no camera hardware or OpenCV
  capture backend is installed — NEVER returns a synthetic dummy frame!
"""

from __future__ import annotations

import contextlib
import importlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass

from jarvis.application.camera_service import CameraServiceError, RawCameraFrame
from jarvis.domain.models import ErrorCode

_VALID_DEVICE_ID_RE = re.compile(r"^cam-([0-9]{1,2})$")


@dataclass(frozen=True)
class DiscoveredCameraDevice:
    device_id: str
    friendly_name: str
    status: str
    capture_backend_ready: bool


def _probe_cv2_available() -> bool:
    try:
        importlib.import_module("cv2")
        return True
    except ImportError:
        return False


def discover_windows_camera_devices() -> list[DiscoveredCameraDevice]:
    """Non-invasively enumerate local Windows camera devices via PnP without opening any video stream."""
    backend_ready = _probe_cv2_available()
    if sys.platform != "win32":
        return []

    ps_exe = shutil.which("powershell.exe")
    if not ps_exe:
        return []
    ps_script = (
        "$cams = @(Get-PnpDevice -Class Camera,Image -Status OK -ErrorAction SilentlyContinue "
        "| Select-Object FriendlyName, Status); "
        "$cams | ConvertTo-Json -Compress"
    )
    try:
        proc = subprocess.run(  # noqa: S603
            [ps_exe, "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []

    raw = (proc.stdout or "").strip()
    if not raw or proc.returncode != 0:
        return []

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []

    items = parsed if isinstance(parsed, list) else [parsed] if isinstance(parsed, dict) else []
    devices: list[DiscoveredCameraDevice] = []
    for idx, entry in enumerate(items):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("FriendlyName") or f"Camera {idx}").strip()
        dev_status = str(entry.get("Status") or "OK").strip()
        devices.append(
            DiscoveredCameraDevice(
                device_id=f"cam-{idx}",
                friendly_name=name,
                status=dev_status,
                capture_backend_ready=backend_ready,
            )
        )
    return devices


class WindowsOnDemandCameraAdapter:
    """On-demand RAM-only single-frame Windows camera adapter honoring FR-IOT-01."""

    def __init__(self, *, allow_live_hardware_capture: bool = True) -> None:
        self._allow_live = allow_live_hardware_capture
        self._open_handles: dict[str, object] = {}

    def list_devices(self) -> list[DiscoveredCameraDevice]:
        return discover_windows_camera_devices()

    def is_capture_backend_ready(self) -> bool:
        return self._allow_live and sys.platform == "win32" and _probe_cv2_available()

    def capture_single_frame(self, device_id: str) -> RawCameraFrame:
        match = _VALID_DEVICE_ID_RE.match(device_id.strip())
        if not match:
            raise CameraServiceError(
                ErrorCode.INVALID_ARGS,
                f"Invalid local camera device_id '{device_id}'; expected canonical 'cam-<index>'.",
            )
        if not self._allow_live or sys.platform != "win32":
            raise CameraServiceError(
                ErrorCode.UNSUPPORTED,
                "Live hardware camera capture is disabled or unavailable on this host.",
            )

        try:
            cv2 = importlib.import_module("cv2")
        except ImportError as exc:
            raise CameraServiceError(
                ErrorCode.UNSUPPORTED,
                "Optional camera capture backend (opencv-python-headless) is not installed; refusing synthetic frame.",
            ) from exc

        cam_index = int(match.group(1))
        cap = cv2.VideoCapture(cam_index, getattr(cv2, "CAP_DSHOW", 0))
        self._open_handles[device_id] = cap
        try:
            if not cap.isOpened():
                raise CameraServiceError(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    f"Camera device '{device_id}' could not be opened (disconnected or busy).",
                )
            ok, frame = cap.read()
            if not ok or frame is None:
                raise CameraServiceError(
                    ErrorCode.RUNTIME_UNAVAILABLE,
                    f"Camera device '{device_id}' returned no frame.",
                )
            height, width = int(frame.shape[0]), int(frame.shape[1])
            raw_bytes = bytearray(frame.tobytes())
            return RawCameraFrame(
                device_id=device_id,
                width=width,
                height=height,
                raw_frame_bytes=raw_bytes,
                summary_caption=f"On-demand local camera frame ({width}x{height}) captured into RAM.",
            )
        finally:
            with contextlib.suppress(Exception):
                cap.release()
            self._open_handles.pop(device_id, None)

    def close_device(self, device_id: str) -> None:
        handle = self._open_handles.pop(device_id, None)
        if handle is not None and hasattr(handle, "release"):
            with contextlib.suppress(Exception):
                handle.release()
