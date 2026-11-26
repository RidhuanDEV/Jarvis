"""Windows HardwareDiscoveryPort: dynamic probe of CPU, RAM, GPU, Display Hz, Storage & Power (DEC-016)."""

from __future__ import annotations

import ctypes
import platform
import sys
import uuid
from datetime import UTC, datetime
from typing import Literal

import psutil

from jarvis.domain.models import (
    AudioEndpointInfo,
    CpuInfo,
    DisplayInfo,
    GpuInfo,
    HardwareSnapshot,
    OsInfo,
    PowerState,
)
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter


class _DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", ctypes.c_uint32),
        ("DeviceName", ctypes.c_wchar * 32),
        ("DeviceString", ctypes.c_wchar * 128),
        ("StateFlags", ctypes.c_uint32),
        ("DeviceID", ctypes.c_wchar * 128),
        ("DeviceKey", ctypes.c_wchar * 128),
    ]


class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", ctypes.c_uint16),
        ("dmDriverVersion", ctypes.c_uint16),
        ("dmSize", ctypes.c_uint16),
        ("dmDriverExtra", ctypes.c_uint16),
        ("dmFields", ctypes.c_uint32),
        ("dmPositionX", ctypes.c_int32),
        ("dmPositionY", ctypes.c_int32),
        ("dmDisplayOrientation", ctypes.c_uint32),
        ("dmDisplayFixedOutput", ctypes.c_uint32),
        ("dmColor", ctypes.c_int16),
        ("dmDuplex", ctypes.c_int16),
        ("dmYResolution", ctypes.c_int16),
        ("dmTTOption", ctypes.c_int16),
        ("dmCollate", ctypes.c_int16),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_uint16),
        ("dmBitsPerPel", ctypes.c_uint32),
        ("dmPelsWidth", ctypes.c_uint32),
        ("dmPelsHeight", ctypes.c_uint32),
        ("dmDisplayFlags", ctypes.c_uint32),
        ("dmDisplayFrequency", ctypes.c_uint32),
        ("dmICMMethod", ctypes.c_uint32),
        ("dmICMIntent", ctypes.c_uint32),
        ("dmMediaType", ctypes.c_uint32),
        ("dmDitherType", ctypes.c_uint32),
        ("dmReserved1", ctypes.c_uint32),
        ("dmReserved2", ctypes.c_uint32),
        ("dmPanningWidth", ctypes.c_uint32),
        ("dmPanningHeight", ctypes.c_uint32),
    ]


DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004
ENUM_CURRENT_SETTINGS = -1


