"""Pure Voice Domain Primitives: Ring Buffer, Echo Guard, Voiced-Only Segmenter, STT Confidence & Bilingual TTS Normalizer (B11, B12, BR-13, DEC-028, NFR-16).

Strictly OS-independent (zero Win32/ctypes/IO imports).
"""

from __future__ import annotations

import collections
import re
from dataclasses import dataclass
from typing import Any, Literal

from jarvis.domain.models import AudioEndpointInfo

PCM16_16KHZ_MONO_BYTES_PER_SEC = 16000 * 2  # 32,000 bytes/sec
MAX_RING_BUFFER_SECONDS = 2.0
MAX_RING_BUFFER_BYTES = int(PCM16_16KHZ_MONO_BYTES_PER_SEC * MAX_RING_BUFFER_SECONDS)  # 64,000 bytes


class BoundedAudioRingBuffer:
    """RAM-only circular audio pre-roll buffer strictly capped at <= 2.0s (BR-13, zero disk write)."""

    def __init__(self, max_bytes: int = MAX_RING_BUFFER_BYTES) -> None:
        if max_bytes <= 0 or max_bytes > MAX_RING_BUFFER_BYTES:
            raise ValueError(f"Ring buffer cap must be 1..{MAX_RING_BUFFER_BYTES} bytes (<= 2.0s).")
        self._max_bytes = max_bytes
        self._buf = bytearray()

    @property
    def max_bytes(self) -> int:
        return self._max_bytes

    def append_frame(self, pcm16_chunk: bytes) -> None:
        if not pcm16_chunk:
            return
        if len(pcm16_chunk) >= self._max_bytes:
            self._buf = bytearray(pcm16_chunk[-self._max_bytes :])
            return
        self._buf.extend(pcm16_chunk)
        overflow = len(self._buf) - self._max_bytes
        if overflow > 0:
            del self._buf[:overflow]

    def snapshot_bytes(self) -> bytes:
        return bytes(self._buf)

    def duration_seconds(self) -> float:
        return len(self._buf) / PCM16_16KHZ_MONO_BYTES_PER_SEC

    def clear(self) -> None:
        """Zero and clear RAM buffer immediately on mute, session lock, or idle."""
        for i in range(len(self._buf)):
            self._buf[i] = 0
        self._buf.clear()


@dataclass(frozen=True)
class EchoGuardDecision:
    allow_mic_wake_or_vad: bool
    allow_voice_barge_in: bool
    allow_ptt_or_ui_barge_in: bool
    reason: str


class EndpointAwareEchoGuard:
    """Prevents open-speaker TTS self-triggering while preserving headphone voice barge-in and instant PTT (DEC-028)."""

    def __init__(self, post_playback_tail_ms: float = 250.0) -> None:
        self._post_playback_tail_ms = max(0.0, post_playback_tail_ms)

    def evaluate(
        self,
        *,
        output_endpoint: AudioEndpointInfo | None,
        is_tts_playing: bool,
        ms_since_tts_ended: float | None,
        echo_guard_enabled: bool = True,
        aec_verified_active: bool = False,
    ) -> EchoGuardDecision:
        form_factor = output_endpoint.form_factor if output_endpoint is not None else "unknown"

        # Headphones / headsets isolate playback from mic -> allow voice barge-in freely
        if form_factor in ("headphones", "headset"):
            return EchoGuardDecision(
                allow_mic_wake_or_vad=True,
                allow_voice_barge_in=True,
                allow_ptt_or_ui_barge_in=True,
                reason="Isolated headphone/headset output detected; full voice barge-in enabled.",
            )

        # Open speakers or unknown output: guard against TTS bleed unless AEC verified
        if not echo_guard_enabled or aec_verified_active:
            return EchoGuardDecision(
                allow_mic_wake_or_vad=True,
                allow_voice_barge_in=True,
                allow_ptt_or_ui_barge_in=True,
                reason="Verified AEC active or echo guard overridden by user.",
            )

        in_tail_window = (
            ms_since_tts_ended is not None and 0.0 <= ms_since_tts_ended < self._post_playback_tail_ms
        )
        if is_tts_playing or in_tail_window:
            return EchoGuardDecision(
                allow_mic_wake_or_vad=False,
                allow_voice_barge_in=False,
                allow_ptt_or_ui_barge_in=True,
                reason=(
                    "Open-speaker playback active (or within acoustic tail window); "
                    "mic wake/VAD gated to prevent self-triggering. PTT/UI Stop remains active."
                ),
            )

        return EchoGuardDecision(
            allow_mic_wake_or_vad=True,
            allow_voice_barge_in=False,
            allow_ptt_or_ui_barge_in=True,
            reason="Open-speaker idle; mic wake/VAD listening enabled.",
        )


