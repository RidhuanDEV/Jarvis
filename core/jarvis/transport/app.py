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

from jarvis.application.approval_service import ApprovalError, ApprovalService
from jarvis.application.backup_service import BackupService, BackupServiceError
from jarvis.application.config_service import (
    ConfigService,
    ConfigServiceError,
    build_default_config,
    build_default_storage_roots,
)
from jarvis.application.license_service import LicenseInventoryService
from jarvis.application.storage_service import StorageService, StorageServiceError
from jarvis.domain.licensing import LicenseValidationError
from jarvis.domain.models import (
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
)
from jarvis.domain.policy import PolicyEngine
from jarvis.domain.ports import (
    ClockPort,
    FilesystemSafetyPort,
    HardwareDiscoveryPort,
    LocalIpcTransportPort,
    ProcessSupervisorPort,
    SecretVaultAndCryptoPort,
)
from jarvis.domain.recommendations import recommend_configuration
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus
from jarvis.infrastructure.logging_setup import configure_logging, get_logger
from jarvis.platform.portable_mock import SystemClock, TokenIpcTransport
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
    event_bus: SequencedEventBus
    policy_engine: PolicyEngine
    config_service: ConfigService
    storage_service: StorageService
    approval_service: ApprovalService
    backup_service: BackupService
    license_service: LicenseInventoryService


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
) -> CoreContainer:
    data_dir = settings.resolved_data_dir()
    cache_dir = settings.resolved_cache_dir()
    roots = build_default_storage_roots(data_dir, cache_dir)

    resolved_clock = clock or SystemClock()
    resolved_fs = fs_port or WindowsFilesystemSafetyAdapter()
    resolved_hw = hardware_port or WindowsHardwareDiscoveryAdapter()
    resolved_sup = supervisor or WindowsJobProcessSupervisor()
    resolved_vault = vault or WindowsVaultAndCryptoAdapter()

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

    approval_service = ApprovalService(db, resolved_clock, event_bus)
    backup_service = BackupService(db, resolved_clock)
    license_service = LicenseInventoryService(db, resolved_clock)
    license_service.seed_baseline_if_empty()

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
        event_bus=event_bus,
        policy_engine=PolicyEngine(default_tool_registry()),
        config_service=config_service,
        storage_service=storage_service,
        approval_service=approval_service,
        backup_service=backup_service,
        license_service=license_service,
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
        canceled = active_container.approval_service.cancel_all_pending_on_lock(
            reason=body.reason, correlation_id=_corr(request)
        )
        return {"schema_version": 1, "canceled_approvals": canceled}

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
