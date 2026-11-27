"""Portable Managed Local LLM Runtime Manager (llama-server CUDA/Vulkan/CPU auto-discovery & lifecycle).

Discovers llama-server binaries and GGUF models strictly from configured StorageRoots or portable env overrides,
spawns llama-server under ProcessSupervisorPort (Win32 Job Object -> 0 orphans), and binds LlamaCppServerAdapter.
"""

from __future__ import annotations

import asyncio
import socket
from dataclasses import dataclass
from pathlib import Path

import httpx

from jarvis.application.ai_registry_service import AiRegistryService
from jarvis.domain.ai_models import AiProfileRecord, ModelProviderRecord
from jarvis.domain.models import (
    AiProfileMode,
    BackendPreference,
    HardwareSnapshot,
    RuntimeOwnershipMode,
    SupportTier,
    TrustZone,
)
from jarvis.domain.ports import ManagedProcessHandle, ProcessSupervisorPort
from jarvis.infrastructure.logging_setup import get_logger
from jarvis.infrastructure.provenance import ArtifactProvenanceError, ArtifactProvenanceVerifier
from jarvis.infrastructure.providers.llama_cpp_adapter import (
    LlamaCppServerAdapter,
    build_llama_server_args,
)


@dataclass(frozen=True)
class LocalLlmStatus:
    ready: bool
    starting: bool
    provider_id: str | None = None
    model_name: str | None = None
    model_path: str | None = None
    backend: str = "none"
    endpoint_url: str | None = None
    process_id: int | None = None
    note: str = "Direct Mode (no local GGUF model or runtime configured)."


def _pick_free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def discover_llama_server_binary(
    search_dirs: tuple[Path, ...],
    *,
    has_cuda: bool,
    has_vulkan: bool,
) -> tuple[Path, BackendPreference] | None:
    """Locate llama-server binary dynamically across user-configured runtime directories."""
    ordered_subdirs: list[tuple[str, BackendPreference]] = []
    if has_cuda:
        ordered_subdirs.append(("llama-cuda", BackendPreference.CUDA))
    if has_vulkan:
        ordered_subdirs.append(("llama-vulkan", BackendPreference.VULKAN))
    ordered_subdirs.extend(
        [
            ("llama-vulkan", BackendPreference.VULKAN),
            ("llama-cuda", BackendPreference.CUDA),
            ("llama-cpu", BackendPreference.CPU),
            ("", BackendPreference.CPU),
        ]
    )

    seen: set[tuple[str, BackendPreference]] = set()
    for base in search_dirs:
        if not base.exists():
            continue
        for sub, backend in ordered_subdirs:
            if (f"{base}/{sub}", backend) in seen:
                continue
            seen.add((f"{base}/{sub}", backend))
            target_dir = base / sub if sub else base
            for exe_name in ("llama-server.exe", "llama-server"):
                cand = target_dir / exe_name
                if cand.is_file():
                    return (cand, backend)
    return None


def discover_best_gguf_model(
    search_dirs: tuple[Path, ...],
    *,
    vram_mib: int,
) -> Path | None:
    """Pick the best installed local GGUF model fitting available GPU/RAM budget without hardcoding paths."""
    candidates: list[Path] = []
    for base in search_dirs:
        if not base.exists():
            continue
        candidates.extend(sorted(base.glob("*.gguf")))
        for sub in base.iterdir():
            if sub.is_dir():
                candidates.extend(sorted(sub.glob("*.gguf")))

    if not candidates:
        return None

    # Prefer Qwen3-4B on >= 3800 MiB VRAM (fits Q4_K_M + Q8 KV cache cleanly on 4 GB VRAM GPUs), else 1.7B, else first GGUF
    def _rank(p: Path) -> tuple[int, int]:
        low = p.name.lower()
        if vram_mib >= 3800 and "4b" in low and "qwen" in low:
            return (0, p.stat().st_size)
        if "1.7b" in low and "qwen" in low:
            return (1, p.stat().st_size)
        if "3b" in low or "4b" in low:
            return (2, p.stat().st_size)
        return (3, p.stat().st_size)

    candidates.sort(key=_rank)
    return candidates[0]


