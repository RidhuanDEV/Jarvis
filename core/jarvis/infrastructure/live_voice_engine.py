"""Unified Asynchronous RAM-Only Voice Runtime: Selected Device Binding, Voiced-Only Silero VAD,
Bilingual faster-whisper STT + Confidence Gate, Generation-Guarded Streaming Piper TTS & Voice Lab Diagnostics (B11, B12, DEC-013, DEC-028).

Strict privacy & portability invariants:
- Zero audio files written to disk; all capture & TTS synthesis buffers stay strictly in RAM.
- Decoupled capture callback -> DSP/Wake/VAD thread -> bounded utterance queue -> STT/Turn worker -> generation-guarded TTS playback.
- Voiced-only frame counting eliminates single-click false triggers (DEF-17).
- EndpointAwareEchoGuard prevents open-speaker self-triggering while enabling headset voice barge-in (< 50ms generation cutoff).
- Language-aware ID/EN TTS text normalization never alters displayed UI text.
"""

from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import contextlib
import io
import math
import queue
import re
import threading
import time
import uuid
import wave
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from jarvis.domain.models import AudioEndpointInfo
from jarvis.domain.voice import (
    EndpointAwareEchoGuard,
    SttAcousticEvidence,
    VoiceTimingTrace,
    VoiceUtteranceSegmenter,
    build_scoped_stt_prompt,
    detect_text_language,
    evaluate_stt_confidence,
    normalize_text_for_tts,
)
from jarvis.infrastructure.logging_setup import get_logger
from jarvis.infrastructure.provenance import ArtifactProvenanceError, ArtifactProvenanceVerifier

VoiceMode = Literal["muted", "wake", "active", "ptt"]
VoicePhase = Literal[
    "muted",
    "standby_wake",
    "listening_command",
    "transcribing",
    "thinking",
    "speaking",
    "unavailable",
]

# Wake phrase detector: Indonesian/English + common Whisper phonetic variants of "Hey Jarvis" / "Jarvis"
_WAKE_PREFIX_RE = re.compile(
    r"^\s*(?:(?:hey|hei|hai|halo|hello|hi|ok|oke|okay|yo)\s+)?"
    r"(?:j\.?\s*a\.?\s*r\.?\s*v\.?\s*i\.?\s*s\.?|jarvis|jervis|jarfis|jarviz|yarvis|charvis|garvis)"
    r"[\s,!?:.\-]*(.*)$",
    re.IGNORECASE,
)

_WAKE_ANYWHERE_RE = re.compile(
    r"\b(?:hey|hei|hai|halo|hello|ok|oke)\s+(?:jarvis|jervis|jarfis|jarviz|garvis|j\.?\s*a\.?\s*r\.?\s*v\.?\s*i\.?\s*s\.?)"
    r"[\s,!?:.\-]*(.*)$",
    re.IGNORECASE,
)

# Precision-guarded sleep commands to return JARVIS from Active Conversation Session back to Standby Wake mode
_SLEEP_COMMAND_RE = re.compile(
    r"^\s*(?:"
    r"(?:cukup|selesai|sudah)(?:\s+(?:dulu|ya|jarvis|terima\s+kasih|makasih))?"
    r"|(?:jarvis\s+)?(?:tidur(?:\s+dulu)?|istirahat(?:\s+dulu)?|kembali\s+siaga|mode\s+siaga|stand\s*by|diam(?:\s+dulu)?|go\s+to\s+sleep|sleep\s+now)"
    r"|(?:terima\s+kasih|makasih|thanks|thank\s+you)\s+(?:jarvis|selesai|cukup)"
    r"|that(?:'s|\s+is)\s+all(?:\s+jarvis)?"
    r")\s*[.!?]*\s*$",
    re.IGNORECASE,
)

# Known Whisper silence/subtitle phantom artifacts to discard cleanly
_WHISPER_HALLUCINATION_RE = re.compile(
    r"^\s*(?:terima\s+kasih\s+(?:telah|sudah)\s+menonton.*|subtitle\s+oleh.*|subscribe.*|selamat\s+menonton.*|thank\s+you\s+for\s+watching.*|[.\s,!?-]+)\s*$",
    re.IGNORECASE,
)

_ACTIONABLE_HINT_RE = re.compile(
    r"\b(?:buka|bukain|open|launch|start|atur|ubah|set|pindahkan|move|rename|cari|find|ingatkan|remind|buat|hapus|delete)\b",
    re.IGNORECASE,
)

_MARKDOWN_CLEAN_RE = re.compile(r"[`*_#>\[\]]+")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def extract_wake_command(transcript: str) -> tuple[bool, str]:
    """Return (woke, command_text) for Tony Stark wake-word gating ('Hey Jarvis' / 'Jarvis' / 'Halo Jarvis')."""
    cleaned = re.sub(r"\s+", " ", transcript.strip())
    if not cleaned:
        return (False, "")

    m = _WAKE_PREFIX_RE.match(cleaned)
    if m:
        return (True, m.group(1).strip())

    m2 = _WAKE_ANYWHERE_RE.search(cleaned)
    if m2:
        return (True, m2.group(1).strip())

    return (False, "")


def strip_optional_wake_prefix(transcript: str) -> str:
    """Strip redundant leading 'Hey Jarvis,' even when already inside an active conversation session."""
    cleaned = re.sub(r"\s+", " ", transcript.strip())
    if not cleaned:
        return ""
    m = _WAKE_PREFIX_RE.match(cleaned)
    if m:
        return m.group(1).strip()
    return cleaned


def is_sleep_command(transcript: str) -> bool:
    """Detect explicit sleep/standby intent while avoiding false positives in ordinary sentences."""
    cleaned = re.sub(r"\s+", " ", transcript.strip())
    if not cleaned:
        return False
    return _SLEEP_COMMAND_RE.match(cleaned) is not None


def is_whisper_hallucination(transcript: str) -> bool:
    """Filter common Whisper silence hallucinations ('Terima kasih telah menonton', punctuation-only)."""
    cleaned = transcript.strip()
    if not cleaned or len(cleaned) <= 1:
        return True
    return _WHISPER_HALLUCINATION_RE.match(cleaned) is not None


def sanitize_for_speech(text: str) -> str:
    """Strip markdown punctuation so spoken TTS output sounds natural and crisp."""
    no_md = _MARKDOWN_CLEAN_RE.sub(" ", text)
    return re.sub(r"\s+", " ", no_md).strip()


