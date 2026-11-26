"""Portable system utilities and deterministic test adapters for all Platform Portability Ports."""

from __future__ import annotations

import hashlib
import hmac
import os
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from jarvis.domain.ai_models import SttResult, TtsResult, TtsVoiceInfo
from jarvis.domain.models import (
    AudioEndpointInfo,
    HardwareSnapshot,
    RuntimeOwnershipMode,
    StorageVolumeInfo,
)
from jarvis.domain.ports import (
    IpcEndpointInfo,
    ManagedProcessHandle,
    PathSafetyInspection,
    TargetHandleSnapshot,
)


class SystemClock:
    def now_utc(self) -> datetime:
        return datetime.now(tz=UTC)


class FrozenClock:
    def __init__(self, initial: datetime) -> None:
        self._now = initial

    def now_utc(self) -> datetime:
        return self._now

    def advance_seconds(self, seconds: int) -> datetime:
        self._now = self._now + timedelta(seconds=seconds)
        return self._now


class TokenIpcTransport:
    """LocalIpcTransportPort implementation holding 256-bit per-run token in memory."""

    def __init__(self, *, transport_kind: str, address: str, auth_token: str) -> None:
        if len(auth_token) < 32:
            raise ValueError("IPC auth token must be at least 32 characters (>= 256-bit entropy).")
        self._info = IpcEndpointInfo(transport_kind=transport_kind, address=address, authenticated=True)
        self._token = auth_token

    def endpoint_info(self) -> IpcEndpointInfo:
        return self._info

    def verify_token(self, presented_token: str) -> bool:
        return hmac.compare_digest(presented_token, self._token)


