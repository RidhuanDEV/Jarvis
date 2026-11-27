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
    (re.compile(r"\b(?:powershell|pwsh|cmd\.exe|command\s+prompt|bash|terminal|jalankan\s+shell|run\s+shell|regedit|diskpart|mshta)\b", re.I), "os.shell.exec"),
    (re.compile(r"\b(?:hapus\s+permanen|hapus\s+file|hapus\s+folder|delete\s+file|shred\s+file|permanent\s+delete|recycle\s+bin|format\s+drive)\b", re.I), "fs.delete_permanent"),
    (re.compile(r"\b(?:transfer\s+(?:uang|dana)|bayar\s+otomatis|execute\s+payment)\b", re.I), "payment.transfer"),
    (re.compile(r"\b(?:kirim\s+email|send\s+email|hapus\s+email)\b", re.I), "email.send"),
    (re.compile(r"\b(?:buka\s+kunci\s+pintu|unlock\s+door|matikan\s+alarm|disable\s+alarm)\b", re.I), "iot.lock"),
)

# U-A02 Negation & educational meta-question guards: never execute actions on negations or "what is X?"
_NEGATION_PREFIX_RE = re.compile(
    r"^(?:jangan|tidak\s+usah|gak\s+usah|nggak\s+usah|tak\s+usah|tidak\s+perlu|batal(?:kan)?|stop\s+opening|don'?t|do\s+not|never)\b",
    re.I,
)
_META_QUESTION_RE = re.compile(
    r"^(?:apa\s+itu|apa\s+sih|apa\s+fungsi|apa\s+gunanya|jelaskan(?:\s+tentang)?|ceritakan\s+tentang|kenapa|mengapa|bagaimana\s+cara|what\s+is|what\s+does|explain|tell\s+me\s+about|why\s+is|how\s+does)\b",
    re.I,
)
_POLITE_PREFIX_RE = re.compile(
    r"^(?:(?:hey|hei|hai|halo|hi)\s+jarvis|jarvis|tolong|mohon|coba|bisa(?:\s+tolong)?|bantu(?:\s+saya)?|please|pls|can\s+you|could\s+you)\b[\s,:-]*",
    re.I,
)

_TIME_RE = re.compile(
    r"^(?:sekarang\s+)?(?:jam\s+berapa|jam\s+brp|pukul\s+berapa|sekarangnya\s+berapa|what\s+time\s+is\s+it|current\s+time)(?:\s+(?:sekarang|saat\s+ini|nih|ya|dong|now)){0,2}$",
    re.I,
)
_VOLUME_SET_RE = re.compile(
    r"^(?:atur|setel|ubah|set)\s+volume(?:\s+(?:ke|menjadi|to))?\s+(\d{1,3})\s*(?:%|persen|percent)?$",
    re.I,
)
_COMPOUND_MULTI_ACTION_RE = re.compile(
    r"(?:,\s*|;\s*|\s+(?:dan|lalu|kemudian|and|then)\s+)(?:atur|setel|ubah|set|buka|bukain|bukakan|jalankan|open|launch|buat|tambah(?:kan)?|catat|ingatkan|remind|cari|search|bisukan|mute)\b",
    re.I,
)
_VOLUME_MUTE_RE = re.compile(r"^(?:bisukan\s+(?:suara|audio)|mute\s+(?:audio|volume))$", re.I)
_VOLUME_AMBIGUOUS_RE = re.compile(r"^(?:atur|ubah|set)\s+volume\s*$", re.I)

_FILE_RECENT_RE = re.compile(
    r"^(?:(?:lihat|tampilkan|daftar|show|list)\s+)?(?:file|dokumen|berkas)\s+(?:terbaru|terakhir|recent)|^(?:recent\s+files|latest\s+files)$",
    re.I,
)
_FILE_SEARCH_RE = re.compile(
    r"^(?:cari|cariin|carikan|temukan|find|search|locate)\s+(?:file|berkas)(?:\s+(?:bernama|yang\s+bernama|tentang|dengan\s+nama|named|for))?\s+(.{1,120})$",
    re.I,
)
_FILE_OPEN_INDEX_RE = re.compile(
    r"^(?:buka|bukain|bukakan|open)\s+(?:(?:file|dokumen|berkas|hasil)\s+)?(?:(?:nomor|no\.?|urutan|number|result)\s+#?(\d{1,2})|yang\s+(pertama|kedua|ketiga|keempat|kelima|ke-?(\d{1,2}))|(?:file|dokumen|berkas)\s+tadi)$",
    re.I,
)
_FILE_OPEN_NAME_RE = re.compile(
    r"^(?:buka|bukain|bukakan|open)\s+(?:file|dokumen|berkas)\s+(.{1,160})$",
    re.I,
)

