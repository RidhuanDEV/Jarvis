"""Core domain models, enums, and canonical hashing helpers (pure, zero IO)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class RiskClass(StrEnum):
    R0 = "R0"
    R1 = "R1"
    R2 = "R2"
    R3 = "R3"


class ChannelKind(StrEnum):
    LOCAL = "local"
    REMOTE = "remote"


class InputModality(StrEnum):
    TRUSTED_UI = "trusted_ui"
    TEXT = "text"
    VOICE = "voice"
    WORKFLOW = "workflow"
    REMOTE_API = "remote_api"


class SupportTier(StrEnum):
    SUPPORTED = "Supported"
    EXPERIMENTAL = "Experimental"
    UNVERIFIED = "Unverified"
    UNSUPPORTED = "Unsupported"


class RuntimeOwnershipMode(StrEnum):
    NONE = "none"
    MANAGED_LOCAL = "managed_local"
    EXTERNAL_LOCAL = "external_local"
    AUTHORIZED_LAN = "authorized_lan"
    CUSTOM_COMPATIBLE = "custom_compatible"


class TrustZone(StrEnum):
    LOCAL_DEVICE = "local_device"
    PRIVATE_LAN = "private_lan"
    CUSTOM_ISOLATED = "custom_isolated"


class StorageCategory(StrEnum):
    APP_DATA = "app_data"
    MODELS = "models"
    RUNTIMES = "runtimes"
    CORE_DB = "core_db"
    KNOWLEDGE_DB = "knowledge_db"
    LOGS = "logs"
    TEMP = "temp"
    CACHE = "cache"
    BACKUPS = "backups"
    IMPORTED_DOCS = "imported_docs"
    EXTENSIONS = "extensions"


WAL_DATABASE_CATEGORIES: frozenset[StorageCategory] = frozenset({StorageCategory.CORE_DB, StorageCategory.KNOWLEDGE_DB})

EVICTABLE_CACHE_CATEGORIES: frozenset[StorageCategory] = frozenset({StorageCategory.CACHE, StorageCategory.TEMP})


class LicenseArtifactCategory(StrEnum):
    APP_PACKAGE = "app_package"
    NATIVE_LIBRARY = "native_library"
    AI_RUNTIME = "ai_runtime"
    MODEL_WEIGHTS = "model_weights"
    TRAINING_DATASET = "training_dataset"
    VOICE_ASSET = "voice_asset"
    WAKE_MODEL = "wake_model"
    FONT = "font"
    ICON_SET = "icon_set"
    AUDIO_SFX = "audio_sfx"
    UI_ASSET = "ui_asset"


class ErrorCode(StrEnum):
    INVALID_ARGS = "INVALID_ARGS"
    DENIED = "DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    APPROVAL_EXPIRED = "APPROVAL_EXPIRED"
    TARGET_CHANGED = "TARGET_CHANGED"
    TARGET_AMBIGUOUS = "TARGET_AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    OFFLINE = "OFFLINE"
    INSUFFICIENT_DISK = "INSUFFICIENT_DISK"
    UNSUPPORTED_FILESYSTEM = "UNSUPPORTED_FILESYSTEM"
    RUNTIME_UNAVAILABLE = "RUNTIME_UNAVAILABLE"
    WORKER_OOM = "WORKER_OOM"
    LICENSE_UNVERIFIED = "LICENSE_UNVERIFIED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    VERIFY_TIMEOUT = "VERIFY_TIMEOUT"
    QUEUE_FULL = "QUEUE_FULL"
    CANCELED = "CANCELED"
    UNSUPPORTED = "UNSUPPORTED"
    INTERNAL = "INTERNAL"


class ActionOutcomeState(StrEnum):
    PENDING = "pending"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELED = "canceled"
    UNKNOWN = "unknown"


class ApprovalState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELED = "canceled"


class AiProfileMode(StrEnum):
    DIRECT = "direct"
    ECO = "eco"
    PERFORMANCE = "performance"
    BALANCED = "balanced"
    QUALITY = "quality"
    ADAPTIVE = "adaptive"
    CUSTOM = "custom"


class BackendPreference(StrEnum):
    AUTO = "auto"
    CPU = "cpu"
    CUDA = "cuda"
    VULKAN = "vulkan"
    ROCM = "rocm"
    METAL = "metal"
    REMOTE_LAN = "remote_lan"


class LifecyclePolicy(StrEnum):
    ALWAYS_LOADED = "always_loaded"
    ON_DEMAND = "on_demand"
    IDLE_UNLOAD = "idle_unload"


class VisualQualityTier(StrEnum):
    CINEMATIC = "cinematic"
    BALANCED = "balanced"
    LITE = "lite"
    REDUCED_MOTION = "reduced_motion"


class FpsTarget(StrEnum):
    AUTO = "auto"
    FPS_30 = "30"
    FPS_60 = "60"
    FPS_120 = "120"
    NATIVE = "native"


class PowerState(StrEnum):
    AC = "ac"
    BATTERY = "battery"
    BATTERY_SAVER = "battery_saver"
    UNKNOWN = "unknown"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OsInfo(StrictModel):
    system: str
    release: str
    version: str
    arch: str


class CpuInfo(StrictModel):
    model_name: str
    physical_cores: int = Field(ge=1)
    logical_cores: int = Field(ge=1)
    isa_flags: tuple[str, ...] = ()


class GpuInfo(StrictModel):
    index: int = Field(ge=0)
    vendor: Literal["nvidia", "amd", "intel", "apple", "unknown"]
    name: str
    vram_total_mib: int = Field(ge=0)
    vram_free_mib: int = Field(ge=0)
    driver_version: str = ""
    is_integrated: bool = False
    supports_cuda: bool = False
    supports_vulkan: bool = False
    supports_rocm: bool = False


class DisplayInfo(StrictModel):
    name: str
    width_px: int = Field(ge=320)
    height_px: int = Field(ge=240)
    refresh_hz: float = Field(ge=24.0)
    scale_percent: int = Field(ge=50, le=400, default=100)
    is_primary: bool = False


class StorageVolumeInfo(StrictModel):
    mount_point: str
    filesystem_kind: str
    total_bytes: int = Field(ge=0)
    free_bytes: int = Field(ge=0)
    is_removable: bool = False
    is_network: bool = False


class AudioEndpointInfo(StrictModel):
    id: str
    name: str
    direction: Literal["input", "output"]
    is_default: bool = False
    form_factor: Literal["headphones", "headset", "speakers", "microphone", "unknown"] = "unknown"


class HardwareSnapshot(StrictModel):
    id: str
    os_info: OsInfo
    cpu: CpuInfo
    ram_total_bytes: int = Field(gt=0)
    ram_available_bytes: int = Field(ge=0)
    gpus: tuple[GpuInfo, ...] = ()
    displays: tuple[DisplayInfo, ...] = ()
    volumes: tuple[StorageVolumeInfo, ...] = ()
    audio_endpoints: tuple[AudioEndpointInfo, ...] = ()
    power_state: PowerState = PowerState.UNKNOWN
    captured_at: datetime


class LocaleConfig(StrictModel):
    primary_language: str = Field(default="id-ID", min_length=2, max_length=16)
    multilingual_enabled: bool = True
    fallback_languages: tuple[str, ...] = ("en-US",)
    timezone_iana: str = Field(default="UTC", min_length=2, max_length=64)


class QuietHoursConfig(StrictModel):
    enabled: bool = True
    start_local: str = Field(default="22:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    end_local: str = Field(default="07:00", pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    allow_voice_priority: bool = False


class PersonaConfig(StrictModel):
    style: Literal["concise", "balanced", "formal", "warm"] = "balanced"
    verbosity: Literal["brief", "standard", "detailed"] = "standard"
    quiet_hours: QuietHoursConfig = Field(default_factory=QuietHoursConfig)
    proactive_enabled: bool = False


class StorageRootsConfig(StrictModel):
    app_data: str = Field(min_length=1)
    models: str = Field(min_length=1)
    runtimes: str = Field(min_length=1)
    core_db: str = Field(min_length=1)
    knowledge_db: str = Field(min_length=1)
    logs: str = Field(min_length=1)
    temp: str = Field(min_length=1)
    cache: str = Field(min_length=1)
    backups: str = Field(min_length=1)
    imported_docs: str = Field(min_length=1)
    extensions: str = Field(min_length=1)

    def as_category_map(self) -> dict[StorageCategory, str]:
        return {
            StorageCategory.APP_DATA: self.app_data,
            StorageCategory.MODELS: self.models,
            StorageCategory.RUNTIMES: self.runtimes,
            StorageCategory.CORE_DB: self.core_db,
            StorageCategory.KNOWLEDGE_DB: self.knowledge_db,
            StorageCategory.LOGS: self.logs,
            StorageCategory.TEMP: self.temp,
            StorageCategory.CACHE: self.cache,
            StorageCategory.BACKUPS: self.backups,
            StorageCategory.IMPORTED_DOCS: self.imported_docs,
            StorageCategory.EXTENSIONS: self.extensions,
        }


class StorageConfig(StrictModel):
    roots: StorageRootsConfig
    shared_model_directories: tuple[str, ...] = ()
    cache_quota_bytes: int | None = Field(default=10 * 1024 * 1024 * 1024, ge=1024 * 1024 * 1024)


class AiConfig(StrictModel):
    active_mode: AiProfileMode = AiProfileMode.DIRECT
    backend_preference: BackendPreference = BackendPreference.AUTO
    runtime_ownership_mode: RuntimeOwnershipMode = RuntimeOwnershipMode.NONE
    lifecycle_policy: LifecyclePolicy = LifecyclePolicy.IDLE_UNLOAD
    idle_unload_seconds: int = Field(default=300, ge=30, le=86400)
    max_ram_mib: int = Field(default=4096, ge=512, le=1048576)
    max_vram_mib: int = Field(default=0, ge=0, le=262144)
    cpu_threads: int = Field(default=4, ge=1, le=256)
    context_tokens: int = Field(default=4096, ge=512, le=131072)
    offline_mode: bool = True
    allow_cross_zone_fallback: Literal[False] = False


class VisualConfig(StrictModel):
    quality_tier: VisualQualityTier = VisualQualityTier.BALANCED
    fps_target: FpsTarget = FpsTarget.AUTO
    gpu_acceleration_enabled: bool = True
    reduced_motion_override: bool = False
    battery_saver_throttle: bool = True
    gaming_throttle: bool = True


class AudioConfig(StrictModel):
    mode: Literal["muted", "ptt", "wake"] = "muted"
    input_device_id: str | None = None
    output_device_id: str | None = None
    echo_guard_enabled: bool = True
    speech_rate: float = Field(default=1.0, ge=0.5, le=2.0)


class PermissionsConfig(StrictModel):
    deny_by_default: Literal[True] = True
    conversation_history_retention_enabled: bool = False
    remote_gateway_enabled: bool = False


class OnboardingConfig(StrictModel):
    completed: bool = False
    completed_steps: tuple[int, ...] = ()
    setup_mode: Literal["recommended", "custom"] = "recommended"

    @field_validator("completed_steps")
    @classmethod
    def validate_steps(cls, steps: tuple[int, ...]) -> tuple[int, ...]:
        if len(set(steps)) != len(steps):
            raise ValueError("completed_steps must not contain duplicates")
        for s in steps:
            if s < 1 or s > 10:
                raise ValueError("onboarding step must be between 1 and 10")
        return steps


class ConfigDocument(StrictModel):
    schema_version: Literal[1] = 1
    profile_name: str = Field(default="default", min_length=1, max_length=64)
    locale: LocaleConfig = Field(default_factory=LocaleConfig)
    persona: PersonaConfig = Field(default_factory=PersonaConfig)
    storage: StorageConfig
    ai: AiConfig = Field(default_factory=AiConfig)
    visual: VisualConfig = Field(default_factory=VisualConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    permissions: PermissionsConfig = Field(default_factory=PermissionsConfig)
    onboarding: OnboardingConfig = Field(default_factory=OnboardingConfig)


class ToolSpec(StrictModel):
    tool_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$", max_length=64)
    version: int = Field(ge=1, le=99)
    risk: RiskClass
    channels: tuple[ChannelKind, ...]
    capability: str = Field(min_length=2, max_length=64)
    timeout_ms: int = Field(ge=100, le=120000)
    idempotent: bool
    requires_network: bool = False
    verification: str = Field(min_length=1, max_length=64)


class ToolStepProposal(StrictModel):
    tool_id: str = Field(pattern=r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$", max_length=64)
    version: int = Field(ge=1, le=99)
    args: dict[str, Any] = Field(default_factory=dict)


class ToolProposal(StrictModel):
    steps: tuple[ToolStepProposal, ...] = Field(min_length=1, max_length=5)


class GrantRecord(StrictModel):
    id: str
    subject_type: Literal["local_owner", "device", "extension"]
    subject_id: str
    capability: str
    scope: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revision: int = Field(ge=1, default=1)


class SessionContext(StrictModel):
    session_id: str
    actor_ref: str
    channel: ChannelKind
    modality: InputModality
    is_os_locked: bool = False
    is_suspended: bool = False
    is_muted: bool = False
    offline_mode: bool = True
    untrusted_origin: bool = False


class ApprovalChallenge(StrictModel):
    approval_id: str
    action_run_id: str
    tool_id: str
    tool_version: int
    bound_hash: str
    nonce: str
    expires_at: datetime
    state: ApprovalState = ApprovalState.PENDING


class ApprovalDecisionRequest(StrictModel):
    decision: Literal["approve", "reject"]
    nonce: str = Field(min_length=16, max_length=256)
    bound_hash: str = Field(min_length=64, max_length=64)
    modality: InputModality = InputModality.TRUSTED_UI
    channel: ChannelKind = ChannelKind.LOCAL
    current_target_snapshot_hash: str | None = None


class StorageLocationRecord(StrictModel):
    category: StorageCategory
    resolved_path: str
    quota_bytes: int | None = None
    is_removable: bool = False
    filesystem_kind: str
    status: Literal["healthy", "degraded", "migrating", "offline", "blocked"]
    updated_at: datetime


class LicenseArtifact(StrictModel):
    schema_version: Literal[1] = 1
    id: str = Field(min_length=2, max_length=128)
    category: LicenseArtifactCategory
    name: str = Field(min_length=1, max_length=160)
    version_or_rev: str = Field(min_length=1, max_length=128)
    license_spdx: str = Field(min_length=2, max_length=128)
    obligations: tuple[str, ...] = ()
    source_url: str = Field(min_length=8, max_length=512)
    notice_text: str = Field(min_length=1, max_length=8192)
    verified_at: datetime


class SequencedEvent(StrictModel):
    schema_version: Literal[1] = 1
    event_id: str
    seq: int = Field(ge=1)
    request_id: str | None = None
    correlation_id: str
    type: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)


class ErrorEnvelope(StrictModel):
    code: ErrorCode
    message: str
    correlation_id: str
    retryable: bool = False


def canonical_json(data: Any) -> str:
    """Serialize data deterministically for cryptographic hashing."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def canonical_json_hash(data: Any) -> str:
    """Compute SHA-256 hex digest of canonical JSON representation."""
    return hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
