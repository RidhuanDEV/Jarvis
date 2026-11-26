"""Pure Voice Domain Primitives: 2s RAM Ring Buffer, Endpoint-Aware Echo Guard & Sentence Chunker (B05, BR-13, DEC-028)."""

from __future__ import annotations

import re
from dataclasses import dataclass

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