@dataclass(frozen=True)
class SegmentFlushResult:
    accepted: bool
    frames: tuple[Any, ...]
    voiced_frames: int
    total_frames: int
    voiced_duration_ms: float
    reason: Literal["voiced_utterance", "below_min_voiced_duration"]


class VoiceUtteranceSegmenter:
    """Utterance segmenter counting REAL voiced frames only (fixes DEF-17 click false-triggers!).

    Pre-roll and trailing silence frames are preserved for clean STT acoustics,
    but NEVER counted toward min_voiced_frames.
    """

    def __init__(
        self,
        *,
        frame_ms: float = 32.0,
        pre_roll_frames: int = 10,
        min_voiced_frames: int = 9,
        silence_end_frames: int = 22,
        max_utterance_frames: int = 375,
    ) -> None:
        self._frame_ms = frame_ms
        self._pre_roll_frames = max(0, pre_roll_frames)
        self._min_voiced_frames = max(1, min_voiced_frames)
        self._silence_end_frames = max(1, silence_end_frames)
        self._max_utterance_frames = max(self._min_voiced_frames, max_utterance_frames)
        self._pre_roll: collections.deque[Any] = collections.deque(maxlen=self._pre_roll_frames)
        self._speech_frames: list[Any] = []
        self._voiced_frames: int = 0
        self._silence_frames: int = 0
        self._in_speech: bool = False

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def voiced_frames(self) -> int:
        return self._voiced_frames

    def reset(self) -> None:
        self._pre_roll.clear()
        self._speech_frames.clear()
        self._voiced_frames = 0
        self._silence_frames = 0
        self._in_speech = False

    def push_frame(self, frame: Any, *, is_voice: bool) -> SegmentFlushResult | None:
        if is_voice:
            if not self._in_speech:
                self._speech_frames.extend(self._pre_roll)
                self._pre_roll.clear()
                self._in_speech = True
            self._speech_frames.append(frame)
            self._voiced_frames += 1
            self._silence_frames = 0
        elif self._in_speech:
            self._speech_frames.append(frame)
            self._silence_frames += 1
        else:
            if self._pre_roll_frames > 0:
                self._pre_roll.append(frame)
            return None

        should_flush = self._in_speech and (
            self._silence_frames >= self._silence_end_frames
            or len(self._speech_frames) >= self._max_utterance_frames
        )
        if not should_flush:
            return None

        buffered = tuple(self._speech_frames)
        voiced_count = self._voiced_frames
        voiced_ms = round(voiced_count * self._frame_ms, 1)
        self._speech_frames.clear()
        self._voiced_frames = 0
        self._silence_frames = 0
        self._in_speech = False

        if voiced_count < self._min_voiced_frames:
            return SegmentFlushResult(
                accepted=False,
                frames=(),
                voiced_frames=voiced_count,
                total_frames=len(buffered),
                voiced_duration_ms=voiced_ms,
                reason="below_min_voiced_duration",
            )
        return SegmentFlushResult(
            accepted=True,
            frames=buffered,
            voiced_frames=voiced_count,
            total_frames=len(buffered),
            voiced_duration_ms=voiced_ms,
            reason="voiced_utterance",
        )


@dataclass(frozen=True)
class SttAcousticEvidence:
    text: str
    detected_language: str
    avg_logprob: float | None
    no_speech_prob: float | None
    voiced_duration_ms: float


@dataclass(frozen=True)
class SttConfidenceDecision:
    action: Literal["accept", "clarify", "discard"]
    confidence: float
    reason: str
    clarification_prompt: str | None = None


_PHANTOM_HALLUCINATION_RE = re.compile(
    r"^\s*(?:terima\s+kasih\s+(?:telah|sudah)\s+menonton.*|subtitle\s+oleh.*|subscribe.*"
    r"|selamat\s+menonton.*|thank\s+you\s+for\s+watching.*|you\s*\.?|[.\s,!?-]+)\s*$",
    re.IGNORECASE,
)