_APP_LAUNCH_RE = re.compile(
    r"^(?:buka|bukain|bukakan|jalankan|open|launch|start)\s+(?:aplikasi\s+|program\s+|app\s+)?(.{2,80})$",
    re.I,
)

_ORDINAL_WORD_MAP: dict[str, int] = {
    "pertama": 1,
    "kedua": 2,
    "ketiga": 3,
    "keempat": 4,
    "kelima": 5,
}
_EXT_TOKEN_RE = re.compile(r"(?:^|\s)\.?([a-z0-9]{2,5})\b", re.I)
_KNOWN_SEARCH_EXTENSIONS: frozenset[str] = frozenset(
    {"pdf", "docx", "doc", "xlsx", "xls", "pptx", "ppt", "txt", "md", "csv", "json", "png", "jpg", "jpeg", "mp3", "mp4", "zip"}
)

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

_TASK_CREATE_RE = re.compile(
    r"^(?:buat|tambah(?:kan)?|catat)\s+tugas(?:\s+baru)?\s*[:,-]?\s+(.{2,250})$"
    r"|^(?:create|add)\s+(?:a\s+)?task\s*[:,-]?\s+(.{2,250})$",
    re.I,
)

_TASK_LIST_RE = re.compile(
    r"^(?:apa\s+saja\s+tugas(?:\s+saya)?|daftar\s+tugas(?:\s+saya)?|lihat\s+tugas|list\s+(?:my\s+)?tasks|what\s+are\s+my\s+tasks)\??$",
    re.I,
)

_KNOWLEDGE_QUERY_RE = re.compile(
    r"^(?:cari(?:\s+di)?\s+dokumen|tanya\s+dokumen|cek\s+dokumen|search\s+(?:my\s+)?documents?(?:\s+for)?)\s*[:,-]?\s+(.{2,400})$",
    re.I,
)

