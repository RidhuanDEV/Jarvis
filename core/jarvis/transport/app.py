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
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.application.ai_registry_service import AiRegistryError, AiRegistryService
from jarvis.application.approval_service import ApprovalError, ApprovalService
from jarvis.application.backup_service import BackupService, BackupServiceError
from jarvis.application.config_service import (
    ConfigService,
    ConfigServiceError,
    build_default_config,
    build_default_storage_roots,
)
from jarvis.application.ecosystem_service import (
    EcosystemGovernanceService,
    EcosystemServiceError,
    ExtensionManifest,
    PrivateLanProviderRegistration,
)
from jarvis.application.knowledge_service import KnowledgeRagService, KnowledgeServiceError
from jarvis.application.license_service import LicenseInventoryService
from jarvis.application.memory_service import MemoryServiceError, MemoryVaultService
from jarvis.application.personal_life_service import PersonalLifeError, PersonalLifeService
from jarvis.application.reminder_service import ReminderSchedulerService, ReminderServiceError
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
    AudioDevicePort,
    ClockPort,
    DesktopAutomationPort,
    FilesystemSafetyPort,
    HardwareDiscoveryPort,
    LocalIpcTransportPort,
    NotificationPort,
    ProcessSupervisorPort,
    SecretVaultAndCryptoPort,
)
from jarvis.domain.recommendations import recommend_configuration
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus
from jarvis.infrastructure.logging_setup import configure_logging, get_logger
from jarvis.infrastructure.web_fetch import SafeWebFetchClient
from jarvis.platform.portable_mock import FakeNotificationAdapter, SystemClock, TokenIpcTransport
from jarvis.platform.windows.audio import (
    WindowsAudioDeviceAdapter,
    WindowsOneCoreVoiceProbeAdapter,
)
from jarvis.platform.windows.desktop_automation import WindowsDesktopAutomationAdapter
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter
from jarvis.platform.windows.hardware import WindowsHardwareDiscoveryAdapter
from jarvis.platform.windows.supervisor import WindowsJobProcessSupervisor
from jarvis.platform.windows.vault import WindowsVaultAndCryptoAdapter
from jarvis.transport.settings import CoreStartupSettings

MAX_PAYLOAD_BYTES = 256 * 1024
ALLOWED_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "[::1]", "testserver"})


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
            verification="process_started",
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
    reminder_service: ReminderSchedulerService
    turn_orchestrator: TurnOrchestratorService
    knowledge_service: KnowledgeRagService
    web_service: WebIntelligenceService
    screen_service: ScreenAwarenessService
    life_service: PersonalLifeService
    workflow_service: WorkflowEngineService
    ecosystem_service: EcosystemGovernanceService


class _StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SetStorageLocationBody(_StrictRequest):
    path: str = Field(min_length=1, max_length=1024)
    quota_bytes: int | None = Field(default=None, ge=1024 * 1024 * 1024)


class MigrateStorageBody(_StrictRequest):
    category: StorageCategory
    target_path: str = Field(min_length=1, max_length=1024)


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


class SubmitTurnBody(_StrictRequest):
    utterance: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    channel: ChannelKind = ChannelKind.LOCAL
    modality: InputModality = InputModality.TRUSTED_UI
    is_os_locked: bool = False
    is_suspended: bool = False
    is_muted: bool = False


class SetAudioModeBody(_StrictRequest):
    mode: str = Field(pattern=r"^(muted|ptt|wake)$")


class SelectAudioDevicesBody(_StrictRequest):
    input_device_id: str | None = None
    output_device_id: str | None = None


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


class WebQueryBody(_StrictRequest):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=5, ge=1, le=10)
    private_query_approved: bool = False


class WebFetchBody(_StrictRequest):
    url: str = Field(min_length=8, max_length=2048)
    require_https: bool = False


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
    session_id: str = Field(default="local-session-1", min_length=1, max_length=64)
    actor_ref: str = Field(default="local_owner", min_length=1, max_length=64)
    cancel_after_step: int | None = None
    simulate_unknown_at_step: int | None = None