def evaluate_stt_confidence(
    evidence: SttAcousticEvidence,
    *,
    is_actionable_intent: bool = False,
    primary_language: str = "id-ID",
) -> SttConfidenceDecision:
    """Calibrated acoustic confidence gate separating silence/hallucination, low-conf clarify, and accept (B11)."""
    cleaned = evidence.text.strip()
    if not cleaned or len(cleaned) <= 1 or _PHANTOM_HALLUCINATION_RE.match(cleaned):
        return SttConfidenceDecision(
            action="discard",
            confidence=0.0,
            reason="empty_or_whisper_hallucination",
        )

    if evidence.no_speech_prob is not None and evidence.no_speech_prob >= 0.72:
        return SttConfidenceDecision(
            action="discard",
            confidence=round(max(0.0, 1.0 - evidence.no_speech_prob), 3),
            reason="high_no_speech_prob",
        )

    if evidence.voiced_duration_ms > 0.0 and evidence.voiced_duration_ms < 220.0:
        return SttConfidenceDecision(
            action="discard",
            confidence=0.15,
            reason="voiced_duration_too_short",
        )

    # Combine acoustic avg_logprob (typical good Whisper: -0.05 to -0.65; poor: < -1.1) and speech prob
    logprob_score = 0.80
    if evidence.avg_logprob is not None:
        # Map [-1.5, -0.15] linearly to [0.0, 1.0]
        logprob_score = max(0.0, min(1.0, (evidence.avg_logprob + 1.5) / 1.35))

    speech_score = 1.0
    if evidence.no_speech_prob is not None:
        speech_score = max(0.0, min(1.0, 1.0 - evidence.no_speech_prob))

    combined = round((logprob_score * 0.65) + (speech_score * 0.35), 3)

    if combined < 0.36:
        return SttConfidenceDecision(
            action="discard",
            confidence=combined,
            reason="low_acoustic_confidence_discarded",
        )

    if combined < 0.60 and is_actionable_intent:
        is_en = (evidence.detected_language or primary_language).lower().startswith("en")
        prompt = (
            f"I'm not fully certain I heard '{cleaned}'. Could you confirm or repeat?"
            if is_en
            else f"Saya kurang yakin menangkap perintah '{cleaned}'. Bisa diulang atau dikonfirmasi?"
        )
        return SttConfidenceDecision(
            action="clarify",
            confidence=combined,
            reason="low_confidence_actionable_intent",
            clarification_prompt=prompt,
        )

    return SttConfidenceDecision(
        action="accept",
        confidence=combined,
        reason="acoustic_confidence_verified",
    )


@dataclass(frozen=True)
class VoiceTimingTrace:
    """End-to-end voice turn timing trace for Voice Lab diagnostics (Section 8.3)."""

    request_id: str
    transcript: str
    detected_language: str
    confidence: float
    route_kind: str
    t_capture_start_ms: float
    t_end_speech_ms: float
    t_stt_final_ms: float
    t_route_ms: float | None = None
    t_model_first_token_ms: float | None = None
    t_first_sentence_ms: float | None = None
    t_audio_start_ms: float | None = None
    t_action_verified_ms: float | None = None
    t_turn_done_ms: float | None = None

    @property
    def stt_latency_ms(self) -> float:
        return round(max(0.0, self.t_stt_final_ms - self.t_end_speech_ms), 2)

    @property
    def ttfa_from_end_of_speech_ms(self) -> float | None:
        if self.t_audio_start_ms is None:
            return None
        return round(max(0.0, self.t_audio_start_ms - self.t_end_speech_ms), 2)

    @property
    def total_perceived_ms(self) -> float | None:
        if self.t_turn_done_ms is None:
            return None
        return round(max(0.0, self.t_turn_done_ms - self.t_capture_start_ms), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "transcript": self.transcript,
            "detected_language": self.detected_language,
            "confidence": self.confidence,
            "route_kind": self.route_kind,
            "stt_latency_ms": self.stt_latency_ms,
            "ttfa_from_end_of_speech_ms": self.ttfa_from_end_of_speech_ms,
            "total_perceived_ms": self.total_perceived_ms,
            "t_capture_start_ms": round(self.t_capture_start_ms, 2),
            "t_end_speech_ms": round(self.t_end_speech_ms, 2),
            "t_stt_final_ms": round(self.t_stt_final_ms, 2),
            "t_route_ms": round(self.t_route_ms, 2) if self.t_route_ms is not None else None,
            "t_audio_start_ms": round(self.t_audio_start_ms, 2) if self.t_audio_start_ms is not None else None,
            "t_turn_done_ms": round(self.t_turn_done_ms, 2) if self.t_turn_done_ms is not None else None,
        }