_SCREEN_ANALYZE_RE = re.compile(
    r"^(?:baca\s+layar(?:\s+(?:ini|aktif|sekarang))?|apa\s+yang\s+ada\s+di\s+layar(?:\s+sekarang)?|lihat\s+layar\s+aktif|analyze\s+(?:my\s+|active\s+)?screen|what(?:'s|\s+is)\s+on\s+my\s+screen)\??$",
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


def strip_boundary_punctuation(text: str) -> str:
    """Strip punctuation strictly at utterance boundaries (preserves internal dots like report.pdf)."""
    cleaned = text.strip()
    cleaned = re.sub(r"^[\s.,!?;:]+", "", cleaned)
    cleaned = re.sub(r"[\s.,!?;:]+$", "", cleaned)
    return cleaned.strip()


def strip_polite_prefixes(text: str) -> str:
    """Strip repeated leading wake/politeness prefixes ('Hey Jarvis, tolong ...')."""
    current = text.strip()
    for _ in range(3):
        updated = _POLITE_PREFIX_RE.sub("", current, count=1).strip()
        if updated == current or not updated:
            break
        current = updated
    return current


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
        raw_text = normalize_utterance(utterance)
        is_en = primary_language.lower().startswith("en")
        if not raw_text:
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

        # Strip polite/wake prefixes & utterance-boundary punctuation (preserving internal dots!)
        cmd_text = strip_boundary_punctuation(strip_polite_prefixes(raw_text))
        if not cmd_text:
            cmd_text = strip_boundary_punctuation(raw_text)

        # 0. Negation & educational meta-question guard (U-A02): NEVER trigger tools on "jangan buka X" or "apa itu PowerShell?"
        if _NEGATION_PREFIX_RE.match(cmd_text) or _META_QUESTION_RE.match(cmd_text):
            return RouteMatch(
                matched_deterministic=False,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=None,
                intent_label="llm_candidate",
            )

        text = cmd_text

        # 1. Catch R3 hard-prohibited requests deterministically
        for pattern, r3_tool_id in _R3_INTENT_PATTERNS:
            if pattern.search(text):
                return RouteMatch(
                    matched_deterministic=True,
                    needs_clarification=False,
                    clarification_prompt=None,
                    proposal=ToolProposal(
                        steps=(ToolStepProposal(tool_id=r3_tool_id, version=1, args={"raw": raw_text}),)
                    ),
                    intent_label="prohibited_r3",
                )

        # 1b. Compound multi-action utterances escalate to the Multi-Step LLM Coordinator (B14, U-I01)
        if _COMPOUND_MULTI_ACTION_RE.search(text):
            return RouteMatch(
                matched_deterministic=False,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=None,
                intent_label="llm_candidate",
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
        vol_match = _VOLUME_SET_RE.match(text)
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

        # 6b. Layer-1 Fast Scoped File Metadata Search & Recent Files (B10, R0)
        if _FILE_RECENT_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="fs.metadata.search", version=1, args={"query": "", "recent": True}),)
                ),
                intent_label="fs.metadata.search",
            )

        file_search_match = _FILE_SEARCH_RE.match(text)
        if file_search_match:
            raw_query = strip_boundary_punctuation(file_search_match.group(1))
            detected_ext: str | None = None
            query_tokens: list[str] = []
            for tok in raw_query.split():
                clean_tok = tok.lstrip(".").lower()
                if (tok.startswith(".") or len(raw_query.split()) > 1) and clean_tok in _KNOWN_SEARCH_EXTENSIONS and detected_ext is None:
                    detected_ext = f".{clean_tok}"
                else:
                    query_tokens.append(tok)
            search_args: dict[str, Any] = {"query": " ".join(query_tokens).strip()}
            if detected_ext is not None:
                search_args["ext"] = detected_ext
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="fs.metadata.search", version=1, args=search_args),)
                ),
                intent_label="fs.metadata.search",
            )

        # 6c. Safe Registered File Open (B10, R1 — supports working-set ordinal & filename!)
        file_idx_match = _FILE_OPEN_INDEX_RE.match(text)
        if file_idx_match:
            num_str = file_idx_match.group(1) or file_idx_match.group(3)
            word_ord = (file_idx_match.group(2) or "").lower()
            if num_str:
                idx_val = int(num_str)
            elif word_ord in _ORDINAL_WORD_MAP:
                idx_val = _ORDINAL_WORD_MAP[word_ord]
            else:
                idx_val = 1
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="fs.file.open", version=1, args={"result_index": idx_val}),)
                ),
                intent_label="fs.file.open",
            )

        file_name_match = _FILE_OPEN_NAME_RE.match(text)
        if file_name_match:
            fname = strip_boundary_punctuation(file_name_match.group(1))
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="fs.file.open", version=1, args={"file_query": fname}),)
                ),
                intent_label="fs.file.open",
            )

        # 7. Dynamic Catalog App Launch (B09, R1)
        app_match = _APP_LAUNCH_RE.match(text)
        if app_match:
            raw_app = strip_boundary_punctuation(app_match.group(1))
            lower_app = raw_app.lower()
            app_id = _APP_ALIASES.get(lower_app, raw_app)
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="os.app.launch", version=1, args={"app_id": app_id}),)
                ),
                intent_label="os.app.launch",
            )

        # 8. Personal Life Tasks (R1 create / R0 list)
        task_create_match = _TASK_CREATE_RE.match(text)
        if task_create_match:
            title = (task_create_match.group(1) or task_create_match.group(2) or "").strip()
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="life.task.create", version=1, args={"title": title}),)
                ),
                intent_label="life.task.create",
            )

        if _TASK_LIST_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="life.task.list", version=1, args={}),)
                ),
                intent_label="life.task.list",
            )

        # 9. Knowledge Base Hybrid RAG Query (R0, tools=[] enforced inside KnowledgeRagService!)
        kb_match = _KNOWLEDGE_QUERY_RE.match(text)
        if kb_match:
            query_str = kb_match.group(1).strip()
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(ToolStepProposal(tool_id="knowledge.query", version=1, args={"query": query_str}),)
                ),
                intent_label="knowledge.query",
            )

        # 10. Explicit On-Demand Screen Awareness (R1, password/UAC hard-blocked + secret-redacted)
        if _SCREEN_ANALYZE_RE.match(text):
            return RouteMatch(
                matched_deterministic=True,
                needs_clarification=False,
                clarification_prompt=None,
                proposal=ToolProposal(
                    steps=(
                        ToolStepProposal(
                            tool_id="screen.analyze", version=1, args={"window_selector": "active"}
                        ),
                    )
                ),
                intent_label="screen.analyze",
            )

        # Otherwise escalate to Bounded LLM Planner (or Direct Mode polite response if no LLM active)
        return RouteMatch(
            matched_deterministic=False,
            needs_clarification=False,
            clarification_prompt=None,
            proposal=None,
            intent_label="llm_candidate",
        )