def _probe_nvidia_gpus() -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    try:
        import pynvml

        pynvml.nvmlInit()
        try:
            driver = pynvml.nvmlSystemGetDriverVersion()
            driver_str = driver.decode("utf-8", "replace") if isinstance(driver, bytes) else str(driver)
            count = int(pynvml.nvmlDeviceGetCount())
            for idx in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                name_raw = pynvml.nvmlDeviceGetName(handle)
                name = name_raw.decode("utf-8", "replace") if isinstance(name_raw, bytes) else str(name_raw)
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                gpus.append(
                    GpuInfo(
                        index=idx,
                        vendor="nvidia",
                        name=name,
                        vram_total_mib=int(mem.total // (1024 * 1024)),
                        vram_free_mib=int(mem.free // (1024 * 1024)),
                        driver_version=driver_str,
                        is_integrated=False,
                        supports_cuda=True,
                        supports_vulkan=True,
                        supports_rocm=False,
                    )
                )
        finally:
            pynvml.nvmlShutdown()
    except Exception:
        return []
    return gpus


def _classify_gpu_vendor(device_string: str) -> Literal["nvidia", "amd", "intel", "apple", "unknown"]:
    low = device_string.lower()
    if "nvidia" in low:
        return "nvidia"
    if "amd" in low or "radeon" in low:
        return "amd"
    if "intel" in low:
        return "intel"
    if "apple" in low:
        return "apple"
    return "unknown"


def _probe_windows_displays_and_adapters() -> tuple[tuple[DisplayInfo, ...], list[GpuInfo]]:
    if sys.platform != "win32":
        return ((), [])
    user32 = ctypes.windll.user32
    displays: list[DisplayInfo] = []
    adapter_gpus: list[GpuInfo] = []
    seen_adapters: set[str] = set()

    dev = _DISPLAY_DEVICEW()
    dev.cb = ctypes.sizeof(_DISPLAY_DEVICEW)
    idx = 0
    while user32.EnumDisplayDevicesW(None, idx, ctypes.byref(dev), 0):
        idx += 1
        flags = int(dev.StateFlags)
        if flags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            dm = _DEVMODEW()
            dm.dmSize = ctypes.sizeof(_DEVMODEW)
            if user32.EnumDisplaySettingsW(dev.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
                width = max(320, int(dm.dmPelsWidth))
                height = max(240, int(dm.dmPelsHeight))
                hz = float(dm.dmDisplayFrequency) if dm.dmDisplayFrequency >= 24 else 60.0
                displays.append(
                    DisplayInfo(
                        name=str(dev.DeviceName),
                        width_px=width,
                        height_px=height,
                        refresh_hz=hz,
                        scale_percent=100,
                        is_primary=bool(flags & DISPLAY_DEVICE_PRIMARY_DEVICE),
                    )
                )
            adapter_name = str(dev.DeviceString).strip()
            if adapter_name and adapter_name not in seen_adapters:
                seen_adapters.add(adapter_name)
                vendor = _classify_gpu_vendor(adapter_name)
                if vendor != "nvidia":
                    adapter_gpus.append(
                        GpuInfo(
                            index=len(adapter_gpus),
                            vendor=vendor,
                            name=adapter_name,
                            vram_total_mib=0,
                            vram_free_mib=0,
                            driver_version="",
                            is_integrated=(vendor == "intel" and "arc" not in adapter_name.lower()),
                            supports_cuda=False,
                            supports_vulkan=(vendor in ("amd", "intel")),
                            supports_rocm=(vendor == "amd"),
                        )
                    )
        dev = _DISPLAY_DEVICEW()
        dev.cb = ctypes.sizeof(_DISPLAY_DEVICEW)

    return (tuple(displays), adapter_gpus)


def _probe_power_state() -> PowerState:
    try:
        batt = psutil.sensors_battery()
    except Exception:
        return PowerState.UNKNOWN
    if batt is None:
        return PowerState.AC
    if batt.power_plugged:
        return PowerState.AC
    return PowerState.BATTERY_SAVER if batt.percent <= 20 else PowerState.BATTERY


class WindowsHardwareDiscoveryAdapter:
    """Live dynamic hardware probe on Windows without hardcoded reference machine values."""

    def __init__(self, fs_adapter: WindowsFilesystemSafetyAdapter | None = None) -> None:
        self._fs = fs_adapter or WindowsFilesystemSafetyAdapter()

    def discover(self) -> HardwareSnapshot:
        vm = psutil.virtual_memory()
        physical = psutil.cpu_count(logical=False) or 1
        logical = psutil.cpu_count(logical=True) or physical

        nvidia_gpus = _probe_nvidia_gpus()
        displays, other_gpus = _probe_windows_displays_and_adapters()

        merged_gpus: list[GpuInfo] = list(nvidia_gpus)
        next_idx = len(merged_gpus)
        for g in other_gpus:
            merged_gpus.append(g.model_copy(update={"index": next_idx}))
            next_idx += 1

        volumes = self._fs.list_volumes()
        # Placeholder empty endpoints in Phase 2 until Phase 3 sounddevice/pycaw AudioDevicePort wires in
        audio_endpoints: tuple[AudioEndpointInfo, ...] = ()

        return HardwareSnapshot(
            id=str(uuid.uuid4()),
            os_info=OsInfo(
                system=platform.system(),
                release=platform.release(),
                version=platform.version(),
                arch=platform.machine(),
            ),
            cpu=CpuInfo(
                model_name=platform.processor() or "Unknown CPU",
                physical_cores=physical,
                logical_cores=logical,
                isa_flags=(),
            ),
            ram_total_bytes=int(vm.total),
            ram_available_bytes=int(vm.available),
            gpus=tuple(merged_gpus),
            displays=displays,
            volumes=volumes,
            audio_endpoints=audio_endpoints,
            power_state=_probe_power_state(),
            captured_at=datetime.now(tz=UTC),
        )