class LocalLlmRuntimeManager:
    """Manages optional local llama-server worker lifecycle with clean Job Object shutdown."""

    def __init__(
        self,
        *,
        supervisor: ProcessSupervisorPort,
        ai_registry: AiRegistryService,
        runtimes_dirs: tuple[Path, ...],
        models_dirs: tuple[Path, ...],
        hardware_snapshot: HardwareSnapshot,
        provenance_verifier: ArtifactProvenanceVerifier | None = None,
    ) -> None:
        self._supervisor = supervisor
        self._ai_registry = ai_registry
        self._runtimes_dirs = runtimes_dirs
        self._models_dirs = models_dirs
        self._hw = hardware_snapshot
        self._provenance = provenance_verifier
        self._logger = get_logger("jarvis.local_llm")
        self._proc: ManagedProcessHandle | None = None
        self._status = LocalLlmStatus(ready=False, starting=False)

    @property
    def status(self) -> LocalLlmStatus:
        return self._status

    async def start_if_available(self) -> LocalLlmStatus:
        """Start managed local llama-server asynchronously if binary & GGUF model are present."""
        has_cuda = any(g.supports_cuda for g in self._hw.gpus)
        has_vulkan = any(g.supports_vulkan for g in self._hw.gpus)
        max_vram_mib = max((g.vram_total_mib for g in self._hw.gpus), default=0)

        found_bin = discover_llama_server_binary(
            self._runtimes_dirs, has_cuda=has_cuda, has_vulkan=has_vulkan
        )
        found_model = discover_best_gguf_model(self._models_dirs, vram_mib=max_vram_mib)

        if found_bin is None or found_model is None:
            self._status = LocalLlmStatus(
                ready=False,
                starting=False,
                note="Direct Mode aktif — belum ada runtime llama-server / model GGUF di direktori penyimpanan.",
            )
            return self._status

        binary_path, backend = found_bin
        # IR-05 / B06: verify binary & GGUF model SHA-256 against trusted manifest before executing!
        if self._provenance is not None:
            try:
                self._provenance.verify_artifact(binary_path)
                self._provenance.verify_artifact(found_model)
            except ArtifactProvenanceError as exc:
                self._logger.warning(
                    "local_llm.provenance_rejected",
                    binary=binary_path.name,
                    model=found_model.name,
                    reason=str(exc),
                )
                self._status = LocalLlmStatus(
                    ready=False,
                    starting=False,
                    note=f"Direct Mode aktif — verifikasi integritas SHA-256 gagal: {exc}",
                )
                return self._status

        port = _pick_free_loopback_port()
        endpoint = f"http://127.0.0.1:{port}"
        threads = max(2, min(8, self._hw.cpu.physical_cores))

        self._status = LocalLlmStatus(
            ready=False,
            starting=True,
            provider_id="local_llama_cpp",
            model_name=found_model.stem,
            model_path=str(found_model),
            backend=backend.value,
            endpoint_url=endpoint,
            note=f"Memuat model lokal {found_model.stem} ({backend.value.upper()})...",
        )

        cmd = build_llama_server_args(
            binary_path=str(binary_path),
            model_path=str(found_model),
            host="127.0.0.1",
            port=port,
            context_tokens=4096,
            cpu_threads=threads,
            backend=backend,
            gpu_layers=99 if backend != BackendPreference.CPU else 0,
            kv_quant_q8=True,
        )

        try:
            self._proc = self._supervisor.spawn_managed(cmd, label=f"llama-server:{found_model.stem}")
        except Exception as exc:
            self._status = LocalLlmStatus(
                ready=False,
                starting=False,
                note=f"Gagal memulai llama-server lokal: {exc}",
            )
            return self._status

        # Wait up to 45s for llama-server /health == 200 (model loading onto GPU/RAM)
        ready = False
        async with httpx.AsyncClient(timeout=2.0, trust_env=False) as client:
            for _ in range(90):
                if self._proc is not None and not self._supervisor.is_alive(self._proc.process_id):
                    break
                try:
                    resp = await client.get(f"{endpoint}/health")
                    if resp.status_code == 200:
                        ready = True
                        break
                except (httpx.HTTPError, OSError) as exc:
                    self._logger.debug("local_llm.health_poll_waiting", error=type(exc).__name__)
                await asyncio.sleep(0.5)

        if not ready:
            self.stop()
            self._status = LocalLlmStatus(
                ready=False,
                starting=False,
                note=f"Model {found_model.stem} gagal siap dalam batas waktu; kembali ke Direct Mode.",
            )
            return self._status

        adapter = LlamaCppServerAdapter(
            provider_id="local_llama_cpp",
            endpoint_url=endpoint,
            ownership_mode=RuntimeOwnershipMode.MANAGED_LOCAL,
            trust_zone=TrustZone.LOCAL_DEVICE,
        )
        self._ai_registry.register_provider(
            ModelProviderRecord(
                id="local_llama_cpp",
                adapter_kind="llama_cpp",
                adapter_version="1.0.0",
                ownership_mode=RuntimeOwnershipMode.MANAGED_LOCAL,
                trust_zone=TrustZone.LOCAL_DEVICE,
                endpoint_ref=endpoint,
                support_tier=SupportTier.SUPPORTED,
                enabled=True,
                health_code="ok",
            ),
            correlation_id="bootstrap-local-llm",
        )
        self._ai_registry.bind_adapter(adapter)
        # Bind and activate balanced profile rev 2 to the live local Qwen3 / GGUF model
        self._ai_registry.upsert_profile(
            AiProfileRecord(
                id="balanced",
                revision=2,
                mode=AiProfileMode.BALANCED,
                role_bindings={
                    "llm_provider": "local_llama_cpp",
                    "llm_model": found_model.stem,
                },
                runtime_knobs={
                    "backend": backend.value,
                    "context_tokens": 4096,
                    "non_thinking": True,
                },
                resource_limits={"max_vram_mib": max_vram_mib or 0, "cpu_threads": threads},
                fallback_allowlist=("direct",),
            )
        )
        self._ai_registry.switch_profile_atomic(
            "balanced", target_revision=2, correlation_id="bootstrap-local-llm"
        )

        self._status = LocalLlmStatus(
            ready=True,
            starting=False,
            provider_id="local_llama_cpp",
            model_name=found_model.stem,
            model_path=str(found_model),
            backend=backend.value,
            endpoint_url=endpoint,
            process_id=self._proc.process_id if self._proc else None,
            note=f"Model lokal aktif: {found_model.stem} ({backend.value.upper()}).",
        )
        self._logger.info(
            "local_llm.ready",
            model=found_model.stem,
            backend=backend.value,
            port=port,
            pid=self._proc.process_id if self._proc else None,
        )
        return self._status

    def stop(self) -> None:
        if self._proc is not None:
            self._supervisor.terminate_process(self._proc)
            self._proc = None
        self._status = LocalLlmStatus(ready=False, starting=False, note="Local LLM stopped.")
