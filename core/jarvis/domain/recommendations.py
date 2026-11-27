"""Hardware-Adaptive Configuration Recommendation Engine (DEC-016, BR-AI-01, BR-SYS-01).

Pure domain logic: computes explainable, manually overridable defaults from a live
HardwareSnapshot with honest SupportTier classification (Supported, Experimental,
Unverified, Unsupported) and zero hardcoded developer-machine assumptions.
"""

from __future__ import annotations

from jarvis.domain.models import (
    AiProfileMode,
    BackendPreference,
    FpsTarget,
    GpuInfo,
    HardwareSnapshot,
    PowerState,
    RuntimeOwnershipMode,
    StrictModel,
    SupportTier,
    VisualQualityTier,
)

GIB = 1024 * 1024 * 1024


class HardwareRecommendation(StrictModel):
    support_tier: SupportTier
    hardware_class: str
    recommended_ai_mode: AiProfileMode
    recommended_backend: BackendPreference
    recommended_runtime_ownership: RuntimeOwnershipMode
    recommended_model_class: str
    recommended_max_ram_mib: int
    recommended_max_vram_mib: int
    recommended_cpu_threads: int
    recommended_context_tokens: int
    recommended_visual_tier: VisualQualityTier
    recommended_fps_target: FpsTarget
    reasons: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _pick_best_gpu(gpus: tuple[GpuInfo, ...]) -> GpuInfo | None:
    if not gpus:
        return None
    # Prefer discrete GPU with highest VRAM, then highest VRAM overall
    return max(gpus, key=lambda g: (0 if g.is_integrated else 1, g.vram_total_mib))


