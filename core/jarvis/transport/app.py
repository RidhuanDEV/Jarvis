"""Authenticated FastAPI local core service with strict Host/Origin guards, wide-event JSON logging & SSE."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog
from fastapi import FastAPI, HTTPException, Query, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.application.ai_registry_service import AiRegistryError, AiRegistryService
from jarvis.application.approval_service import ApprovalError, ApprovalService
from jarvis.application.backup_service import BackupService, BackupServiceError
from jarvis.application.camera_service import (
    CameraCapturePort,
    CameraServiceError,
    OnDemandCameraService,
)
from jarvis.application.config_service import (
    ConfigService,
    ConfigServiceError,
    build_default_config,
    build_default_storage_roots,
)
from jarvis.application.context_service import ContextAssemblerService
from jarvis.application.ecosystem_service import (
    EcosystemGovernanceService,
    EcosystemServiceError,
    ExtensionManifest,
    PrivateLanProviderRegistration,
)
from jarvis.application.file_index_service import FileIndexError, FileIndexService
from jarvis.application.file_mutation_service import FileMutationError, FileMutationService
from jarvis.application.home_assistant_service import (
    HomeAssistantClientPort,
    HomeAssistantError,
    HomeAssistantService,
)
from jarvis.application.knowledge_service import KnowledgeRagService, KnowledgeServiceError
from jarvis.application.license_service import LicenseInventoryService
from jarvis.application.mcp_host_service import McpHostError, McpHostService
from jarvis.application.memory_service import MemoryServiceError, MemoryVaultService
from jarvis.application.oauth_connector_service import (
    OAuthConnectorError,
    OAuthReadOnlyConnectorService,
)
from jarvis.application.personal_life_service import PersonalLifeError, PersonalLifeService
from jarvis.application.preference_proposal_service import (
    PreferenceProposalError,
    PreferenceProposalService,
)
from jarvis.application.reminder_service import ReminderSchedulerService, ReminderServiceError
from jarvis.application.remote_gateway_service import RemoteGatewayError, RemoteGatewayService
from jarvis.application.scheduler_runner import BackgroundSchedulerRunner
from jarvis.application.screen_service import ScreenAwarenessError, ScreenAwarenessService
from jarvis.application.storage_service import StorageService, StorageServiceError
from jarvis.application.turn_orchestrator import TurnOrchestratorService
from jarvis.application.voice_service import VoicePipelineService, VoiceServiceError
from jarvis.application.web_search_service import WebIntelligenceService, WebSearchError
from jarvis.application.workflow_service import (
    WorkflowEngineService,
    WorkflowServiceError,
    WorkflowTrigger,
)
from jarvis.domain.ai_models import ModelManifestRecord, ModelProviderRecord
from jarvis.domain.licensing import LicenseValidationError
from jarvis.domain.mcp import McpServerRegistration
from jarvis.domain.models import (
    ActionOutcomeState,
    ApprovalDecisionRequest,
    ChannelKind,
    ErrorCode,
    ErrorEnvelope,
    GrantRecord,
    InputModality,
    LicenseArtifact,
    RiskClass,
    SessionContext,
    StorageCategory,
    ToolSpec,
    ToolStepProposal,
)
from jarvis.domain.policy import PolicyEngine
from jarvis.domain.ports import (
    ApplicationCatalogPort,
    AudioDevicePort,
    ClockPort,
    DesktopAutomationPort,
    FileOpenerPort,
    FilesystemSafetyPort,
    HardwareDiscoveryPort,
    LocalIpcTransportPort,
    NotificationPort,
    ProcessSupervisorPort,
    SecretVaultAndCryptoPort,
)
from jarvis.domain.recommendations import DynamicResourceGovernor, recommend_configuration
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus
from jarvis.infrastructure.home_assistant_client import PrivateLanHomeAssistantClient
from jarvis.infrastructure.live_voice_engine import LiveVoiceEngine, VoiceMode
from jarvis.infrastructure.logging_setup import configure_logging, get_logger
from jarvis.infrastructure.mcp_stdio_transport import McpStdioTransport
from jarvis.infrastructure.provenance import ArtifactProvenanceVerifier
from jarvis.infrastructure.providers.local_runtime_manager import LocalLlmRuntimeManager
from jarvis.infrastructure.web_fetch import SafeWebFetchClient
from jarvis.infrastructure.web_search_provider import SearxngWebSearchProvider
from jarvis.platform.portable_mock import (
    FakeNotificationAdapter,
    SystemClock,
    TokenIpcTransport,
    UnavailableNotificationAdapter,
)
from jarvis.platform.windows.app_catalog import WindowsApplicationCatalogAdapter
from jarvis.platform.windows.audio import (
    WindowsAudioDeviceAdapter,
    WindowsOneCoreVoiceProbeAdapter,
)
from jarvis.platform.windows.camera import WindowsOnDemandCameraAdapter
from jarvis.platform.windows.desktop_automation import WindowsDesktopAutomationAdapter
from jarvis.platform.windows.file_opener import WindowsFileOpenerAdapter
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter
from jarvis.platform.windows.hardware import WindowsHardwareDiscoveryAdapter
from jarvis.platform.windows.notifications import WindowsToastNotificationAdapter
from jarvis.platform.windows.screen_capture import WindowsActiveWindowCaptureAdapter
from jarvis.platform.windows.session_lock import is_windows_workstation_locked
from jarvis.platform.windows.supervisor import WindowsJobProcessSupervisor
from jarvis.platform.windows.vault import WindowsVaultAndCryptoAdapter
from jarvis.transport.settings import CoreStartupSettings

MAX_PAYLOAD_BYTES = 256 * 1024
ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "testserver"})


def _extract_host_without_port(raw_host_header: str) -> str:
    """Parse HTTP Host header safely for IPv4, hostname, and bracketed IPv6 ([::1]:port) (DEF-22)."""
    cleaned = raw_host_header.strip().lower()
    if not cleaned:
        return ""
    if cleaned.startswith("["):
        end_bracket = cleaned.find("]")
        if end_bracket == -1:
            return ""
        rest = cleaned[end_bracket + 1 :]
        if rest and not rest.startswith(":"):
            return ""
        return cleaned[: end_bracket + 1]
    return cleaned.split(":", 1)[0]


def default_tool_registry() -> dict[tuple[str, int], ToolSpec]:
    """Phase 2 baseline deterministic tool registry spanning R0, R1, R2, and explicit R3 probes."""
    specs = (
        ToolSpec(
            tool_id="system.time.get",
            version=1,
            risk=RiskClass.R0,
            channels=(ChannelKind.LOCAL, ChannelKind.REMOTE),
            capability="system.time",
            timeout_ms=1000,
            idempotent=True,
            verification="return_clock",
        ),
        ToolSpec(
            tool_id="os.volume.set",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL,),
            capability="os.volume",
            timeout_ms=3000,
            idempotent=True,
            verification="readback_volume",
        ),
        ToolSpec(
            tool_id="os.app.launch",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL,),
            capability="os.app.launch",
            timeout_ms=5000,
            idempotent=False,
            verification="os_activation_ack",
        ),
        ToolSpec(
            tool_id="fs.metadata.search",
            version=1,
            risk=RiskClass.R0,
            channels=(ChannelKind.LOCAL,),
            capability="fs.read",
            timeout_ms=5000,
            idempotent=True,
            verification="sqlite_read",
        ),
        ToolSpec(
            tool_id="fs.file.open",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL,),
            capability="fs.read",
            timeout_ms=5000,
            idempotent=False,
            verification="os_registered_open",
        ),
        ToolSpec(
            tool_id="memory.create",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL,),
            capability="memory.write",
            timeout_ms=3000,
            idempotent=False,
            verification="sqlite_commit",
        ),
        ToolSpec(
            tool_id="reminder.create",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL, ChannelKind.REMOTE),
            capability="reminder.write",
            timeout_ms=3000,
            idempotent=False,
            verification="sqlite_commit",
        ),
        ToolSpec(
            tool_id="life.task.create",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL, ChannelKind.REMOTE),
            capability="life.task",
            timeout_ms=3000,
            idempotent=False,
            verification="sqlite_commit",
        ),
        ToolSpec(
            tool_id="life.task.list",
            version=1,
            risk=RiskClass.R0,
            channels=(ChannelKind.LOCAL, ChannelKind.REMOTE),
            capability="life.task",
            timeout_ms=3000,
            idempotent=True,
            verification="sqlite_read",
        ),
        ToolSpec(
            tool_id="knowledge.query",
            version=1,
            risk=RiskClass.R0,
            channels=(ChannelKind.LOCAL, ChannelKind.REMOTE),
            capability="knowledge.read",
            timeout_ms=10000,
            idempotent=True,
            verification="citation_readback",
        ),
        ToolSpec(
            tool_id="screen.analyze",
            version=1,
            risk=RiskClass.R1,
            channels=(ChannelKind.LOCAL,),
            capability="screen.read",
            timeout_ms=5000,
            idempotent=True,
            verification="redacted_uia_read",
        ),
        ToolSpec(
            tool_id="storage.location.migrate",
            version=1,
            risk=RiskClass.R2,
            channels=(ChannelKind.LOCAL,),
            capability="storage.migrate",
            timeout_ms=60000,
            idempotent=False,
            verification="sha256_integrity",
        ),
        ToolSpec(
            tool_id="fs.file.move",
            version=1,
            risk=RiskClass.R2,
            channels=(ChannelKind.LOCAL,),
            capability="fs.move",
            timeout_ms=10000,
            idempotent=False,
            verification="handle_readback",
        ),
        ToolSpec(
            tool_id="fs.file.edit",
            version=1,
            risk=RiskClass.R2,
            channels=(ChannelKind.LOCAL,),
            capability="fs.edit",
            timeout_ms=10000,
            idempotent=False,
            verification="sha256_readback",
        ),
        ToolSpec(
            tool_id="web.search.query",
            version=1,
            risk=RiskClass.R0,
            channels=(ChannelKind.LOCAL,),
            capability="web.search",
            timeout_ms=10000,
            idempotent=True,
            requires_network=True,
            verification="http_response",
        ),
        ToolSpec(
            tool_id="workflow.execute",
            version=1,
            risk=RiskClass.R2,
            channels=(ChannelKind.LOCAL,),
            capability="workflow.execute",
            timeout_ms=120000,
            idempotent=False,
            verification="workflow_step_receipts",
        ),
        ToolSpec(
            tool_id="os.shell.exec",
            version=1,
            risk=RiskClass.R3,
            channels=(ChannelKind.LOCAL,),
            capability="shell.exec",
            timeout_ms=1000,
            idempotent=False,
            verification="never",
        ),
    )
    return {(s.tool_id, s.version): s for s in specs}


@dataclass
class CoreContainer:
    settings: CoreStartupSettings
    clock: ClockPort
    db: DualSqliteManager
    ipc_transport: LocalIpcTransportPort
    fs_port: FilesystemSafetyPort
    hardware_port: HardwareDiscoveryPort
    supervisor: ProcessSupervisorPort
    vault: SecretVaultAndCryptoPort
    audio_port: AudioDevicePort
    desktop_port: DesktopAutomationPort
    app_catalog: ApplicationCatalogPort
    file_opener: FileOpenerPort
    notification_port: NotificationPort
    event_bus: SequencedEventBus
    policy_engine: PolicyEngine
    config_service: ConfigService
    storage_service: StorageService
    approval_service: ApprovalService
    backup_service: BackupService
    license_service: LicenseInventoryService
    ai_registry: AiRegistryService
    voice_service: VoicePipelineService
    memory_service: MemoryVaultService
    context_service: ContextAssemblerService
    reminder_service: ReminderSchedulerService
    scheduler_runner: BackgroundSchedulerRunner
    turn_orchestrator: TurnOrchestratorService
    knowledge_service: KnowledgeRagService
    file_index_service: FileIndexService
    file_mutation_service: FileMutationService
    web_service: WebIntelligenceService
    screen_service: ScreenAwarenessService
    life_service: PersonalLifeService
    workflow_service: WorkflowEngineService
    ecosystem_service: EcosystemGovernanceService
    mcp_host_service: McpHostService
    oauth_connector_service: OAuthReadOnlyConnectorService
    camera_service: OnDemandCameraService
    ha_service: HomeAssistantService
    remote_gateway_service: RemoteGatewayService
    preference_proposal_service: PreferenceProposalService
    local_llm_manager: LocalLlmRuntimeManager
    live_voice_engine: LiveVoiceEngine
    resource_governor: DynamicResourceGovernor
    os_lock_probe: Callable[[], bool] = is_windows_workstation_locked
    manual_os_locked: bool = False

    def effective_os_locked(self, client_flag: bool = False) -> bool:
        """Authoritative workstation lock state: client False can NEVER override locked host/session (IR-07)."""
        return bool(self.manual_os_locked or self.os_lock_probe() or client_flag)


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetStorageLocationBody(_StrictRequest):
    path: str = Field(min_length=1, max_length=1024)
    quota_bytes: int | None = Field(default=None, ge=1024 * 1024 * 1024)


class MigrateStorageBody(_StrictRequest):
    category: StorageCategory
    target_path: str = Field(min_length=1, max_length=1024)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class ApplyStorageMigrationBody(_StrictRequest):
    approval_id: str = Field(min_length=8, max_length=128)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class CleanupCacheBody(_StrictRequest):
    category: StorageCategory
    max_bytes: int = Field(ge=0)


class UpsertGrantBody(_StrictRequest):
    id: str | None = None
    subject_type: str = Field(default="local_owner", pattern=r"^(local_owner|device|extension)$")
    subject_id: str = Field(default="local_owner", min_length=1, max_length=128)
    capability: str = Field(min_length=2, max_length=64)
    scope: dict[str, Any] = Field(default_factory=dict)
    expires_at: datetime | None = None


class PolicyEvalBody(_StrictRequest):
    tool_id: str = Field(min_length=2, max_length=64)
    tool_version: int = Field(default=1, ge=1, le=99)
    args: dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    channel: ChannelKind = ChannelKind.LOCAL
    modality: InputModality = InputModality.TRUSTED_UI
    is_os_locked: bool = False
    is_suspended: bool = False
    is_muted: bool = False
    target_snapshot_hash: str | None = None
    summary: str = Field(default="", max_length=512)


class BackupCreateBody(_StrictRequest):
    archive_path: str = Field(min_length=1, max_length=1024)
    recovery_passphrase: str = Field(min_length=8, max_length=256)


class BackupVerifyBody(_StrictRequest):
    archive_path: str = Field(min_length=1, max_length=1024)
    recovery_passphrase: str = Field(min_length=8, max_length=256)


class SessionLockBody(_StrictRequest):
    reason: str = Field(default="os_session_locked", min_length=1, max_length=128)


class CancelRequestBody(_StrictRequest):
    request_id: str | None = Field(default=None, max_length=64)


class SubmitTurnBody(_StrictRequest):
    utterance: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    channel: ChannelKind = ChannelKind.LOCAL
    modality: InputModality = InputModality.TRUSTED_UI
    is_os_locked: bool = False
    is_suspended: bool = False
    is_muted: bool = False
    speak_reply: bool = False


class ArmLiveVoiceBody(_StrictRequest):
    mode: VoiceMode


class SetAudioModeBody(_StrictRequest):
    mode: str = Field(pattern=r"^(muted|ptt|wake)$")


class SelectAudioDevicesBody(_StrictRequest):
    input_device_id: str | None = None
    output_device_id: str | None = None


class SetSpeechRateBody(_StrictRequest):
    speech_rate: float = Field(ge=0.5, le=2.0)


class ReplayTranscriptBody(_StrictRequest):
    transcript: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="local-voice-session", min_length=1, max_length=64)
    speak_reply: bool = False


class CreateMemoryBody(_StrictRequest):
    kind: str = Field(default="fact", pattern=r"^(fact|preference|instruction|note)$")
    content: str = Field(min_length=1, max_length=4000)
    sensitivity: str = Field(default="normal", pattern=r"^(normal|sensitive)$")
    source_ref: str = Field(default="local_owner", min_length=1, max_length=128)
    status: str = Field(default="active", pattern=r"^(active|proposal)$")


class UpdateMemoryBody(_StrictRequest):
    expected_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=4000)
    change_reason: str = Field(default="user_edit", min_length=1, max_length=128)


class ApproveProposalBody(_StrictRequest):
    expected_revision: int = Field(ge=1)


class CreateReminderBody(_StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    due_at_utc: datetime
    timezone_iana: str | None = Field(default=None, min_length=2, max_length=64)


class SnoozeReminderBody(_StrictRequest):
    expected_revision: int = Field(ge=1)
    minutes: int = Field(ge=1, le=1440)


class DismissReminderBody(_StrictRequest):
    expected_revision: int = Field(ge=1)


class AddSourceRootBody(_StrictRequest):
    path: str = Field(min_length=1, max_length=1024)
    scope: dict[str, Any] | None = None


class KnowledgeQueryBody(_StrictRequest):
    query: str = Field(min_length=1, max_length=1000)
    top_k: int = Field(default=5, ge=1, le=20)


class FileSearchBody(_StrictRequest):
    query: str = Field(default="", max_length=256)
    ext: str | None = Field(default=None, max_length=16)
    modified_after_utc: datetime | None = None
    limit: int = Field(default=10, ge=1, le=50)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class FileOpenBody(_StrictRequest):
    file_query: str | None = Field(default=None, max_length=256)
    result_index: int | None = Field(default=None, ge=1, le=50)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class ProposeFileEditBody(_StrictRequest):
    root_id: str = Field(min_length=1, max_length=64)
    relative_path: str = Field(min_length=1, max_length=512)
    new_content: str = Field(min_length=1, max_length=131072)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class ProposeFileMoveBody(_StrictRequest):
    root_id: str = Field(min_length=1, max_length=64)
    source_relative_path: str = Field(min_length=1, max_length=512)
    target_relative_path: str = Field(min_length=1, max_length=512)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class ApplyFileMutationBody(_StrictRequest):
    approval_id: str = Field(min_length=8, max_length=128)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class WebQueryBody(_StrictRequest):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)
    private_query_approved: bool = False
    allow_stale_cache_when_offline: bool = False
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class WebFetchBody(_StrictRequest):
    url: str = Field(min_length=8, max_length=2048)
    require_https: bool = False
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class WebProviderConfigBody(_StrictRequest):
    provider_name: str = Field(default="searxng_json", min_length=2, max_length=64)
    endpoint_url: str = Field(min_length=10, max_length=512)
    allow_loopback_searxng: bool = False
    consent_acknowledged: bool = False


class HaConnectBody(_StrictRequest):
    base_url: str = Field(min_length=10, max_length=512)
    credential_vault_ref: str = Field(min_length=3, max_length=128)
    allow_loopback_http: bool = False
    consent_acknowledged: bool = False


class OAuthStartBody(_StrictRequest):
    connector_id: str = Field(min_length=3, max_length=64)
    kind: str = Field(pattern=r"^(oauth_calendar|oauth_mail)$")
    provider_name: str = Field(min_length=2, max_length=64)
    authorize_url: str = Field(min_length=10, max_length=512)
    token_url: str = Field(min_length=10, max_length=512)
    api_base_url: str = Field(min_length=10, max_length=512)
    redirect_uri: str = Field(min_length=12, max_length=256)
    client_id: str = Field(min_length=2, max_length=128)
    scopes: tuple[str, ...] = Field(min_length=1, max_length=8)
    consent_acknowledged: bool = False


class OAuthCompleteBody(_StrictRequest):
    state_nonce: str = Field(min_length=12, max_length=128)
    authorization_code: str = Field(min_length=2, max_length=512)
    code_verifier: str = Field(min_length=43, max_length=128)


class RemoteTlsProvisionBody(_StrictRequest):
    bind_address: str = Field(min_length=3, max_length=64)
    validity_days: int = Field(default=365, ge=1, le=825)


class ScreenAnalyzeBody(_StrictRequest):
    window_selector: str = Field(min_length=1, max_length=256)
    explicit_user_request: bool = False
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    is_os_locked: bool = False


class CreateTaskBody(_StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    due_at_utc: datetime | None = None


class UpdateTaskStatusBody(_StrictRequest):
    expected_revision: int = Field(ge=1)
    status: str = Field(pattern=r"^(open|in_progress|completed|canceled)$")


class CreateCalendarEventBody(_StrictRequest):
    title: str = Field(min_length=1, max_length=300)
    start_at_utc: datetime
    end_at_utc: datetime
    timezone_iana: str = Field(min_length=2, max_length=64)


class RecordExpenseBody(_StrictRequest):
    amount_minor: int = Field(gt=0)
    currency_iso: str = Field(min_length=3, max_length=3)
    kind: str = Field(default="expense", pattern=r"^(expense|refund)$")
    category: str = Field(min_length=1, max_length=64)
    notes: str | None = Field(default=None, max_length=500)


class LogHabitBody(_StrictRequest):
    habit_key: str = Field(min_length=1, max_length=64)
    local_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    timezone_iana: str = Field(min_length=2, max_length=64)
    value: float
    unit: str = Field(min_length=1, max_length=32)


class CreateWorkflowBody(_StrictRequest):
    name: str = Field(min_length=1, max_length=128)
    trigger: WorkflowTrigger = Field(default_factory=lambda: WorkflowTrigger(kind="manual"))
    steps: tuple[ToolStepProposal, ...] = Field(min_length=1, max_length=5)
    total_timeout_seconds: int = Field(default=60, ge=1, le=120)
    enabled: bool = True


class ExecuteWorkflowBody(_StrictRequest):
    approved_bound_hash: str | None = None
    approval_id: str | None = Field(default=None, min_length=8, max_length=128)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    cancel_after_step: int | None = None
    simulate_unknown_at_step: int | None = None


class InstallExtensionBody(_StrictRequest):
    manifest: ExtensionManifest
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class ToggleExtensionBody(_StrictRequest):
    enabled: bool


class ToggleMcpServerBody(_StrictRequest):
    enabled: bool


class CallMcpToolBody(_StrictRequest):
    tool_name: str = Field(min_length=2, max_length=64)
    arguments: dict[str, Any] = Field(default_factory=dict)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)


class CameraGrantBody(_StrictRequest):
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    explicit_local_consent: bool = False
    is_os_locked: bool = False


class CameraSnapshotBody(_StrictRequest):
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    device_id: str = Field(min_length=1, max_length=128)
    explicit_user_request: bool = False
    is_os_locked: bool = False
    is_suspended: bool = False


class HaAllowlistBody(_StrictRequest):
    entity_id: str = Field(min_length=3, max_length=128)
    friendly_name: str = Field(min_length=1, max_length=128)
    allowed_actions: tuple[str, ...] = Field(min_length=1, max_length=8)


class HaActionBody(_StrictRequest):
    entity_id: str = Field(min_length=3, max_length=128)
    action: str = Field(min_length=2, max_length=64)
    params: dict[str, Any] = Field(default_factory=dict)
    is_os_locked: bool = False


class RemoteGatewayConfigBody(_StrictRequest):
    enabled: bool
    bind_address: str = Field(min_length=3, max_length=64)
    bind_port: int = Field(default=47443, ge=1024, le=65535)
    tls_cert_fingerprint_sha256: str = Field(default="", max_length=64)
    rate_limit_per_minute: int = Field(default=30, ge=1, le=120)


class RemotePairingInitBody(_StrictRequest):
    device_label: str = Field(min_length=2, max_length=64)
    device_fingerprint: str = Field(min_length=8, max_length=128)


class RemotePairingApproveBody(_StrictRequest):
    pairing_code: str = Field(min_length=6, max_length=6)
    scopes: tuple[str, ...] = Field(
        default=("remote.status.read", "remote.chat.send", "remote.reminder.read"),
        min_length=1,
        max_length=8,
    )
    token_ttl_hours: int = Field(default=24, ge=1, le=168)
    is_os_locked: bool = False


class PreferenceProposalCreateBody(_StrictRequest):
    preference_key: str = Field(min_length=3, max_length=128)
    proposed_value: str = Field(min_length=1, max_length=128)
    rationale: str = Field(min_length=3, max_length=500)
    evidence_count: int = Field(default=2, ge=1, le=100)


class PreferenceProposalDecideBody(_StrictRequest):
    decision: str = Field(pattern=r"^(approve|reject|dismiss)$")
    is_os_locked: bool = False


def _error_status_for_code(code: ErrorCode) -> int:
    mapping = {
        ErrorCode.INVALID_ARGS: status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.DENIED: status.HTTP_403_FORBIDDEN,
        ErrorCode.APPROVAL_REQUIRED: status.HTTP_202_ACCEPTED,
        ErrorCode.APPROVAL_EXPIRED: status.HTTP_409_CONFLICT,
        ErrorCode.TARGET_CHANGED: status.HTTP_409_CONFLICT,
        ErrorCode.NOT_FOUND: status.HTTP_404_NOT_FOUND,
        ErrorCode.OFFLINE: status.HTTP_503_SERVICE_UNAVAILABLE,
        ErrorCode.INSUFFICIENT_DISK: status.HTTP_507_INSUFFICIENT_STORAGE,
        ErrorCode.UNSUPPORTED_FILESYSTEM: status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.LICENSE_UNVERIFIED: status.HTTP_422_UNPROCESSABLE_CONTENT,
        ErrorCode.QUEUE_FULL: status.HTTP_429_TOO_MANY_REQUESTS,
    }
    return mapping.get(code, status.HTTP_400_BAD_REQUEST)


def _error_response(
    *,
    code: ErrorCode,
    message: str,
    correlation_id: str,
    http_status: int | None = None,
    retryable: bool = False,
) -> JSONResponse:
    envelope = ErrorEnvelope(code=code, message=message, correlation_id=correlation_id, retryable=retryable)
    return JSONResponse(
        status_code=http_status or _error_status_for_code(code),
        content=envelope.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id},
    )


def build_default_container(
    settings: CoreStartupSettings,
    *,
    clock: ClockPort | None = None,
    fs_port: FilesystemSafetyPort | None = None,
    hardware_port: HardwareDiscoveryPort | None = None,
    supervisor: ProcessSupervisorPort | None = None,
    vault: SecretVaultAndCryptoPort | None = None,
    audio_port: AudioDevicePort | None = None,
    desktop_port: DesktopAutomationPort | None = None,
    app_catalog: ApplicationCatalogPort | None = None,
    file_opener: FileOpenerPort | None = None,
    notification_port: NotificationPort | None = None,
    camera_port: CameraCapturePort | None = None,
    ha_client: HomeAssistantClientPort | None = None,
    tier1_auto_allow: bool | None = None,
) -> CoreContainer:
    data_dir = settings.resolved_data_dir()
    cache_dir = settings.resolved_cache_dir()
    roots = build_default_storage_roots(data_dir, cache_dir)

    resolved_clock = clock or SystemClock()
    resolved_fs = fs_port or WindowsFilesystemSafetyAdapter()
    resolved_hw = hardware_port or WindowsHardwareDiscoveryAdapter()
    resolved_sup = supervisor or WindowsJobProcessSupervisor()
    resolved_vault = vault or WindowsVaultAndCryptoAdapter()
    resolved_audio = audio_port or WindowsAudioDeviceAdapter()
    resolved_desktop = desktop_port or WindowsDesktopAutomationAdapter(
        allow_live_launch=(settings.env != "test")
    )
    resolved_app_catalog: ApplicationCatalogPort = (
        app_catalog
        if app_catalog is not None
        else WindowsApplicationCatalogAdapter(scan_registry=(settings.env != "test"))
    )
    resolved_file_opener: FileOpenerPort = (
        file_opener
        if file_opener is not None
        else WindowsFileOpenerAdapter(
            resolved_fs, allow_live_open=(settings.env != "test")
        )
    )
    resolved_notify: NotificationPort = (
        notification_port
        if notification_port is not None
        else (
            FakeNotificationAdapter()
            if settings.env == "test"
            else (
                WindowsToastNotificationAdapter(allow_live_toast=True)
                if sys.platform == "win32"
                else UnavailableNotificationAdapter()
            )
        )
    )
    resolved_lock_probe: Callable[[], bool] = (
        (lambda: False) if settings.env == "test" else is_windows_workstation_locked
    )
    resolved_tier1 = (
        tier1_auto_allow if tier1_auto_allow is not None else (settings.env != "test")
    )

    db = DualSqliteManager(
        core_db_path=Path(roots.core_db) / "jarvis_core.db",
        knowledge_db_path=Path(roots.knowledge_db) / "jarvis_knowledge.db",
        pre_migration_backup_dir=Path(roots.backups) / "pre_migration",
        load_sqlite_vec=True,
    )
    db.initialize()

    event_bus = SequencedEventBus()
    config_service = ConfigService(db, resolved_clock)
    config_service.ensure_initialized(build_default_config(roots))

    storage_service = StorageService(db, config_service, resolved_fs, resolved_clock)
    storage_service.sync_locations_from_config()

    policy_engine = PolicyEngine(
        default_tool_registry(), tier1_auto_allow=resolved_tier1
    )
    approval_service = ApprovalService(db, resolved_clock, event_bus)
    backup_service = BackupService(
        db,
        resolved_clock,
        allowed_backup_root=Path(roots.backups),
        fs_port=resolved_fs,
        vault=resolved_vault,
    )
    license_service = LicenseInventoryService(db, resolved_clock)
    license_service.seed_baseline_if_empty()

    ai_registry = AiRegistryService(db, resolved_clock, event_bus)
    ai_registry.seed_default_profiles()

    voice_service = VoicePipelineService(
        db,
        config_service,
        resolved_audio,
        resolved_clock,
        event_bus,
        tts_providers=(WindowsOneCoreVoiceProbeAdapter(),),
    )
    memory_service = MemoryVaultService(db, resolved_vault, resolved_clock)
    context_service = ContextAssemblerService(db, config_service, memory_service, resolved_clock)
    reminder_service = ReminderSchedulerService(
        db, config_service, resolved_notify, resolved_clock, event_bus
    )
    scheduler_runner = BackgroundSchedulerRunner(
        reminder_service, resolved_clock, interval_seconds=5.0
    )
    knowledge_service = KnowledgeRagService(db, resolved_fs, resolved_clock, event_bus)
    file_index_service = FileIndexService(
        db, resolved_fs, resolved_clock, opener=resolved_file_opener
    )
    file_mutation_service = FileMutationService(
        db, policy_engine, approval_service, resolved_fs, resolved_clock
    )
    web_service = WebIntelligenceService(
        db,
        config_service,
        SafeWebFetchClient(resolved_clock),
        resolved_clock,
        context_service=context_service,
    )
    screen_service = ScreenAwarenessService(
        db,
        resolved_clock,
        capture_port=(
            WindowsActiveWindowCaptureAdapter()
            if sys.platform == "win32" and settings.env != "test"
            else None
        ),
    )
    life_service = PersonalLifeService(db, resolved_clock)
    turn_orchestrator = TurnOrchestratorService(
        db=db,
        config_service=config_service,
        policy_engine=policy_engine,
        approval_service=approval_service,
        ai_registry=ai_registry,
        memory_service=memory_service,
        reminder_service=reminder_service,
        desktop_port=resolved_desktop,
        fs_port=resolved_fs,
        clock=resolved_clock,
        event_bus=event_bus,
        knowledge_service=knowledge_service,
        life_service=life_service,
        screen_service=screen_service,
        app_catalog=resolved_app_catalog,
        file_index_service=file_index_service,
        context_service=context_service,
    )

    async def _workflow_step_executor(
        step: ToolStepProposal, session: SessionContext, correlation_id: str
    ) -> tuple[ActionOutcomeState, bool, str]:
        rec = await turn_orchestrator.execute_verified_step_for_workflow(
            step.tool_id,
            step.version,
            step.args,
            session=session,
            correlation_id=correlation_id,
        )
        return (rec.state, rec.verified, rec.summary)

    workflow_service = WorkflowEngineService(
        db,
        policy_engine,
        resolved_clock,
        approval_service=approval_service,
        allow_simulated_steps=False,
        async_step_executor=_workflow_step_executor,
    )
    ecosystem_service = EcosystemGovernanceService(db, resolved_vault, resolved_clock)
    mcp_host_service = McpHostService(
        db,
        resolved_vault,
        resolved_clock,
        event_bus,
        context_service=context_service,
        transport=McpStdioTransport(),
    )
    oauth_connector_service = OAuthReadOnlyConnectorService(
        db,
        config_service,
        resolved_vault,
        life_service,
        resolved_clock,
        context_service=context_service,
    )
    resolved_camera_port: CameraCapturePort | None = camera_port
    if resolved_camera_port is None and sys.platform == "win32" and settings.env != "test":
        resolved_camera_port = WindowsOnDemandCameraAdapter(allow_live_hardware_capture=True)
    camera_service = OnDemandCameraService(
        db, resolved_clock, event_bus, capture_port=resolved_camera_port
    )
    ha_service = HomeAssistantService(db, resolved_clock, client=ha_client)
    remote_gateway_service = RemoteGatewayService(
        db, resolved_clock, tls_dir=data_dir / "remote_tls"
    )
    preference_proposal_service = PreferenceProposalService(db, config_service, resolved_clock)

    active_cfg = config_service.get_active().document
    runtimes_dirs_list: list[Path] = []
    if settings.runtimes_dir is not None:
        runtimes_dirs_list.append(settings.runtimes_dir)
    runtimes_dirs_list.append(Path(roots.runtimes))
    models_dirs_list: list[Path] = []
    if settings.models_dir is not None:
        models_dirs_list.append(settings.models_dir)
    models_dirs_list.append(Path(roots.models))
    for shared_dir in active_cfg.storage.shared_model_directories:
        models_dirs_list.append(Path(shared_dir))

    hw_snapshot = resolved_hw.discover()
    provenance_verifier = ArtifactProvenanceVerifier(
        manifest_path=data_dir / "trusted_artifacts.json",
        require_manifest=True,
    )
    local_llm_manager = LocalLlmRuntimeManager(
        supervisor=resolved_sup,
        ai_registry=ai_registry,
        runtimes_dirs=tuple(runtimes_dirs_list),
        models_dirs=tuple(models_dirs_list),
        hardware_snapshot=hw_snapshot,
        provenance_verifier=provenance_verifier,
    )

    async def _on_voice_utterance(spoken_text: str) -> tuple[str, str, bool]:
        cfg_now = config_service.get_active().document
        voice_session = SessionContext(
            session_id="local-voice-session",
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.VOICE,
            is_os_locked=resolved_lock_probe(),
            offline_mode=cfg_now.ai.offline_mode,
        )
        res = await turn_orchestrator.submit_turn(
            spoken_text, session=voice_session, correlation_id=f"voice_{uuid.uuid4().hex[:12]}"
        )
        return (res.reply, res.route_kind, res.llm_called)

    async def _on_voice_utterance_stream(
        spoken_text: str, on_sentence: Callable[[str], None]
    ) -> tuple[str, str, bool]:
        cfg_now = config_service.get_active().document
        voice_session = SessionContext(
            session_id="local-voice-session",
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.VOICE,
            is_os_locked=resolved_lock_probe(),
            offline_mode=cfg_now.ai.offline_mode,
        )
        res = await turn_orchestrator.submit_turn_streaming(
            spoken_text,
            session=voice_session,
            correlation_id=f"voice_{uuid.uuid4().hex[:12]}",
            on_sentence=on_sentence,
        )
        return (res.reply, res.route_kind, res.llm_called)

    def _voice_hotwords() -> tuple[tuple[str, ...], tuple[str, ...]]:
        app_names = tuple(e.display_name for e in resolved_app_catalog.list_apps()[:12])
        recent_files = tuple(
            h.display_name
            for h in file_index_service.working_set.get_all("local-voice-session")[:5]
        )
        return (app_names, recent_files)

    live_voice_engine = LiveVoiceEngine(
        models_dirs=tuple(models_dirs_list),
        turn_callback=_on_voice_utterance,
        stream_turn_callback=_on_voice_utterance_stream,
        provenance_verifier=provenance_verifier,
        hotword_provider=_voice_hotwords,
    )
    # B11: Retire the split between VoicePipelineService and LiveVoiceEngine by unifying lifecycle & config!
    voice_service.bind_live_hook(live_voice_engine)

    ipc_transport = TokenIpcTransport(
        transport_kind="win_named_pipe_or_loopback" if sys.platform == "win32" else "loopback",
        address=f"{settings.bind_host}:{settings.bind_port}",
        auth_token=settings.auth_token,
    )

    return CoreContainer(
        settings=settings,
        clock=resolved_clock,
        db=db,
        ipc_transport=ipc_transport,
        fs_port=resolved_fs,
        hardware_port=resolved_hw,
        supervisor=resolved_sup,
        vault=resolved_vault,
        audio_port=resolved_audio,
        desktop_port=resolved_desktop,
        app_catalog=resolved_app_catalog,
        file_opener=resolved_file_opener,
        notification_port=resolved_notify,
        event_bus=event_bus,
        policy_engine=policy_engine,
        config_service=config_service,
        storage_service=storage_service,
        approval_service=approval_service,
        backup_service=backup_service,
        license_service=license_service,
        ai_registry=ai_registry,
        voice_service=voice_service,
        memory_service=memory_service,
        context_service=context_service,
        reminder_service=reminder_service,
        scheduler_runner=scheduler_runner,
        turn_orchestrator=turn_orchestrator,
        knowledge_service=knowledge_service,
        file_index_service=file_index_service,
        file_mutation_service=file_mutation_service,
        web_service=web_service,
        screen_service=screen_service,
        life_service=life_service,
        workflow_service=workflow_service,
        ecosystem_service=ecosystem_service,
        mcp_host_service=mcp_host_service,
        oauth_connector_service=oauth_connector_service,
        camera_service=camera_service,
        ha_service=ha_service,
        remote_gateway_service=remote_gateway_service,
        preference_proposal_service=preference_proposal_service,
        local_llm_manager=local_llm_manager,
        live_voice_engine=live_voice_engine,
        resource_governor=DynamicResourceGovernor(idle_vram_unload_seconds=300),
        os_lock_probe=resolved_lock_probe,
        manual_os_locked=False,
    )


def create_app(container: CoreContainer | None = None) -> FastAPI:
    """Create authenticated local J.A.R.V.I.S. Core FastAPI application."""
    active_container = container or build_default_container(CoreStartupSettings())
    configure_logging(active_container.settings.log_level)
    logger = get_logger("jarvis.transport")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        active_container.live_voice_engine.bind_event_loop(asyncio.get_running_loop())
        llm_boot_task: asyncio.Task[Any] | None = None
        if active_container.settings.auto_start_local_llm and active_container.settings.env != "test":
            llm_boot_task = asyncio.create_task(
                active_container.local_llm_manager.start_if_available()
            )
        if active_container.settings.env != "test":
            await active_container.scheduler_runner.start()
        logger.info(
            "core.startup.ready",
            env=active_container.settings.env,
            release_sha=active_container.settings.release_sha,
            sqlite_vec_loaded=active_container.db.sqlite_vec_loaded,
        )
        try:
            yield
        finally:
            await active_container.scheduler_runner.stop()
            if llm_boot_task is not None and not llm_boot_task.done():
                llm_boot_task.cancel()
            active_container.live_voice_engine.shutdown()
            active_container.local_llm_manager.stop()
            active_container.mcp_host_service.kill_all_servers(correlation_id="core-shutdown")
            closed_children = active_container.supervisor.close_all_managed()
            active_container.db.close()
            logger.info("core.shutdown.completed", closed_managed_children=closed_children)

    app = FastAPI(
        title="J.A.R.V.I.S. Local Core API",
        version="0.2.2",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.container = active_container
    pending_storage_migrations: dict[str, tuple[StorageCategory, str, str]] = {}

    @app.middleware("http")
    async def security_and_wide_event_middleware(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        request_id = request.headers.get("X-Request-Id") or f"req_{uuid.uuid4().hex[:16]}"
        correlation_id = request.headers.get("X-Correlation-Id") or request_id
        request.state.correlation_id = correlation_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id, correlation_id=correlation_id)

        # 1. Strict Host header validation: supports IPv6 [::1]:port AND rejects empty/missing Host (DEF-22, B05)
        raw_host_header = request.headers.get("host") or ""
        parsed_host = _extract_host_without_port(raw_host_header)
        if not parsed_host or parsed_host not in ALLOWED_LOOPBACK_HOSTS:
            resp = _error_response(
                code=ErrorCode.DENIED,
                message="Missing or disallowed Host header on local core transport.",
                correlation_id=correlation_id,
                http_status=status.HTTP_403_FORBIDDEN,
            )
            resp.headers["X-Request-Id"] = request_id
            return resp

        # 2. Zero CORS: reject any browser cross-origin request carrying Origin header
        if request.headers.get("origin") is not None:
            resp = _error_response(
                code=ErrorCode.DENIED,
                message="Cross-origin requests are prohibited on local core transport.",
                correlation_id=correlation_id,
                http_status=status.HTTP_403_FORBIDDEN,
            )
            resp.headers["X-Request-Id"] = request_id
            return resp

        # 3. Payload size ceiling <= 256 KiB enforced on BOTH Content-Length AND chunked bodies (DEF-22, B05)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_PAYLOAD_BYTES:
                    resp = _error_response(
                        code=ErrorCode.INVALID_ARGS,
                        message="Payload exceeds 256 KiB local IPC limit.",
                        correlation_id=correlation_id,
                        http_status=status.HTTP_413_CONTENT_TOO_LARGE,
                    )
                    resp.headers["X-Request-Id"] = request_id
                    return resp
            except ValueError:
                resp = _error_response(
                    code=ErrorCode.INVALID_ARGS,
                    message="Malformed Content-Length header.",
                    correlation_id=correlation_id,
                    http_status=status.HTTP_400_BAD_REQUEST,
                )
                resp.headers["X-Request-Id"] = request_id
                return resp
        elif request.method in ("POST", "PUT", "PATCH"):
            body_chunks = bytearray()
            async for chunk in request.stream():
                body_chunks.extend(chunk)
                if len(body_chunks) > MAX_PAYLOAD_BYTES:
                    resp = _error_response(
                        code=ErrorCode.INVALID_ARGS,
                        message="Chunked payload exceeds 256 KiB local IPC limit.",
                        correlation_id=correlation_id,
                        http_status=status.HTTP_413_CONTENT_TOO_LARGE,
                    )
                    resp.headers["X-Request-Id"] = request_id
                    return resp
            # Cache validated body bytes so downstream route handlers can read JSON cleanly
            request._body = bytes(body_chunks)  # noqa: SLF001

        # 4. Constant-time 256-bit Bearer authentication on all /v1/* endpoints
        if request.url.path != "/healthz":
            auth_header = request.headers.get("authorization") or ""
            if not auth_header.startswith("Bearer "):
                resp = _error_response(
                    code=ErrorCode.DENIED,
                    message="Missing local transport Bearer token.",
                    correlation_id=correlation_id,
                    http_status=status.HTTP_401_UNAUTHORIZED,
                )
                resp.headers["X-Request-Id"] = request_id
                return resp
            token = auth_header[len("Bearer ") :].strip()
            if not active_container.ipc_transport.verify_token(token):
                resp = _error_response(
                    code=ErrorCode.DENIED,
                    message="Invalid local transport Bearer token.",
                    correlation_id=correlation_id,
                    http_status=status.HTTP_401_UNAUTHORIZED,
                )
                resp.headers["X-Request-Id"] = request_id
                return resp

        response: Response
        error_code: str | None = None
        try:
            response = await call_next(request)
        except Exception:
            error_code = ErrorCode.INTERNAL.value
            logger.exception("http.request.unhandled_error", path=request.url.path)
            response = _error_response(
                code=ErrorCode.INTERNAL,
                message="Internal core error.",
                correlation_id=correlation_id,
                http_status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        duration_ms = round((time.perf_counter() - started) * 1000.0, 2)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Correlation-Id"] = correlation_id
        response.headers["Cache-Control"] = "no-store"

        route_obj = request.scope.get("route")
        route_template = getattr(route_obj, "path", request.url.path)
        if request.url.path != "/healthz":
            log_fn = (
                logger.error
                if response.status_code >= 500
                else (logger.warning if response.status_code >= 400 else logger.info)
            )
            log_fn(
                "http.request.completed",
                method=request.method,
                routeTemplate=route_template,
                statusCode=response.status_code,
                durationMs=duration_ms,
                errorCode=error_code,
            )
        return response

    def _corr(request: Request) -> str:
        return str(getattr(request.state, "correlation_id", uuid.uuid4().hex))

    @app.get("/healthz")
    async def liveness() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/v1/health")
    @app.get("/v1/ready")
    async def readiness() -> dict[str, Any]:
        # IR-17 / B07: fast SELECT 1 check avoids blocking Uvicorn event loop with full PRAGMA integrity_check
        db_health = active_container.db.check_health_fast()
        desktop_live = bool(getattr(active_container.desktop_port, "_allow_live_launch", True))
        notify_available = not isinstance(active_container.notification_port, UnavailableNotificationAdapter)
        llm_status = active_container.local_llm_manager.status
        return {
            "schema_version": 1,
            "status": "ready" if db_health["core_db_ok"] and db_health["knowledge_db_ok"] else "degraded",
            "release_sha": active_container.settings.release_sha,
            "components": db_health,
            "event_seq": active_container.event_bus.current_seq,
            "os_locked": active_container.effective_os_locked(),
            "capability_states": {
                "desktop_app_launch": "ready" if desktop_live else "unavailable",
                "notifications": "ready" if notify_available else "unavailable",
                "scheduler": "ready",
                "workflow_execution": "ready",
                "storage_migration_http": "ready_tier2_gui_approval",
                "file_move": "ready_tier2_gui_approval",
                "file_edit": "ready_tier2_gui_approval",
                "mcp_host": "ready_opt_in_readonly_pilot",
                "web_search": (
                    "ready_opt_in"
                    if active_container.web_service.get_provider_consent_state().enabled
                    else "opt_in_unconfigured"
                ),
                "oauth_readonly": "ready_opt_in_pkce",
                "home_assistant": (
                    "ready_lan_allowlist"
                    if active_container.ha_service.is_live_client_configured()
                    else "opt_in_unconfigured"
                ),
                "camera": (
                    "ready_on_demand"
                    if isinstance(
                        active_container.camera_service._capture_port, WindowsOnDemandCameraAdapter
                    )
                    and active_container.camera_service._capture_port.is_capture_backend_ready()
                    else "opt_in_unavailable"
                ),
                "remote_gateway": (
                    "experimental"
                    if active_container.settings.env == "test"
                    else (
                        "ready_tls_hardened"
                        if active_container.remote_gateway_service.get_config().enabled
                        and active_container.remote_gateway_service.verify_provisioned_tls(
                            active_container.remote_gateway_service.get_config().tls_cert_fingerprint_sha256
                        )[0]
                        else "opt_in_tls_required"
                    )
                ),
                "local_llm": "ready" if llm_status.ready else ("degraded" if llm_status.starting else "unavailable"),
            },
        }

    @app.get("/v1/diagnostics/integrity")
    async def deep_integrity_check() -> dict[str, Any]:
        """Run deep PRAGMA integrity_check off the async event loop (IR-17, B07)."""
        db_health = await asyncio.to_thread(active_container.db.check_health)
        return {"schema_version": 1, "integrity": db_health}

    @app.get("/v1/system/capabilities")
    async def discover_capabilities() -> dict[str, Any]:
        snapshot = active_container.hardware_port.discover()
        recommendation = recommend_configuration(snapshot)
        with active_container.db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO hardware_snapshot(
                    id, os_info_json, cpu_json, ram_bytes, gpus_json, displays_json, audio_json, power_state, captured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.id,
                    snapshot.os_info.model_dump_json(),
                    snapshot.cpu.model_dump_json(),
                    snapshot.ram_total_bytes,
                    json.dumps([g.model_dump(mode="json") for g in snapshot.gpus]),
                    json.dumps([d.model_dump(mode="json") for d in snapshot.displays]),
                    json.dumps([a.model_dump(mode="json") for a in snapshot.audio_endpoints]),
                    snapshot.power_state.value,
                    snapshot.captured_at.isoformat(),
                ),
            )
        return {
            "schema_version": 1,
            "snapshot": snapshot.model_dump(mode="json"),
            "recommendation": recommendation.model_dump(mode="json"),
        }

    @app.get("/v1/system/governor")
    async def evaluate_resource_governor(
        idle_seconds: float = Query(default=0.0, ge=0.0, le=86400.0),
        gaming_active: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Live hardware-aware resource governor evaluation (B20, NFR-14, DEC-016)."""
        snapshot = active_container.hardware_port.discover()
        active_profile = active_container.ai_registry.get_active_profile().profile
        llm_st = active_container.local_llm_manager.status
        llm_healthy = active_profile.mode.value == "direct" or llm_st.ready or active_container.ai_registry.get_adapter(
            active_profile.role_bindings.get("llm_provider", "")
        ) is not None
        decision = active_container.resource_governor.evaluate(
            snapshot,
            requested_mode=active_profile.mode,
            idle_seconds=idle_seconds,
            gaming_or_fullscreen_active=gaming_active,
            llm_runtime_healthy=llm_healthy,
        )
        return {
            "schema_version": 1,
            "active_profile_id": active_profile.id,
            "decision": decision.model_dump(mode="json"),
        }

    @app.get("/v1/config")
    async def get_config() -> dict[str, Any]:
        rev = active_container.config_service.get_active()
        return {
            "schema_version": 1,
            "revision": rev.revision,
            "source": rev.source,
            "previous_healthy_revision": rev.previous_healthy_revision,
            "created_at": rev.created_at,
            "config": rev.document.model_dump(mode="json"),
        }

    @app.put("/v1/config")
    async def update_config(request: Request, body: dict[str, Any]) -> Response:
        try:
            validated = active_container.config_service.validate_payload(body)
            rev = active_container.config_service.save_revision(validated, source="user", correlation_id=_corr(request))
            active_container.storage_service.sync_locations_from_config()
            active_container.voice_service.bind_live_hook(active_container.live_voice_engine)
            return JSONResponse(
                {
                    "schema_version": 1,
                    "revision": rev.revision,
                    "config": rev.document.model_dump(mode="json"),
                }
            )
        except ConfigServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/config/rollback")
    async def rollback_config(request: Request) -> Response:
        try:
            rev = active_container.config_service.rollback(correlation_id=_corr(request))
            active_container.storage_service.sync_locations_from_config()
            return JSONResponse(
                {
                    "schema_version": 1,
                    "revision": rev.revision,
                    "source": rev.source,
                    "config": rev.document.model_dump(mode="json"),
                }
            )
        except ConfigServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/config/export")
    async def export_config() -> dict[str, Any]:
        return active_container.config_service.export_secret_free_profile()

    @app.post("/v1/config/import")
    async def import_config(request: Request, body: dict[str, Any]) -> Response:
        try:
            rev = active_container.config_service.import_profile(body, correlation_id=_corr(request))
            active_container.storage_service.sync_locations_from_config()
            return JSONResponse(
                {"schema_version": 1, "revision": rev.revision, "config": rev.document.model_dump(mode="json")}
            )
        except ConfigServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/onboarding/steps/{step}")
    async def complete_onboarding_step(
        step: int, request: Request, mark_completed: bool = Query(default=False)
    ) -> Response:
        try:
            rev = active_container.config_service.complete_onboarding_step(
                step, mark_completed=mark_completed, correlation_id=_corr(request)
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "revision": rev.revision,
                    "onboarding": rev.document.onboarding.model_dump(mode="json"),
                }
            )
        except ConfigServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/storage/volumes")
    async def list_volumes() -> dict[str, Any]:
        vols = active_container.storage_service.list_volumes()
        return {"schema_version": 1, "volumes": [v.model_dump(mode="json") for v in vols]}

    @app.get("/v1/storage/locations")
    async def list_storage_locations() -> dict[str, Any]:
        locs = active_container.storage_service.list_locations()
        return {"schema_version": 1, "locations": [loc.model_dump(mode="json") for loc in locs]}

    @app.put("/v1/storage/locations/{category}")
    async def set_storage_location(
        category: StorageCategory, body: SetStorageLocationBody, request: Request
    ) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; storage root reconfiguration denied.",
                correlation_id=_corr(request),
            )
        try:
            rec = active_container.storage_service.set_location(
                category, body.path, quota_bytes=body.quota_bytes, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "location": rec.model_dump(mode="json")})
        except StorageServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/storage/migrate")
    async def migrate_storage(body: MigrateStorageBody, request: Request) -> Response:
        # IR-02 / B03 / B19: direct unapproved HTTP migration remains permanently disabled; callers MUST use propose + apply!
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; storage migration denied.",
                correlation_id=_corr(request),
            )
        return _error_response(
            code=ErrorCode.UNSUPPORTED,
            message="Direct unapproved storage migration is prohibited; use POST /v1/storage/migrate/propose + GUI R2 approval + POST /v1/storage/migrate/apply.",
            correlation_id=_corr(request),
            http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.post("/v1/storage/migrate/propose")
    async def propose_storage_migration(body: MigrateStorageBody, request: Request) -> Response:
        """Stage G5 (B19): propose quiesced online-backup storage migration requiring single-use GUI R2 approval."""
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        decision = active_container.policy_engine.evaluate_step(
            tool_id="storage.location.migrate",
            tool_version=1,
            args={"category": body.category.value, "target_path": body.target_path},
            session=session,
            grants=_load_all_grants(),
            now_utc=active_container.clock.now_utc(),
        )
        if not decision.requires_approval and not decision.allowed:
            return _error_response(
                code=decision.error_code or ErrorCode.DENIED,
                message=decision.reason,
                correlation_id=_corr(request),
            )
        current_path = cfg.storage.roots.as_category_map()[body.category]
        try:
            challenge = active_container.approval_service.create_challenge(
                request_id=f"req_mig_{uuid.uuid4().hex[:10]}",
                correlation_id=_corr(request),
                tool_id="storage.location.migrate",
                tool_version=1,
                canonical_args_hash=decision.canonical_args_hash,
                session=session,
                summary=f"Migrate storage '{body.category.value}' from '{current_path}' to '{body.target_path}' (quiesced online backup, source kept intact)",
            )
        except ApprovalError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))
        pending_storage_migrations[challenge.approval_id] = (
            body.category,
            body.target_path,
            challenge.bound_hash,
        )
        return JSONResponse(
            status_code=status.HTTP_202_ACCEPTED,
            content={
                "schema_version": 1,
                "requires_approval": True,
                "before_preview": f"{body.category.value} -> {current_path}",
                "after_preview": f"{body.category.value} -> {body.target_path}",
                "approval": challenge.model_dump(mode="json"),
            },
        )

    @app.post("/v1/storage/migrate/apply")
    async def apply_storage_migration(body: ApplyStorageMigrationBody, request: Request) -> Response:
        """Stage G5 (B19): consume GUI approval and run checksum-verified quiesced online-backup migration."""
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; storage migration denied.",
                correlation_id=_corr(request),
            )
        spec = pending_storage_migrations.get(body.approval_id)
        if spec is None:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message=f"No pending storage migration for approval '{body.approval_id}'.",
                correlation_id=_corr(request),
            )
        category, target_path, bound_hash = spec
        try:
            active_container.approval_service.consume_approved_for_execution(
                body.approval_id,
                expected_bound_hash=bound_hash,
                session_id=body.session_id,
                actor_ref="local_owner",
                expected_tool_id="storage.location.migrate",
            )
        except ApprovalError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

        try:
            res = await asyncio.to_thread(
                active_container.storage_service.migrate_location,
                category,
                target_path,
                correlation_id=_corr(request),
            )
            pending_storage_migrations.pop(body.approval_id, None)
            return JSONResponse(
                {
                    "schema_version": 1,
                    "category": res.category.value,
                    "source_path": res.source_path,
                    "target_path": res.target_path,
                    "files_verified": res.files_verified,
                    "total_bytes": res.total_bytes,
                    "rolled_back": res.rolled_back,
                }
            )
        except StorageServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/storage/cleanup")
    async def cleanup_storage_cache(body: CleanupCacheBody, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; cache cleanup denied.",
                correlation_id=_corr(request),
            )
        try:
            res = active_container.storage_service.cleanup_cache_lru(
                body.category, body.max_bytes, correlation_id=_corr(request)
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "category": res.category.value,
                    "deleted_files": res.deleted_files,
                    "freed_bytes": res.freed_bytes,
                    "remaining_bytes": res.remaining_bytes,
                }
            )
        except StorageServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    def _load_all_grants() -> tuple[GrantRecord, ...]:
        with active_container.db.core_read() as conn:
            rows = conn.execute(
                "SELECT id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision FROM grant"
            ).fetchall()
        return tuple(
            GrantRecord(
                id=str(r["id"]),
                subject_type=str(r["subject_type"]),  # type: ignore[arg-type]
                subject_id=str(r["subject_id"]),
                capability=str(r["capability"]),
                scope=json.loads(str(r["scope_json"])),
                expires_at=datetime.fromisoformat(str(r["expires_at"])) if r["expires_at"] else None,
                revoked_at=datetime.fromisoformat(str(r["revoked_at"])) if r["revoked_at"] else None,
                revision=int(r["revision"]),
            )
            for r in rows
        )

    @app.get("/v1/grants")
    async def list_grants() -> dict[str, Any]:
        items = [g.model_dump(mode="json") for g in _load_all_grants()]
        return {"schema_version": 1, "grants": items}

    @app.put("/v1/grants")
    async def upsert_grant(body: UpsertGrantBody, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; permission grant modification denied.",
                correlation_id=_corr(request),
            )
        canonical_scope = json.dumps(body.scope, sort_keys=True)
        now_iso = active_container.clock.now_utc().isoformat()
        with active_container.db.core_tx() as conn:
            # B02 / DEF-20: deduplicate active grants for same (subject_type, subject_id, capability, scope)
            grant_id = body.id
            if grant_id is None:
                existing = conn.execute(
                    """
                    SELECT id FROM grant
                    WHERE subject_type = ? AND subject_id = ? AND capability = ?
                      AND scope_json = ? AND revoked_at IS NULL
                    ORDER BY revision DESC LIMIT 1
                    """,
                    (body.subject_type, body.subject_id, body.capability, canonical_scope),
                ).fetchone()
                grant_id = str(existing["id"]) if existing is not None else str(uuid.uuid4())
            conn.execute(
                """
                INSERT INTO grant(id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision)
                VALUES (?, ?, ?, ?, ?, ?, NULL, 1)
                ON CONFLICT(id) DO UPDATE SET
                    scope_json = excluded.scope_json,
                    expires_at = excluded.expires_at,
                    revoked_at = NULL,
                    revision = grant.revision + 1
                """,
                (
                    grant_id,
                    body.subject_type,
                    body.subject_id,
                    body.capability,
                    canonical_scope,
                    body.expires_at.isoformat() if body.expires_at else None,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'grant.upserted', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    _corr(request),
                    json.dumps({"grant_id": grant_id, "capability": body.capability}),
                    now_iso,
                ),
            )
        return JSONResponse({"schema_version": 1, "grant_id": grant_id, "capability": body.capability})

    @app.delete("/v1/grants/{grant_id}")
    async def revoke_grant(grant_id: str, request: Request) -> Response:
        now_iso = active_container.clock.now_utc().isoformat()
        with active_container.db.core_tx() as conn:
            target = conn.execute(
                "SELECT subject_id, capability FROM grant WHERE id = ? AND revoked_at IS NULL",
                (grant_id,),
            ).fetchone()
            if target is None:
                return _error_response(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Active grant '{grant_id}' not found.",
                    correlation_id=_corr(request),
                )
            subject_id = str(target["subject_id"])
            capability = str(target["capability"])
            # B02 / DEF-20: atomically revoke ALL matching active grants for (subject_id, capability)
            cur = conn.execute(
                """
                UPDATE grant
                SET revoked_at = ?, revision = revision + 1
                WHERE subject_id = ? AND capability = ? AND revoked_at IS NULL
                """,
                (now_iso, subject_id, capability),
            )
            revoked_count = cur.rowcount

        affected_tools = tuple(
            tool_id
            for (tool_id, _ver), spec in default_tool_registry().items()
            if spec.capability == capability
        )
        canceled_approvals = active_container.approval_service.cancel_pending_for_tools(
            affected_tools, reason=f"grant_revoked:{capability}", correlation_id=_corr(request)
        )
        active_container.event_bus.publish(
            event_type="permission.revoked",
            correlation_id=_corr(request),
            payload={
                "grant_id": grant_id,
                "capability": capability,
                "revoked_count": revoked_count,
                "canceled_approvals": canceled_approvals,
            },
        )
        return JSONResponse(
            {
                "schema_version": 1,
                "grant_id": grant_id,
                "revoked": True,
                "revoked_count": revoked_count,
                "canceled_approvals": canceled_approvals,
            }
        )

    @app.post("/v1/policy/evaluate")
    async def evaluate_policy(body: PolicyEvalBody, request: Request) -> Response:
        active_cfg = active_container.config_service.get_active().document
        grants = _load_all_grants()
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=body.channel,
            modality=body.modality,
            is_os_locked=active_container.effective_os_locked(body.is_os_locked),
            is_suspended=body.is_suspended,
            is_muted=body.is_muted,
            offline_mode=active_cfg.ai.offline_mode,
        )
        decision = active_container.policy_engine.evaluate_step(
            tool_id=body.tool_id,
            tool_version=body.tool_version,
            args=body.args,
            session=session,
            grants=grants,
            now_utc=active_container.clock.now_utc(),
            target_snapshot_hash=body.target_snapshot_hash,
        )
        if decision.requires_approval:
            challenge = active_container.approval_service.create_challenge(
                request_id=str(uuid.uuid4()),
                correlation_id=_corr(request),
                tool_id=body.tool_id,
                tool_version=body.tool_version,
                canonical_args_hash=decision.canonical_args_hash,
                session=session,
                target_snapshot_hash=body.target_snapshot_hash,
                summary=body.summary or f"Approve {body.tool_id} v{body.tool_version}",
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "schema_version": 1,
                    "allowed": False,
                    "requires_approval": True,
                    "risk": decision.risk.value,
                    "approval": challenge.model_dump(mode="json"),
                },
            )
        if not decision.allowed and decision.error_code is not None:
            return _error_response(code=decision.error_code, message=decision.reason, correlation_id=_corr(request))
        return JSONResponse(
            {
                "schema_version": 1,
                "allowed": True,
                "requires_approval": False,
                "risk": decision.risk.value,
                "canonical_args_hash": decision.canonical_args_hash,
            }
        )

    @app.post("/v1/approvals/{approval_id}/decision")
    async def submit_approval_decision(
        approval_id: str,
        body: ApprovalDecisionRequest,
        request: Request,
        session_id: str = Query(default="local-session-1"),
        actor_ref: str = Query(default="local_owner"),
    ) -> Response:
        session = SessionContext(
            session_id=session_id,
            actor_ref=actor_ref,
            channel=body.channel,
            modality=body.modality,
            is_os_locked=active_container.effective_os_locked(),
        )
        try:
            final_state = active_container.approval_service.decide(
                approval_id, body, session=session, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "approval_id": approval_id, "state": final_state.value})
        except ApprovalError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/session/lock")
    async def lock_session(body: SessionLockBody, request: Request) -> dict[str, Any]:
        corr = _corr(request)
        active_container.manual_os_locked = True
        active_container.voice_service.on_session_locked()
        active_container.live_voice_engine.stop_speaking()
        active_container.live_voice_engine.set_mode("muted")
        closed_cameras = active_container.camera_service.stop_and_revoke_all(
            reason=body.reason, correlation_id=corr
        )
        active_container.remote_gateway_service.set_os_lock_state(True)
        active_container.turn_orchestrator.clear_session_history()
        active_container.file_index_service.working_set.clear_session()
        canceled = active_container.approval_service.cancel_all_pending_on_lock(
            reason=body.reason, correlation_id=corr
        )
        return {
            "schema_version": 1,
            "locked": True,
            "canceled_approvals": canceled,
            "closed_cameras": closed_cameras,
        }

    @app.post("/v1/session/unlock")
    async def unlock_session(request: Request) -> Response:
        if active_container.os_lock_probe():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Workstation is still locked at OS level; cannot unlock Core session.",
                correlation_id=_corr(request),
            )
        active_container.manual_os_locked = False
        active_container.remote_gateway_service.set_os_lock_state(False)
        return JSONResponse({"schema_version": 1, "locked": False})

    def _serialize_live_voice_status() -> dict[str, Any]:
        vs = active_container.live_voice_engine.snapshot()
        llm = active_container.local_llm_manager.status
        return {
            "schema_version": 1,
            "mode": vs.mode,
            "phase": vs.phase,
            "amplitude": vs.amplitude,
            "stt_ready": vs.stt_ready,
            "stt_model": vs.stt_model,
            "tts_ready": vs.tts_ready,
            "tts_model": vs.tts_model,
            "mic_available": vs.mic_available,
            "active_command_window": vs.active_command_window,
            "session_active": vs.session_active,
            "session_seconds_left": vs.session_seconds_left,
            "vad_engine": vs.vad_engine,
            "wake_engine": vs.wake_engine,
            "last_transcript": vs.last_transcript,
            "last_reply": vs.last_reply,
            "last_route_kind": vs.last_route_kind,
            "last_llm_called": vs.last_llm_called,
            "error": vs.error,
            "llm_ready": llm.ready,
            "llm_starting": llm.starting,
            "llm_model": llm.model_name,
            "llm_backend": llm.backend,
            "llm_note": llm.note,
        }

    @app.get("/v1/voice/live-status")
    async def get_live_voice_status() -> dict[str, Any]:
        return _serialize_live_voice_status()

    @app.post("/v1/voice/arm")
    async def arm_live_voice(body: ArmLiveVoiceBody) -> dict[str, Any]:
        active_container.voice_service.bind_live_hook(active_container.live_voice_engine)
        active_container.live_voice_engine.set_mode(body.mode)
        return _serialize_live_voice_status()

    @app.post("/v1/voice/stop-speaking")
    async def stop_live_speaking() -> dict[str, Any]:
        gen = active_container.live_voice_engine.stop_speaking()
        return {"schema_version": 1, "stopped": True, "playback_generation": gen}

    @app.get("/v1/voice/diagnostics")
    async def get_voice_diagnostics() -> dict[str, Any]:
        """Voice Lab live audio diagnostics, echo-guard status, installed voices & timing trace (B11/B12)."""
        snap = active_container.voice_service.get_state()
        diag = active_container.live_voice_engine.get_diagnostics()
        return {
            "schema_version": 1,
            "diagnostics": diag,
            "endpoints": [e.model_dump(mode="json") for e in snap.endpoints],
            "installed_os_voices": [v.model_dump(mode="json") for v in snap.installed_voices],
        }

    @app.put("/v1/audio/speech-rate")
    async def set_audio_speech_rate(body: SetSpeechRateBody, request: Request) -> dict[str, Any]:
        active = active_container.config_service.get_active().document
        updated = active.model_copy(
            update={"audio": active.audio.model_copy(update={"speech_rate": body.speech_rate})}
        )
        active_container.config_service.save_revision(
            updated, source="user", correlation_id=_corr(request)
        )
        active_container.voice_service.bind_live_hook(active_container.live_voice_engine)
        return {"schema_version": 1, "speech_rate": body.speech_rate}

    @app.post("/v1/voice/replay-transcript")
    async def replay_voice_transcript(body: ReplayTranscriptBody, request: Request) -> Response:
        """Manual transcript correction/replay strictly routed through shared TurnOrchestrator + PolicyEngine (B11)."""
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        result = await active_container.turn_orchestrator.submit_turn(
            body.transcript, session=session, correlation_id=_corr(request)
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "request_id": result.request_id,
            "state": result.state.value,
            "route_kind": result.route_kind,
            "reply": result.reply,
            "llm_called": result.llm_called,
            "steps": [
                {
                    "tool_id": s.tool_id,
                    "tool_version": s.tool_version,
                    "state": s.state.value,
                    "verified": s.verified,
                    "summary": s.summary,
                    "error_code": s.error_code.value if s.error_code else None,
                    "data": s.data,
                }
                for s in result.steps
            ],
            "approval": result.approval.model_dump(mode="json") if result.approval else None,
        }
        if result.state == ActionOutcomeState.AWAITING_APPROVAL:
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)
        if result.state == ActionOutcomeState.FAILED and result.error_code is not None:
            return _error_response(
                code=result.error_code, message=result.reply, correlation_id=_corr(request)
            )
        if result.state == ActionOutcomeState.COMPLETED and body.speak_reply and result.reply:
            active_container.live_voice_engine.speak_async(result.reply)
        return JSONResponse(content=payload)

    # --- Phase 3: Turn Orchestration (Deterministic-First + Bounded LLM) ---

    @app.post("/v1/requests/cancel")
    async def cancel_active_request(
        body: CancelRequestBody, request: Request
    ) -> dict[str, Any]:
        """Cancel active voice/turn activity cleanly without stopping Core (IR-08, B07)."""
        corr = _corr(request)
        active_container.live_voice_engine.stop_speaking()
        active_container.event_bus.publish(
            event_type="request.state_changed",
            correlation_id=corr,
            request_id=body.request_id,
            payload={"state": "Idle", "canceled": True},
        )
        return {
            "schema_version": 1,
            "canceled": True,
            "request_id": body.request_id,
        }

    @app.post("/v1/requests")
    async def submit_turn(body: SubmitTurnBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=body.channel,
            modality=body.modality,
            is_os_locked=active_container.effective_os_locked(body.is_os_locked),
            is_suspended=body.is_suspended,
            is_muted=body.is_muted,
            offline_mode=cfg.ai.offline_mode,
        )
        result = await active_container.turn_orchestrator.submit_turn(
            body.utterance, session=session, correlation_id=_corr(request)
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "request_id": result.request_id,
            "state": result.state.value,
            "route_kind": result.route_kind,
            "reply": result.reply,
            "llm_called": result.llm_called,
            "steps": [
                {
                    "tool_id": s.tool_id,
                    "tool_version": s.tool_version,
                    "state": s.state.value,
                    "verified": s.verified,
                    "summary": s.summary,
                    "error_code": s.error_code.value if s.error_code else None,
                    "data": s.data,
                }
                for s in result.steps
            ],
            "approval": result.approval.model_dump(mode="json") if result.approval else None,
        }
        if result.state == ActionOutcomeState.AWAITING_APPROVAL:
            return JSONResponse(status_code=status.HTTP_202_ACCEPTED, content=payload)
        if result.state == ActionOutcomeState.FAILED and result.error_code is not None:
            return _error_response(
                code=result.error_code, message=result.reply, correlation_id=_corr(request)
            )
        if result.state == ActionOutcomeState.COMPLETED and body.speak_reply and result.reply:
            active_container.live_voice_engine.speak_async(result.reply)
        return JSONResponse(content=payload)

    # --- Phase 3: Providers, Model Manifests & Atomic AI Profiles ---

    @app.get("/v1/providers")
    async def list_providers() -> dict[str, Any]:
        providers = active_container.ai_registry.list_providers()
        return {
            "schema_version": 1,
            "providers": [p.model_dump(mode="json") for p in providers],
        }

    @app.post("/v1/providers")
    async def register_provider(provider: ModelProviderRecord, request: Request) -> Response:
        try:
            saved, warnings = active_container.ai_registry.register_provider(
                provider, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "schema_version": 1,
                    "provider": saved.model_dump(mode="json"),
                    "warnings": warnings,
                },
            )
        except AiRegistryError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/providers/{provider_id}/probe")
    async def probe_provider(provider_id: str, request: Request) -> Response:
        try:
            res = await active_container.ai_registry.probe_provider(
                provider_id, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "probe": res.model_dump(mode="json")})
        except AiRegistryError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/models")
    async def list_models() -> dict[str, Any]:
        manifests = active_container.ai_registry.list_manifests()
        return {"schema_version": 1, "models": [m.model_dump(mode="json") for m in manifests]}

    @app.post("/v1/models")
    async def register_model(
        manifest: ModelManifestRecord,
        request: Request,
        verify_local_file: bool = Query(default=True),
    ) -> Response:
        try:
            saved = active_container.ai_registry.register_manifest(
                manifest, verify_local_file=verify_local_file, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "model": saved.model_dump(mode="json")},
            )
        except AiRegistryError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/profiles")
    async def list_profiles() -> dict[str, Any]:
        active = active_container.ai_registry.get_active_profile()
        profiles = active_container.ai_registry.list_profiles()
        return {
            "schema_version": 1,
            "active_profile_id": active.profile.id,
            "previous_healthy_profile_id": active.previous_healthy_profile_id,
            "profiles": [p.model_dump(mode="json") for p in profiles],
        }

    @app.post("/v1/profiles/{profile_id}/activate")
    async def activate_profile(profile_id: str, request: Request) -> Response:
        try:
            outcome = active_container.ai_registry.switch_profile_atomic(
                profile_id, correlation_id=_corr(request)
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "committed": outcome.committed,
                    "rolled_back": outcome.rolled_back,
                    "active_profile": outcome.active_profile.model_dump(mode="json"),
                    "reason": outcome.reason,
                }
            )
        except AiRegistryError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/profiles/rollback")
    async def rollback_profile(request: Request) -> Response:
        try:
            state = active_container.ai_registry.rollback_profile(correlation_id=_corr(request))
            return JSONResponse(
                {
                    "schema_version": 1,
                    "active_profile": state.profile.model_dump(mode="json"),
                }
            )
        except AiRegistryError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 3: Adaptive Audio & Voice ---

    @app.get("/v1/audio/state")
    async def get_audio_state() -> dict[str, Any]:
        snap = active_container.voice_service.get_state()
        return {
            "schema_version": 1,
            "mode": snap.mode,
            "input_device_id": snap.input_device_id,
            "output_device_id": snap.output_device_id,
            "echo_guard_enabled": snap.echo_guard_enabled,
            "is_tts_playing": snap.is_tts_playing,
            "ring_buffer_seconds": snap.ring_buffer_seconds,
            "echo_guard": {
                "allow_mic_wake_or_vad": snap.echo_guard_decision.allow_mic_wake_or_vad,
                "allow_voice_barge_in": snap.echo_guard_decision.allow_voice_barge_in,
                "allow_ptt_or_ui_barge_in": snap.echo_guard_decision.allow_ptt_or_ui_barge_in,
                "reason": snap.echo_guard_decision.reason,
            },
            "installed_voices": [v.model_dump(mode="json") for v in snap.installed_voices],
            "endpoints": [e.model_dump(mode="json") for e in snap.endpoints],
        }

    @app.put("/v1/audio/mode")
    async def set_audio_mode(body: SetAudioModeBody, request: Request) -> dict[str, Any]:
        snap = active_container.voice_service.set_mode(
            body.mode,  # type: ignore[arg-type]
            correlation_id=_corr(request),
        )
        return {"schema_version": 1, "mode": snap.mode}

    @app.put("/v1/audio/devices")
    async def select_audio_devices(body: SelectAudioDevicesBody, request: Request) -> Response:
        try:
            snap = active_container.voice_service.select_devices(
                input_device_id=body.input_device_id,
                output_device_id=body.output_device_id,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "input_device_id": snap.input_device_id,
                    "output_device_id": snap.output_device_id,
                }
            )
        except VoiceServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/audio/test")
    async def test_audio(request: Request) -> dict[str, Any]:
        return {"schema_version": 1, **active_container.voice_service.run_self_test(correlation_id=_corr(request))}

    # --- Phase 3: Explicit Encrypted Memory Vault ---

    @app.get("/v1/memories")
    async def list_memories(
        include_proposals: bool = Query(default=False),
        q: str | None = Query(default=None),
    ) -> dict[str, Any]:
        items = active_container.memory_service.list_memories(
            include_proposals=include_proposals, query=q
        )
        return {"schema_version": 1, "memories": [m.model_dump(mode="json") for m in items]}

    @app.get("/v1/memories/inspector")
    async def get_memory_inspector(
        session_id: str = Query(default="local-session-1"),
    ) -> dict[str, Any]:
        """Return bounded provenance of memories that influenced the latest turn (B13)."""
        return {
            "schema_version": 1,
            "session_id": session_id,
            "influenced_memories": active_container.context_service.get_last_memory_inspector(
                session_id
            ),
            "user_aliases": active_container.memory_service.get_user_app_aliases(),
            "session_untrusted_taint": active_container.context_service.is_session_tainted(
                session_id
            ),
        }

    @app.post("/v1/memories")
    async def create_memory(body: CreateMemoryBody, request: Request) -> Response:
        try:
            rec = active_container.memory_service.create_memory(
                kind=body.kind,  # type: ignore[arg-type]
                content=body.content,
                sensitivity=body.sensitivity,  # type: ignore[arg-type]
                source_ref=body.source_ref,
                status=body.status,  # type: ignore[arg-type]
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "memory": rec.model_dump(mode="json")},
            )
        except MemoryServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.patch("/v1/memories/{memory_id}")
    async def update_memory(memory_id: str, body: UpdateMemoryBody, request: Request) -> Response:
        try:
            rec = active_container.memory_service.update_memory(
                memory_id,
                expected_revision=body.expected_revision,
                new_content=body.content,
                change_reason=body.change_reason,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "memory": rec.model_dump(mode="json")})
        except MemoryServiceError as exc:
            http_st = (
                status.HTTP_409_CONFLICT
                if "Optimistic lock" in str(exc)
                else _error_status_for_code(exc.code)
            )
            return _error_response(
                code=exc.code, message=str(exc), correlation_id=_corr(request), http_status=http_st
            )

    @app.post("/v1/memories/{memory_id}/approve")
    async def approve_memory_proposal(
        memory_id: str, body: ApproveProposalBody, request: Request
    ) -> Response:
        try:
            rec = active_container.memory_service.approve_proposal(
                memory_id, expected_revision=body.expected_revision, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "memory": rec.model_dump(mode="json")})
        except MemoryServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/memories/{memory_id}")
    async def delete_memory(memory_id: str, request: Request) -> Response:
        deleted = active_container.memory_service.delete_memory(
            memory_id, correlation_id=_corr(request)
        )
        if not deleted:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message=f"Memory '{memory_id}' not found.",
                correlation_id=_corr(request),
            )
        return JSONResponse({"schema_version": 1, "deleted": True, "tombstone_recorded": True})

    # --- Phase 3: Persistent IANA/UTC Reminders & Quiet Hours ---

    @app.get("/v1/reminders")
    async def list_reminders() -> dict[str, Any]:
        rems = active_container.reminder_service.list_reminders()
        return {"schema_version": 1, "reminders": [r.model_dump(mode="json") for r in rems]}

    @app.post("/v1/reminders")
    async def create_reminder(body: CreateReminderBody, request: Request) -> Response:
        try:
            rec = active_container.reminder_service.create_reminder(
                title=body.title,
                due_at_utc=body.due_at_utc,
                timezone_iana=body.timezone_iana,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "reminder": rec.model_dump(mode="json")},
            )
        except ReminderServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/scheduler/status")
    async def get_scheduler_status() -> dict[str, Any]:
        """Return background reminder scheduler health & tick counter (B15)."""
        snap = active_container.scheduler_runner.snapshot()
        return {
            "schema_version": 1,
            "running": snap.running,
            "tick_count": snap.tick_count,
            "total_processed": snap.total_processed,
            "last_tick_utc": snap.last_tick_utc,
        }

    @app.post("/v1/reminders/process-due")
    async def process_due_reminders(request: Request) -> dict[str, Any]:
        outcomes = active_container.reminder_service.process_due_reminders(
            correlation_id=_corr(request)
        )
        return {
            "schema_version": 1,
            "processed": [
                {"reminder_id": o.reminder_id, "title": o.title, "status": o.status}
                for o in outcomes
            ],
        }

    @app.post("/v1/reminders/{reminder_id}/snooze")
    async def snooze_reminder(
        reminder_id: str, body: SnoozeReminderBody, request: Request
    ) -> Response:
        try:
            rec = active_container.reminder_service.snooze_reminder(
                reminder_id,
                expected_revision=body.expected_revision,
                minutes=body.minutes,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "reminder": rec.model_dump(mode="json")})
        except ReminderServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/reminders/{reminder_id}/dismiss")
    async def dismiss_reminder(
        reminder_id: str, body: DismissReminderBody, request: Request
    ) -> Response:
        try:
            rec = active_container.reminder_service.dismiss_reminder(
                reminder_id, expected_revision=body.expected_revision
            )
            return JSONResponse({"schema_version": 1, "reminder": rec.model_dump(mode="json")})
        except ReminderServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 4 (R2): Knowledge Base & Hybrid RAG ---

    @app.get("/v1/roots")
    async def list_knowledge_roots() -> dict[str, Any]:
        roots = active_container.knowledge_service.list_source_roots()
        return {"schema_version": 1, "roots": [r.model_dump(mode="json") for r in roots]}

    @app.post("/v1/roots")
    async def add_knowledge_root(body: AddSourceRootBody, request: Request) -> Response:
        try:
            rec = active_container.knowledge_service.add_source_root(
                body.path, scope=body.scope, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "root": rec.model_dump(mode="json")},
            )
        except KnowledgeServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/roots/{root_id}")
    async def revoke_knowledge_root(root_id: str, request: Request) -> Response:
        try:
            purged = active_container.knowledge_service.revoke_source_root(
                root_id, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "revoked": True, "purged_documents": purged})
        except KnowledgeServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/roots/{root_id}/sync")
    async def sync_knowledge_root(root_id: str, request: Request) -> Response:
        try:
            summary = await asyncio.to_thread(
                active_container.knowledge_service.sync_source_root,
                root_id,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "root_id": summary.root_id,
                    "indexed_files": summary.indexed_files,
                    "skipped_unchanged": summary.skipped_unchanged,
                    "ocr_required_files": summary.ocr_required_files,
                    "unsupported_files": summary.unsupported_files,
                    "failed_files": summary.failed_files,
                    "removed_stale_files": summary.removed_stale_files,
                }
            )
        except KnowledgeServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/knowledge/query")
    async def query_knowledge(body: KnowledgeQueryBody) -> dict[str, Any]:
        res = await active_container.knowledge_service.answer_from_knowledge(
            body.query, top_k=body.top_k
        )
        return {"schema_version": 1, **res.model_dump(mode="json")}

    # --- Stage G2 (B09 & B10): Dynamic Native App Catalog & Layer-1 Scoped File Intelligence ---

    @app.get("/v1/apps")
    async def list_installed_apps() -> dict[str, Any]:
        entries = await asyncio.to_thread(active_container.app_catalog.list_apps)
        return {
            "schema_version": 1,
            "count": len(entries),
            "apps": [
                {
                    "app_id": e.app_id,
                    "display_name": e.display_name,
                    "activation_kind": e.activation_kind,
                    "aliases": list(e.aliases),
                    "source": e.source,
                    "trust_class": e.trust_class,
                }
                for e in entries
            ],
        }

    @app.post("/v1/apps/refresh")
    async def refresh_installed_apps() -> dict[str, Any]:
        entries = await asyncio.to_thread(active_container.app_catalog.refresh)
        return {"schema_version": 1, "count": len(entries)}

    @app.post("/v1/files/index/{root_id}")
    async def index_authorized_files(root_id: str, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; file indexing denied.",
                correlation_id=_corr(request),
            )
        try:
            summary = await asyncio.to_thread(
                active_container.file_index_service.scan_authorized_root, root_id
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "root_id": summary.root_id,
                    "indexed_files": summary.indexed_files,
                    "removed_stale": summary.removed_stale,
                    "skipped_excluded": summary.skipped_excluded,
                    "skipped_reparse_points": summary.skipped_reparse_points,
                    "permission_errors": summary.permission_errors,
                    "availability": summary.availability,
                    "elapsed_ms": summary.elapsed_ms,
                }
            )
        except FileIndexError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/files/search")
    async def search_indexed_files(body: FileSearchBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        decision = active_container.policy_engine.evaluate_step(
            tool_id="fs.metadata.search",
            tool_version=1,
            args={"query": body.query, "ext": body.ext},
            session=session,
            grants=_load_all_grants(),
            now_utc=active_container.clock.now_utc(),
        )
        if not decision.allowed and decision.error_code is not None:
            return _error_response(
                code=decision.error_code, message=decision.reason, correlation_id=_corr(request)
            )
        res = await asyncio.to_thread(
            active_container.file_index_service.search_metadata,
            body.query,
            ext=body.ext,
            modified_after_utc=body.modified_after_utc,
            limit=body.limit,
            session_id=body.session_id,
        )
        return JSONResponse(
            {
                "schema_version": 1,
                "query": res.query,
                "active_roots_count": res.active_roots_count,
                "total_candidates_scanned": res.total_candidates_scanned,
                "elapsed_ms": res.elapsed_ms,
                "hits": [
                    {
                        "index": i,
                        "file_id": h.file_id,
                        "root_id": h.root_id,
                        "display_name": h.display_name,
                        "relative_path": h.relative_path,
                        "ext": h.ext,
                        "size_bytes": h.size_bytes,
                        "mtime_ns": h.mtime_ns,
                        "availability": h.availability,
                        "score": h.score,
                    }
                    for i, h in enumerate(res.hits, start=1)
                ],
            }
        )

    @app.post("/v1/files/open")
    async def open_indexed_file(body: FileOpenBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        decision = active_container.policy_engine.evaluate_step(
            tool_id="fs.file.open",
            tool_version=1,
            args={"file_query": body.file_query, "result_index": body.result_index},
            session=session,
            grants=_load_all_grants(),
            now_utc=active_container.clock.now_utc(),
        )
        if not decision.allowed and decision.error_code is not None:
            return _error_response(
                code=decision.error_code, message=decision.reason, correlation_id=_corr(request)
            )
        target_hit = None
        if body.result_index is not None:
            target_hit = active_container.file_index_service.resolve_working_set_index(
                body.session_id, body.result_index
            )
        elif body.file_query:
            sres = active_container.file_index_service.search_metadata(
                body.file_query, limit=3, session_id=body.session_id
            )
            live = [h for h in sres.hits if h.availability == "available"]
            if live:
                target_hit = live[0]
        if target_hit is None:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message="Requested file was not found in authorized indexed roots.",
                correlation_id=_corr(request),
            )
        receipt = active_container.file_index_service.open_file(target_hit)
        if receipt.verification_kind == "prohibited":
            return _error_response(
                code=ErrorCode.DENIED, message=receipt.detail, correlation_id=_corr(request)
            )
        if receipt.verification_kind == "not_found":
            return _error_response(
                code=ErrorCode.NOT_FOUND, message=receipt.detail, correlation_id=_corr(request)
            )
        return JSONResponse(
            {
                "schema_version": 1,
                "opened": receipt.opened,
                "display_name": target_hit.display_name,
                "relative_path": target_hit.relative_path,
                "verification_kind": receipt.verification_kind,
                "detail": receipt.detail,
            }
        )

    # --- Stage G4 (B14, Decision A2): Tier-2 GUI Diff File Edit & Same-Scope No-Overwrite Move ---

    @app.post("/v1/files/edit/propose")
    async def propose_file_edit(body: ProposeFileEditBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            challenge, diff_preview = active_container.file_mutation_service.propose_file_edit(
                root_id=body.root_id,
                relative_path=body.relative_path,
                new_content=body.new_content,
                session=session,
                grants=_load_all_grants(),
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "schema_version": 1,
                    "requires_approval": True,
                    "approval": challenge.model_dump(mode="json"),
                    "diff_preview": diff_preview,
                },
            )
        except FileMutationError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/files/edit/apply")
    async def apply_file_edit(body: ApplyFileMutationBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            receipt = active_container.file_mutation_service.apply_approved_file_edit(
                approval_id=body.approval_id,
                session=session,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "tool_id": receipt.tool_id,
                    "verified": receipt.verified,
                    "canonical_path": receipt.canonical_path,
                    "sha256": receipt.sha256,
                    "summary": receipt.summary,
                }
            )
        except FileMutationError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/files/move/propose")
    async def propose_file_move(body: ProposeFileMoveBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            challenge = active_container.file_mutation_service.propose_file_move(
                root_id=body.root_id,
                source_relative_path=body.source_relative_path,
                target_relative_path=body.target_relative_path,
                session=session,
                grants=_load_all_grants(),
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content={
                    "schema_version": 1,
                    "requires_approval": True,
                    "approval": challenge.model_dump(mode="json"),
                },
            )
        except FileMutationError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/files/move/apply")
    async def apply_file_move(body: ApplyFileMutationBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            receipt = active_container.file_mutation_service.apply_approved_file_move(
                approval_id=body.approval_id,
                session=session,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "tool_id": receipt.tool_id,
                    "verified": receipt.verified,
                    "canonical_path": receipt.canonical_path,
                    "sha256": receipt.sha256,
                    "summary": receipt.summary,
                }
            )
        except FileMutationError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 4 (R2) + Stage G7 (B26): Pluggable Web Search & Anti-SSRF Fetch ---

    @app.get("/v1/web/provider")
    async def get_web_provider_state() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "provider": active_container.web_service.get_provider_consent_state().model_dump(mode="json"),
        }

    @app.put("/v1/web/provider")
    async def configure_web_provider(body: WebProviderConfigBody, request: Request) -> Response:
        try:
            provider = SearxngWebSearchProvider(
                endpoint_url=body.endpoint_url,
                clock=active_container.clock,
                provider_name=body.provider_name,
                allow_loopback_searxng=body.allow_loopback_searxng,
            )
            st = active_container.web_service.configure_search_provider(
                provider=provider,
                endpoint_url=provider.endpoint_url,
                consent_acknowledged=body.consent_acknowledged,
                allow_loopback_searxng=body.allow_loopback_searxng,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "provider": st.model_dump(mode="json")})
        except WebSearchError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/web/provider")
    async def revoke_web_provider(request: Request) -> dict[str, Any]:
        st = active_container.web_service.revoke_search_provider(correlation_id=_corr(request))
        return {"schema_version": 1, "provider": st.model_dump(mode="json")}

    @app.post("/v1/web/query")
    async def web_query(body: WebQueryBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        if not cfg.ai.offline_mode:
            session = SessionContext(
                session_id=body.session_id,
                actor_ref="local_owner",
                channel=ChannelKind.LOCAL,
                modality=InputModality.TRUSTED_UI,
                is_os_locked=active_container.effective_os_locked(),
                offline_mode=cfg.ai.offline_mode,
            )
            decision = active_container.policy_engine.evaluate_step(
                tool_id="web.search.query",
                tool_version=1,
                args={"query": body.query},
                session=session,
                grants=_load_all_grants(),
                now_utc=active_container.clock.now_utc(),
            )
            if not decision.allowed and decision.error_code is not None:
                return _error_response(
                    code=decision.error_code, message=decision.reason, correlation_id=_corr(request)
                )
        try:
            res = await active_container.web_service.query_web(
                body.query,
                limit=body.limit,
                private_query_approved=body.private_query_approved,
                allow_stale_cache_when_offline=body.allow_stale_cache_when_offline,
                session_id=body.session_id,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, **res})
        except WebSearchError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/web/fetch")
    async def web_fetch(body: WebFetchBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        decision = active_container.policy_engine.evaluate_step(
            tool_id="web.search.query",
            tool_version=1,
            args={"url": body.url},
            session=session,
            grants=_load_all_grants(),
            now_utc=active_container.clock.now_utc(),
        )
        if not decision.allowed and decision.error_code is not None:
            return _error_response(
                code=decision.error_code, message=decision.reason, correlation_id=_corr(request)
            )
        try:
            page = await active_container.web_service.fetch_page(
                body.url,
                require_https=body.require_https,
                session_id=body.session_id,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "url": page.url,
                    "status_code": page.status_code,
                    "text_excerpt": page.text_excerpt,
                    "fetched_at": page.fetched_at.isoformat(),
                    "is_stale": page.is_stale,
                    "from_cache": page.from_cache,
                }
            )
        except WebSearchError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 4 (R2): Screen Awareness ---

    @app.post("/v1/screen/analyze")
    async def analyze_screen(body: ScreenAnalyzeBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(body.is_os_locked),
            offline_mode=cfg.ai.offline_mode,
        )
        # B02 / IR-03: direct REST screen capture MUST pass PolicyEngine screen.read grant check
        decision = active_container.policy_engine.evaluate_step(
            tool_id="screen.analyze",
            tool_version=1,
            args={"window_selector": body.window_selector},
            session=session,
            grants=_load_all_grants(),
            now_utc=active_container.clock.now_utc(),
        )
        if not decision.allowed and decision.error_code is not None:
            return _error_response(
                code=decision.error_code, message=decision.reason, correlation_id=_corr(request)
            )
        try:
            res = active_container.screen_service.analyze_window(
                body.window_selector,
                session=session,
                explicit_user_request=body.explicit_user_request,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, **res.model_dump(mode="json")})
        except ScreenAwarenessError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 4 (R2): Personal Life Management ---

    @app.get("/v1/tasks")
    async def list_tasks() -> dict[str, Any]:
        return {
            "schema_version": 1,
            "tasks": [t.model_dump(mode="json") for t in active_container.life_service.list_tasks()],
        }

    @app.post("/v1/tasks")
    async def create_task(body: CreateTaskBody, request: Request) -> Response:
        try:
            rec = active_container.life_service.create_task(
                title=body.title, due_at_utc=body.due_at_utc, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "task": rec.model_dump(mode="json")},
            )
        except PersonalLifeError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.patch("/v1/tasks/{task_id}")
    async def update_task_status(
        task_id: str, body: UpdateTaskStatusBody, request: Request
    ) -> Response:
        try:
            rec = active_container.life_service.update_task_status(
                task_id,
                expected_revision=body.expected_revision,
                status=body.status,  # type: ignore[arg-type]
            )
            return JSONResponse({"schema_version": 1, "task": rec.model_dump(mode="json")})
        except PersonalLifeError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/calendar")
    async def list_calendar_events() -> dict[str, Any]:
        events = active_container.life_service.list_calendar_events()
        return {"schema_version": 1, "events": [e.model_dump(mode="json") for e in events]}

    @app.post("/v1/calendar")
    async def create_calendar_event(body: CreateCalendarEventBody, request: Request) -> Response:
        try:
            ev = active_container.life_service.create_calendar_event(
                title=body.title,
                start_at_utc=body.start_at_utc,
                end_at_utc=body.end_at_utc,
                timezone_iana=body.timezone_iana,
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "event": ev.model_dump(mode="json")},
            )
        except PersonalLifeError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/expenses")
    async def record_expense(body: RecordExpenseBody, request: Request) -> Response:
        try:
            rec = active_container.life_service.record_expense(
                amount_minor=body.amount_minor,
                currency_iso=body.currency_iso,
                kind=body.kind,  # type: ignore[arg-type]
                category=body.category,
                notes=body.notes,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "expense": rec.model_dump(mode="json")},
            )
        except PersonalLifeError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/expenses/summary")
    async def summarize_expenses() -> dict[str, Any]:
        sums = active_container.life_service.summarize_expenses_by_currency()
        return {"schema_version": 1, "currencies": [s.model_dump(mode="json") for s in sums]}

    @app.post("/v1/habits")
    async def log_habit(body: LogHabitBody, request: Request) -> Response:
        try:
            rec = active_container.life_service.log_habit(
                habit_key=body.habit_key,
                local_date=body.local_date,
                timezone_iana=body.timezone_iana,
                value=body.value,
                unit=body.unit,
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "habit_log": rec.model_dump(mode="json")},
            )
        except PersonalLifeError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/habits/{habit_key}/summary")
    async def habit_summary(habit_key: str) -> dict[str, Any]:
        return {
            "schema_version": 1,
            **active_container.life_service.descriptive_habit_summary(habit_key).model_dump(mode="json"),
        }

    # --- Phase 4 (R2): Declarative Typed Workflows ---

    @app.get("/v1/workflows")
    async def list_workflows() -> dict[str, Any]:
        wfs = active_container.workflow_service.list_workflows()
        return {"schema_version": 1, "workflows": [w.model_dump(mode="json") for w in wfs]}

    @app.post("/v1/workflows")
    async def create_workflow(body: CreateWorkflowBody, request: Request) -> Response:
        try:
            wf = active_container.workflow_service.create_workflow(
                name=body.name,
                trigger=body.trigger,
                steps=body.steps,
                total_timeout_seconds=body.total_timeout_seconds,
                enabled=body.enabled,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "workflow": wf.model_dump(mode="json")},
            )
        except WorkflowServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/workflows/{workflow_id}/dry-run")
    async def dry_run_workflow(workflow_id: str, request: Request) -> Response:
        try:
            prev = active_container.workflow_service.dry_run_preview(workflow_id)
            return JSONResponse(
                {
                    "schema_version": 1,
                    "workflow_id": prev.workflow_id,
                    "revision": prev.revision,
                    "bound_hash": prev.bound_hash,
                    "requires_r2_approval": prev.requires_r2_approval,
                    "steps": [
                        {
                            "index": s.index,
                            "tool_id": s.tool_id,
                            "version": s.version,
                            "risk": s.risk.value,
                            "idempotent": s.idempotent,
                            "requires_r2_approval": s.requires_r2_approval,
                            "summary": s.summary,
                        }
                        for s in prev.steps
                    ],
                }
            )
        except WorkflowServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/workflows/{workflow_id}/execute")
    async def execute_workflow(
        workflow_id: str, body: ExecuteWorkflowBody, request: Request
    ) -> Response:
        cfg = active_container.config_service.get_active().document
        grants = _load_all_grants()
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        if session.is_os_locked:
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; workflow execution denied.",
                correlation_id=_corr(request),
            )
        try:
            res = await active_container.workflow_service.execute_workflow_async(
                workflow_id,
                session=session,
                grants=grants,
                approved_bound_hash=body.approved_bound_hash,
                approval_id=body.approval_id,
                cancel_after_step=body.cancel_after_step,
                simulate_unknown_at_step=body.simulate_unknown_at_step,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "run_id": res.run_id,
                    "workflow_id": res.workflow_id,
                    "state": res.state.value,
                    "needs_user_reconciliation": res.needs_user_reconciliation,
                    "steps": [
                        {
                            "index": s.index,
                            "tool_id": s.tool_id,
                            "state": s.state.value,
                            "idempotency_key": s.idempotency_key,
                            "note": s.note,
                        }
                        for s in res.steps
                    ],
                }
            )
        except WorkflowServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Phase 4 (R2): Private LAN Opt-In & Trusted Extension SDK ---

    @app.post("/v1/providers/lan/register")
    async def register_lan_provider(
        body: PrivateLanProviderRegistration, request: Request
    ) -> Response:
        try:
            res = active_container.ecosystem_service.register_private_lan_provider(
                body, correlation_id=_corr(request)
            )
            return JSONResponse(status_code=status.HTTP_201_CREATED, content={"schema_version": 1, **res})
        except EcosystemServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/providers/lan/{provider_id}")
    async def revoke_lan_provider(provider_id: str, request: Request) -> Response:
        ok = active_container.ecosystem_service.revoke_private_lan_provider(
            provider_id, correlation_id=_corr(request)
        )
        if not ok:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message=f"Private LAN provider '{provider_id}' not found.",
                correlation_id=_corr(request),
            )
        return JSONResponse({"schema_version": 1, "revoked": True})

    @app.get("/v1/extensions")
    async def list_extensions() -> dict[str, Any]:
        exts = active_container.ecosystem_service.list_extensions()
        return {"schema_version": 1, "extensions": [e.model_dump(mode="json") for e in exts]}

    @app.post("/v1/extensions/install")
    async def install_extension(body: InstallExtensionBody, request: Request) -> Response:
        try:
            rec = active_container.ecosystem_service.install_extension(
                body.manifest, expected_sha256=body.expected_sha256, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "extension": rec.model_dump(mode="json")},
            )
        except EcosystemServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.put("/v1/extensions/{extension_id}/toggle")
    async def toggle_extension(
        extension_id: str, body: ToggleExtensionBody, request: Request
    ) -> Response:
        try:
            rec = active_container.ecosystem_service.set_extension_enabled(
                extension_id, enabled=body.enabled, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "extension": rec.model_dump(mode="json")})
        except EcosystemServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    # --- Stage G6 (B23): Hardened Opt-In MCP Host (Read-Only Pilot, Rug-Pull Pinning & Kill Switch) ---

    @app.get("/v1/mcp/servers")
    async def list_mcp_servers() -> dict[str, Any]:
        servers = active_container.mcp_host_service.list_servers()
        return {"schema_version": 1, "servers": [s.model_dump(mode="json") for s in servers]}

    @app.post("/v1/mcp/servers")
    async def register_mcp_server(body: McpServerRegistration, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; MCP server registration denied.",
                correlation_id=_corr(request),
            )
        try:
            rec = active_container.mcp_host_service.register_server(
                body, correlation_id=_corr(request)
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "server": rec.model_dump(mode="json")},
            )
        except McpHostError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/mcp/servers/{server_id}/discover")
    async def discover_mcp_server_tools(server_id: str, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; MCP tool discovery denied.",
                correlation_id=_corr(request),
            )
        try:
            rec = await asyncio.to_thread(
                active_container.mcp_host_service.discover_and_pin_tools,
                server_id,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "server": rec.model_dump(mode="json")})
        except McpHostError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.put("/v1/mcp/servers/{server_id}/toggle")
    async def toggle_mcp_server(
        server_id: str, body: ToggleMcpServerBody, request: Request
    ) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; MCP server toggle denied.",
                correlation_id=_corr(request),
            )
        try:
            rec = active_container.mcp_host_service.set_server_enabled(
                server_id, enabled=body.enabled, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "server": rec.model_dump(mode="json")})
        except McpHostError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/mcp/servers/{server_id}/call")
    async def call_mcp_tool(
        server_id: str, body: CallMcpToolBody, request: Request
    ) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=active_container.effective_os_locked(),
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            res = await asyncio.to_thread(
                active_container.mcp_host_service.invoke_tool,
                server_id,
                body.tool_name,
                body.arguments,
                session=session,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "result": res.model_dump(mode="json")})
        except McpHostError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/mcp/kill-switch")
    async def trigger_mcp_kill_switch(request: Request) -> dict[str, Any]:
        counts = active_container.mcp_host_service.kill_all_servers(correlation_id=_corr(request))
        return {"schema_version": 1, **counts}

    # --- Phase 5 (R3): On-Demand Camera, Home Assistant Allowlist, Private Remote Gateway & Preference Proposals ---

    @app.get("/v1/camera/state")
    async def get_camera_state() -> dict[str, Any]:
        return {"schema_version": 1, "camera": active_container.camera_service.get_state().model_dump(mode="json")}

    @app.get("/v1/camera/devices")
    async def list_camera_devices() -> dict[str, Any]:
        """Non-invasively list local camera devices without opening video streams (Stage G7, FR-IOT-01)."""
        port = active_container.camera_service._capture_port
        if isinstance(port, WindowsOnDemandCameraAdapter):
            devs = await asyncio.to_thread(port.list_devices)
            return {
                "schema_version": 1,
                "backend_ready": port.is_capture_backend_ready(),
                "devices": [
                    {
                        "device_id": d.device_id,
                        "friendly_name": d.friendly_name,
                        "status": d.status,
                        "capture_backend_ready": d.capture_backend_ready,
                    }
                    for d in devs
                ],
            }
        return {"schema_version": 1, "backend_ready": False, "devices": []}

    @app.post("/v1/camera/grant")
    async def grant_camera_session(body: CameraGrantBody, request: Request) -> Response:
        try:
            st = active_container.camera_service.grant_session_permission(
                session_id=body.session_id,
                device_id=body.device_id,
                explicit_local_consent=body.explicit_local_consent,
                is_os_locked=active_container.effective_os_locked(body.is_os_locked),
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "camera": st.model_dump(mode="json")})
        except CameraServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/camera/snapshot")
    async def capture_camera_snapshot(body: CameraSnapshotBody, request: Request) -> Response:
        try:
            snap = active_container.camera_service.capture_on_demand_snapshot(
                session_id=body.session_id,
                device_id=body.device_id,
                explicit_user_request=body.explicit_user_request,
                channel="local",
                is_os_locked=active_container.effective_os_locked(body.is_os_locked),
                is_suspended=body.is_suspended,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "snapshot": snap.model_dump(mode="json")})
        except CameraServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/camera/stop")
    async def stop_camera(request: Request) -> dict[str, Any]:
        closed = active_container.camera_service.stop_and_revoke_all(
            reason="user_stop", correlation_id=_corr(request)
        )
        return {"schema_version": 1, "devices_closed": closed}

    @app.get("/v1/iot/ha/entities")
    async def list_ha_entities() -> dict[str, Any]:
        items = active_container.ha_service.list_allowlisted_entities()
        return {"schema_version": 1, "entities": [e.model_dump(mode="json") for e in items]}

    @app.put("/v1/iot/ha/connect")
    async def connect_ha_bridge(body: HaConnectBody, request: Request) -> Response:
        try:
            if active_container.vault.get_secret(body.credential_vault_ref) is None:
                return _error_response(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Vault credential '{body.credential_vault_ref}' not found in OS Credential Vault.",
                    correlation_id=_corr(request),
                )
            client = PrivateLanHomeAssistantClient(
                base_url=body.base_url,
                vault=active_container.vault,
                credential_vault_ref=body.credential_vault_ref,
                clock=active_container.clock,
                allow_loopback_http=body.allow_loopback_http,
            )
            res = active_container.ha_service.configure_connection(
                client=client,
                endpoint_url=client.base_url,
                credential_vault_ref=body.credential_vault_ref,
                consent_acknowledged=body.consent_acknowledged,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, **res})
        except HomeAssistantError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/iot/ha/connect")
    async def disconnect_ha_bridge(request: Request) -> dict[str, Any]:
        res = active_container.ha_service.disconnect_connection(correlation_id=_corr(request))
        return {"schema_version": 1, **res}

    # --- Stage G7 (B26): Opt-In Read-Only OAuth 2.0 PKCE Calendar & Email Connectors (FR-LIF-04) ---

    @app.get("/v1/connectors/oauth")
    async def list_oauth_connectors() -> dict[str, Any]:
        items = active_container.oauth_connector_service.list_connectors()
        return {"schema_version": 1, "connectors": [c.model_dump(mode="json") for c in items]}

    @app.post("/v1/connectors/oauth/start")
    async def start_oauth_pkce(body: OAuthStartBody, request: Request) -> Response:
        try:
            started = active_container.oauth_connector_service.start_pkce_authorization(
                connector_id=body.connector_id,
                kind=body.kind,  # type: ignore[arg-type]
                provider_name=body.provider_name,
                authorize_url=body.authorize_url,
                token_url=body.token_url,
                api_base_url=body.api_base_url,
                redirect_uri=body.redirect_uri,
                client_id=body.client_id,
                scopes=body.scopes,
                consent_acknowledged=body.consent_acknowledged,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "pkce": started.model_dump(mode="json")},
            )
        except OAuthConnectorError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/connectors/oauth/complete")
    async def complete_oauth_pkce(body: OAuthCompleteBody, request: Request) -> Response:
        try:
            view = await active_container.oauth_connector_service.complete_pkce_callback(
                state_nonce=body.state_nonce,
                authorization_code=body.authorization_code,
                code_verifier=body.code_verifier,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "connector": view.model_dump(mode="json")})
        except OAuthConnectorError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/connectors/oauth/{connector_id}/sync-calendar")
    async def sync_oauth_calendar(
        connector_id: str,
        request: Request,
        session_id: str = Query(default="local-session-1", min_length=1, max_length=64),
    ) -> Response:
        try:
            res = await active_container.oauth_connector_service.sync_readonly_calendar(
                connector_id, session_id=session_id, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, **res})
        except OAuthConnectorError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/connectors/oauth/{connector_id}/mail-headers")
    async def list_oauth_mail_headers(
        connector_id: str,
        request: Request,
        session_id: str = Query(default="local-session-1", min_length=1, max_length=64),
    ) -> Response:
        try:
            res = await active_container.oauth_connector_service.list_readonly_mail_headers(
                connector_id, session_id=session_id, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, **res})
        except OAuthConnectorError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.delete("/v1/connectors/oauth/{connector_id}")
    async def revoke_oauth_connector(connector_id: str, request: Request) -> Response:
        ok = active_container.oauth_connector_service.revoke_connector(
            connector_id, correlation_id=_corr(request)
        )
        if not ok:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message=f"OAuth connector '{connector_id}' not found.",
                correlation_id=_corr(request),
            )
        return JSONResponse({"schema_version": 1, "revoked": True})

    @app.post("/v1/iot/ha/entities")
    async def add_ha_entity(body: HaAllowlistBody, request: Request) -> Response:
        try:
            rec = active_container.ha_service.register_allowlisted_entity(
                entity_id=body.entity_id,
                friendly_name=body.friendly_name,
                allowed_actions=body.allowed_actions,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "entity": rec.model_dump(mode="json")},
            )
        except HomeAssistantError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/iot/ha/actuate")
    async def actuate_ha_entity(body: HaActionBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        try:
            res = active_container.ha_service.execute_entity_action(
                entity_id=body.entity_id,
                action=body.action,
                params=body.params,
                offline_mode=cfg.ai.offline_mode,
                channel="local",
                is_os_locked=active_container.effective_os_locked(body.is_os_locked),
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "result": res.model_dump(mode="json")})
        except HomeAssistantError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/remote/config")
    async def get_remote_gateway_config() -> dict[str, Any]:
        cfg = active_container.remote_gateway_service.get_config()
        return {"schema_version": 1, "gateway": cfg.model_dump(mode="json")}

    @app.post("/v1/remote/tls/provision")
    async def provision_remote_tls(body: RemoteTlsProvisionBody, request: Request) -> Response:
        try:
            mat = active_container.remote_gateway_service.provision_tls_certificate(
                bind_address=body.bind_address,
                validity_days=body.validity_days,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "schema_version": 1,
                    "tls": {
                        "bind_address": mat.bind_address,
                        "fingerprint_sha256": mat.fingerprint_sha256,
                        "not_before_utc": mat.not_before_utc.isoformat(),
                        "not_after_utc": mat.not_after_utc.isoformat(),
                    },
                },
            )
        except RemoteGatewayError as exc:
            return _error_response(
                code=exc.code, message=str(exc), correlation_id=_corr(request), http_status=exc.http_status
            )

    @app.put("/v1/remote/config")
    async def configure_remote_gateway(body: RemoteGatewayConfigBody, request: Request) -> Response:
        if active_container.settings.env != "test" and body.enabled:
            tls_ok, tls_reason = active_container.remote_gateway_service.verify_provisioned_tls(
                body.tls_cert_fingerprint_sha256
            )
            if not tls_ok:
                return _error_response(
                    code=ErrorCode.UNSUPPORTED,
                    message=f"Remote gateway activation requires verified local TLS certificate provisioning: {tls_reason}",
                    correlation_id=_corr(request),
                    http_status=status.HTTP_503_SERVICE_UNAVAILABLE,
                )
        try:
            cfg = active_container.remote_gateway_service.configure_gateway(
                enabled=body.enabled,
                bind_address=body.bind_address,
                bind_port=body.bind_port,
                tls_cert_fingerprint_sha256=body.tls_cert_fingerprint_sha256,
                rate_limit_per_minute=body.rate_limit_per_minute,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "gateway": cfg.model_dump(mode="json")})
        except RemoteGatewayError as exc:
            return _error_response(
                code=exc.code, message=str(exc), correlation_id=_corr(request), http_status=exc.http_status
            )

    @app.get("/v1/remote/devices")
    async def list_remote_devices() -> dict[str, Any]:
        devices = active_container.remote_gateway_service.list_devices()
        return {"schema_version": 1, "devices": [d.model_dump(mode="json") for d in devices]}

    @app.post("/v1/remote/pairing/initiate")
    async def initiate_remote_pairing(body: RemotePairingInitBody, request: Request) -> Response:
        try:
            challenge = active_container.remote_gateway_service.initiate_pairing(
                device_label=body.device_label,
                device_fingerprint=body.device_fingerprint,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "challenge": challenge.model_dump(mode="json")},
            )
        except RemoteGatewayError as exc:
            return _error_response(
                code=exc.code, message=str(exc), correlation_id=_corr(request), http_status=exc.http_status
            )

    @app.post("/v1/remote/pairing/{challenge_id}/approve")
    async def approve_remote_pairing(
        challenge_id: str, body: RemotePairingApproveBody, request: Request
    ) -> Response:
        try:
            receipt = active_container.remote_gateway_service.approve_pairing_locally(
                challenge_id=challenge_id,
                pairing_code=body.pairing_code,
                scopes=body.scopes,
                token_ttl_hours=body.token_ttl_hours,
                channel="local",
                is_os_locked=active_container.effective_os_locked(body.is_os_locked),
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "receipt": receipt.model_dump(mode="json")})
        except RemoteGatewayError as exc:
            return _error_response(
                code=exc.code, message=str(exc), correlation_id=_corr(request), http_status=exc.http_status
            )

    @app.delete("/v1/remote/devices/{device_id}")
    async def revoke_remote_device(device_id: str, request: Request) -> Response:
        ok = active_container.remote_gateway_service.revoke_device(device_id, correlation_id=_corr(request))
        if not ok:
            return _error_response(
                code=ErrorCode.NOT_FOUND,
                message=f"Active paired device '{device_id}' not found.",
                correlation_id=_corr(request),
            )
        return JSONResponse({"schema_version": 1, "revoked": True})

    @app.get("/v1/preferences/proposals")
    async def list_preference_proposals() -> dict[str, Any]:
        props = active_container.preference_proposal_service.list_proposals()
        return {"schema_version": 1, "proposals": [p.model_dump(mode="json") for p in props]}

    @app.post("/v1/preferences/proposals")
    async def create_preference_proposal(body: PreferenceProposalCreateBody, request: Request) -> Response:
        try:
            prop = active_container.preference_proposal_service.create_proposal(
                preference_key=body.preference_key,
                proposed_value=body.proposed_value,
                rationale=body.rationale,
                evidence_count=body.evidence_count,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "proposal": prop.model_dump(mode="json")},
            )
        except PreferenceProposalError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/preferences/proposals/{proposal_id}/decide")
    async def decide_preference_proposal(
        proposal_id: str, body: PreferenceProposalDecideBody, request: Request
    ) -> Response:
        try:
            prop = active_container.preference_proposal_service.decide_proposal(
                proposal_id,
                decision=body.decision,  # type: ignore[arg-type]
                channel="local",
                is_os_locked=active_container.effective_os_locked(body.is_os_locked),
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, "proposal": prop.model_dump(mode="json")})
        except PreferenceProposalError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/licenses/inventory")
    async def get_license_inventory() -> dict[str, Any]:
        artifacts = active_container.license_service.list_artifacts()
        return {
            "schema_version": 1,
            "count": len(artifacts),
            "artifacts": [a.model_dump(mode="json") for a in artifacts],
        }

    @app.post("/v1/licenses/inventory")
    async def register_license_artifact(artifact: LicenseArtifact, request: Request) -> Response:
        try:
            saved = active_container.license_service.register_artifact(artifact)
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "artifact": saved.model_dump(mode="json")},
            )
        except LicenseValidationError as exc:
            return _error_response(code=exc.error_code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/licenses/sbom")
    async def export_sbom() -> dict[str, Any]:
        return active_container.license_service.export_sbom()

    @app.get("/v1/licenses/notices", response_class=PlainTextResponse)
    async def export_notices() -> PlainTextResponse:
        return PlainTextResponse(active_container.license_service.export_notices())

    @app.post("/v1/backups/create")
    async def create_backup(body: BackupCreateBody, request: Request) -> Response:
        if active_container.effective_os_locked():
            return _error_response(
                code=ErrorCode.DENIED,
                message="Session is locked; backup creation denied.",
                correlation_id=_corr(request),
            )
        try:
            meta = await asyncio.to_thread(
                active_container.backup_service.create_backup,
                Path(body.archive_path),
                body.recovery_passphrase,
                correlation_id=_corr(request),
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={
                    "schema_version": 1,
                    "backup_id": meta.backup_id,
                    "created_at": meta.created_at,
                    "core_db_sha256": meta.core_db_sha256,
                    "core_db_bytes": meta.core_db_bytes,
                    "deletion_tombstone_count": meta.deletion_tombstone_count,
                },
            )
        except (BackupServiceError, ValueError) as exc:
            code = exc.code if isinstance(exc, BackupServiceError) else ErrorCode.INVALID_ARGS
            return _error_response(code=code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/backups/verify")
    async def verify_backup(body: BackupVerifyBody, request: Request) -> Response:
        try:
            meta = active_container.backup_service.verify_backup(Path(body.archive_path), body.recovery_passphrase)
            return JSONResponse(
                {
                    "schema_version": 1,
                    "valid": True,
                    "backup_id": meta.backup_id,
                    "core_db_sha256": meta.core_db_sha256,
                }
            )
        except BackupServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.get("/v1/events")
    async def stream_events(
        after_seq: int = Query(default=0, ge=0),
        once: bool = Query(default=False),
    ) -> StreamingResponse:
        """Reliable sequenced domain event stream (SSE) supporting cursor resumption."""

        async def event_generator() -> AsyncIterator[str]:
            missed, resync_required = active_container.event_bus.replay_after(after_seq)
            if resync_required:
                yield (
                    "event: resync_required\n"
                    f"data: {json.dumps({'current_seq': active_container.event_bus.current_seq})}\n\n"
                )
            for ev in missed:
                yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {ev.model_dump_json()}\n\n"
            if once:
                return

            queue = active_container.event_bus.subscribe()
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                        yield f"id: {ev.seq}\nevent: {ev.type}\ndata: {ev.model_dump_json()}\n\n"
                    except TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                active_container.event_bus.unsubscribe(queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    # Convert FastAPI validation and HTTP errors into standard ErrorEnvelope (DEF-22, B05)
    @app.exception_handler(RequestValidationError)
    async def handle_validation_exc(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _error_response(
            code=ErrorCode.INVALID_ARGS,
            message=f"Request validation failed: {len(exc.errors())} invalid field(s).",
            correlation_id=_corr(request),
            http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exc(request: Request, exc: HTTPException) -> JSONResponse:
        return _error_response(
            code=ErrorCode.INVALID_ARGS,
            message=str(exc.detail),
            correlation_id=_corr(request),
            http_status=exc.status_code,
        )

    return app


def utc_now() -> datetime:
    return datetime.now(tz=UTC)