def split_sentences_for_tts(text: str) -> list[str]:
    """Split assistant reply into natural speakable chunks for low-latency sentence-streaming TTS."""
    cleaned = sanitize_for_speech(text)
    if not cleaned:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(cleaned) if p.strip()]
    return parts if parts else [cleaned]


@dataclass(frozen=True)
class _QueuedUtterance:
    pcm_audio: Any
    voiced_duration_ms: float
    t_capture_start_ms: float
    t_end_speech_ms: float
    generation: int


@dataclass(frozen=True)
class LiveVoiceSnapshot:
    mode: VoiceMode
    phase: VoicePhase
    amplitude: float
    stt_ready: bool
    stt_model: str | None
    tts_ready: bool
    tts_model: str | None
    mic_available: bool
    active_command_window: bool
    session_active: bool
    session_seconds_left: int
    vad_engine: str
    wake_engine: str
    last_transcript: str
    last_reply: str
    last_route_kind: str
    last_llm_called: bool
    error: str | None = None


def _discover_whisper_dir(models_dirs: tuple[Path, ...]) -> Path | None:
    preferred = ("faster-whisper-small", "faster-whisper-base", "faster-whisper-tiny")
    for name in preferred:
        for base in models_dirs:
            cand = base / name
            if (cand / "model.bin").is_file():
                return cand
    return None


def _discover_silero_vad_path(models_dirs: tuple[Path, ...]) -> Path | None:
    for base in models_dirs:
        for cand in (base / "silero_vad.onnx", base / "openwakeword" / "silero_vad.onnx"):
            if cand.is_file():
                return cand
    return None


def _discover_openwakeword_paths(models_dirs: tuple[Path, ...]) -> tuple[Path, Path, Path] | None:
    """Locate openWakeWord ONNX wake model + feature extractors across configured model roots."""
    for base in models_dirs:
        for folder in (base / "openwakeword", base):
            if not folder.is_dir():
                continue
            mel = folder / "melspectrogram.onnx"
            emb = folder / "embedding_model.onnx"
            hey_list = sorted(folder.glob("hey_jarvis*.onnx"))
            if hey_list and mel.is_file() and emb.is_file():
                return (hey_list[0], mel, emb)
    return None


def _infer_piper_lang(folder_name: str, onnx_name: str) -> str:
    combined = f"{folder_name} {onnx_name}".casefold()
    if "id_id" in combined or "id-id" in combined or "indonesian" in combined:
        return "id"
    if "en_us" in combined or "en_gb" in combined or "en-us" in combined or "en-gb" in combined or "english" in combined:
        return "en"
    return "default"


def _discover_piper_voices(models_dirs: tuple[Path, ...]) -> dict[str, tuple[Path, Path, Path]]:
    """Locate all installed Piper VITS ONNX voice models indexed by language ('id', 'en', 'default')."""
    found: dict[str, tuple[Path, Path, Path]] = {}
    for base in models_dirs:
        if not base.exists():
            continue
        for sub in sorted(base.iterdir()):
            if not sub.is_dir():
                continue
            for onnx_path in sorted(sub.glob("*.onnx")):
                cfg_path = Path(f"{onnx_path}.json")
                if cfg_path.is_file():
                    lang_key = _infer_piper_lang(sub.name, onnx_path.name)
                    found.setdefault(lang_key, (sub, onnx_path, cfg_path))
                    found.setdefault("default", (sub, onnx_path, cfg_path))
    return found


class _SileroVadRunner:
    """Lightweight ONNX Runtime wrapper for Silero VAD (512-sample 16 kHz frames, < 0.3ms/frame)."""

    def __init__(self, model_path: Path) -> None:
        import numpy as np
        import onnxruntime as ort

        sess_opts = ort.SessionOptions()
        sess_opts.intra_op_num_threads = 1
        sess_opts.inter_op_num_threads = 1
        self._session = ort.InferenceSession(
            str(model_path), sess_options=sess_opts, providers=["CPUExecutionProvider"]
        )
        input_names = {i.name for i in self._session.get_inputs()}
        self._mode = "xhc" if {"x", "h", "c"} <= input_names else "state_sr"
        self._h = np.zeros((2, 1, 64), dtype=np.float32)
        self._c = np.zeros((2, 1, 64), dtype=np.float32)
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._sr = np.array(16000, dtype=np.int64)

    def reset(self) -> None:
        self._h.fill(0.0)
        self._c.fill(0.0)
        self._state.fill(0.0)

    def speech_prob(self, frame_512: Any) -> float:
        import numpy as np

        x = np.asarray(frame_512, dtype=np.float32).reshape(1, 512)
        if self._mode == "xhc":
            out = self._session.run(None, {"x": x, "h": self._h, "c": self._c})
            prob, self._h, self._c = out[0], out[1], out[2]
            return float(prob.item())
        out = self._session.run(None, {"input": x, "state": self._state, "sr": self._sr})
        prob, self._state = out[0], out[1]
        return float(prob.item())


class _OpenWakeWordRunner:
    """Dedicated 80ms ONNX 'hey_jarvis' wake-word detector (< 3% CPU, 0 Whisper calls in standby)."""

    FRAME_SAMPLES = 1280  # 80ms at 16 kHz

    def __init__(self, hey_path: Path, mel_path: Path, emb_path: Path) -> None:
        import numpy as np
        from openwakeword.model import Model

        self._model = Model(
            wakeword_models=[str(hey_path)],
            inference_framework="onnx",
            melspec_model_path=str(mel_path),
            embedding_model_path=str(emb_path),
        )
        self._buf: Any = np.zeros(0, dtype=np.int16)

    def reset(self) -> None:
        import numpy as np

        self._buf = np.zeros(0, dtype=np.int16)
        with contextlib.suppress(Exception):
            self._model.reset()

    def push_float32_and_max_score(self, chunk_f32: Any) -> float:
        import numpy as np

        pcm16 = np.clip(chunk_f32 * 32767.0, -32768.0, 32767.0).astype(np.int16)
        self._buf = np.concatenate((self._buf, pcm16)) if self._buf.size else pcm16
        max_score = 0.0
        while self._buf.size >= self.FRAME_SAMPLES:
            frame = self._buf[: self.FRAME_SAMPLES]
            self._buf = self._buf[self.FRAME_SAMPLES :]
            preds = self._model.predict(frame)
            for val in preds.values():
                fval = float(val)
                if fval > max_score:
                    max_score = fval
        return max_score