def recommend_configuration(snapshot: HardwareSnapshot) -> HardwareRecommendation:
    """Derive explainable initial AI and visual defaults from detected hardware."""
    ram_gib = snapshot.ram_total_bytes / GIB
    ram_mib = int(snapshot.ram_total_bytes // (1024 * 1024))
    physical_cores = max(1, snapshot.cpu.physical_cores)
    recommended_threads = max(2, min(physical_cores, max(1, snapshot.cpu.logical_cores - 2)))
    best_gpu = _pick_best_gpu(snapshot.gpus)
    warnings: list[str] = []
    reasons: list[str] = []

    if snapshot.power_state in (PowerState.BATTERY, PowerState.BATTERY_SAVER):
        warnings.append("Device is currently on battery power; conservative thermal and FPS defaults apply.")

    # Check primary display refresh rate for honest FPS note (never hardcoded to 60 Hz)
    primary_display = next((d for d in snapshot.displays if d.is_primary), None)
    if primary_display is None and snapshot.displays:
        primary_display = snapshot.displays[0]

    # Case 0: Very low system RAM (< 6 GiB) — local LLM unsupported, Direct Mode supported
    if ram_gib < 6.0:
        return HardwareRecommendation(
            support_tier=SupportTier.UNSUPPORTED,
            hardware_class="low_ram_direct_only",
            recommended_ai_mode=AiProfileMode.DIRECT,
            recommended_backend=BackendPreference.CPU,
            recommended_runtime_ownership=RuntimeOwnershipMode.NONE,
            recommended_model_class="none_direct_mode",
            recommended_max_ram_mib=max(512, int(ram_mib * 0.35)),
            recommended_max_vram_mib=0,
            recommended_cpu_threads=min(2, physical_cores),
            recommended_context_tokens=1024,
            recommended_visual_tier=VisualQualityTier.LITE,
            recommended_fps_target=FpsTarget.FPS_30,
            reasons=(
                f"Detected {ram_gib:.1f} GiB RAM (< 6 GiB minimum for local LLM inference).",
                "Direct Mode deterministic commands remain available offline with Lite visuals.",
            ),
            warnings=tuple(warnings + ["Local LLM execution is not recommended under 6 GiB RAM."]),
        )

    # Case 1: Discrete NVIDIA GPU with CUDA
    if best_gpu is not None and best_gpu.vendor == "nvidia" and not best_gpu.is_integrated:
        vram = best_gpu.vram_total_mib
        safe_vram_budget = max(1024, int(vram * 0.80))
        if vram >= 20000:
            reasons.append(f"Detected NVIDIA GPU '{best_gpu.name}' with {vram} MiB VRAM and {ram_gib:.1f} GiB RAM.")
            reasons.append("High VRAM supports larger local quantized models and Cinematic rendering.")
            return HardwareRecommendation(
                support_tier=SupportTier.SUPPORTED,
                hardware_class="nvidia_high_vram",
                recommended_ai_mode=AiProfileMode.QUALITY,
                recommended_backend=BackendPreference.CUDA,
                recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
                recommended_model_class="14B-32B quantized (Q4_K_M / Q6_K)",
                recommended_max_ram_mib=min(16384, int(ram_mib * 0.50)),
                recommended_max_vram_mib=safe_vram_budget,
                recommended_cpu_threads=recommended_threads,
                recommended_context_tokens=8192,
                recommended_visual_tier=VisualQualityTier.CINEMATIC,
                recommended_fps_target=FpsTarget.AUTO,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
            )
        if vram >= 10000:
            reasons.append(f"Detected NVIDIA GPU '{best_gpu.name}' with {vram} MiB VRAM and {ram_gib:.1f} GiB RAM.")
            reasons.append("12 GB-class VRAM fits 7B-14B quantized models within safe headroom.")
            return HardwareRecommendation(
                support_tier=SupportTier.SUPPORTED,
                hardware_class="nvidia_mid_vram",
                recommended_ai_mode=AiProfileMode.QUALITY,
                recommended_backend=BackendPreference.CUDA,
                recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
                recommended_model_class="7B-14B quantized (Q4_K_M)",
                recommended_max_ram_mib=min(12288, int(ram_mib * 0.50)),
                recommended_max_vram_mib=safe_vram_budget,
                recommended_cpu_threads=recommended_threads,
                recommended_context_tokens=8192,
                recommended_visual_tier=VisualQualityTier.CINEMATIC,
                recommended_fps_target=FpsTarget.AUTO,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
            )
        if vram >= 3500:
            reasons.append(f"Detected NVIDIA GPU '{best_gpu.name}' with {vram} MiB VRAM and {ram_gib:.1f} GiB RAM.")
            reasons.append("4-8 GB VRAM class runs 1.7B-4B Q4_K_M models with Q8_0 KV cache within 80% VRAM cap.")
            return HardwareRecommendation(
                support_tier=SupportTier.SUPPORTED,
                hardware_class="nvidia_entry_vram",
                recommended_ai_mode=AiProfileMode.BALANCED,
                recommended_backend=BackendPreference.CUDA,
                recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
                recommended_model_class="1.7B-4B quantized (Q4_K_M)",
                recommended_max_ram_mib=min(8192, int(ram_mib * 0.45)),
                recommended_max_vram_mib=safe_vram_budget,
                recommended_cpu_threads=recommended_threads,
                recommended_context_tokens=4096,
                recommended_visual_tier=VisualQualityTier.BALANCED,
                recommended_fps_target=FpsTarget.AUTO,
                reasons=tuple(reasons),
                warnings=tuple(warnings),
            )

    # Case 2: AMD or Intel discrete/capable Vulkan GPU
    if best_gpu is not None and best_gpu.vendor in ("amd", "intel") and best_gpu.vram_total_mib >= 3500:
        backend = (
            BackendPreference.ROCM
            if (best_gpu.vendor == "amd" and best_gpu.supports_rocm)
            else BackendPreference.VULKAN
        )
        safe_vram_budget = max(1024, int(best_gpu.vram_total_mib * 0.75))
        reasons.append(
            f"Detected {best_gpu.vendor.upper()} GPU '{best_gpu.name}' ({best_gpu.vram_total_mib} MiB VRAM)."
        )
        reasons.append(
            f"Recommending Adaptive mode via {backend.value.upper()} backend; users may switch to CPU or LAN anytime."
        )
        warnings.append(
            f"{best_gpu.vendor.upper()} {backend.value.upper()} acceleration is labeled Experimental until benchmarked on this host."
        )
        return HardwareRecommendation(
            support_tier=SupportTier.EXPERIMENTAL,
            hardware_class=f"{best_gpu.vendor}_gpu",
            recommended_ai_mode=AiProfileMode.ADAPTIVE,
            recommended_backend=backend,
            recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
            recommended_model_class=(
                "7B quantized (Q4_K_M)" if best_gpu.vram_total_mib >= 10000 else "1.7B-4B quantized (Q4_K_M)"
            ),
            recommended_max_ram_mib=min(8192, int(ram_mib * 0.45)),
            recommended_max_vram_mib=safe_vram_budget,
            recommended_cpu_threads=recommended_threads,
            recommended_context_tokens=4096,
            recommended_visual_tier=VisualQualityTier.BALANCED,
            recommended_fps_target=FpsTarget.AUTO,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    # Case 3: Unrecognized GPU vendor — honest Unverified badge with safe CPU/Vulkan fallback
    if best_gpu is not None and best_gpu.vendor == "unknown":
        reasons.append(f"Detected unrecognized GPU '{best_gpu.name}'; defaulting safely to CPU inference.")
        warnings.append(
            "GPU capabilities are unverified on this hardware profile; GPU offload can be enabled manually after benchmark."
        )
        return HardwareRecommendation(
            support_tier=SupportTier.UNVERIFIED,
            hardware_class="unknown_gpu_cpu_fallback",
            recommended_ai_mode=AiProfileMode.ECO if ram_gib < 14.0 else AiProfileMode.BALANCED,
            recommended_backend=BackendPreference.CPU,
            recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
            recommended_model_class="1.7B quantized (Q4_K_M CPU)",
            recommended_max_ram_mib=min(6144, int(ram_mib * 0.45)),
            recommended_max_vram_mib=0,
            recommended_cpu_threads=recommended_threads,
            recommended_context_tokens=2048 if ram_gib < 14.0 else 4096,
            recommended_visual_tier=VisualQualityTier.LITE if ram_gib < 14.0 else VisualQualityTier.BALANCED,
            recommended_fps_target=FpsTarget.AUTO,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    # Case 4: CPU-only (or small integrated GPU) with >= 14 GiB RAM
    if ram_gib >= 14.0:
        reasons.append(f"CPU-focused profile with {ram_gib:.1f} GiB RAM and {physical_cores} physical cores.")
        if primary_display is not None:
            reasons.append(
                f"Display detected at {primary_display.width_px}x{primary_display.height_px} @ {primary_display.refresh_hz:.0f} Hz; Auto FPS adapts dynamically."
            )
        return HardwareRecommendation(
            support_tier=SupportTier.SUPPORTED,
            hardware_class="cpu_only_16gb_plus",
            recommended_ai_mode=AiProfileMode.BALANCED,
            recommended_backend=BackendPreference.CPU,
            recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
            recommended_model_class="1.7B-3B quantized (CPU int4/Q4_K_M)",
            recommended_max_ram_mib=min(8192, int(ram_mib * 0.45)),
            recommended_max_vram_mib=0,
            recommended_cpu_threads=recommended_threads,
            recommended_context_tokens=4096,
            recommended_visual_tier=VisualQualityTier.BALANCED,
            recommended_fps_target=FpsTarget.AUTO,
            reasons=tuple(reasons),
            warnings=tuple(warnings),
        )

    # Case 5: CPU-only with 6..14 GiB RAM (8 GB class)
    reasons.append(
        f"Compact CPU-only profile with {ram_gib:.1f} GiB RAM; using Eco small quantized model and Lite visuals."
    )
    return HardwareRecommendation(
        support_tier=SupportTier.SUPPORTED,
        hardware_class="cpu_only_8gb",
        recommended_ai_mode=AiProfileMode.ECO,
        recommended_backend=BackendPreference.CPU,
        recommended_runtime_ownership=RuntimeOwnershipMode.MANAGED_LOCAL,
        recommended_model_class="1.5B-1.7B quantized (Q4_K_M CPU)",
        recommended_max_ram_mib=min(3584, int(ram_mib * 0.45)),
        recommended_max_vram_mib=0,
        recommended_cpu_threads=min(4, recommended_threads),
        recommended_context_tokens=2048,
        recommended_visual_tier=VisualQualityTier.LITE,
        recommended_fps_target=FpsTarget.FPS_30,
        reasons=tuple(reasons),
        warnings=tuple(warnings),
    )


class RuntimeGovernanceDecision(StrictModel):
    """Hardware-aware live runtime resource governor output (B20, NFR-14, DEC-016)."""

    effective_ai_mode: AiProfileMode
    effective_backend: BackendPreference
    effective_max_ram_mib: int
    effective_max_vram_mib: int
    effective_fps_target: FpsTarget
    unload_vram_now: bool
    fallback_to_direct: bool
    throttle_reasons: tuple[str, ...] = ()


class DynamicResourceGovernor:
    """Evaluates live hardware, battery, gaming pressure, idle VRAM TTL, and LLM health (B20, pure domain)."""

    def __init__(self, *, idle_vram_unload_seconds: int = 300) -> None:
        self._idle_vram_unload_seconds = max(30, idle_vram_unload_seconds)

    def evaluate(
        self,
        snapshot: HardwareSnapshot,
        *,
        requested_mode: AiProfileMode,
        idle_seconds: float = 0.0,
        gaming_or_fullscreen_active: bool = False,
        llm_runtime_healthy: bool = True,
    ) -> RuntimeGovernanceDecision:
        rec = recommend_configuration(snapshot)
        reasons: list[str] = []
        mode = requested_mode
        backend = rec.recommended_backend
        max_ram = rec.recommended_max_ram_mib
        max_vram = rec.recommended_max_vram_mib
        fps = rec.recommended_fps_target
        unload_vram = False
        fallback_direct = False

        if not llm_runtime_healthy and requested_mode != AiProfileMode.DIRECT:
            mode = AiProfileMode.DIRECT
            backend = BackendPreference.CPU
            max_vram = 0
            fallback_direct = True
            reasons.append("Local LLM runtime unhealthy/crashed; degraded safely to offline Direct Mode.")

        if snapshot.power_state == PowerState.BATTERY_SAVER:
            if mode in (AiProfileMode.QUALITY, AiProfileMode.BALANCED, AiProfileMode.PERFORMANCE):
                mode = AiProfileMode.ECO
            fps = FpsTarget.FPS_30
            max_vram = min(max_vram, 1536)
            reasons.append("Battery Saver active; capped visuals to 30 FPS and AI to Eco budget.")
        elif snapshot.power_state == PowerState.BATTERY:
            fps = FpsTarget.FPS_30
            reasons.append("On battery power; conservative 30 FPS visual pacing active.")

        if gaming_or_fullscreen_active:
            if mode != AiProfileMode.DIRECT:
                mode = AiProfileMode.ECO
            max_vram = 0
            backend = BackendPreference.CPU
            fps = FpsTarget.FPS_30
            unload_vram = True
            reasons.append("Fullscreen/gaming workload active; yielding GPU VRAM and capping background load.")

        if idle_seconds >= self._idle_vram_unload_seconds and max_vram > 0:
            unload_vram = True
            reasons.append(
                f"Idle for {int(idle_seconds)}s (>= {self._idle_vram_unload_seconds}s TTL); scheduling VRAM model unload."
            )

        # Memory pressure guard: if available RAM drops below 1.5 GiB, shrink RAM cap and drop to Eco/Direct
        avail_mib = int(snapshot.ram_available_bytes // (1024 * 1024))
        if avail_mib > 0 and avail_mib < 1536:
            max_ram = min(max_ram, max(512, avail_mib // 2))
            if mode in (AiProfileMode.QUALITY, AiProfileMode.BALANCED):
                mode = AiProfileMode.ECO
            reasons.append(f"Low available system RAM ({avail_mib} MiB); reduced active memory budget.")

        return RuntimeGovernanceDecision(
            effective_ai_mode=mode,
            effective_backend=backend,
            effective_max_ram_mib=max_ram,
            effective_max_vram_mib=max_vram,
            effective_fps_target=fps,
            unload_vram_now=unload_vram,
            fallback_to_direct=fallback_direct,
            throttle_reasons=tuple(reasons),
        )