class InstallExtensionBody(_StrictRequest):
    manifest: ExtensionManifest
    expected_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class ToggleExtensionBody(_StrictRequest):
    enabled: bool


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
    notification_port: NotificationPort | None = None,
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
    resolved_desktop = desktop_port or WindowsDesktopAutomationAdapter(allow_live_launch=False)
    resolved_notify = notification_port or FakeNotificationAdapter()

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

    policy_engine = PolicyEngine(default_tool_registry())
    approval_service = ApprovalService(db, resolved_clock, event_bus)
    backup_service = BackupService(db, resolved_clock)
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
    reminder_service = ReminderSchedulerService(
        db, config_service, resolved_notify, resolved_clock, event_bus
    )
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
    )
    knowledge_service = KnowledgeRagService(db, resolved_fs, resolved_clock, event_bus)
    web_service = WebIntelligenceService(
        db, config_service, SafeWebFetchClient(resolved_clock), resolved_clock
    )
    screen_service = ScreenAwarenessService(db, resolved_clock)
    life_service = PersonalLifeService(db, resolved_clock)
    workflow_service = WorkflowEngineService(db, policy_engine, resolved_clock)
    ecosystem_service = EcosystemGovernanceService(db, resolved_vault, resolved_clock)

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
        reminder_service=reminder_service,
        turn_orchestrator=turn_orchestrator,
        knowledge_service=knowledge_service,
        web_service=web_service,
        screen_service=screen_service,
        life_service=life_service,
        workflow_service=workflow_service,
        ecosystem_service=ecosystem_service,
    )


