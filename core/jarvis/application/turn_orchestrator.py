"""Deterministic-First Turn Orchestrator, Bounded LLM Planner & Verified OS Tool Executor (B06, B07)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from jarvis.application.ai_registry_service import AiRegistryService
from jarvis.application.approval_service import ApprovalService
from jarvis.application.config_service import ConfigService
from jarvis.application.memory_service import MemoryVaultService
from jarvis.application.reminder_service import ReminderSchedulerService
from jarvis.domain.ai_models import ChatMessage, LlmCompletionRequest
from jarvis.domain.models import (
    ActionOutcomeState,
    AiProfileMode,
    ApprovalChallenge,
    ErrorCode,
    GrantRecord,
    SessionContext,
    ToolProposal,
)
from jarvis.domain.policy import PolicyEngine
from jarvis.domain.ports import ClockPort, DesktopAutomationPort, FilesystemSafetyPort
from jarvis.domain.router import (
    DeterministicRouter,
    build_static_tool_catalog_prompt,
    parse_llm_tool_proposal,
    resolve_user_timezone,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


@dataclass(frozen=True)
class StepExecutionRecord:
    tool_id: str
    tool_version: int
    state: ActionOutcomeState
    verified: bool
    summary: str
    error_code: ErrorCode | None = None
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class TurnResult:
    request_id: str
    state: ActionOutcomeState
    route_kind: str
    reply: str
    llm_called: bool
    steps: tuple[StepExecutionRecord, ...] = ()
    approval: ApprovalChallenge | None = None
    error_code: ErrorCode | None = None


class TurnOrchestratorService:
    """Executes deterministic-first turns (0 LLM calls), bounded LLM proposals, and verified OS tools."""

    def __init__(
        self,
        *,
        db: DualSqliteManager,
        config_service: ConfigService,
        policy_engine: PolicyEngine,
        approval_service: ApprovalService,
        ai_registry: AiRegistryService,
        memory_service: MemoryVaultService,
        reminder_service: ReminderSchedulerService,
        desktop_port: DesktopAutomationPort,
        fs_port: FilesystemSafetyPort,
        clock: ClockPort,
        event_bus: SequencedEventBus,
    ) -> None:
        self._db = db
        self._config = config_service
        self._policy = policy_engine
        self._approvals = approval_service
        self._ai = ai_registry
        self._memory = memory_service
        self._reminders = reminder_service
        self._desktop = desktop_port
        self._fs = fs_port
        self._clock = clock
        self._bus = event_bus
        self._router = DeterministicRouter()

    def _load_grants(self) -> tuple[GrantRecord, ...]:
        with self._db.core_read() as conn:
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

    async def submit_turn(
        self,
        utterance: str,
        *,
        session: SessionContext,
        correlation_id: str,
        request_id: str | None = None,
    ) -> TurnResult:
        req_id = request_id or f"req_{uuid.uuid4().hex[:16]}"
        now = self._clock.now_utc()
        cfg = self._config.get_active().document
        tz_iana = cfg.locale.timezone_iana
        lang = cfg.locale.primary_language

        self._bus.publish(
            event_type="request.state_changed",
            correlation_id=correlation_id,
            request_id=req_id,
            payload={"state": "Thinking"},
        )

        # 1. Deterministic-First Routing (0 LLM calls!)
        route = self._router.route(
            utterance, now_utc=now, timezone_iana=tz_iana, primary_language=lang
        )
        if route.needs_clarification:
            self._bus.publish(
                event_type="request.state_changed",
                correlation_id=correlation_id,
                request_id=req_id,
                payload={"state": "Idle"},
            )
            return TurnResult(
                request_id=req_id,
                state=ActionOutcomeState.COMPLETED,
                route_kind=route.intent_label,
                reply=route.clarification_prompt or "Mohon perjelas perintah Anda.",
                llm_called=False,
            )

        proposal: ToolProposal | None = route.proposal
        llm_called = False
        route_kind = route.intent_label

        # 2. Bounded LLM Planner (only when deterministic grammar didn't match)
        if proposal is None:
            active_prof = self._ai.get_active_profile().profile
            llm_provider_id = active_prof.role_bindings.get("llm_provider")
            llm_model_id = active_prof.role_bindings.get("llm_model")
            adapter = self._ai.get_adapter(llm_provider_id) if llm_provider_id else None

            if active_prof.mode == AiProfileMode.DIRECT or adapter is None or not llm_model_id:
                reply = (
                    "Direct Mode aktif (tanpa runtime LLM). Gunakan perintah deterministik seperti "
                    "'jam berapa', 'atur volume ke 40', 'ingat bahwa ...', 'ingatkan saya 10 menit lagi ...', "
                    "atau aktifkan profil AI lokal."
                    if not lang.lower().startswith("en")
                    else "Direct Mode is active (0 LLM runtime). Use deterministic commands or enable a local AI profile."
                )
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.COMPLETED,
                    route_kind="direct_mode_no_match",
                    reply=reply,
                    llm_called=False,
                )

            llm_called = True
            route_kind = "bounded_llm_planner"
            try:
                resp = await adapter.complete(
                    LlmCompletionRequest(
                        model_id=llm_model_id,
                        messages=(
                            ChatMessage(role="system", content=build_static_tool_catalog_prompt()),
                            ChatMessage(role="user", content=utterance),
                        ),
                        max_tokens=512,
                        temperature=0.0,
                        enforce_non_thinking=True,
                        expect_json=True,
                        timeout_seconds=60.0,
                    )
                )
            except Exception as exc:
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind=route_kind,
                    reply=f"Runtime LLM gagal merespons ({type(exc).__name__}); Direct Mode tetap tersedia.",
                    llm_called=True,
                    error_code=ErrorCode.RUNTIME_UNAVAILABLE,
                )

            parsed_prop, parse_err = parse_llm_tool_proposal(resp.content)
            if parsed_prop is None:
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind=route_kind,
                    reply=f"Proposal model ditolak karena tidak mematuhi skema ketat: {parse_err}",
                    llm_called=True,
                    error_code=ErrorCode.INVALID_ARGS,
                )
            proposal = parsed_prop

        # 3. Validate proposal bounds & evaluate every step through deterministic Policy Engine
        bounds_err = self._policy.validate_proposal_bounds(proposal)
        if bounds_err is not None:
            return TurnResult(
                request_id=req_id,
                state=ActionOutcomeState.FAILED,
                route_kind=route_kind,
                reply=bounds_err.reason,
                llm_called=llm_called,
                error_code=bounds_err.error_code,
            )

        grants = self._load_grants()
        step_results: list[StepExecutionRecord] = []

        for step in proposal.steps:
            decision = self._policy.evaluate_step(
                tool_id=step.tool_id,
                tool_version=step.version,
                args=step.args,
                session=session,
                grants=grants,
                now_utc=now,
            )
            if decision.requires_approval:
                challenge = self._approvals.create_challenge(
                    request_id=req_id,
                    correlation_id=correlation_id,
                    tool_id=step.tool_id,
                    tool_version=step.version,
                    canonical_args_hash=decision.canonical_args_hash,
                    session=session,
                    summary=f"Konfirmasi aksi R2: {step.tool_id} ({json.dumps(step.args)})",
                )
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.AWAITING_APPROVAL,
                    route_kind=route_kind,
                    reply=f"Aksi '{step.tool_id}' berisiko R2 dan menunggu persetujuan lokal pada dialog native.",
                    llm_called=llm_called,
                    steps=tuple(step_results),
                    approval=challenge,
                    error_code=ErrorCode.APPROVAL_REQUIRED,
                )

            if not decision.allowed:
                self._bus.publish(
                    event_type="request.state_changed",
                    correlation_id=correlation_id,
                    request_id=req_id,
                    payload={"state": "Error"},
                )
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind=route_kind,
                    reply=decision.reason,
                    llm_called=llm_called,
                    steps=tuple(step_results),
                    error_code=decision.error_code,
                )

            # 4. Execute verified deterministic R0/R1 adapter (BR-05 readback proof!)
            outcome = self._execute_verified_step(
                step.tool_id, step.version, step.args, tz_iana=tz_iana, correlation_id=correlation_id
            )
            step_results.append(outcome)
            if outcome.state != ActionOutcomeState.COMPLETED:
                return TurnResult(
                    request_id=req_id,
                    state=outcome.state,
                    route_kind=route_kind,
                    reply=outcome.summary,
                    llm_called=llm_called,
                    steps=tuple(step_results),
                    error_code=outcome.error_code,
                )

        self._bus.publish(
            event_type="request.state_changed",
            correlation_id=correlation_id,
            request_id=req_id,
            payload={"state": "Success"},
        )
        final_reply = " ".join(s.summary for s in step_results)
        return TurnResult(
            request_id=req_id,
            state=ActionOutcomeState.COMPLETED,
            route_kind=route_kind,
            reply=final_reply,
            llm_called=llm_called,
            steps=tuple(step_results),
        )

    def _execute_verified_step(
        self,
        tool_id: str,
        tool_version: int,
        args: dict[str, Any],
        *,
        tz_iana: str,
        correlation_id: str,
    ) -> StepExecutionRecord:
        if tool_id == "system.time.get":
            target_tz = str(args.get("timezone_iana") or tz_iana)
            tz = resolve_user_timezone(target_tz)
            local_now = self._clock.now_utc().astimezone(tz)
            formatted = local_now.strftime("%Y-%m-%d %H:%M:%S %Z")
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Waktu saat ini ({target_tz}): {formatted}.",
                data={"formatted": formatted, "timezone_iana": target_tz},
            )

        if tool_id == "os.volume.set":
            pct = int(args["percent"])
            readback = self._desktop.set_volume_percent(pct)
            verified = abs(readback - pct) <= 2
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED if verified else ActionOutcomeState.UNKNOWN,
                verified=verified,
                summary=(
                    f"Volume sistem diatur dan terverifikasi pada {readback}%."
                    if verified
                    else f"Permintaan volume {pct}% dikirim, tetapi readback melaporkan {readback}% (status unknown)."
                ),
                data={"requested_percent": pct, "verified_percent": readback},
            )

        if tool_id == "os.app.launch":
            app_id = str(args["app_id"])
            try:
                ok = self._desktop.launch_allowlisted_app(app_id)
            except PermissionError as exc:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=str(exc),
                    error_code=ErrorCode.DENIED,
                )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED if ok else ActionOutcomeState.FAILED,
                verified=ok,
                summary=f"Aplikasi terizinkan '{app_id}' berhasil dijalankan." if ok else f"Gagal membuka '{app_id}'.",
                data={"app_id": app_id},
            )

        if tool_id == "memory.create":
            mem = self._memory.create_memory(
                kind=str(args.get("kind", "fact")),  # type: ignore[arg-type]
                content=str(args["content"]),
                sensitivity=str(args.get("sensitivity", "normal")),  # type: ignore[arg-type]
                correlation_id=correlation_id,
            )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Memori baru tersimpan (ID: {mem.id[:8]}).",
                data={"memory_id": mem.id},
            )

        if tool_id == "reminder.create":
            due_dt = datetime.fromisoformat(str(args["due_at_utc"]))
            rem = self._reminders.create_reminder(
                title=str(args["title"]),
                due_at_utc=due_dt,
                timezone_iana=str(args.get("timezone_iana") or tz_iana),
                correlation_id=correlation_id,
            )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Pengingat '{rem.title}' dijadwalkan ({rem.timezone_iana}).",
                data={"reminder_id": rem.id, "due_at_utc": rem.due_at_utc.isoformat()},
            )

        return StepExecutionRecord(
            tool_id=tool_id,
            tool_version=tool_version,
            state=ActionOutcomeState.FAILED,
            verified=False,
            summary=f"Adapter eksekusi untuk tool '{tool_id}' tidak tersedia.",
            error_code=ErrorCode.UNSUPPORTED,
        )

    def execute_approved_file_move(
        self,
        *,
        approval_id: str,
        root_path: str,
        source_relative_path: str,
        target_relative_path: str,
        correlation_id: str,
    ) -> StepExecutionRecord:
        """Execute an R2 handle-pinned file rename/move strictly AFTER approved state & anti-overwrite check (T04)."""
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT state, consumed_at FROM approval WHERE id = ?", (approval_id,)
            ).fetchone()
        if row is None or str(row["state"]) != "approved":
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary="Eksekusi fs.file.move ditolak: persetujuan R2 belum disetujui.",
                error_code=ErrorCode.DENIED,
            )

        try:
            src_resolved = Path(self._fs.resolve_within_root(root_path, source_relative_path))
            dst_resolved = Path(self._fs.resolve_within_root(root_path, target_relative_path))
        except PermissionError as exc:
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=str(exc),
                error_code=ErrorCode.DENIED,
            )

        if not src_resolved.is_file():
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=f"File sumber tidak ditemukan: '{source_relative_path}'.",
                error_code=ErrorCode.NOT_FOUND,
            )
        if dst_resolved.exists():
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary="Penimpaan file tujuan dilarang oleh kebijakan keamanan T04.",
                error_code=ErrorCode.DENIED,
            )

        dst_resolved.parent.mkdir(parents=True, exist_ok=True)
        src_resolved.rename(dst_resolved)
        verified = dst_resolved.is_file() and not src_resolved.exists()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'fs.file.moved', ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    "completed" if verified else "unknown",
                    json.dumps({"approval_id": approval_id, "verified": verified}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return StepExecutionRecord(
            tool_id="fs.file.move",
            tool_version=1,
            state=ActionOutcomeState.COMPLETED if verified else ActionOutcomeState.UNKNOWN,
            verified=verified,
            summary=f"File berhasil dipindahkan ke '{target_relative_path}' dan terverifikasi."
            if verified
            else "Status pemindahan tidak pasti (unknown).",
        )