def build_scoped_stt_prompt(
    app_names: tuple[str, ...] = (),
    recent_filenames: tuple[str, ...] = (),
    *,
    max_chars: int = 420,
) -> str:
    """Build bounded bilingual Whisper vocabulary hint from scoped app/file catalog (never full disk!)."""
    base = (
        "Percakapan asisten J.A.R.V.I.S. (Bahasa Indonesia & English): "
        "Hey Jarvis, jam berapa sekarang, buka aplikasi, cari file, buka nomor 1, "
        "atur volume, ingatkan saya, buat tugas, cukup Jarvis, standby."
    )
    hints: list[str] = []
    for name in app_names[:12]:
        clean = name.strip()
        if clean and clean not in hints:
            hints.append(clean)
    for fname in recent_filenames[:5]:
        clean = fname.strip()
        if clean and clean not in hints:
            hints.append(clean)
    if not hints:
        return base[:max_chars]
    combined = f"{base} Aplikasi & dokumen: {', '.join(hints)}."
    return combined[:max_chars]


_ID_MARKER_WORDS: frozenset[str] = frozenset(
    {
        "yang",
        "dan",
        "untuk",
        "dengan",
        "tidak",
        "saya",
        "anda",
        "ini",
        "itu",
        "pada",
        "dari",
        "sekarang",
        "pukul",
        "aplikasi",
        "berhasil",
        "dibuka",
        "ditemukan",
        "pengingat",
        "silakan",
        "maaf",
        "baik",
        "siap",
        "adalah",
        "bisa",
        "dalam",
        "file",
        "sudah",
        "belum",
        "volume",
    }
)
_EN_MARKER_WORDS: frozenset[str] = frozenset(
    {
        "the",
        "and",
        "for",
        "with",
        "not",
        "you",
        "your",
        "this",
        "that",
        "from",
        "current",
        "time",
        "opened",
        "found",
        "reminder",
        "please",
        "sorry",
        "ready",
        "cannot",
        "successfully",
        "application",
        "document",
        "local",
        "active",
        "scheduled",
    }
)


def detect_text_language(text: str, *, default_lang: str = "id-ID") -> Literal["id", "en"]:
    """Deterministic lightweight Indonesian vs English language classifier for bilingual TTS routing (B12)."""
    tokens = re.findall(r"[a-z]+", text.casefold())
    if not tokens:
        return "en" if default_lang.lower().startswith("en") else "id"
    id_hits = sum(1 for t in tokens if t in _ID_MARKER_WORDS)
    en_hits = sum(1 for t in tokens if t in _EN_MARKER_WORDS)
    if en_hits > id_hits and en_hits >= 2:
        return "en"
    if id_hits > en_hits:
        return "id"
    return "en" if default_lang.lower().startswith("en") else "id"


_THINK_STRIP_RE = re.compile(r"<think>.*?</think>\s*", re.IGNORECASE | re.DOTALL)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_URL_RE = re.compile(r"https?://(?:www\.)?([a-zA-Z0-9.-]+)(?:/[^\s,.)]*)?", re.I)
_WIN_PATH_RE = re.compile(
    r"(?:[A-Za-z]:\\|\\\\)[^\s\"'<>|]+\\([^\s\"'<>|\\]+)",
)
_REL_PATH_RE = re.compile(
    r"\b(?:[A-Za-z0-9_.-]+/)+([A-Za-z0-9_.-]+\.[A-Za-z0-9]{2,5})\b",
)
_MD_SYMBOLS_RE = re.compile(r"[`*_#>\[\]]+")
_PERCENT_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
_TIME_24H_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_JARVIS_DOTTED_RE = re.compile(r"\bJ\.A\.R\.V\.I\.S\.?", re.I)

_TTS_ACRONYM_MAP_ID: dict[str, str] = {
    "PDF": "P D F",
    "CPU": "C P U",
    "GPU": "G P U",
    "VRAM": "V RAM",
    "USB": "U S B",
    "API": "A P I",
    "URL": "U R L",
    "SQL": "S Q L",
    "JSON": "Jayson",
    "LLM": "L L M",
    "STT": "S T T",
    "TTS": "T T S",
    "VAD": "V A D",
    "UI": "U I",
    "OS": "O S",
    "UTC": "U T C",
}

