"""Pure AI Provider, Model Manifest, Profile, Resource Governor & Voice Ports (zero IO, NFR-16)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import Field

from jarvis.domain.models import (
    AiProfileMode,
    BackendPreference,
    ErrorCode,
    RuntimeOwnershipMode,
    StrictModel,
    SupportTier,
    TrustZone,
)

THINK_BLOCK_RE = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)


def strip_thinking_blocks(text: str) -> str:
    """Remove <think>...</think> internal reasoning tags emitted by hybrid reasoning models."""
    return THINK_BLOCK_RE.sub("", text).strip()


def is_exposed_non_loopback_host(endpoint_ref: str) -> bool:
    """Detect 0.0.0.0 or [::] wildcard exposure warnings for local runtimes (FR-AIP-08)."""
    lowered = endpoint_ref.lower().strip()
    return "0.0.0.0" in lowered or "[::]" in lowered or "://::" in lowered  # noqa: S104


class ProviderCapabilityFlags(StrictModel):
    streaming: bool = True
    structured_json: bool = True
    thinking_control: bool = True
    cancelable: bool = True
    max_context_tokens: int = Field(default=4096, ge=512, le=131072)
    # B20 / DEF-35: optional Private LAN security pinning fields so GET /v1/providers validates cleanly without 500
    tls_fingerprint_sha256: str | None = None
    allowed_data_scopes: tuple[str, ...] = ()
    allow_cross_zone_fallback: bool = False


class ModelProviderRecord(StrictModel):
    id: str = Field(min_length=2, max_length=128)
    adapter_kind: Literal["llama_cpp", "ollama", "custom_openai_compatible"]
    adapter_version: str = Field(default="1.0.0", min_length=1, max_length=32)
    ownership_mode: RuntimeOwnershipMode
    trust_zone: TrustZone
    endpoint_ref: str = Field(min_length=4, max_length=512)
    credential_vault_ref: str | None = None
    capabilities: ProviderCapabilityFlags = Field(default_factory=ProviderCapabilityFlags)
    support_tier: SupportTier = SupportTier.UNVERIFIED
    enabled: bool = False
    last_probe_at: datetime | None = None
    health_code: str = "unknown"


class ModelResourceEstimate(StrictModel):
    ram_mib: int = Field(ge=64, le=524288)
    vram_mib: int = Field(ge=0, le=262144)
    min_context_tokens: int = Field(default=1024, ge=512)
    max_context_tokens: int = Field(default=4096, ge=512)


class ModelManifestRecord(StrictModel):
    id: str = Field(min_length=2, max_length=128)
    provider_id: str = Field(min_length=2, max_length=128)
    role: Literal["llm", "stt", "tts", "embedding", "vision", "wake", "reranker"]
    family: str = Field(min_length=1, max_length=64)
    revision: str = Field(min_length=1, max_length=128)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    byte_size: int = Field(gt=0)
    storage_ref: str | None = None
    is_shared_external_file: bool = False
    format: Literal["gguf", "onnx", "safetensors", "os_native", "ollama_blob"] = "gguf"
    license_spdx: str = Field(min_length=2, max_length=128)
    model_card_ref: str | None = None
    dataset_license_note: str | None = None
    supports_structured_output: bool = True
    supports_thinking_control: bool = True
    trust_remote_code: Literal[False] = False
    resource_estimate: ModelResourceEstimate
    approval_state: Literal["pending", "approved", "rejected", "revoked"] = "approved"
    verified_at: datetime | None = None


class AiProfileRecord(StrictModel):
    id: str = Field(min_length=2, max_length=64)
    revision: int = Field(ge=1, default=1)
    mode: AiProfileMode
    role_bindings: dict[str, str] = Field(default_factory=dict)
    runtime_knobs: dict[str, Any] = Field(default_factory=dict)
    resource_limits: dict[str, int] = Field(default_factory=dict)
    fallback_allowlist: tuple[str, ...] = ()


class ProviderProbeResult(StrictModel):
    healthy: bool
    health_code: str
    latency_ms: float = Field(ge=0.0)
    detected_models: tuple[str, ...] = ()
    capabilities: ProviderCapabilityFlags = Field(default_factory=ProviderCapabilityFlags)
    warnings: tuple[str, ...] = ()


class ChatMessage(StrictModel):
    role: Literal["system", "user", "assistant"]
    content: str


class LlmCompletionRequest(StrictModel):
    model_id: str
    messages: tuple[ChatMessage, ...] = Field(min_length=1)
    max_tokens: int = Field(default=512, ge=16, le=4096)
    temperature: float = Field(default=0.1, ge=0.0, le=1.5)
    enforce_non_thinking: bool = True
    expect_json: bool = False
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=120.0)


class LlmCompletionResponse(StrictModel):
    content: str
    raw_content: str
    model_id: str
    provider_id: str
    elapsed_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_stripped: bool = False


class LlmProviderPort(Protocol):
    """Port for pluggable LLM inference providers (llama.cpp, Ollama, custom)."""

    @property
    def provider_id(self) -> str: ...

    @property
    def ownership_mode(self) -> RuntimeOwnershipMode: ...

    @property
    def trust_zone(self) -> TrustZone: ...

    async def probe(self) -> ProviderProbeResult: ...

    async def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse: ...


class SttResult(StrictModel):
    text: str
    language: str
    confidence: float = Field(ge=0.0, le=1.0)
    elapsed_ms: float = Field(ge=0.0)
    engine_name: str


class SttProviderPort(Protocol):
    @property
    def engine_name(self) -> str: ...

    def transcribe_pcm16(
        self, pcm16_mono_16khz: bytes, *, language_hint: str | None = None
    ) -> SttResult: ...


class TtsVoiceInfo(StrictModel):
    id: str
    name: str
    language: str
    engine: str
    installed: bool
    license_spdx: str


class TtsResult(StrictModel):
    audio_pcm_or_wav: bytes
    sample_rate_hz: int
    elapsed_ms: float
    engine_name: str
    voice_id: str


class TtsProviderPort(Protocol):
    @property
    def engine_name(self) -> str: ...

    def list_installed_voices(self) -> tuple[TtsVoiceInfo, ...]: ...

    def synthesize(self, text: str, *, voice_id: str | None = None, rate: float = 1.0) -> TtsResult: ...


@dataclass(frozen=True)
class ResourceLoadPlan:
    permitted: bool
    backend: BackendPreference
    context_tokens: int
    degraded: bool
    fallback_to_direct: bool
    reason: str
    error_code: ErrorCode | None = None


class DynamicResourceGovernor:
    """Evaluates live free RAM/VRAM before model loads & enforces same-zone graceful degradation (BR-AI-02)."""

    @staticmethod
    def evaluate_model_load(
        *,
        estimate: ModelResourceEstimate,
        free_ram_mib: int,
        free_vram_mib: int,
        max_ram_cap_mib: int,
        max_vram_cap_mib: int,
        requested_backend: BackendPreference,
        requested_context: int,
        on_battery_saver: bool = False,
        gaming_active: bool = False,
    ) -> ResourceLoadPlan:
        """Select safe backend/context within caps without ever silently crossing trust zones."""
        if gaming_active:
            return ResourceLoadPlan(
                permitted=False,
                backend=BackendPreference.CPU,
                context_tokens=0,
                degraded=True,
                fallback_to_direct=True,
                reason="Heavy fullscreen/gaming workload detected; pausing local LLM load -> Direct Mode.",
                error_code=ErrorCode.RUNTIME_UNAVAILABLE,
            )

        effective_ram_budget = min(int(free_ram_mib * 0.85), max_ram_cap_mib)
        effective_vram_budget = min(int(free_vram_mib * 0.85), max_vram_cap_mib)
        target_ctx = min(requested_context, estimate.max_context_tokens)

        if on_battery_saver:
            target_ctx = min(target_ctx, max(estimate.min_context_tokens, 2048))

        wants_gpu = requested_backend in (
            BackendPreference.CUDA,
            BackendPreference.VULKAN,
            BackendPreference.ROCM,
            BackendPreference.AUTO,
        )

        # 1. Try GPU offload if VRAM budget satisfies estimate
        if wants_gpu and estimate.vram_mib > 0 and effective_vram_budget >= estimate.vram_mib:
            chosen = (
                BackendPreference.CUDA
                if requested_backend == BackendPreference.AUTO
                else requested_backend
            )
            return ResourceLoadPlan(
                permitted=True,
                backend=chosen,
                context_tokens=target_ctx,
                degraded=on_battery_saver,
                fallback_to_direct=False,
                reason=f"GPU VRAM budget ({effective_vram_budget} MiB) fits model ({estimate.vram_mib} MiB).",
            )

        # 2. Degrade context window to min_context_tokens for tight GPU VRAM (90% heuristic)
        reduced_vram = int(estimate.vram_mib * 0.85)
        if wants_gpu and estimate.vram_mib > 0 and effective_vram_budget >= reduced_vram:
            chosen = (
                BackendPreference.VULKAN
                if requested_backend == BackendPreference.AUTO
                else requested_backend
            )
            return ResourceLoadPlan(
                permitted=True,
                backend=chosen,
                context_tokens=estimate.min_context_tokens,
                degraded=True,
                fallback_to_direct=False,
                reason=(
                    f"Tight VRAM ({effective_vram_budget} MiB); degraded context to "
                    f"{estimate.min_context_tokens} tokens within local device zone."
                ),
            )

        # 3. Same-zone degradation to CPU RAM if RAM budget fits
        if effective_ram_budget >= estimate.ram_mib:
            degraded_ctx = min(target_ctx, 2048) if wants_gpu else target_ctx
            return ResourceLoadPlan(
                permitted=True,
                backend=BackendPreference.CPU,
                context_tokens=max(estimate.min_context_tokens, degraded_ctx),
                degraded=wants_gpu or on_battery_saver,
                fallback_to_direct=False,
                reason=(
                    f"Using CPU inference within RAM budget ({effective_ram_budget} MiB >= "
                    f"{estimate.ram_mib} MiB)."
                ),
            )

        # 4. Insufficient local memory -> honest Direct Mode fallback (never silent cloud/LAN!)
        return ResourceLoadPlan(
            permitted=False,
            backend=BackendPreference.CPU,
            context_tokens=0,
            degraded=True,
            fallback_to_direct=True,
            reason=(
                f"Insufficient local RAM ({effective_ram_budget} MiB) and VRAM ({effective_vram_budget} MiB) "
                f"for model ({estimate.ram_mib}/{estimate.vram_mib} MiB); entering Direct Mode."
            ),
            error_code=ErrorCode.WORKER_OOM,
        )
