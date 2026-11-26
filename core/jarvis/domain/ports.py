"""9 Platform Portability Ports (DEC-023, NFR-16) and ClockPort.

Domain and application layers depend strictly on these Protocol interfaces,
never on Win32, ctypes, OS registry, or platform-specific libraries directly.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from jarvis.domain.models import (
    AudioEndpointInfo,
    HardwareSnapshot,
    RuntimeOwnershipMode,
    StorageVolumeInfo,
)


class ClockPort(Protocol):
    """Deterministic UTC clock abstraction."""

    def now_utc(self) -> datetime: ...


@dataclass(frozen=True)
class IpcEndpointInfo:
    transport_kind: str
    address: str
    authenticated: bool


class LocalIpcTransportPort(Protocol):
    """Port 1: Authenticated local IPC transport (Named Pipe DACL / authenticated loopback)."""

    def endpoint_info(self) -> IpcEndpointInfo: ...

    def verify_token(self, presented_token: str) -> bool: ...


@dataclass(frozen=True)
class ManagedProcessHandle:
    process_id: int
    ownership_mode: RuntimeOwnershipMode
    label: str


class ProcessSupervisorPort(Protocol):
    """Port 2: OS process lifecycle supervision (Job Object KILL_ON_JOB_CLOSE on Windows).

    Enforces BR-AI-04: may terminate managed_local processes only; MUST NOT terminate
    external_local processes without explicit owner authorization.
    """

    def spawn_managed(
        self,
        command: Sequence[str],
        label: str,
        env_overrides: dict[str, str] | None = None,
    ) -> ManagedProcessHandle: ...

    def register_external(self, process_id: int, label: str) -> ManagedProcessHandle: ...

    def terminate_process(self, handle: ManagedProcessHandle, *, force_external_approved: bool = False) -> bool: ...

    def is_alive(self, process_id: int) -> bool: ...

    def close_all_managed(self) -> int: ...


class SecretVaultAndCryptoPort(Protocol):
    """Port 3: OS credential vault & local data-encryption-key (DEK) protection."""

    def get_secret(self, key_ref: str) -> str | None: ...

    def set_secret(self, key_ref: str, value: str) -> None: ...

    def delete_secret(self, key_ref: str) -> bool: ...

    def get_or_create_master_dek(self, key_ref: str) -> bytes: ...


class DesktopAutomationPort(Protocol):
    """Port 4: Allowlisted non-shell desktop automation (Phase 3+ execution adapters)."""

    def launch_allowlisted_app(self, app_id: str) -> bool: ...

    def get_volume_percent(self) -> int: ...

    def set_volume_percent(self, percent: int) -> int: ...


class AudioDevicePort(Protocol):
    """Port 5: Dynamic audio endpoint enumeration & hotplug awareness."""

    def list_endpoints(self) -> tuple[AudioEndpointInfo, ...]: ...


@dataclass(frozen=True)
class PathSafetyInspection:
    canonical_path: str
    exists: bool
    is_reparse_point: bool
    filesystem_kind: str
    is_network: bool
    is_removable: bool
    free_bytes: int
    writable: bool


@dataclass(frozen=True)
class TargetHandleSnapshot:
    canonical_path: str
    size_bytes: int
    mtime_ns: int
    file_index_id: str
    snapshot_hash: str


class FilesystemSafetyPort(Protocol):
    """Port 6: Handle-pinned path canonicalization, reparse check, and WAL FS validation."""

    def inspect_path(self, raw_path: str) -> PathSafetyInspection: ...

    def is_wal_supported_path(self, raw_path: str) -> tuple[bool, str]: ...

    def resolve_within_root(self, root_path: str, relative_path: str) -> str: ...

    def snapshot_target(self, canonical_path: str) -> TargetHandleSnapshot: ...

    def list_volumes(self) -> tuple[StorageVolumeInfo, ...]: ...


class HardwareDiscoveryPort(Protocol):
    """Port 7: Live hardware capability discovery (CPU, RAM, GPU, Display, Storage, Power)."""

    def discover(self) -> HardwareSnapshot: ...


class NotificationPort(Protocol):
    """Port 8: Local OS notification delivery."""

    def send_local_notification(self, title: str, body: str, *, silent: bool = False) -> bool: ...


class StartupIntegrationPort(Protocol):
    """Port 9: Per-user OS startup registration without admin privileges."""

    def is_startup_enabled(self) -> bool: ...

    def set_startup_enabled(self, enabled: bool) -> bool: ...