def build_static_tool_catalog_prompt(local_time_context: str | None = None) -> str:
    """Concise Bahasa Indonesia-first J.A.R.V.I.S. persona & Tool Catalog prompt (DEC-027)."""
    time_line = f"\nWaktu lokal saat ini: {local_time_context}\n" if local_time_context else "\n"
    return (
        "Kamu adalah J.A.R.V.I.S., asisten suara AI pribadi yang tenang, cerdas, akurat, dan ringkas ala J.A.R.V.I.S. milik Tony Stark."
        f"{time_line}"
        "Aturan wajib:\n"
        "1. SELALU jawab langsung dalam bahasa yang sama dengan pengguna (Bahasa Indonesia jika pengguna bicara Indonesia, English jika English) secara ringkas (1-3 kalimat) agar enak diucapkan suara.\n"
        "2. DILARANG menerjemahkan kalimat atau pertanyaan pengguna ke bahasa lain, KECUALI pengguna secara eksplisit meminta terjemahan (memakai kata 'terjemahkan', 'translate', 'artinya dalam bahasa ...', atau 'bahasa ... dari ...').\n"
        "3. Jika pengguna benar-benar meminta terjemahan, terjemahkan secara akurat ke bahasa target yang diminta, dan sertakan cara baca aksara Latin bila target menggunakan aksara non-Latin.\n"
        "4. Jika pengguna menanyakan jam, waktu, hari, atau tanggal saat ini (termasuk variasi percakapan seperti 'sekarang jam berapa', 'jam berapa nih', atau salah ketik/dengar ringan), jawab langsung memakai 'Waktu lokal saat ini' di atas secara akurat.\n"
        '5. HANYA jika pengguna secara eksplisit memerintahkan aksi perangkat lokal di bawah ini, balas HANYA dengan satu objek JSON mentah tanpa teks tambahan: {"steps":[{"tool_id":"...","version":1,"args":{...}}]}\n'
        "Daftar tool lokal yang diizinkan:\n"
        '- system.time.get v1: args={"timezone_iana": string}\n'
        '- os.volume.set v1: args={"percent": int 0..100}\n'
        '- os.app.launch v1: args={"app_id": string (nama aplikasi terinstal biasa, bukan shell/LOLBin)}\n'
        '- fs.metadata.search v1: args={"query": string, "ext": string|null}\n'
        '- fs.file.open v1: args={"file_query": string} atau {"result_index": int}\n'
        '- memory.create v1: args={"kind":"fact|preference|instruction|note","content":string,"sensitivity":"normal|sensitive"}\n'
        '- reminder.create v1: args={"title":string,"due_at_utc":iso8601,"timezone_iana":string}\n'
        '- life.task.create v1: args={"title":string}\n'
        '- life.task.list v1: args={}\n'
        '- knowledge.query v1: args={"query":string}\n'
        '- screen.analyze v1: args={"window_selector":"active"}\n'
        '- fs.file.move v1: args={"source_relative_path":string,"target_relative_path":string}\n'
        "DILARANG mengusulkan shell/terminal, penghapusan permanen, pencurian kredensial, transfer pembayaran, pengiriman email, atau pembukaan kunci/alarm IoT."
    )


def parse_llm_tool_proposal(raw_output: str) -> tuple[ToolProposal | None, str | None]:
    """Strip <think>, extract JSON, and validate strictly against ToolProposal (extra='forbid')."""
    cleaned = strip_thinking_blocks(raw_output)
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


def parse_llm_assistant_or_tool(raw_output: str) -> tuple[ToolProposal | None, str | None, str | None]:
    """Parse LLM output into either a strict ToolProposal OR a safe conversational reply (never executing unvalidated tools).

    Returns (tool_proposal, conversational_reply, parse_error).
    """
    cleaned = strip_thinking_blocks(raw_output).strip()
    if not cleaned:
        return (None, None, "LLM returned an empty response.")

    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.DOTALL | re.IGNORECASE)
    candidate_str = fence.group(1).strip() if fence else cleaned

    if candidate_str.startswith("{"):
        try:
            parsed: Any = json.loads(candidate_str)
        except json.JSONDecodeError as exc:
            return (None, None, f"LLM output is not valid JSON: {exc.msg}")
        if not isinstance(parsed, dict):
            return (None, None, "LLM JSON response must be an object.")
        if "reply" in parsed and "steps" not in parsed and set(parsed.keys()) <= {"reply"}:
            reply_val = str(parsed["reply"]).strip()
            if reply_val:
                return (None, reply_val, None)
            return (None, None, "LLM returned empty reply.")
        try:
            proposal = ToolProposal.model_validate(parsed)
            return (proposal, None, None)
        except ValidationError as exc:
            return (None, None, f"LLM proposal violated strict ToolProposal schema: {exc.error_count()} errors")

    # Plain natural-language reply (no JSON tool object attempted) — safe conversational answer
    return (None, cleaned, None)
