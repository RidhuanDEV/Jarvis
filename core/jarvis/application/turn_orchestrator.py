"""Deterministic-First Turn Orchestrator, SSE Streaming LLM Planner & Verified OS/RAG/Life/Screen Tool Executor (B06, B07)."""

from __future__ import annotations

import collections
import json
import re
import threading
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from jarvis.application.ai_registry_service import AiRegistryService
from jarvis.application.approval_service import ApprovalService
from jarvis.application.config_service import ConfigService
from jarvis.application.context_service import ContextAssemblerService
from jarvis.application.file_index_service import FileIndexService
from jarvis.application.knowledge_service import KnowledgeRagService
from jarvis.application.memory_service import MemoryVaultService
from jarvis.application.personal_life_service import PersonalLifeError, PersonalLifeService
from jarvis.application.reminder_service import ReminderSchedulerService
from jarvis.application.screen_service import ScreenAwarenessError, ScreenAwarenessService
from jarvis.domain.ai_models import ChatMessage, LlmCompletionRequest
from jarvis.domain.app_catalog import AppEntityResolver, is_prohibited_app_query
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
from jarvis.domain.ports import (
    ApplicationCatalogPort,
    ClockPort,
    DesktopAutomationPort,
    FilesystemSafetyPort,
)
from jarvis.domain.router import (
    DeterministicRouter,
    build_static_tool_catalog_prompt,
    parse_llm_assistant_or_tool,
    resolve_user_timezone,
)
from jarvis.domain.tool_schemas import validate_tool_step_args
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus

_STREAM_SENTENCE_BOUNDARY_RE = re.compile(r"([.!?](?:\s+|$)|\n+)")
_ALIAS_CORRECTION_RE = re.compile(
    r"^(?:(?:kalau\s+)?([a-z0-9 _.-]{2,32})\s+maksud\s+saya\s+(?:aplikasi\s+|browser\s+)?(.{2,64})"
    r"|alias\s+([a-z0-9 _.-]{2,32})\s+(?:adalah|=|ke)\s+(.{2,64}))[.!]*$",
    re.IGNORECASE,
)
MAX_LLM_SCHEMA_REPAIRS = 2


