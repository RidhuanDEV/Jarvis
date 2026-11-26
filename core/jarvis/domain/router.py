"""Deterministic-First Multilingual Router (ID/EN), Locale/IANA Normalizer & Bounded LLM Proposal Parser (B06)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from jarvis.domain.ai_models import strip_thinking_blocks
from jarvis.domain.models import ToolProposal, ToolStepProposal

# R3 hard-ban phrasing triggers (routed explicitly to R3 tool_id so PolicyEngine records deterministic DENIED)
_R3_INTENT_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\b(?:powershell|cmd\.exe|bash|terminal|jalankan\s+shell|run\s+shell)\b", re.I), "os.shell.exec"),
    (re.compile(r"\b(?:hapus\s+permanen|shred\s+file|permanent\s+delete)\b", re.I), "fs.delete_permanent"),
    (re.compile(r"\b(?:transfer\s+(?:uang|dana)|bayar\s+otomatis|execute\s+payment)\b", re.I), "payment.transfer"),
    (re.compile(r"\b(?:kirim\s+email|send\s+email|hapus\s+email)\b", re.I), "email.send"),
    (re.compile(r"\b(?:buka\s+kunci\s+pintu|unlock\s+door|matikan\s+alarm|disable\s+alarm)\b", re.I), "iot.lock"),
)

_TIME_RE = re.compile(
    r"^(?:sekarang\s+)?(?:jam\s+berapa|pukul\s+berapa|what\s+time\s+is\s+it|current\s+time)\??$",
    re.I,
)
_VOLUME_SET_RE = re.compile(
    r"(?:atur|setel|ubah|set)\s+volume(?:\s+(?:ke|menjadi|to))?\s+(\d{1,3})\s*%?",
    re.I,
)
_VOLUME_MUTE_RE = re.compile(r"^(?:bisukan\s+(?:suara|audio)|mute\s+(?:audio|volume))$", re.I)
_VOLUME_AMBIGUOUS_RE = re.compile(r"^(?:atur|ubah|set)\s+volume\s*$", re.I)

_APP_LAUNCH_RE = re.compile(r"^(?:buka|open|launch)\s+(?:aplikasi\s+)?([a-z0-9 _.-]{2,40})$", re.I)

_MEMORY_CREATE_RE = re.compile(
    r"^(?:ingat(?:\s+bahwa)?|catat\s+memori|remember(?:\s+that)?)\s*[:,-]?\s+(.{3,500})$",
    re.I,
)

_REMINDER_RELATIVE_ID_RE = re.compile(
    r"^(?:ingatkan(?:\s+saya)?|buat\s+pengingat)\s+(?:dalam\s+)?(\d{1,4})\s+(menit|jam|detik)\s+(?:lagi\s+)?(?:untuk\s+)?(.{2,200})$",
    re.I,
)
_REMINDER_RELATIVE_EN_RE = re.compile(
    r"^remind\s+me\s+in\s+(\d{1,4})\s+(minutes?|hours?|seconds?)\s+(?:to\s+)?(.{2,200})$",
    re.I,
)
_REMINDER_AMBIGUOUS_RE = re.compile(r"^(?:ingatkan(?:\s+saya)?|remind\s+me)\s*$", re.I)

_FILE_MOVE_RE = re.compile(
    r"^(?:pindahkan|ubah\s+nama|rename|move)\s+file\s+([^\s]+)\s+(?:ke|menjadi|to)\s+([^\s]+)$",
    re.I,
)

_APP_ALIASES: dict[str, str] = {
    "kalkulator": "calculator",
    "calculator": "calculator",
    "calc": "calculator",
    "notepad": "notepad",
    "catatan": "notepad",
    "paint": "paint",
}


@dataclass(frozen=True)
class RouteMatch:
    matched_deterministic: bool
    needs_clarification: bool
    clarification_prompt: str | None
    proposal: ToolProposal | None
    intent_label: str


def normalize_utterance(text: str) -> str:
    """Trim whitespace and collapse repeated spaces while preserving casing inside payload text."""
    return re.sub(r"\s+", " ", text.strip())


def resolve_user_timezone(timezone_iana: str) -> ZoneInfo:
    """Resolve explicit IANA timezone with safe UTC fallback (never hardcoded WIB)."""
    try:
        return ZoneInfo(timezone_iana)
    except Exception:
        return ZoneInfo("UTC")


class DeterministicRouter:
    """Zero-LLM deterministic grammar router supporting Bahasa Indonesia & English (FR-COR-01..07)."""

    def route(
        self,
        utterance: str,
        *,
        now_utc: datetime,
        timezone_iana: str,
        primary_language: str = "id-ID",
    ) -> RouteMatch:
        text = normalize_utterance(utterance)
        is_en = primary_language.lower().startswith("en")
        if not text:
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=True,
                clarification_prompt=(
                    "Please enter a command or question."
                    if is_en
                    else "Mohon masukkan perintah atau pertanyaan Anda."
                ),
                proposal=None,
                intent_label="empty",
            )

        # 1. Catch R3 hard-prohibited requests deterministically
        for pattern, r3_tool_id in _R3_INTENT_PATTERNS:
            if pattern.search(text):
                return RouteMatch(
                    matched_deterministic=True,
                    needs_clarification=False,
                    clarification_prompt=None,
                    proposal=ToolProposal(
                        steps=(ToolStepProposal(tool_id=r3_tool_id, version=1, args={"raw": text}),)
                    ),
                    intent_label="prohibited_r3",
                )

        # 2. Time query (R0)
        if _TIME_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(
                        ToolStepProposal(
                            tool_id="system.time.get",
                            version=1,
                            args={"timezone_iana": timezone_iana},
                        ),
                    )
                ),
                intent_label="system.time",
            )

        # 3. Volume mute or set (R1) + ambiguity check (BR-02)
        if _VOLUME_AMBIGUOUS_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=True,
                clarification_prompt=(
                    "What volume percentage (0-100) should I set?"
                    if is_en
                    else "Ke angka persen berapa (0–100) volume harus diatur?"
                ),
                proposal=None,
                intent_label="os.volume.clarify",
            )
        if _VOLUME_MUTE_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="os.volume.set", version=1, args={"percent": 0}),)
                ),
                intent_label="os.volume.mute",
            )
        vol_match = _VOLUME_SET_RE.search(text)
        if vol_match:
            pct = int(vol_match.group(1))
            if pct > 100:
                return RouteMatch(
                    matched_deterministic=True,
                    needs_clarification=True,
                    clarification_prompt=(
                        f"Volume {pct}% is out of range. Please choose 0 to 100."
                        if is_en
                        else f"Volume {pct}% di luar rentang. Pilih nilai antara 0 hingga 100."
                    ),
                    proposal=None,
                    intent_label="os.volume.out_of_range",
                )
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="os.volume.set", version=1, args={"percent": pct}),)
                ),
                intent_label="os.volume.set",
            )

        # 4. Explicit Memory Creation (R1, BR-14)
        mem_match = _MEMORY_CREATE_RE.match(text)
        if mem_match:
            content = mem_match.group(1).strip()
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(
                        ToolStepProposal(
                            tool_id="memory.create",
                            version=1,
                            args={"kind": "fact", "content": content, "sensitivity": "normal"},
                        ),
                    )
                ),
                intent_label="memory.create",
            )

        # 5. Relative Reminders (ID & EN, stored in UTC + active IANA timezone, BR-09)
        if _REMINDER_AMBIGUOUS_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=True,
                clarification_prompt=(
                    "When and what should I remind you about?"
                    if is_en
                    else "Kapan dan tentang apa pengingat yang ingin Anda buat?"
                ),
                proposal=None,
                intent_label="reminder.clarify",
            )
        rem_id = _REMINDER_RELATIVE_ID_RE.match(text)
        rem_en = _REMINDER_RELATIVE_EN_RE.match(text)
        rem_match = rem_id or rem_en
        if rem_match:
            amount = int(rem_match.group(1))
            unit = rem_match.group(2).lower()
            title = rem_match.group(3).strip()
            if unit.startswith(("detik", "second")):
                delta = timedelta(seconds=amount)
            elif unit.startswith(("jam", "hour")):
                delta = timedelta(hours=amount)
            else:
                delta = timedelta(minutes=amount)
            due_utc = (now_utc + delta).isoformat()
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(
                        ToolStepProposal(
                            tool_id="reminder.create",
                            version=1,
                            args={
                                "title": title,
                                "due_at_utc": due_utc,
                                "timezone_iana": timezone_iana,
                            },
                        ),
                    )
                ),
                intent_label="reminder.create",
            )

        # 6. Safe File Rename/Move (R2 -> always requires trusted UI approval!)
        mv_match = _FILE_MOVE_RE.match(text)
        if mv_match:
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(
                        ToolStepProposal(
                            tool_id="fs.file.move",
                            version=1,
                            args={
                                "source_relative_path": mv_match.group(1),
                                "target_relative_path": mv_match.group(2),
                            },
                        ),
                    )
                ),
                intent_label="fs.file.move",
            )

        # 7. Allowlisted App Launch (R1)
        app_match = _APP_LAUNCH_RE.match(text)
        if app_match:
            raw_app = app_match.group(1).strip().lower()
            app_id = _APP_ALIASES.get(raw_app, raw_app)
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="os.app.launch", version=1, args={"app_id": app_id}),)
                ),
                intent_label="os.app.launch",
            )

        # Otherwise escalate to Bounded LLM Planner (or Direct Mode polite response if no LLM active)
        return RouteMatch(
            matched_deterministic=False,
            needs_clarification=False,
            clarification_prompt=None,
            proposal=None,
            intent_label="llm_candidate",
        )


def build_static_tool_catalog_prompt() -> str:
    """Concise static Tool Catalog prefix for KV cache reuse (DEC-027, 06-AI-VOICE-DESIGN §4)."""
    return (
        "You are J.A.R.V.I.S. planner. Output ONLY strict JSON matching "
        '{"steps":[{"tool_id":"...","version":1,"args":{...}}]} (1..5 steps, no extra keys).\n'
        "Allowed tools:\n"
        '- system.time.get v1: args={"timezone_iana": string}\n'
        '- os.volume.set v1: args={"percent": int 0..100}\n'
        '- os.app.launch v1: args={"app_id": string}\n'
        '- memory.create v1: args={"kind":"fact|preference|instruction|note","content":string,"sensitivity":"normal|sensitive"}\n'
        '- reminder.create v1: args={"title":string,"due_at_utc":iso8601,"timezone_iana":string}\n'
        '- fs.file.move v1: args={"source_relative_path":string,"target_relative_path":string}\n'
        "NEVER propose shell execution, permanent deletion, credential extraction, payments, or email mutation."
    )


def parse_llm_tool_proposal(raw_output: str) -> tuple[ToolProposal | None, str | None]:
    """Strip <think>, extract JSON, and validate strictly against ToolProposal (extra='forbid')."""
    cleaned = strip_thinking_blocks(raw_output)
    # Handle optional fenced code block ```json ... ```
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    candidate_str = fence.group(1) if fence else cleaned
    try:
        parsed: Any = json.loads(candidate_str)
    except json.JSONDecodeError as exc:
        return (None, f"LLM output is not valid JSON: {exc.msg}")
    try:
        proposal = ToolProposal.model_validate(parsed)
        return (proposal, None)
    except ValidationError as exc:
        return (None, f"LLM proposal violated strict ToolProposal schema: {exc.error_count()} errors")
