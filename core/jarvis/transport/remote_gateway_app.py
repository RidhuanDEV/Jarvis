"""Structurally Separate Private Scoped Remote Mobile Gateway FastAPI App (B19, FR-REM-01/02/04, NFR-11).

- Completely isolated from the local loopback/named-pipe Core API (different listener & token namespace).
- Disabled by default; never exposes R2 approvals, filesystem, camera, screen, policy, config, or IoT.
- Enforces per-device token revocation, sliding-window rate limits, narrow scope allowlist, and honest
  `host_unreachable` (503) without silent mutation queueing when the desktop host sleeps/disconnects.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import FastAPI, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from jarvis.application.reminder_service import ReminderSchedulerService, ReminderServiceError
from jarvis.application.remote_gateway_service import RemoteGatewayError, RemoteGatewayService
from jarvis.application.turn_orchestrator import TurnOrchestratorService
from jarvis.domain.models import (
    ChannelKind,
    ErrorCode,
    ErrorEnvelope,
    InputModality,
    SessionContext,
)
from jarvis.domain.ports import ClockPort


class _StrictRemoteBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RemoteChatBody(_StrictRemoteBody):
    utterance: str = Field(min_length=1, max_length=1000)


class RemoteReminderBody(_StrictRemoteBody):
    title: str = Field(min_length=1, max_length=250)
    due_at_utc: datetime
    timezone_iana: str = Field(default="UTC", min_length=2, max_length=64)


def _remote_error(
    *,
    code: ErrorCode,
    message: str,
    correlation_id: str,
    http_status: int,
    retryable: bool = False,
) -> JSONResponse:
    env = ErrorEnvelope(code=code, message=message, correlation_id=correlation_id, retryable=retryable)
    return JSONResponse(
        status_code=http_status,
        content=env.model_dump(mode="json"),
        headers={"X-Correlation-Id": correlation_id, "Cache-Control": "no-store"},
    )


def _extract_bearer(request: Request) -> str:
    raw = request.headers.get("authorization") or ""
    if not raw.startswith("Bearer "):
        return ""
    return raw[len("Bearer ") :].strip()


def _extract_replay_headers(request: Request) -> tuple[str | None, float | None]:
    nonce = request.headers.get("x-jarvis-nonce")
    ts_raw = request.headers.get("x-jarvis-timestamp")
    if ts_raw is None:
        return (nonce, None)
    try:
        return (nonce, float(ts_raw.strip()))
    except ValueError:
        return (nonce, -1.0)


def create_remote_gateway_app(
    *,
    remote_service: RemoteGatewayService,
    reminder_service: ReminderSchedulerService,
    turn_orchestrator: TurnOrchestratorService,
    clock: ClockPort,
    require_replay_headers: bool = False,
) -> FastAPI:
    """Build the isolated private-LAN/VPN mobile gateway ASGI application."""
    app = FastAPI(
        title="J.A.R.V.I.S. Private Scoped Remote Gateway",
        version="0.2.2",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    def _corr(request: Request) -> str:
        return request.headers.get("X-Correlation-Id") or f"rem_{uuid.uuid4().hex[:16]}"

    def _authorize(request: Request, *, scope_requested: str, is_mutating: bool, corr: str) -> Any:
        nonce, ts = _extract_replay_headers(request)
        return remote_service.authorize_remote_request(
            bearer_token=_extract_bearer(request),
            scope_requested=scope_requested,
            is_mutating=is_mutating,
            replay_nonce=nonce,
            replay_timestamp_epoch=ts,
            require_replay_headers=require_replay_headers and is_mutating,
            correlation_id=corr,
        )

    @app.get("/remote/v1/status")
    async def remote_status(request: Request) -> Response:
        corr = _corr(request)
        try:
            ctx = _authorize(
                request,
                scope_requested="remote.status.read",
                is_mutating=False,
                corr=corr,
            )
        except RemoteGatewayError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=exc.http_status or status.HTTP_403_FORBIDDEN,
            )
        cfg = remote_service.get_config()
        return JSONResponse(
            {
                "schema_version": 1,
                "status": "online" if cfg.host_available else "host_unreachable",
                "device_id": ctx.device_id,
                "granted_scopes": list(ctx.granted_scopes),
                "remaining_rate_quota": ctx.remaining_rate_quota,
                "server_time_utc": clock.now_utc().isoformat(),
            },
            headers={"X-Correlation-Id": corr, "Cache-Control": "no-store"},
        )

    @app.post("/remote/v1/chat")
    async def remote_chat(body: RemoteChatBody, request: Request) -> Response:
        corr = _corr(request)
        try:
            ctx = _authorize(
                request,
                scope_requested="remote.chat.send",
                is_mutating=True,
                corr=corr,
            )
        except RemoteGatewayError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=exc.http_status or status.HTTP_403_FORBIDDEN,
            )

        session = SessionContext(
            session_id=f"remote:{ctx.device_id}",
            actor_ref=f"remote:{ctx.device_id}",
            channel=ChannelKind.REMOTE,
            modality=InputModality.REMOTE_API,
            is_os_locked=remote_service.get_config().is_os_locked,
            offline_mode=True,
        )
        res = await turn_orchestrator.submit_turn(body.utterance, session=session, correlation_id=corr)
        if res.error_code == ErrorCode.DENIED:
            return _remote_error(
                code=ErrorCode.DENIED,
                message=res.reply,
                correlation_id=corr,
                http_status=status.HTTP_403_FORBIDDEN,
            )
        return JSONResponse(
            {
                "schema_version": 1,
                "request_id": res.request_id,
                "state": res.state.value,
                "reply": res.reply,
                "llm_called": res.llm_called,
            },
            headers={"X-Correlation-Id": corr, "Cache-Control": "no-store"},
        )

    @app.get("/remote/v1/reminders")
    async def remote_list_reminders(request: Request) -> Response:
        corr = _corr(request)
        try:
            _authorize(
                request,
                scope_requested="remote.reminder.read",
                is_mutating=False,
                corr=corr,
            )
        except RemoteGatewayError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=exc.http_status or status.HTTP_403_FORBIDDEN,
            )
        items = reminder_service.list_reminders()
        return JSONResponse(
            {"schema_version": 1, "reminders": [r.model_dump(mode="json") for r in items]},
            headers={"X-Correlation-Id": corr, "Cache-Control": "no-store"},
        )

    @app.post("/remote/v1/reminders")
    async def remote_create_reminder(body: RemoteReminderBody, request: Request) -> Response:
        corr = _corr(request)
        try:
            _authorize(
                request,
                scope_requested="remote.reminder.create",
                is_mutating=True,
                corr=corr,
            )
            created = reminder_service.create_reminder(
                title=body.title,
                due_at_utc=body.due_at_utc,
                timezone_iana=body.timezone_iana,
                correlation_id=corr,
            )
            return JSONResponse(
                status_code=status.HTTP_201_CREATED,
                content={"schema_version": 1, "reminder": created.model_dump(mode="json")},
                headers={"X-Correlation-Id": corr, "Cache-Control": "no-store"},
            )
        except RemoteGatewayError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=exc.http_status or status.HTTP_403_FORBIDDEN,
            )
        except ReminderServiceError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )

    @app.post("/remote/v1/actions/{capability:path}")
    async def remote_restricted_action(capability: str, request: Request) -> Response:
        """Fail-closed endpoint enforcing FR-REM-02: blocks fs/camera/screen/policy/R2 with 403."""
        corr = _corr(request)
        try:
            _authorize(
                request,
                scope_requested=capability,
                is_mutating=True,
                corr=corr,
            )
        except RemoteGatewayError as exc:
            return _remote_error(
                code=exc.code,
                message=str(exc),
                correlation_id=corr,
                http_status=exc.http_status or status.HTTP_403_FORBIDDEN,
            )
        # Even if a valid narrow scope is passed here, generic action execution is denied
        return _remote_error(
            code=ErrorCode.DENIED,
            message="Direct action dispatch is prohibited over remote gateway (FR-REM-02).",
            correlation_id=corr,
            http_status=status.HTTP_403_FORBIDDEN,
        )

    return app


def remote_health_descriptor(cfg: Any) -> dict[str, Any]:
    return {
        "enabled": bool(cfg.enabled),
        "bind_address": str(cfg.bind_address),
        "bind_port": int(cfg.bind_port),
        "host_available": bool(cfg.host_available),
    }