class InMemoryVaultAdapter:
    """In-memory SecretVaultAndCryptoPort for isolated automated tests (never touches host Credential Manager)."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}
        self._deks: dict[str, bytes] = {}

    def get_secret(self, key_ref: str) -> str | None:
        return self._secrets.get(key_ref)

    def set_secret(self, key_ref: str, value: str) -> None:
        self._secrets[key_ref] = value

    def delete_secret(self, key_ref: str) -> bool:
        return self._secrets.pop(key_ref, None) is not None

    def get_or_create_master_dek(self, key_ref: str) -> bytes:
        dek = self._deks.get(key_ref)
        if dek is None:
            dek = os.urandom(32)
            self._deks[key_ref] = dek
        return dek


class PortableFilesystemSafetyAdapter:
    """OS-neutral FilesystemSafetyPort useful for deterministic unit/integration tests."""

    def inspect_path(self, raw_path: str) -> PathSafetyInspection:
        stripped = raw_path.strip()
        if stripped.startswith("\\\\") or stripped.startswith("//") or stripped.lower().startswith("\\\\?\\unc\\"):
            return PathSafetyInspection(
                canonical_path=stripped,
                exists=False,
                is_reparse_point=False,
                filesystem_kind="SMB/UNC",
                is_network=True,
                is_removable=False,
                free_bytes=0,
                writable=False,
            )
        p = Path(stripped).expanduser()
        canonical = str(p.resolve(strict=False))
        probe = Path(canonical)
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        free_b = int(shutil.disk_usage(probe).free) if probe.exists() else 0
        return PathSafetyInspection(
            canonical_path=canonical,
            exists=p.exists(),
            is_reparse_point=p.is_symlink(),
            filesystem_kind="local",
            is_network=False,
            is_removable=False,
            free_bytes=free_b,
            writable=probe.exists() and os.access(probe, os.W_OK),
        )

    def is_wal_supported_path(self, raw_path: str) -> tuple[bool, str]:
        insp = self.inspect_path(raw_path)
        if insp.is_network:
            return (False, "Network filesystem rejected for SQLite WAL.")
        return (True, "Local filesystem verified for SQLite WAL.")

    def resolve_within_root(self, root_path: str, relative_path: str) -> str:
        root = Path(root_path).resolve(strict=True)
        resolved = (root / relative_path).resolve(strict=False)
        if not resolved.is_relative_to(root):
            raise PermissionError(f"Path '{resolved}' escapes authorized root '{root}'.")
        return str(resolved)

    def snapshot_target(self, canonical_path: str) -> TargetHandleSnapshot:
        p = Path(canonical_path)
        st = p.stat()
        file_index = f"{st.st_dev}:{st.st_ino}"
        digest = hashlib.sha256(f"{p.resolve()}|{st.st_size}|{st.st_mtime_ns}|{file_index}".encode()).hexdigest()
        return TargetHandleSnapshot(
            canonical_path=str(p.resolve()),
            size_bytes=int(st.st_size),
            mtime_ns=int(st.st_mtime_ns),
            file_index_id=file_index,
            snapshot_hash=digest,
        )

    def list_volumes(self) -> tuple[StorageVolumeInfo, ...]:
        usage = shutil.disk_usage(Path.cwd())
        return (
            StorageVolumeInfo(
                mount_point=Path.cwd().anchor or "/",
                filesystem_kind="local",
                total_bytes=int(usage.total),
                free_bytes=int(usage.free),
                is_removable=False,
                is_network=False,
            ),
        )


class StaticHardwareDiscoveryAdapter:
    def __init__(self, snapshot: HardwareSnapshot) -> None:
        self._snapshot = snapshot

    def discover(self) -> HardwareSnapshot:
        return self._snapshot


class InMemoryProcessSupervisor:
    """In-memory ProcessSupervisorPort enforcing BR-AI-04 ownership rules in unit tests."""

    def __init__(self) -> None:
        self._next_pid = 10_000
        self._alive: dict[int, ManagedProcessHandle] = {}

    def spawn_managed(
        self,
        command: Sequence[str],
        label: str,
        env_overrides: dict[str, str] | None = None,
    ) -> ManagedProcessHandle:
        self._next_pid += 1
        handle = ManagedProcessHandle(
            process_id=self._next_pid,
            ownership_mode=RuntimeOwnershipMode.MANAGED_LOCAL,
            label=label,
        )
        self._alive[handle.process_id] = handle
        return handle

    def register_external(self, process_id: int, label: str) -> ManagedProcessHandle:
        handle = ManagedProcessHandle(
            process_id=process_id,
            ownership_mode=RuntimeOwnershipMode.EXTERNAL_LOCAL,
            label=label,
        )
        self._alive[process_id] = handle
        return handle

    def terminate_process(self, handle: ManagedProcessHandle, *, force_external_approved: bool = False) -> bool:
        if handle.ownership_mode != RuntimeOwnershipMode.MANAGED_LOCAL and not force_external_approved:
            return False
        return self._alive.pop(handle.process_id, None) is not None

    def is_alive(self, process_id: int) -> bool:
        return process_id in self._alive

    def close_all_managed(self) -> int:
        managed_pids = [pid for pid, h in self._alive.items() if h.ownership_mode == RuntimeOwnershipMode.MANAGED_LOCAL]
        for pid in managed_pids:
            del self._alive[pid]
        return len(managed_pids)


class StaticAudioDeviceAdapter:
    def __init__(self, endpoints: tuple[AudioEndpointInfo, ...] = ()) -> None:
        self._endpoints = endpoints

    def set_endpoints(self, endpoints: tuple[AudioEndpointInfo, ...]) -> None:
        self._endpoints = endpoints

    def list_endpoints(self) -> tuple[AudioEndpointInfo, ...]:
        return self._endpoints


class FakeDesktopAutomationAdapter:
    def __init__(self, *, allowlist: frozenset[str] = frozenset({"calculator", "notepad", "paint"})) -> None:
        self._allowlist = allowlist
        self._volume = 50
        self.launched_apps: list[str] = []

    def launch_allowlisted_app(self, app_id: str) -> bool:
        key = app_id.strip().lower()
        if key not in self._allowlist:
            raise PermissionError(f"Application '{app_id}' is not allowlisted.")
        self.launched_apps.append(key)
        return True

    def get_volume_percent(self) -> int:
        return self._volume

    def set_volume_percent(self, percent: int) -> int:
        if percent < 0 or percent > 100:
            raise ValueError("Volume percent must be 0..100.")
        self._volume = percent
        return self._volume


class FakeNotificationAdapter:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, bool]] = []

    def send_local_notification(self, title: str, body: str, *, silent: bool = False) -> bool:
        self.sent.append((title, body, silent))
        return True


class FakeSttAdapter:
    def __init__(self, transcript: str = "atur volume ke 35") -> None:
        self._transcript = transcript

    @property
    def engine_name(self) -> str:
        return "fake_faster_whisper_small"

    def transcribe_pcm16(
        self, pcm16_mono_16khz: bytes, *, language_hint: str | None = None
    ) -> SttResult:
        return SttResult(
            text=self._transcript,
            language=language_hint or "id-ID",
            confidence=0.95,
            elapsed_ms=12.0,
            engine_name=self.engine_name,
        )


class FakeTtsAdapter:
    def __init__(self, voices: tuple[TtsVoiceInfo, ...] | None = None) -> None:
        self._voices = voices or (
            TtsVoiceInfo(
                id="id_ID-news_tts-medium",
                name="Piper Indonesian News Medium",
                language="id-ID",
                engine="piper_tts_gpl",
                installed=True,
                license_spdx="GPL-3.0-or-later",
            ),
        )

    @property
    def engine_name(self) -> str:
        return "piper_tts_gpl"

    def list_installed_voices(self) -> tuple[TtsVoiceInfo, ...]:
        return self._voices

    def synthesize(self, text: str, *, voice_id: str | None = None, rate: float = 1.0) -> TtsResult:
        return TtsResult(
            audio_pcm_or_wav=b"RIFF-FAKE-WAV-" + text.encode("utf-8")[:32],
            sample_rate_hz=22050,
            elapsed_ms=15.0,
            engine_name=self.engine_name,
            voice_id=voice_id or self._voices[0].id,
        )