_TTS_ACRONYM_MAP_EN: dict[str, str] = {
    "PDF": "P D F",
    "CPU": "C P U",
    "GPU": "G P U",
    "VRAM": "V RAM",
    "USB": "U S B",
    "API": "A P I",
    "URL": "U R L",
    "SQL": "S Q L",
    "JSON": "Jason",
    "LLM": "L L M",
    "STT": "S T T",
    "TTS": "T T S",
    "VAD": "V A D",
    "UI": "U I",
    "OS": "O S",
    "UTC": "U T C",
}


def normalize_text_for_tts(
    text: str,
    *,
    language: str = "id-ID",
    pronunciation_dict: dict[str, str] | None = None,
) -> str:
    """Language-aware ID/EN TTS text normalizer (B12). Never alters displayed UI text.

    Strips reasoning tags, tool JSON, markdown, raw paths/URLs; expands percentages, times, and acronyms.
    """
    cleaned = _THINK_STRIP_RE.sub("", text).strip()
    if not cleaned:
        return ""
    # Never read raw structured tool JSON objects aloud
    if cleaned.startswith("{") and '"steps"' in cleaned and cleaned.endswith("}"):
        return ""

    lang = "en" if language.lower().startswith("en") else "id"

    # Markdown links [label](url) -> label
    cleaned = _MD_LINK_RE.sub(r"\1", cleaned)

    # Full URLs -> readable domain reference
    url_prefix = "link" if lang == "en" else "tautan"
    cleaned = _URL_RE.sub(lambda m: f"{url_prefix} {m.group(1)}", cleaned)

    # Windows absolute paths & relative directory paths -> spoken filename only
    def _humanize_filename(raw_name: str) -> str:
        dot_idx = raw_name.rfind(".")
        if dot_idx > 0:
            stem = raw_name[:dot_idx].replace("_", " ").replace("-", " ")
            ext = raw_name[dot_idx + 1 :].upper()
            spoken_ext = _TTS_ACRONYM_MAP_ID.get(ext, ext)
            return f"file {stem} {spoken_ext}"
        return f"file {raw_name.replace('_', ' ')}"

    cleaned = _WIN_PATH_RE.sub(lambda m: _humanize_filename(m.group(1)), cleaned)
    cleaned = _REL_PATH_RE.sub(lambda m: _humanize_filename(m.group(1)), cleaned)

    # Strip remaining markdown syntax & list markers
    cleaned = re.sub(r"(?m)^\s*[-*•]\s+", "", cleaned)
    cleaned = _MD_SYMBOLS_RE.sub(" ", cleaned)

    # Brand pronunciation
    cleaned = _JARVIS_DOTTED_RE.sub("Jarvis", cleaned)

    # Percentages
    pct_word = "percent" if lang == "en" else "persen"
    cleaned = _PERCENT_RE.sub(rf"\1 {pct_word}", cleaned)

    # 24-hour clock times (in Indonesian: 05:35 -> "05 lewat 35" for smooth Piper cadence)
    if lang == "id":
        def _id_time(m: re.Match[str]) -> str:
            hh = int(m.group(1))
            mm = int(m.group(2))
            if mm == 0:
                return f"{hh:02d} tepat"
            return f"{hh:02d} lewat {mm:02d}"

        cleaned = _TIME_24H_RE.sub(_id_time, cleaned)

    # Acronyms
    acronym_map = _TTS_ACRONYM_MAP_EN if lang == "en" else _TTS_ACRONYM_MAP_ID
    for acr, spoken in acronym_map.items():
        cleaned = re.sub(rf"\b{re.escape(acr)}\b", spoken, cleaned)

    # Optional user pronunciation dictionary overrides
    if pronunciation_dict:
        for src, dst in pronunciation_dict.items():
            if src.strip():
                cleaned = re.sub(
                    rf"\b{re.escape(src.strip())}\b", dst.strip(), cleaned, flags=re.IGNORECASE
                )

    return re.sub(r"\s+", " ", cleaned).strip()


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def split_sentences_for_streaming_tts(text: str, *, max_chunk_chars: int = 180) -> list[str]:
    """Split text into short spoken sentences for low first-audio latency (06-AI-VOICE-DESIGN §1.4)."""
    cleaned = re.sub(r"\s+", " ", text.strip())
    if not cleaned:
        return []
    raw_sentences = _SENTENCE_SPLIT_RE.split(cleaned)
    chunks: list[str] = []
    for sent in raw_sentences:
        s = sent.strip()
        if not s:
            continue
        while len(s) > max_chunk_chars:
            cut = s.rfind(" ", 0, max_chunk_chars)
            if cut <= 20:
                cut = max_chunk_chars
            chunks.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            chunks.append(s)
    return chunks