@runtime_checkable
class _StreamingLlmAdapter(Protocol):
    def stream_complete(self, request: LlmCompletionRequest) -> AsyncIterator[str]: ...


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
    """Executes deterministic-first turns (0 LLM calls), streaming LLM conversations, and verified tools."""

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
        knowledge_service: KnowledgeRagService | None = None,
        life_service: PersonalLifeService | None = None,
        screen_service: ScreenAwarenessService | None = None,
        app_catalog: ApplicationCatalogPort | None = None,
        file_index_service: FileIndexService | None = None,
        context_service: ContextAssemblerService | None = None,
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
        self._knowledge = knowledge_service
        self._life = life_service
        self._screen = screen_service
        self._app_catalog = app_catalog
        self._app_resolver = AppEntityResolver()
        self._file_index = file_index_service
        self._context = context_service
        self._router = DeterministicRouter()
        self._history_lock = threading.RLock()
        self._session_history: dict[str, collections.deque[ChatMessage]] = {}

    def clear_session_history(self, session_id: str | None = None) -> None:
        """Clear volatile in-RAM conversation memory (e.g. on OS lock or session reset)."""
        if self._context is not None:
            self._context.clear_session_history(session_id)
        with self._history_lock:
            if session_id is None:
                self._session_history.clear()
            else:
                self._session_history.pop(session_id, None)

    def _get_history_snapshot(self, session_id: str) -> tuple[ChatMessage, ...]:
        if self._context is not None:
            return self._context.load_history(session_id)
        with self._history_lock:
            buf = self._session_history.get(session_id)
            return tuple(buf) if buf else ()

    def _record_exchange(
        self, session: SessionContext, user_text: str, assistant_text: str
    ) -> None:
        if self._context is not None:
            self._context.record_exchange(
                session.session_id,
                user_text,
                assistant_text,
                channel=session.channel,
                actor_ref=session.actor_ref,
            )
            return
        with self._history_lock:
            buf = self._session_history.setdefault(session.session_id, collections.deque(maxlen=12))
            buf.append(ChatMessage(role="user", content=user_text))
            buf.append(ChatMessage(role="assistant", content=assistant_text))

    @staticmethod
    def _format_live_local_clock(now_utc: datetime, configured_tz_iana: str) -> str:
        """Format accurate local date/time portably (explicit user IANA TZ or OS local TZ, zero hardcoded zones)."""
        if configured_tz_iana and configured_tz_iana.upper() != "UTC":
            tz = resolve_user_timezone(configured_tz_iana)
            local_dt = now_utc.astimezone(tz)
            tz_label = configured_tz_iana
        else:
            local_dt = now_utc.astimezone()
            tz_label = local_dt.tzname() or "Local"
        days_id = ("Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu")
        months_id = (
            "Januari",
            "Februari",
            "Maret",
            "April",
            "Mei",
            "Juni",
            "Juli",
            "Agustus",
            "September",
            "Oktober",
            "November",
            "Desember",
        )
        day_name = days_id[local_dt.weekday()]
        month_name = months_id[local_dt.month - 1]
        return f"{day_name}, {local_dt.day} {month_name} {local_dt.year}, pukul {local_dt.strftime('%H:%M')} ({tz_label})"

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
        return await self.submit_turn_streaming(
            utterance,
            session=session,
            correlation_id=correlation_id,
            request_id=request_id,
            on_sentence=None,
        )

    async def submit_turn_streaming(
        self,
        utterance: str,
        *,
        session: SessionContext,
        correlation_id: str,
        request_id: str | None = None,
        on_sentence: Callable[[str], None] | None = None,
    ) -> TurnResult:
        """Execute a turn, streaming completed natural-language sentences immediately to on_sentence for low-TTFA TTS."""
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

        # 0. Instant non-parametric user alias learning ('Chrome maksud saya Google Chrome', B13)
        alias_m = _ALIAS_CORRECTION_RE.match(utterance.strip())
        if alias_m and not session.is_os_locked and not session.untrusted_origin:
            raw_alias = (alias_m.group(1) or alias_m.group(3) or "").strip()
            raw_target = (alias_m.group(2) or alias_m.group(4) or "").strip()
            if is_prohibited_app_query(raw_target):
                denied_msg = f"Target alias '{raw_target}' termasuk kategori Tier-3 terlarang."
                if on_sentence is not None:
                    on_sentence(denied_msg)
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind="alias.learn.denied",
                    reply=denied_msg,
                    llm_called=False,
                    error_code=ErrorCode.DENIED,
                )
            self._memory.upsert_user_alias(
                raw_alias, raw_target, correlation_id=correlation_id, actor=session.actor_ref
            )
            learned_reply = f"Alias disimpan: '{raw_alias}' sekarang merujuk ke '{raw_target}'."
            self._record_exchange(session, utterance, learned_reply)
            if on_sentence is not None:
                on_sentence(learned_reply)
            return TurnResult(
                request_id=req_id,
                state=ActionOutcomeState.COMPLETED,
                route_kind="alias.learn",
                reply=learned_reply,
                llm_called=False,
            )

        assembled_ctx = (
            self._context.assemble_turn_context(session.session_id, utterance)
            if self._context is not None
            else None
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
            clarification = route.clarification_prompt or "Mohon perjelas perintah Anda."
            if on_sentence is not None:
                on_sentence(clarification)
            return TurnResult(
                request_id=req_id,
                state=ActionOutcomeState.COMPLETED,
                route_kind=route.intent_label,
                reply=clarification,
                llm_called=False,
            )

        proposal: ToolProposal | None = route.proposal
        llm_called = False
        route_kind = route.intent_label
        streamed_any_sentence = False

        # 2. Bounded / Streaming Local LLM Planner with ContextAssembler & <= 2 Schema Repairs (B13, B14)
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
                if on_sentence is not None:
                    on_sentence(reply)
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.COMPLETED,
                    route_kind="direct_mode_no_match",
                    reply=reply,
                    llm_called=False,
                )

            llm_called = True
            route_kind = "bounded_llm_planner"
            live_clock_ctx = self._format_live_local_clock(now, tz_iana)
            sys_prompt = build_static_tool_catalog_prompt(live_clock_ctx)
            if assembled_ctx is not None:
                extra_blocks = [assembled_ctx.persona_prompt_block]
                if assembled_ctx.memory_prompt_block:
                    extra_blocks.append(assembled_ctx.memory_prompt_block)
                sys_prompt = sys_prompt + "\n\n" + "\n".join(extra_blocks)
            history_msgs = (
                assembled_ctx.history_messages
                if assembled_ctx is not None
                else self._get_history_snapshot(session.session_id)
            )
            messages_list: list[ChatMessage] = [
                ChatMessage(role="system", content=sys_prompt),
                *history_msgs,
                ChatMessage(role="user", content=utterance),
            ]

            parsed_prop: ToolProposal | None = None
            conv_reply: str | None = None
            last_schema_err: str | None = None

            for attempt in range(MAX_LLM_SCHEMA_REPAIRS + 1):
                llm_req = LlmCompletionRequest(
                    model_id=llm_model_id,
                    messages=tuple(messages_list),
                    max_tokens=512,
                    temperature=0.3 if attempt == 0 else 0.0,
                    enforce_non_thinking=True,
                    expect_json=(attempt > 0),
                    timeout_seconds=60.0,
                )
                raw_content = ""
                try:
                    if attempt == 0 and on_sentence is not None and isinstance(adapter, _StreamingLlmAdapter):
                        full_chunks: list[str] = []
                        sentence_buf = ""
                        stream_mode: str = "undecided"
                        async for tok in adapter.stream_complete(llm_req):
                            full_chunks.append(tok)
                            sentence_buf += tok
                            if stream_mode == "undecided":
                                stripped_lead = sentence_buf.lstrip()
                                if not stripped_lead:
                                    continue
                                if stripped_lead.startswith("{") or stripped_lead.startswith("`"):
                                    stream_mode = "json"
                                else:
                                    stream_mode = "prose"
                            if stream_mode == "prose":
                                while True:
                                    match = _STREAM_SENTENCE_BOUNDARY_RE.search(sentence_buf)
                                    if match is None:
                                        break
                                    cut = match.end()
                                    ready_sentence = sentence_buf[:cut].strip()
                                    sentence_buf = sentence_buf[cut:]
                                    if ready_sentence:
                                        on_sentence(ready_sentence)
                                        streamed_any_sentence = True
                        if stream_mode == "prose" and sentence_buf.strip():
                            on_sentence(sentence_buf.strip())
                            streamed_any_sentence = True
                        raw_content = "".join(full_chunks)
                    else:
                        resp = await adapter.complete(llm_req)
                        raw_content = resp.content
                except Exception as exc:
                    err_reply = f"Runtime LLM gagal merespons ({type(exc).__name__}); Direct Mode tetap tersedia."
                    if on_sentence is not None and not streamed_any_sentence:
                        on_sentence(err_reply)
                    return TurnResult(
                        request_id=req_id,
                        state=ActionOutcomeState.FAILED,
                        route_kind=route_kind,
                        reply=err_reply,
                        llm_called=True,
                        error_code=ErrorCode.RUNTIME_UNAVAILABLE,
                    )

                parsed_prop, conv_reply, parse_err = parse_llm_assistant_or_tool(raw_content)
                if conv_reply is not None:
                    self._record_exchange(session, utterance, conv_reply)
                    if on_sentence is not None and not streamed_any_sentence:
                        on_sentence(conv_reply)
                    self._bus.publish(
                        event_type="request.state_changed",
                        correlation_id=correlation_id,
                        request_id=req_id,
                        payload={"state": "Success"},
                    )
                    return TurnResult(
                        request_id=req_id,
                        state=ActionOutcomeState.COMPLETED,
                        route_kind="local_llm_reply",
                        reply=conv_reply,
                        llm_called=True,
                    )
                if parsed_prop is not None:
                    # Validate every step's strict tool argument schema before exiting repair loop!
                    step_arg_err: str | None = None
                    for st in parsed_prop.steps:
                        _, s_err = validate_tool_step_args(st.tool_id, st.args)
                        if s_err is not None:
                            step_arg_err = s_err
                            break
                    if step_arg_err is None:
                        break
                    last_schema_err = step_arg_err
                    parsed_prop = None
                else:
                    last_schema_err = parse_err

                if attempt < MAX_LLM_SCHEMA_REPAIRS:
                    messages_list.append(ChatMessage(role="assistant", content=raw_content[:600]))
                    messages_list.append(
                        ChatMessage(
                            role="user",
                            content=(
                                f"Schema validation error: {last_schema_err}. "
                                'Return ONLY valid strict JSON: {"steps":[{"tool_id":"...","version":1,"args":{...}}]}'
                            ),
                        )
                    )

            if parsed_prop is None:
                err_msg = f"Proposal model ditolak karena tidak mematuhi skema ketat: {last_schema_err}"
                if on_sentence is not None and not streamed_any_sentence:
                    on_sentence(err_msg)
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind=route_kind,
                    reply=err_msg,
                    llm_called=True,
                    error_code=ErrorCode.INVALID_ARGS,
                )
            proposal = parsed_prop

        # 3. Validate proposal bounds & strict per-step argument schemas (zero KeyError 500s, B14!)
        bounds_err = self._policy.validate_proposal_bounds(proposal)
        if bounds_err is not None:
            if on_sentence is not None:
                on_sentence(bounds_err.reason)
            return TurnResult(
                request_id=req_id,
                state=ActionOutcomeState.FAILED,
                route_kind=route_kind,
                reply=bounds_err.reason,
                llm_called=llm_called,
                error_code=bounds_err.error_code,
            )

        # Propagate BR-15 untrusted taint across turns when LLM proposes actions after reading untrusted docs/screen
        effective_session = session
        if llm_called and assembled_ctx is not None and assembled_ctx.session_untrusted_taint:
            effective_session = session.model_copy(update={"untrusted_origin": True})

        grants = self._load_grants()
        step_results: list[StepExecutionRecord] = []
        any_completed = False
        any_failed_non_policy = False
        user_aliases = assembled_ctx.user_aliases if assembled_ctx is not None else self._memory.get_user_app_aliases()

        for step in proposal.steps:
            validated_args, arg_err = validate_tool_step_args(step.tool_id, step.args)
            if arg_err is not None or validated_args is None:
                if on_sentence is not None:
                    on_sentence(arg_err or "Argumen tool tidak valid.")
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.FAILED,
                    route_kind=route_kind,
                    reply=arg_err or "Argumen tool tidak valid.",
                    llm_called=llm_called,
                    steps=tuple(step_results),
                    error_code=ErrorCode.INVALID_ARGS,
                )

            decision = self._policy.evaluate_step(
                tool_id=step.tool_id,
                tool_version=step.version,
                args=validated_args,
                session=effective_session,
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
                    session=effective_session,
                    summary=f"Konfirmasi aksi R2: {step.tool_id} ({json.dumps(validated_args)})",
                )
                wait_reply = (
                    f"Aksi '{step.tool_id}' berisiko R2 dan menunggu persetujuan lokal pada dialog native."
                )
                if on_sentence is not None:
                    on_sentence(wait_reply)
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.AWAITING_APPROVAL,
                    route_kind=route_kind,
                    reply=wait_reply,
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
                if on_sentence is not None:
                    on_sentence(decision.reason)
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
            outcome = await self._execute_verified_step(
                step.tool_id,
                step.version,
                validated_args,
                tz_iana=tz_iana,
                session=effective_session,
                correlation_id=correlation_id,
                user_aliases=user_aliases,
            )
            step_results.append(outcome)
            if outcome.state == ActionOutcomeState.COMPLETED:
                any_completed = True
                if step.tool_id in ("knowledge.query", "screen.analyze") and self._context is not None:
                    self._context.mark_session_untrusted_taint(session.session_id)
            else:
                # Never continue after DENIED; allow honest PARTIAL progress on independent multi-step NOT_FOUND (U-I01)
                if len(proposal.steps) > 1 and outcome.error_code == ErrorCode.NOT_FOUND:
                    any_failed_non_policy = True
                    continue
                if on_sentence is not None:
                    on_sentence(outcome.summary)
                return TurnResult(
                    request_id=req_id,
                    state=ActionOutcomeState.PARTIAL if any_completed else outcome.state,
                    route_kind=route_kind,
                    reply=" ".join(s.summary for s in step_results),
                    llm_called=llm_called,
                    steps=tuple(step_results),
                    error_code=outcome.error_code,
                )

        final_state = (
            ActionOutcomeState.PARTIAL
            if (any_failed_non_policy and any_completed)
            else (ActionOutcomeState.FAILED if any_failed_non_policy else ActionOutcomeState.COMPLETED)
        )
        self._bus.publish(
            event_type="request.state_changed",
            correlation_id=correlation_id,
            request_id=req_id,
            payload={"state": "Success" if final_state == ActionOutcomeState.COMPLETED else "Error"},
        )
        final_reply = " ".join(s.summary for s in step_results)
        self._record_exchange(session, utterance, final_reply)
        if on_sentence is not None:
            on_sentence(final_reply)
        return TurnResult(
            request_id=req_id,
            state=final_state,
            route_kind=route_kind,
            reply=final_reply,
            llm_called=llm_called,
            steps=tuple(step_results),
            error_code=ErrorCode.NOT_FOUND if final_state == ActionOutcomeState.FAILED else None,
        )

    async def execute_verified_step_for_workflow(
        self,
        tool_id: str,
        tool_version: int,
        args: dict[str, Any],
        *,
        session: SessionContext,
        correlation_id: str,
    ) -> StepExecutionRecord:
        """Public validated executor invoked by WorkflowEngineService for real tool steps (B15)."""
        validated_args, arg_err = validate_tool_step_args(tool_id, args)
        if arg_err is not None or validated_args is None:
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=arg_err or "Invalid workflow step arguments.",
                error_code=ErrorCode.INVALID_ARGS,
            )
        tz_iana = self._config.get_active().document.locale.timezone_iana
        return await self._execute_verified_step(
            tool_id,
            tool_version,
            validated_args,
            tz_iana=tz_iana,
            session=session,
            correlation_id=correlation_id,
            user_aliases=self._memory.get_user_app_aliases(),
        )

    async def _execute_verified_step(
        self,
        tool_id: str,
        tool_version: int,
        args: dict[str, Any],
        *,
        tz_iana: str,
        session: SessionContext,
        correlation_id: str,
        user_aliases: dict[str, str] | None = None,
    ) -> StepExecutionRecord:
        if tool_id == "system.time.get":
            target_tz = str(args.get("timezone_iana") or tz_iana)
            if target_tz.upper() == "UTC" and tz_iana.upper() == "UTC":
                local_now = self._clock.now_utc().astimezone()
                tz_label = local_now.tzname() or "Local"
            else:
                tz = resolve_user_timezone(target_tz)
                local_now = self._clock.now_utc().astimezone(tz)
                tz_label = target_tz
            formatted = local_now.strftime("%Y-%m-%d %H:%M:%S")
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Sekarang pukul {local_now.strftime('%H:%M')} ({tz_label}), tanggal {local_now.strftime('%Y-%m-%d')}.",
                data={"formatted": formatted, "timezone_iana": tz_label},
            )

        if tool_id == "os.volume.set":
            pct = int(args["percent"])
            try:
                readback = self._desktop.set_volume_percent(pct)
            except (RuntimeError, OSError, ValueError) as exc:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=f"Kontrol volume perangkat tidak tersedia: {exc}",
                    error_code=ErrorCode.RUNTIME_UNAVAILABLE,
                )
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
            raw_app_query = str(args["app_id"])
            if self._app_catalog is not None:
                resolution = self._app_resolver.resolve(
                    raw_app_query,
                    self._app_catalog.list_apps(),
                    user_aliases=user_aliases,
                )
                if resolution.status == "prohibited":
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.FAILED,
                        verified=False,
                        summary=resolution.reason,
                        error_code=ErrorCode.DENIED,
                        data={"status": "prohibited", "query": raw_app_query},
                    )
                if resolution.status == "ambiguous":
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.COMPLETED,
                        verified=False,
                        summary=resolution.reason,
                        data={
                            "status": "ambiguous",
                            "candidates": [
                                {"app_id": c.app_id, "display_name": c.display_name}
                                for c in resolution.candidates
                            ],
                        },
                    )
                if resolution.status == "not_found" or resolution.matched_entry is None:
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.FAILED,
                        verified=False,
                        summary=resolution.reason,
                        error_code=ErrorCode.NOT_FOUND,
                        data={"status": "not_found", "query": raw_app_query},
                    )
                entry = resolution.matched_entry
                try:
                    receipt = self._desktop.launch_catalog_entry(entry)
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
                    state=ActionOutcomeState.COMPLETED if receipt.accepted else ActionOutcomeState.FAILED,
                    verified=receipt.accepted,
                    summary=(
                        f"Aplikasi '{entry.display_name}' berhasil dibuka."
                        if receipt.accepted
                        else f"Gagal membuka '{entry.display_name}': {receipt.detail}"
                    ),
                    error_code=None if receipt.accepted else ErrorCode.RUNTIME_UNAVAILABLE,
                    data={
                        "app_id": entry.app_id,
                        "display_name": entry.display_name,
                        "activation_kind": entry.activation_kind,
                        "pid": receipt.pid,
                        "verification_kind": receipt.verification_kind,
                    },
                )

            try:
                ok = self._desktop.launch_allowlisted_app(raw_app_query)
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
                summary=f"Aplikasi terizinkan '{raw_app_query}' berhasil dijalankan." if ok else f"Gagal membuka '{raw_app_query}'.",
                data={"app_id": raw_app_query},
            )

        if tool_id == "fs.metadata.search":
            if self._file_index is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan indeks file lokal belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            query_str = str(args.get("query") or "")
            ext_filter = str(args["ext"]) if args.get("ext") else None
            limit_val = int(args.get("limit", 5))
            res = self._file_index.search_metadata(
                query_str,
                ext=ext_filter,
                limit=limit_val,
                session_id=session.session_id,
            )
            if res.active_roots_count == 0:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.COMPLETED,
                    verified=True,
                    summary="Belum ada folder lokal yang diizinkan untuk diindeks. Tambahkan folder opt-in terlebih dahulu.",
                    data={"count": 0, "hits": []},
                )
            if not res.hits:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.COMPLETED,
                    verified=True,
                    summary=f"Tidak ditemukan file yang cocok dengan '{query_str or 'terbaru'}' pada folder terizinkan.",
                    data={"count": 0, "hits": []},
                )
            lines = [
                f"{idx}. {h.display_name} ({h.relative_path})"
                + (" [tidak tersedia di disk]" if h.availability != "available" else "")
                for idx, h in enumerate(res.hits[:5], start=1)
            ]
            summary_text = (
                f"Ditemukan {len(res.hits)} file: "
                + "; ".join(lines)
                + ". Ucapkan 'buka nomor 1' untuk membuka dokumen."
            )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=summary_text,
                data={
                    "count": len(res.hits),
                    "elapsed_ms": res.elapsed_ms,
                    "hits": [
                        {
                            "index": i,
                            "file_id": h.file_id,
                            "root_id": h.root_id,
                            "display_name": h.display_name,
                            "relative_path": h.relative_path,
                            "ext": h.ext,
                            "availability": h.availability,
                            "score": h.score,
                        }
                        for i, h in enumerate(res.hits, start=1)
                    ],
                },
            )

        if tool_id == "fs.file.open":
            if self._file_index is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan indeks file lokal belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            target_hit = None
            if "result_index" in args and args["result_index"] is not None:
                idx = int(args["result_index"])
                target_hit = self._file_index.resolve_working_set_index(session.session_id, idx)
                if target_hit is None:
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.FAILED,
                        verified=False,
                        summary=f"Hasil pencarian file nomor {idx} tidak tersedia pada sesi ini. Cari file terlebih dahulu.",
                        error_code=ErrorCode.NOT_FOUND,
                    )
            else:
                fquery = str(args.get("file_query") or "").strip()
                search_res = self._file_index.search_metadata(
                    fquery, limit=5, session_id=session.session_id
                )
                live_hits = [h for h in search_res.hits if h.availability == "available"]
                if not live_hits:
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.FAILED,
                        verified=False,
                        summary=f"File '{fquery}' tidak ditemukan di folder terizinkan.",
                        error_code=ErrorCode.NOT_FOUND,
                    )
                if (
                    len(live_hits) >= 2
                    and live_hits[0].score < 0.99
                    and (live_hits[0].score - live_hits[1].score) < 0.08
                ):
                    opts = "; ".join(
                        f"{i}. {h.display_name} ({h.relative_path})"
                        for i, h in enumerate(live_hits[:3], start=1)
                    )
                    return StepExecutionRecord(
                        tool_id=tool_id,
                        tool_version=tool_version,
                        state=ActionOutcomeState.COMPLETED,
                        verified=False,
                        summary=f"Ada beberapa file yang mirip: {opts}. Sebutkan 'buka nomor 1' atau nomor pilihan Anda.",
                        data={"status": "ambiguous", "count": len(live_hits)},
                    )
                target_hit = live_hits[0]

            open_receipt = self._file_index.open_file(target_hit)
            if open_receipt.verification_kind == "prohibited":
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=open_receipt.detail,
                    error_code=ErrorCode.DENIED,
                    data={"verification_kind": open_receipt.verification_kind},
                )
            if open_receipt.verification_kind == "not_found":
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=open_receipt.detail,
                    error_code=ErrorCode.NOT_FOUND,
                    data={"verification_kind": open_receipt.verification_kind},
                )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED if open_receipt.opened else ActionOutcomeState.FAILED,
                verified=open_receipt.opened,
                summary=(
                    f"Membuka file '{target_hit.display_name}' dengan aplikasi terdaftar."
                    if open_receipt.opened
                    else f"Tidak dapat membuka '{target_hit.display_name}': {open_receipt.detail}"
                ),
                error_code=None if open_receipt.opened else ErrorCode.RUNTIME_UNAVAILABLE,
                data={
                    "file_id": target_hit.file_id,
                    "display_name": target_hit.display_name,
                    "relative_path": target_hit.relative_path,
                    "verification_kind": open_receipt.verification_kind,
                },
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

        if tool_id == "life.task.create":
            if self._life is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan daftar tugas belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            try:
                task = self._life.create_task(
                    title=str(args["title"]), correlation_id=correlation_id
                )
            except PersonalLifeError as exc:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=str(exc),
                    error_code=exc.code,
                )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Tugas baru ditambahkan: {task.title}.",
                data={"task_id": task.id, "title": task.title},
            )

        if tool_id == "life.task.list":
            if self._life is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan daftar tugas belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            open_tasks = [t for t in self._life.list_tasks() if t.status in ("open", "in_progress")]
            if not open_tasks:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.COMPLETED,
                    verified=True,
                    summary="Saat ini belum ada tugas aktif yang tersimpan.",
                    data={"count": 0},
                )
            titles = ", ".join(t.title for t in open_tasks[:5])
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"Anda memiliki {len(open_tasks)} tugas aktif: {titles}.",
                data={"count": len(open_tasks), "titles": [t.title for t in open_tasks[:5]]},
            )

        if tool_id == "knowledge.query":
            if self._knowledge is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan basis pengetahuan dokumen belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            active_prof = self._ai.get_active_profile().profile
            prov_id = active_prof.role_bindings.get("llm_provider")
            mod_id = active_prof.role_bindings.get("llm_model")
            adapter = self._ai.get_adapter(prov_id) if prov_id else None
            rag_res = await self._knowledge.answer_from_knowledge(
                str(args["query"]),
                top_k=5,
                llm_adapter=adapter if active_prof.mode != AiProfileMode.DIRECT else None,
                model_id=mod_id,
            )
            cite_suffix = ""
            if rag_res.citations:
                files = ", ".join(dict.fromkeys(c.relative_path for c in rag_res.citations[:3]))
                cite_suffix = f" (Sumber: {files})"
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=f"{rag_res.answer}{cite_suffix}",
                data={
                    "sufficient_evidence": rag_res.sufficient_evidence,
                    "citation_count": len(rag_res.citations),
                    "tools_disabled": rag_res.tools_disabled,
                },
            )

        if tool_id == "screen.analyze":
            if self._screen is None:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary="Layanan pembacaan layar aman belum terhubung.",
                    error_code=ErrorCode.UNSUPPORTED,
                )
            try:
                scr = self._screen.analyze_window(
                    str(args.get("window_selector", "active")),
                    session=session,
                    explicit_user_request=True,
                    correlation_id=correlation_id,
                )
            except ScreenAwarenessError as exc:
                return StepExecutionRecord(
                    tool_id=tool_id,
                    tool_version=tool_version,
                    state=ActionOutcomeState.FAILED,
                    verified=False,
                    summary=str(exc),
                    error_code=exc.code,
                )
            return StepExecutionRecord(
                tool_id=tool_id,
                tool_version=tool_version,
                state=ActionOutcomeState.COMPLETED,
                verified=True,
                summary=scr.redacted_text,
                data={
                    "window_title": scr.window_title,
                    "process_name": scr.process_name,
                    "redactions_applied": scr.redactions_applied,
                },
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
        g4_file_move_enabled: bool = False,
    ) -> StepExecutionRecord:
        """Execute an R2 handle-pinned file rename/move strictly AFTER approved state & anti-overwrite check (T04).

        Per Gate G0 Owner Decision A2, fs.file.move execution is disabled during Stage G1 Safety Kernel
        until Stage G4 delivers scoped GUI diff + handle-pinned same-scope re-enablement.
        """
        if not g4_file_move_enabled:
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=(
                    "Eksekusi fs.file.move dinonaktifkan sementara selama Stage G1 Safety Kernel "
                    "(dijadwalkan aktif kembali di G4 dengan GUI diff + no-overwrite + same-scope)."
                ),
                error_code=ErrorCode.UNSUPPORTED,
            )
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

        if not src_resolved.exists():
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=f"Berkas sumber '{source_relative_path}' tidak ditemukan.",
                error_code=ErrorCode.NOT_FOUND,
            )
        if dst_resolved.exists():
            return StepExecutionRecord(
                tool_id="fs.file.move",
                tool_version=1,
                state=ActionOutcomeState.FAILED,
                verified=False,
                summary=f"Berkas tujuan '{target_relative_path}' sudah ada; penimpaan diblokir.",
                error_code=ErrorCode.DENIED,
            )

        dst_resolved.parent.mkdir(parents=True, exist_ok=True)
        src_resolved.rename(dst_resolved)
        verified = dst_resolved.exists() and not src_resolved.exists()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'fs.file.move.executed', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"approval_id": approval_id, "verified": verified}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return StepExecutionRecord(
            tool_id="fs.file.move",
            tool_version=1,
            state=ActionOutcomeState.COMPLETED if verified else ActionOutcomeState.UNKNOWN,
            verified=verified,
            summary=f"Berkas '{source_relative_path}' berhasil dipindahkan ke '{target_relative_path}'.",
            data={"source": source_relative_path, "target": target_relative_path},
        )