def _resolve_sounddevice_index(device_name: str | None, *, direction: Literal["input", "output"]) -> int | None:
    if not device_name:
        return None
    target = device_name.strip().casefold()
    if not target:
        return None
    with contextlib.suppress(Exception):
        import sounddevice as sd

        chan_key = "max_input_channels" if direction == "input" else "max_output_channels"
        for idx, dev in enumerate(sd.query_devices()):
            if int(dev.get(chan_key, 0)) <= 0:
                continue
            cand_name = str(dev.get("name", "")).strip().casefold()
            if cand_name == target or target in cand_name or cand_name in target:
                return idx
    return None


class LiveVoiceEngine:
    """Unified async RAM-only Voice Runtime with voiced-only VAD, bilingual STT/TTS & Voice Lab diagnostics (B11/B12)."""

    SAMPLE_RATE = 16000
    BLOCK_SAMPLES = 512  # 32ms native Silero VAD frame size
    PRE_ROLL_FRAMES = 10  # 320ms pre-roll ring buffer prevents clipping initial consonants
    VAD_SPEECH_THRESHOLD = 0.42
    OWW_WAKE_THRESHOLD = 0.45
    RMS_FALLBACK_THRESHOLD = 0.014
    SILENCE_END_SECONDS = 0.72
    POST_WAKE_FOLLOW_SECONDS = 0.58
    MIN_SPEECH_SECONDS = 0.28
    MAX_UTTERANCE_SECONDS = 12.0
    ACTIVE_SESSION_SECONDS = 30.0

    def __init__(
        self,
        *,
        models_dirs: tuple[Path, ...],
        turn_callback: Callable[[str], Coroutine[Any, Any, tuple[str, str, bool]]],
        stream_turn_callback: (
            Callable[[str, Callable[[str], None]], Coroutine[Any, Any, tuple[str, str, bool]]] | None
        ) = None,
        provenance_verifier: ArtifactProvenanceVerifier | None = None,
        hotword_provider: Callable[[], tuple[tuple[str, ...], tuple[str, ...]]] | None = None,
    ) -> None:
        self._models_dirs = models_dirs
        self._turn_callback = turn_callback
        self._stream_turn_callback = stream_turn_callback
        self._provenance = provenance_verifier
        self._hotword_provider = hotword_provider
        self._logger = get_logger("jarvis.live_voice")

        self._lock = threading.RLock()
        self._mode: VoiceMode = "muted"
        self._phase: VoicePhase = "muted"
        self._amplitude: float = 0.0
        self._last_transcript: str = ""
        self._last_reply: str = ""
        self._last_route_kind: str = ""
        self._last_llm_called: bool = False
        self._error: str | None = None

        # Unified audio configuration synced from VoicePipelineService (B11/B12)
        self._selected_input_name: str | None = None
        self._selected_output_name: str | None = None
        self._selected_input_index: int | None = None
        self._selected_output_index: int | None = None
        self._output_endpoint: AudioEndpointInfo | None = None
        self._echo_guard = EndpointAwareEchoGuard(post_playback_tail_ms=300.0)
        self._echo_guard_enabled: bool = True
        self._speech_rate: float = 1.0
        self._primary_language: str = "id-ID"
        self._multilingual_enabled: bool = True

        # Session & barge-in generation control
        self._session_active: bool = False
        self._session_until_monotonic: float = 0.0
        self._speaking: bool = False
        self._tts_ended_monotonic: float | None = None
        self._last_oww_trigger_monotonic: float = 0.0
        self._playback_generation: int = 0

        # Voice Lab diagnostics counters (RAM-only, zero raw audio persisted)
        self._live_rms: float = 0.0
        self._noise_floor_rms: float = 0.003
        self._clipping_events: int = 0
        self._queue_overflow_drops: int = 0
        self._utterance_drops: int = 0
        self._last_confidence: float = 0.0
        self._last_detected_language: str = "id"
        self._recent_traces: collections.deque[VoiceTimingTrace] = collections.deque(maxlen=15)

        # Decoupled queues & threads
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event = threading.Event()
        self._audio_queue: queue.Queue[Any] = queue.Queue(maxsize=250)
        self._utterance_queue: queue.Queue[_QueuedUtterance] = queue.Queue(maxsize=4)
        self._stream: Any = None
        self._capture_thread: threading.Thread | None = None
        self._stt_thread: threading.Thread | None = None

        # Model discovery
        self._whisper_path = _discover_whisper_dir(models_dirs)
        self._piper_voices = _discover_piper_voices(models_dirs)
        self._silero_vad_path = _discover_silero_vad_path(models_dirs)
        self._oww_paths = _discover_openwakeword_paths(models_dirs)
        self._vad_runner: _SileroVadRunner | None = None
        self._oww_runner: _OpenWakeWordRunner | None = None
        self._whisper_model: Any = None
        self._tts_engines: dict[str, Any] = {}
        self._deps_ok, self._mic_ok, self._tts_pkg_ok, self._ort_ok, self._oww_pkg_ok = (
            self._probe_capabilities()
        )

    def _probe_capabilities(self) -> tuple[bool, bool, bool, bool, bool]:
        tts_ok = False
        with contextlib.suppress(Exception):
            import piper.voice  # noqa: F401

            tts_ok = True
        ort_ok = False
        with contextlib.suppress(Exception):
            import onnxruntime  # noqa: F401

            ort_ok = True
        oww_ok = False
        with contextlib.suppress(Exception):
            import openwakeword.model  # noqa: F401

            oww_ok = True
        try:
            import faster_whisper  # noqa: F401
            import numpy  # noqa: F401
            import sounddevice as sd

            devices = sd.query_devices()
            has_in = any(int(d.get("max_input_channels", 0)) > 0 for d in devices)
            return (True, has_in, tts_ok, ort_ok, oww_ok)
        except Exception:
            return (False, False, tts_ok, ort_ok, oww_ok)

    def bind_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    @property
    def playback_generation(self) -> int:
        with self._lock:
            return self._playback_generation

    def sync_audio_config(
        self,
        *,
        input_device_name: str | None,
        output_device_name: str | None,
        output_endpoint: AudioEndpointInfo | None,
        echo_guard_enabled: bool,
        speech_rate: float,
        primary_language: str,
        multilingual_enabled: bool,
    ) -> None:
        """Apply selected mic/speaker, echo-guard endpoint, speech rate & language live (B11/B12)."""
        with self._lock:
            input_changed = input_device_name != self._selected_input_name
            self._selected_input_name = input_device_name
            self._selected_output_name = output_device_name
            self._output_endpoint = output_endpoint
            self._echo_guard_enabled = echo_guard_enabled
            self._speech_rate = max(0.5, min(2.0, float(speech_rate)))
            self._primary_language = primary_language
            self._multilingual_enabled = multilingual_enabled
            self._selected_input_index = _resolve_sounddevice_index(
                input_device_name, direction="input"
            )
            self._selected_output_index = _resolve_sounddevice_index(
                output_device_name, direction="output"
            )
            if input_changed and self._stream is not None and self._mode != "muted":
                self._stop_capture_locked()
                self._start_capture_locked()

    def on_runtime_mode_changed(self, mode: Literal["muted", "ptt", "wake"]) -> None:
        """Keep LiveVoiceEngine synchronized when VoicePipelineService changes mode (B11)."""
        if mode == "muted":
            self.set_mode("muted")
        elif self._deps_ok and self._mic_ok and self._whisper_path is not None:
            self.set_mode(mode)

    def _vad_engine_name(self) -> str:
        return "silero-vad" if (self._ort_ok and self._silero_vad_path is not None) else "rms-fallback"

    def _wake_engine_name(self) -> str:
        return (
            "openwakeword-hey-jarvis"
            if (self._oww_pkg_ok and self._oww_paths is not None)
            else "whisper-fallback"
        )

    def _current_echo_guard_decision(self, now_m: float) -> Any:
        ms_since = (
            (now_m - self._tts_ended_monotonic) * 1000.0
            if (not self._speaking and self._tts_ended_monotonic is not None)
            else None
        )
        return self._echo_guard.evaluate(
            output_endpoint=self._output_endpoint,
            is_tts_playing=self._speaking,
            ms_since_tts_ended=ms_since,
            echo_guard_enabled=self._echo_guard_enabled,
        )

    def snapshot(self) -> LiveVoiceSnapshot:
        with self._lock:
            now_m = time.monotonic()
            remaining = max(0, int(math.ceil(self._session_until_monotonic - now_m))) if self._session_active else 0
            if self._session_active and remaining == 0 and self._phase == "listening_command":
                self._session_active = False
                self._phase = "standby_wake" if self._mode in ("wake", "active", "ptt") else "muted"
            default_piper = self._piper_voices.get("default")
            return LiveVoiceSnapshot(
                mode=self._mode,
                phase=self._phase,
                amplitude=round(self._amplitude, 3),
                stt_ready=self._deps_ok and self._whisper_path is not None,
                stt_model=self._whisper_path.name if self._whisper_path else None,
                tts_ready=self._tts_pkg_ok and default_piper is not None,
                tts_model=default_piper[0].name if default_piper else None,
                mic_available=self._mic_ok,
                active_command_window=self._session_active,
                session_active=self._session_active,
                session_seconds_left=remaining,
                vad_engine=self._vad_engine_name(),
                wake_engine=self._wake_engine_name(),
                last_transcript=self._last_transcript,
                last_reply=self._last_reply,
                last_route_kind=self._last_route_kind,
                last_llm_called=self._last_llm_called,
                error=self._error,
            )

    def get_diagnostics(self) -> dict[str, Any]:
        """Return Voice Lab diagnostics snapshot (zero raw audio, zero secrets, Section 8.3)."""
        with self._lock:
            now_m = time.monotonic()
            eg = self._current_echo_guard_decision(now_m)
            return {
                "mode": self._mode,
                "phase": self._phase,
                "selected_input_device": self._selected_input_name or "OS Default Input",
                "selected_output_device": self._selected_output_name or "OS Default Output",
                "output_form_factor": (
                    self._output_endpoint.form_factor if self._output_endpoint is not None else "unknown"
                ),
                "echo_guard_enabled": self._echo_guard_enabled,
                "echo_guard_reason": eg.reason,
                "voice_barge_in_allowed": eg.allow_voice_barge_in,
                "live_rms": round(self._live_rms, 5),
                "noise_floor_rms": round(self._noise_floor_rms, 5),
                "clipping_events": self._clipping_events,
                "queue_overflow_drops": self._queue_overflow_drops,
                "utterance_drops": self._utterance_drops,
                "playback_generation": self._playback_generation,
                "vad_engine": self._vad_engine_name(),
                "wake_engine": self._wake_engine_name(),
                "stt_model": self._whisper_path.name if self._whisper_path else None,
                "stt_language_mode": (
                    "multilingual_auto" if self._multilingual_enabled else self._primary_language
                ),
                "speech_rate": self._speech_rate,
                "installed_piper_voices": {
                    lang: paths[0].name
                    for lang, paths in self._piper_voices.items()
                    if lang != "default" or len(self._piper_voices) == 1
                },
                "last_confidence": self._last_confidence,
                "last_detected_language": self._last_detected_language,
                "recent_traces": [t.to_dict() for t in self._recent_traces],
            }

    def _verify_model_files(self, *paths: Path) -> bool:
        """Verify voice model files against trusted SHA-256 manifest before loading (IR-05, B06)."""
        if self._provenance is None:
            return True
        for path in paths:
            try:
                self._provenance.verify_artifact(path)
            except ArtifactProvenanceError as exc:
                self._logger.warning("voice.provenance_rejected", artifact=path.name, reason=str(exc))
                self._error = str(exc)
                return False
        return True

    def _ensure_vad_loaded(self) -> _SileroVadRunner | None:
        if self._vad_runner is not None:
            return self._vad_runner
        if not self._ort_ok or self._silero_vad_path is None:
            return None
        if not self._verify_model_files(self._silero_vad_path):
            return None
        try:
            self._vad_runner = _SileroVadRunner(self._silero_vad_path)
            return self._vad_runner
        except Exception as exc:
            self._logger.warning("voice.silero_vad_load_failed", error=str(exc))
            return None

    def _ensure_oww_loaded(self) -> _OpenWakeWordRunner | None:
        if self._oww_runner is not None:
            return self._oww_runner
        if not self._oww_pkg_ok or self._oww_paths is None:
            return None
        try:
            hey_p, mel_p, emb_p = self._oww_paths
            if not self._verify_model_files(hey_p, mel_p, emb_p):
                return None
            self._oww_runner = _OpenWakeWordRunner(hey_p, mel_p, emb_p)
            return self._oww_runner
        except Exception as exc:
            self._logger.warning("voice.openwakeword_load_failed", error=str(exc))
            return None

    def _ensure_stt_loaded(self) -> Any:
        if self._whisper_model is not None:
            return self._whisper_model
        if self._whisper_path is None:
            return None
        if not self._verify_model_files(self._whisper_path / "model.bin"):
            return None
        from faster_whisper import WhisperModel

        self._whisper_model = WhisperModel(
            str(self._whisper_path),
            device="cpu",
            compute_type="int8",
            cpu_threads=4,
            local_files_only=True,
        )
        return self._whisper_model

    def _ensure_tts_loaded_for_language(self, lang_code: Literal["id", "en"]) -> Any:
        key = lang_code if lang_code in self._piper_voices else "default"
        if key in self._tts_engines:
            return self._tts_engines[key]
        paths = self._piper_voices.get(key)
        if paths is None or not self._tts_pkg_ok:
            return None
        try:
            from piper.voice import PiperVoice

            _dir, onnx_path, cfg_path = paths
            if not self._verify_model_files(onnx_path, cfg_path):
                return None
            engine = PiperVoice.load(str(onnx_path), config_path=str(cfg_path))
            self._tts_engines[key] = engine
            return engine
        except Exception as exc:
            self._logger.warning("voice.tts_load_failed", language=key, error=str(exc))
            return None

    def synthesize_pcm_in_ram(
        self, text: str, *, language_hint: str | None = None
    ) -> tuple[Any, int] | None:
        """Normalize text for speech and synthesize strictly in RAM using language-matched Piper voice (B12)."""
        lang = detect_text_language(
            text, default_lang=language_hint or self._primary_language
        )
        spoken = normalize_text_for_tts(text, language=lang)
        if not spoken:
            return None
        tts = self._ensure_tts_loaded_for_language(lang)
        if tts is None:
            return None
        import numpy as np

        with self._lock:
            rate = self._speech_rate

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            # Respect speech_rate via Piper SynthesisConfig(length_scale) when supported
            syn_cfg = None
            if abs(rate - 1.0) > 0.02:
                with contextlib.suppress(Exception):
                    from piper.config import SynthesisConfig

                    syn_cfg = SynthesisConfig(length_scale=round(1.0 / rate, 3))
            if syn_cfg is not None:
                try:
                    tts.synthesize_wav(spoken, wf, syn_config=syn_cfg)
                except TypeError:
                    tts.synthesize_wav(spoken, wf)
            else:
                tts.synthesize_wav(spoken, wf)
        buf.seek(0)
        with wave.open(buf, "rb") as rf:
            sr = int(rf.getframerate())
            raw_frames = rf.readframes(rf.getnframes())
        samples = np.frombuffer(raw_frames, dtype=np.int16).astype(np.float32) / 32768.0
        return (samples, sr)

    def set_mode(self, mode: VoiceMode) -> LiveVoiceSnapshot:
        with self._lock:
            self._error = None
            if mode == "muted":
                self._stop_capture_locked()
                self._mode = "muted"
                self._phase = "muted"
                self._amplitude = 0.0
                self._live_rms = 0.0
                self._session_active = False
                self._session_until_monotonic = 0.0
                return self.snapshot()

            if not self._deps_ok or not self._mic_ok or self._whisper_path is None:
                self._mode = "muted"
                self._phase = "unavailable"
                self._error = (
                    "Mikrofon atau model STT lokal (faster-whisper) tidak tersedia; gunakan fallback teks."
                )
                return self.snapshot()

            if mode in ("active", "ptt"):
                self._mode = "wake"
                self._session_active = True
                self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS
                self._phase = "listening_command"
            else:
                self._mode = "wake"
                self._session_active = False
                self._session_until_monotonic = 0.0
                self._phase = "standby_wake"

            self._start_capture_locked()
            return self.snapshot()

    def stop_speaking(self) -> int:
        """Immediate generation-guarded barge-in audio cutoff (< 50ms, FR-VOI-04, U-V02)."""
        with self._lock:
            self._playback_generation += 1
            gen = self._playback_generation
            was_speaking = self._speaking
            self._speaking = False
            if was_speaking:
                self._tts_ended_monotonic = time.monotonic()
            self._amplitude = 0.0
            if self._mode != "muted":
                if self._session_active:
                    self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS
                    self._phase = "listening_command"
                else:
                    self._phase = "standby_wake"
        try:
            import sounddevice as sd

            sd.stop()
        except Exception as exc:
            self._logger.debug("voice.stop_speaking_ignored", error=type(exc).__name__)
        return gen

    def speak_async(self, text: str) -> None:
        """Synthesize and play spoken response on a background thread with Echo Guard & generation check."""
        if not text.strip():
            return
        with self._lock:
            self._playback_generation += 1
            gen = self._playback_generation
        threading.Thread(
            target=self._speak_blocking, args=(text, False, gen), daemon=True
        ).start()

    def _play_samples_if_current(self, samples: Any, sr: int, generation: int) -> bool:
        with self._lock:
            if not self._speaking or self._playback_generation != generation:
                return False
            out_dev = self._selected_output_index
        import sounddevice as sd

        sd.play(samples, samplerate=sr, device=out_dev, blocking=True)
        return True

    def _speak_blocking(
        self, text: str, keep_session_alive: bool = False, generation: int | None = None
    ) -> float | None:
        """Sentence-chunked streaming Piper TTS with pre-synthesis lookahead & generation cancellation."""
        chunks = split_sentences_for_tts(text)
        if not chunks:
            return None

        with self._lock:
            if generation is None:
                self._playback_generation += 1
                gen = self._playback_generation
            else:
                gen = generation
            if self._playback_generation != gen:
                return None
            self._speaking = True
            self._phase = "speaking"
            self._amplitude = 0.45

        first_audio_ms: float | None = None
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                next_fut: concurrent.futures.Future[tuple[Any, int] | None] | None = pool.submit(
                    self.synthesize_pcm_in_ram, chunks[0]
                )
                for idx in range(len(chunks)):
                    with self._lock:
                        if not self._speaking or self._playback_generation != gen:
                            break
                    cur_fut = next_fut
                    next_fut = (
                        pool.submit(self.synthesize_pcm_in_ram, chunks[idx + 1])
                        if idx + 1 < len(chunks) and self._speaking
                        else None
                    )
                    if cur_fut is None:
                        continue
                    synthesized = cur_fut.result()
                    if synthesized is not None:
                        samples, sr = synthesized
                        if samples.size > 0:
                            if first_audio_ms is None:
                                first_audio_ms = time.monotonic() * 1000.0
                            if not self._play_samples_if_current(samples, sr, gen):
                                break
        except Exception as exc:
            self._logger.warning("voice.tts_speak_failed", error=str(exc))
        finally:
            self._finish_speaking_state(keep_session_alive=keep_session_alive, generation=gen)
        return first_audio_ms

    def _finish_speaking_state(
        self, *, keep_session_alive: bool, generation: int | None = None
    ) -> None:
        with self._lock:
            if generation is not None and self._playback_generation != generation:
                return
            self._speaking = False
            self._tts_ended_monotonic = time.monotonic()
            self._amplitude = 0.0
            if self._mode == "muted":
                self._phase = "muted"
            elif keep_session_alive or self._session_active:
                self._session_active = True
                self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS
                self._phase = "listening_command"
            else:
                self._phase = "standby_wake"

    def _consume_streaming_tts_queue(
        self,
        sentence_q: queue.Queue[str | None],
        generation: int,
        audio_start_box: list[float],
    ) -> None:
        """Play streamed LLM sentences through Piper TTS as soon as each sentence completes."""
        started_audio = False
        try:
            while True:
                item = sentence_q.get()
                if item is None:
                    break
                with self._lock:
                    if self._playback_generation != generation:
                        continue
                    if started_audio and not self._speaking:
                        continue
                synthesized = self.synthesize_pcm_in_ram(item)
                if synthesized is None:
                    continue
                samples, sr = synthesized
                if samples.size == 0:
                    continue
                with self._lock:
                    if self._playback_generation != generation:
                        continue
                    if not started_audio:
                        self._speaking = True
                        self._phase = "speaking"
                        self._amplitude = 0.45
                        started_audio = True
                    elif not self._speaking:
                        continue
                if not audio_start_box:
                    audio_start_box.append(time.monotonic() * 1000.0)
                if not self._play_samples_if_current(samples, sr, generation):
                    break
        except Exception as exc:
            self._logger.warning("voice.streaming_tts_failed", error=str(exc))
        finally:
            if started_audio:
                self._finish_speaking_state(keep_session_alive=True, generation=generation)

    def shutdown(self) -> None:
        self.stop_speaking()
        with self._lock:
            self._stop_capture_locked()
            self._mode = "muted"
            self._phase = "muted"
            self._session_active = False

    def _start_capture_locked(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        self._stop_event.clear()
        for q_obj in (self._audio_queue, self._utterance_queue):
            while not q_obj.empty():
                try:
                    q_obj.get_nowait()
                except queue.Empty:
                    break

        def _audio_cb(indata: Any, _frames: int, _time_info: Any, _status: Any) -> None:
            if self._stop_event.is_set():
                return
            try:
                self._audio_queue.put_nowait(indata[:, 0].copy())
            except queue.Full:
                self._queue_overflow_drops += 1

        self._stream = sd.InputStream(
            device=self._selected_input_index,
            samplerate=self.SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocksize=self.BLOCK_SAMPLES,
            callback=_audio_cb,
        )
        self._stream.start()
        self._capture_thread = threading.Thread(
            target=self._capture_loop, name="jarvis-voice-capture", daemon=True
        )
        self._stt_thread = threading.Thread(
            target=self._stt_turn_worker_loop, name="jarvis-voice-stt", daemon=True
        )
        self._capture_thread.start()
        self._stt_thread.start()

    def _stop_capture_locked(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as exc:
                self._logger.debug("voice.stream_close_ignored", error=type(exc).__name__)
            self._stream = None

    def _capture_loop(self) -> None:
        import numpy as np

        vad = self._ensure_vad_loaded()
        oww = self._ensure_oww_loaded()
        blocks_per_sec = self.SAMPLE_RATE / self.BLOCK_SAMPLES  # 31.25 frames/sec
        segmenter = VoiceUtteranceSegmenter(
            frame_ms=(self.BLOCK_SAMPLES / self.SAMPLE_RATE) * 1000.0,
            pre_roll_frames=self.PRE_ROLL_FRAMES,
            min_voiced_frames=max(1, int(self.MIN_SPEECH_SECONDS * blocks_per_sec)),
            silence_end_frames=max(1, int(self.SILENCE_END_SECONDS * blocks_per_sec)),
            max_utterance_frames=int(self.MAX_UTTERANCE_SECONDS * blocks_per_sec),
        )
        oww_pending_follow_until = 0.0
        speech_start_ms = 0.0

        while not self._stop_event.is_set():
            try:
                chunk = self._audio_queue.get(timeout=0.15)
            except queue.Empty:
                now_q = time.monotonic()
                if oww_pending_follow_until > 0.0 and now_q >= oww_pending_follow_until and not segmenter.in_speech:
                    oww_pending_follow_until = 0.0
                    self._acknowledge_wake_only()
                with self._lock:
                    if (
                        self._session_active
                        and self._phase == "listening_command"
                        and now_q >= self._session_until_monotonic
                        and not segmenter.in_speech
                    ):
                        self._session_active = False
                        self._phase = "standby_wake" if self._mode != "muted" else "muted"
                continue

            now_m = time.monotonic()
            # DC-offset high-pass cleanup & clipping/level diagnostics
            chunk = chunk - float(np.mean(chunk))
            peak = float(np.max(np.abs(chunk))) if chunk.size else 0.0
            rms = float(math.sqrt(float(np.mean(chunk * chunk)))) if chunk.size else 0.0
            if peak >= 0.98:
                self._clipping_events += 1

            with self._lock:
                eg_decision = self._current_echo_guard_decision(now_m)
                is_speaking_now = self._speaking
                self._live_rms = rms
                self._amplitude = min(1.0, rms * 14.0)
                if not segmenter.in_speech and not is_speaking_now:
                    self._noise_floor_rms = (self._noise_floor_rms * 0.95) + (rms * 0.05)
                if (
                    self._session_active
                    and self._phase == "listening_command"
                    and now_m >= self._session_until_monotonic
                    and not segmenter.in_speech
                ):
                    self._session_active = False
                    self._phase = "standby_wake" if self._mode != "muted" else "muted"
                session_awake = self._session_active

            # Endpoint-Aware Echo Guard (open speakers gated during playback + tail; headsets allow voice barge-in!)
            if not eg_decision.allow_mic_wake_or_vad:
                segmenter.reset()
                oww_pending_follow_until = 0.0
                if vad is not None:
                    vad.reset()
                if oww is not None:
                    oww.reset()
                continue

            # Neural Silero VAD primary detection (with adaptive floor)
            noise_gate = max(0.004, self._noise_floor_rms * 1.4)
            if vad is not None and len(chunk) == self.BLOCK_SAMPLES:
                is_voice = (rms >= noise_gate) and (vad.speech_prob(chunk) >= self.VAD_SPEECH_THRESHOLD)
            else:
                is_voice = rms >= max(self.RMS_FALLBACK_THRESHOLD, noise_gate * 1.5)

            # Headset full-duplex voice barge-in: user speaks during TTS -> immediately halt playback!
            if is_voice and is_speaking_now and eg_decision.allow_voice_barge_in:
                self.stop_speaking()

            # FAST 80ms openWakeWord path when STANDBY (0 Whisper calls on room chatter!)
            if not session_awake and oww is not None:
                score = oww.push_float32_and_max_score(chunk)
                if score >= self.OWW_WAKE_THRESHOLD and (now_m - self._last_oww_trigger_monotonic) >= 1.5:
                    self._last_oww_trigger_monotonic = now_m
                    oww.reset()
                    segmenter.reset()
                    with self._lock:
                        self._session_active = True
                        self._session_until_monotonic = now_m + self.ACTIVE_SESSION_SECONDS + 3.0
                        self._phase = "listening_command"
                    oww_pending_follow_until = now_m + self.POST_WAKE_FOLLOW_SECONDS
                    self._logger.info("voice.openwakeword.triggered", score=round(score, 3))
                continue

            if oww_pending_follow_until > 0.0:
                if is_voice:
                    oww_pending_follow_until = 0.0
                elif now_m >= oww_pending_follow_until:
                    oww_pending_follow_until = 0.0
                    self._acknowledge_wake_only()
                    continue

            if is_voice and not segmenter.in_speech:
                speech_start_ms = now_m * 1000.0

            flush = segmenter.push_frame(chunk, is_voice=is_voice)
            if flush is None:
                continue

            if vad is not None:
                vad.reset()
            if not flush.accepted:
                # Below min_voiced_frames (click / transient) -> silently discarded!
                continue

            pcm_audio = np.concatenate(flush.frames)
            with self._lock:
                gen = self._playback_generation
            queued = _QueuedUtterance(
                pcm_audio=pcm_audio,
                voiced_duration_ms=flush.voiced_duration_ms,
                t_capture_start_ms=speech_start_ms or (now_m * 1000.0),
                t_end_speech_ms=now_m * 1000.0,
                generation=gen,
            )
            try:
                self._utterance_queue.put_nowait(queued)
            except queue.Full:
                self._utterance_drops += 1
                with contextlib.suppress(queue.Empty):
                    self._utterance_queue.get_nowait()
                with contextlib.suppress(queue.Full):
                    self._utterance_queue.put_nowait(queued)

    def _stt_turn_worker_loop(self) -> None:
        """Dedicated STT & turn dispatch thread decoupled from audio capture (B11)."""
        while not self._stop_event.is_set():
            try:
                item = self._utterance_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._process_utterance_audio(item)

    def _acknowledge_wake_only(self) -> None:
        with self._lock:
            self._last_transcript = "Hey Jarvis"
            self._last_reply = "Ya, siap. Ada yang bisa saya bantu?"
            self._session_active = True
            self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS + 3.0
        self._speak_blocking("Ya, siap. Ada yang bisa saya bantu?", keep_session_alive=True)

    def _build_dynamic_stt_prompt(self) -> str:
        app_names: tuple[str, ...] = ()
        recent_files: tuple[str, ...] = ()
        if self._hotword_provider is not None:
            with contextlib.suppress(Exception):
                app_names, recent_files = self._hotword_provider()
        return build_scoped_stt_prompt(app_names, recent_files)

    def _process_utterance_audio(self, item: _QueuedUtterance) -> None:
        with self._lock:
            current_mode = self._mode
            session_is_awake = self._session_active and time.monotonic() < self._session_until_monotonic
            if current_mode == "muted":
                return
            self._phase = "transcribing"
            multilingual = self._multilingual_enabled
            primary_lang = self._primary_language

        req_id = f"vreq_{uuid.uuid4().hex[:10]}"
        detected_lang = primary_lang[:2].lower()
        avg_logprob: float | None = None
        no_speech_prob: float | None = None
        try:
            model = self._ensure_stt_loaded()
            if model is None:
                return
            lang_arg = None if multilingual else primary_lang[:2].lower()
            segments_iter, info = model.transcribe(
                item.pcm_audio,
                language=lang_arg,
                beam_size=3,
                vad_filter=False,
                condition_on_previous_text=False,
                initial_prompt=self._build_dynamic_stt_prompt(),
            )
            seg_list = list(segments_iter)
            transcript = " ".join(seg.text.strip() for seg in seg_list).strip()
            detected_lang = str(getattr(info, "language", detected_lang) or detected_lang)
            if seg_list:
                lps = [float(getattr(s, "avg_logprob", -0.3)) for s in seg_list]
                nsps = [float(getattr(s, "no_speech_prob", 0.0)) for s in seg_list]
                avg_logprob = sum(lps) / len(lps)
                no_speech_prob = sum(nsps) / len(nsps)
        except Exception as exc:
            self._logger.warning("voice.stt_error", error=str(exc))
            with self._lock:
                self._phase = "listening_command" if session_is_awake else "standby_wake"
            return

        t_stt_final_ms = time.monotonic() * 1000.0
        conf_decision = evaluate_stt_confidence(
            SttAcousticEvidence(
                text=transcript,
                detected_language=detected_lang,
                avg_logprob=avg_logprob,
                no_speech_prob=no_speech_prob,
                voiced_duration_ms=item.voiced_duration_ms,
            ),
            is_actionable_intent=_ACTIONABLE_HINT_RE.search(transcript) is not None,
            primary_language=primary_lang,
        )

        with self._lock:
            self._last_confidence = conf_decision.confidence
            self._last_detected_language = detected_lang

        if conf_decision.action == "discard" or is_whisper_hallucination(transcript):
            with self._lock:
                if session_is_awake:
                    self._phase = "listening_command"
                else:
                    self._phase = "standby_wake" if self._mode != "muted" else "muted"
            return

        if conf_decision.action == "clarify" and conf_decision.clarification_prompt:
            with self._lock:
                self._last_transcript = transcript
                self._last_reply = conf_decision.clarification_prompt
                self._last_route_kind = "voice.low_confidence_clarify"
                self._last_llm_called = False
            audio_ms = self._speak_blocking(
                conf_decision.clarification_prompt, keep_session_alive=True
            )
            self._record_trace(
                VoiceTimingTrace(
                    request_id=req_id,
                    transcript=transcript,
                    detected_language=detected_lang,
                    confidence=conf_decision.confidence,
                    route_kind="voice.low_confidence_clarify",
                    t_capture_start_ms=item.t_capture_start_ms,
                    t_end_speech_ms=item.t_end_speech_ms,
                    t_stt_final_ms=t_stt_final_ms,
                    t_audio_start_ms=audio_ms,
                    t_turn_done_ms=time.monotonic() * 1000.0,
                )
            )
            return

        # Branch A: STANDBY fallback (when openWakeWord assets are absent)
        command_text = transcript
        if not session_is_awake:
            woke, stripped = extract_wake_command(transcript)
            if not woke:
                with self._lock:
                    self._phase = "standby_wake"
                return
            if not stripped:
                self._acknowledge_wake_only()
                return
            command_text = stripped
        else:
            stripped = strip_optional_wake_prefix(transcript)
            if not stripped:
                with self._lock:
                    self._session_active = True
                    self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS + 2.0
                    self._last_reply = "Ya, saya masih mendengarkan."
                self._speak_blocking("Ya, saya masih mendengarkan.", keep_session_alive=True)
                return
            command_text = stripped

        if is_sleep_command(command_text):
            with self._lock:
                self._last_transcript = command_text
                self._last_reply = "Baik, saya kembali siaga."
                self._last_route_kind = "voice.sleep"
                self._last_llm_called = False
                self._session_active = False
                self._session_until_monotonic = 0.0
            self._speak_blocking("Baik, saya kembali siaga.", keep_session_alive=False)
            return

        # Dispatch clean command with generation-guarded parallel LLM SSE -> Sentence Queue -> Piper TTS!
        with self._lock:
            self._last_transcript = command_text
            self._session_active = True
            self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS + 10.0
            self._phase = "thinking"
            self._playback_generation += 1
            turn_gen = self._playback_generation

        t_route_ms = time.monotonic() * 1000.0
        reply_text = ""
        route_kind = ""
        llm_called = False
        audio_start_box: list[float] = []

        if self._stream_turn_callback is not None and self._loop is not None:
            sentence_q: queue.Queue[str | None] = queue.Queue()
            tts_thread = threading.Thread(
                target=self._consume_streaming_tts_queue,
                args=(sentence_q, turn_gen, audio_start_box),
                daemon=True,
            )
            tts_thread.start()
            emitted_any = False

            def _on_sentence(sent: str) -> None:
                nonlocal emitted_any
                emitted_any = True
                sentence_q.put(sent)

            try:
                fut: concurrent.futures.Future[tuple[str, str, bool]] = asyncio.run_coroutine_threadsafe(
                    self._stream_turn_callback(command_text, _on_sentence), self._loop
                )
                reply_text, route_kind, llm_called = fut.result(timeout=65.0)
            except Exception as exc:
                reply_text = f"Maaf, terjadi gangguan saat memproses perintah: {type(exc).__name__}."
                route_kind = "error"
                if not emitted_any:
                    sentence_q.put(reply_text)
            finally:
                sentence_q.put(None)

            with self._lock:
                self._last_reply = reply_text
                self._last_route_kind = route_kind
                self._last_llm_called = llm_called

            tts_thread.join(timeout=60.0)
            self._record_trace(
                VoiceTimingTrace(
                    request_id=req_id,
                    transcript=command_text,
                    detected_language=detected_lang,
                    confidence=conf_decision.confidence,
                    route_kind=route_kind,
                    t_capture_start_ms=item.t_capture_start_ms,
                    t_end_speech_ms=item.t_end_speech_ms,
                    t_stt_final_ms=t_stt_final_ms,
                    t_route_ms=t_route_ms,
                    t_audio_start_ms=audio_start_box[0] if audio_start_box else None,
                    t_turn_done_ms=time.monotonic() * 1000.0,
                )
            )
            with self._lock:
                if not self._speaking and self._mode != "muted":
                    self._session_active = True
                    self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS
                    self._phase = "listening_command"
            return

        # Fallback non-streaming callback path
        try:
            if self._loop is not None:
                fut_std: concurrent.futures.Future[tuple[str, str, bool]] = asyncio.run_coroutine_threadsafe(
                    self._turn_callback(command_text), self._loop
                )
                reply_text, route_kind, llm_called = fut_std.result(timeout=65.0)
        except Exception as exc:
            reply_text = f"Maaf, terjadi gangguan saat memproses perintah: {type(exc).__name__}."
            route_kind = "error"

        with self._lock:
            self._last_reply = reply_text
            self._last_route_kind = route_kind
            self._last_llm_called = llm_called

        fallback_audio_ms: float | None = None
        if reply_text:
            fallback_audio_ms = self._speak_blocking(
                reply_text, keep_session_alive=True, generation=turn_gen
            )
        else:
            with self._lock:
                self._session_active = True
                self._session_until_monotonic = time.monotonic() + self.ACTIVE_SESSION_SECONDS
                self._phase = "listening_command"

        self._record_trace(
            VoiceTimingTrace(
                request_id=req_id,
                transcript=command_text,
                detected_language=detected_lang,
                confidence=conf_decision.confidence,
                route_kind=route_kind,
                t_capture_start_ms=item.t_capture_start_ms,
                t_end_speech_ms=item.t_end_speech_ms,
                t_stt_final_ms=t_stt_final_ms,
                t_route_ms=t_route_ms,
                t_audio_start_ms=fallback_audio_ms,
                t_turn_done_ms=time.monotonic() * 1000.0,
            )
        )

    def _record_trace(self, trace: VoiceTimingTrace) -> None:
        with self._lock:
            self._recent_traces.appendleft(trace)