def create_app(container: CoreContainer | None = None) -> FastAPI:
    """Create authenticated local J.A.R.V.I.S. Core FastAPI application."""
    active_container = container or build_default_container(CoreStartupSettings())
    configure_logging(active_container.settings.log_level)
    logger = get_logger("jarvis.transport")

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        logger.info(
            "core.startup.ready",
            env=active_container.settings.env,
            release_sha=active_container.settings.release_sha,
            sqlite_vec_loaded=active_container.db.sqlite_vec_loaded,
        )
        try:
            yield
        finally:
            closed_children = active_container.supervisor.close_all_managed()
            active_container.db.close()
            logger.info("core.shutdown.completed", closed_managed_children=closed_children)

    app = FastAPI(
        title="J.A.R.V.I.S. Local Core API",
        version="0.2.1",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.container = active_container

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

        # 1. Strict Host header validation (anti DNS-rebinding, 08-INTERFACE-CONTRACTS.md §1)
        raw_host = (request.headers.get("host") or "").split(":", 1)[0].lower()
        if raw_host and raw_host not in ALLOWED_LOOPBACK_HOSTS:
            resp = _error_response(
                code=ErrorCode.DENIED,
                message="Disallowed Host header on local core transport.",
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

        # 3. Payload size ceiling <= 256 KiB (08-INTERFACE-CONTRACTS.md §1)
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                if int(content_length) > MAX_PAYLOAD_BYTES:
                    resp = _error_response(
                        code=ErrorCode.INVALID_ARGS,
                        message="Payload exceeds 256 KiB local IPC limit.",
                        correlation_id=correlation_id,
                        http_status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                    )
                    resp.headers["X-Request-Id"] = request_id
                    return resp
            except ValueError:
                pass

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
        db_health = active_container.db.check_health()
        return {
            "schema_version": 1,
            "status": "ready" if db_health["core_db_ok"] and db_health["knowledge_db_ok"] else "degraded",
            "release_sha": active_container.settings.release_sha,
            "components": db_health,
            "event_seq": active_container.event_bus.current_seq,
        }

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
        try:
            rec = active_container.storage_service.set_location(
                category, body.path, quota_bytes=body.quota_bytes, correlation_id=_corr(request)
            )
            return JSONResponse({"schema_version": 1, "location": rec.model_dump(mode="json")})
        except StorageServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/storage/migrate")
    async def migrate_storage(body: MigrateStorageBody, request: Request) -> Response:
        try:
            res = active_container.storage_service.migrate_location(
                body.category, body.target_path, correlation_id=_corr(request)
            )
            return JSONResponse(
                {
                    "schema_version": 1,
                    "category": res.category.value,
                    "source_path": res.source_path,
                    "target_path": res.target_path,
                    "files_verified": res.files_verified,
                    "total_bytes": res.total_bytes,
                }
            )
        except StorageServiceError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/storage/cleanup")
    async def cleanup_storage_cache(body: CleanupCacheBody, request: Request) -> Response:
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

    @app.get("/v1/grants")
    async def list_grants() -> dict[str, Any]:
        with active_container.db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision
                FROM grant ORDER BY id ASC
                """
            ).fetchall()
        items = [
            GrantRecord(
                id=str(r["id"]),
                subject_type=str(r["subject_type"]),  # type: ignore[arg-type]
                subject_id=str(r["subject_id"]),
                capability=str(r["capability"]),
                scope=json.loads(str(r["scope_json"])),
                expires_at=datetime.fromisoformat(str(r["expires_at"])) if r["expires_at"] else None,
                revoked_at=datetime.fromisoformat(str(r["revoked_at"])) if r["revoked_at"] else None,
                revision=int(r["revision"]),
            ).model_dump(mode="json")
            for r in rows
        ]
        return {"schema_version": 1, "grants": items}

    @app.put("/v1/grants")
    async def upsert_grant(body: UpsertGrantBody, request: Request) -> dict[str, Any]:
        grant_id = body.id or str(uuid.uuid4())
        now_iso = active_container.clock.now_utc().isoformat()
        with active_container.db.core_tx() as conn:
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
                    json.dumps(body.scope, sort_keys=True),
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
        return {"schema_version": 1, "grant_id": grant_id, "capability": body.capability}

    @app.delete("/v1/grants/{grant_id}")
    async def revoke_grant(grant_id: str, request: Request) -> Response:
        now_iso = active_container.clock.now_utc().isoformat()
        with active_container.db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE grant SET revoked_at = ?, revision = revision + 1 WHERE id = ? AND revoked_at IS NULL",
                (now_iso, grant_id),
            )
            if cur.rowcount == 0:
                return _error_response(
                    code=ErrorCode.NOT_FOUND,
                    message=f"Active grant '{grant_id}' not found.",
                    correlation_id=_corr(request),
                )
        active_container.event_bus.publish(
            event_type="permission.revoked",
            correlation_id=_corr(request),
            payload={"grant_id": grant_id},
        )
        return JSONResponse({"schema_version": 1, "grant_id": grant_id, "revoked": True})

    @app.post("/v1/policy/evaluate")
    async def evaluate_policy(body: PolicyEvalBody, request: Request) -> Response:
        active_cfg = active_container.config_service.get_active().document
        with active_container.db.core_read() as conn:
            rows = conn.execute(
                "SELECT id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision FROM grant"
            ).fetchall()
        grants = tuple(
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
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=body.channel,
            modality=body.modality,
            is_os_locked=body.is_os_locked,
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
        active_container.voice_service.on_session_locked()
        canceled = active_container.approval_service.cancel_all_pending_on_lock(
            reason=body.reason, correlation_id=_corr(request)
        )
        return {"schema_version": 1, "canceled_approvals": canceled}

    # --- Phase 3: Turn Orchestration (Deterministic-First + Bounded LLM) ---

    @app.post("/v1/requests")
    async def submit_turn(body: SubmitTurnBody, request: Request) -> Response:
        cfg = active_container.config_service.get_active().document
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=body.channel,
            modality=body.modality,
            is_os_locked=body.is_os_locked,
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
            summary = active_container.knowledge_service.sync_source_root(
                root_id, correlation_id=_corr(request)
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

    # --- Phase 4 (R2): Pluggable Web Search & Anti-SSRF Fetch ---

    @app.post("/v1/web/query")
    async def web_query(body: WebQueryBody, request: Request) -> Response:
        try:
            res = await active_container.web_service.query_web(
                body.query,
                limit=body.limit,
                private_query_approved=body.private_query_approved,
                correlation_id=_corr(request),
            )
            return JSONResponse({"schema_version": 1, **res})
        except WebSearchError as exc:
            return _error_response(code=exc.code, message=str(exc), correlation_id=_corr(request))

    @app.post("/v1/web/fetch")
    async def web_fetch(body: WebFetchBody, request: Request) -> Response:
        try:
            page = await active_container.web_service.fetch_page(
                body.url, require_https=body.require_https, correlation_id=_corr(request)
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
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            is_os_locked=body.is_os_locked,
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
        with active_container.db.core_read() as conn:
            rows = conn.execute(
                "SELECT id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision FROM grant"
            ).fetchall()
        grants = tuple(
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
        session = SessionContext(
            session_id=body.session_id,
            actor_ref=body.actor_ref,
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
            offline_mode=cfg.ai.offline_mode,
        )
        try:
            res = active_container.workflow_service.execute_workflow(
                workflow_id,
                session=session,
                grants=grants,
                approved_bound_hash=body.approved_bound_hash,
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
        try:
            meta = active_container.backup_service.create_backup(
                Path(body.archive_path), body.recovery_passphrase, correlation_id=_corr(request)
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

    # Convert FastAPI validation errors into standard ErrorEnvelope
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
