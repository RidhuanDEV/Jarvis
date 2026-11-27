"""Adaptive Voice Pipeline Orchestrator: Audio Hotplug, Ring Buffer, Echo Guard, STT & TTS Fallback (B05)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from jarvis.application.config_service import ConfigService
from jarvis.domain.ai_models import SttProviderPort, SttResult, TtsProviderPort, TtsResult, TtsVoiceInfo
from jarvis.domain.models import AudioEndpointInfo, ErrorCode
from jarvis.domain.ports import AudioDevicePort, ClockPort
from jarvis.domain.voice import (
    BoundedAudioRingBuffer,
    EchoGuardDecision,
    EndpointAwareEchoGuard,
    normalize_text_for_tts,
    split_sentences_for_streaming_tts,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class LiveVoiceRuntimeHook(Protocol):
    """Port unifying VoicePipelineService configuration/lifecycle with the live audio runtime (B11, NFR-16)."""

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
    ) -> None: ...

    def on_runtime_mode_changed(self, mode: Literal["muted", "ptt", "wake"]) -> None: ...

    def stop_speaking(self) -> int | None: ...


class VoiceServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class VoiceStateSnapshot:
    mode: Literal["muted", "ptt", "wake"]
    input_device_id: str | None
    output_device_id: str | None
    echo_guard_enabled: bool
    is_tts_playing: bool
    ring_buffer_seconds: float
    echo_guard_decision: EchoGuardDecision
    installed_voices: tuple[TtsVoiceInfo, ...]
    endpoints: tuple[AudioEndpointInfo, ...]


class VoicePipelineService:
    """Coordinates dynamic audio endpoints, RAM-only ring buffer, echo guard, STT, and TTS fallback."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        audio_port: AudioDevicePort,
        clock: ClockPort,
        event_bus: SequencedEventBus,
        *,
        stt_provider: SttProviderPort | None = None,
        tts_providers: tuple[TtsProviderPort, ...] = (),
        live_hook: LiveVoiceRuntimeHook | None = None,
    ) -> None:
        self._db = db
        self._config = config_service
        self._audio = audio_port
        self._clock = clock
        self._bus = event_bus
        self._stt = stt_provider
        self._tts_providers = tts_providers
        self._live_hook = live_hook
        self._ring_buffer = BoundedAudioRingBuffer()
        self._echo_guard = EndpointAwareEchoGuard()
        self._is_tts_playing = False
        self._ms_since_tts_ended: float | None = None

    def bind_live_hook(self, hook: LiveVoiceRuntimeHook) -> None:
        """Bind the unified live voice runtime and push current audio/locale configuration immediately."""
        self._live_hook = hook
        self._sync_live_runtime_config()

    def _active_input_endpoint(self) -> AudioEndpointInfo | None:
        cfg = self._config.get_active().document.audio
        endpoints = self._audio.list_endpoints()
        if cfg.input_device_id:
            for ep in endpoints:
                if ep.id == cfg.input_device_id and ep.direction == "input":
                    return ep
        return next((ep for ep in endpoints if ep.direction == "input" and ep.is_default), None)

    def _sync_live_runtime_config(self) -> None:
        if self._live_hook is None:
            return
        doc = self._config.get_active().document
        in_ep = self._active_input_endpoint()
        out_ep = self._active_output_endpoint()
        self._live_hook.sync_audio_config(
            input_device_name=in_ep.name if in_ep is not None else None,
            output_device_name=out_ep.name if out_ep is not None else None,
            output_endpoint=out_ep,
            echo_guard_enabled=doc.audio.echo_guard_enabled,
            speech_rate=doc.audio.speech_rate,
            primary_language=doc.locale.primary_language,
            multilingual_enabled=doc.locale.multilingual_enabled,
        )

    def _active_output_endpoint(self) -> AudioEndpointInfo | None:
        cfg = self._config.get_active().document.audio
        endpoints = self._audio.list_endpoints()
        if cfg.output_device_id:
            for ep in endpoints:
                if ep.id == cfg.output_device_id and ep.direction == "output":
                    return ep
        return next((ep for ep in endpoints if ep.direction == "output" and ep.is_default), None)

    def get_state(self) -> VoiceStateSnapshot:
        cfg = self._config.get_active().document.audio
        endpoints = self._audio.list_endpoints()
        output_ep = self._active_output_endpoint()
        guard_dec = self._echo_guard.evaluate(
            output_endpoint=output_ep,
            is_tts_playing=self._is_tts_playing,
            ms_since_tts_ended=self._ms_since_tts_ended,
            echo_guard_enabled=cfg.echo_guard_enabled,
        )
        voices: list[TtsVoiceInfo] = []
        for tts in self._tts_providers:
            voices.extend(tts.list_installed_voices())

        return VoiceStateSnapshot(
            mode=cfg.mode,
            input_device_id=cfg.input_device_id,
            output_device_id=cfg.output_device_id,
            echo_guard_enabled=cfg.echo_guard_enabled,
            is_tts_playing=self._is_tts_playing,
            ring_buffer_seconds=round(self._ring_buffer.duration_seconds(), 3),
            echo_guard_decision=guard_dec,
            installed_voices=tuple(voices),
            endpoints=endpoints,
        )

    def set_mode(
        self,
        mode: Literal["muted", "ptt", "wake"],
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> VoiceStateSnapshot:
        if mode == "muted":
            self._ring_buffer.clear()
        active = self._config.get_active().document
        updated = active.model_copy(update={"audio": active.audio.model_copy(update={"mode": mode})})
        self._config.save_revision(updated, source="user", correlation_id=correlation_id, actor=actor)
        self._sync_live_runtime_config()
        if self._live_hook is not None:
            self._live_hook.on_runtime_mode_changed(mode)
        self._bus.publish(
            event_type="voice.state_changed",
            correlation_id=correlation_id,
            payload={"mode": mode},
        )
        return self.get_state()

    def select_devices(
        self,
        *,
        input_device_id: str | None,
        output_device_id: str | None,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> VoiceStateSnapshot:
        endpoints = {ep.id: ep for ep in self._audio.list_endpoints()}
        if input_device_id is not None and (
            input_device_id not in endpoints or endpoints[input_device_id].direction != "input"
        ):
            raise VoiceServiceError(ErrorCode.NOT_FOUND, f"Input audio device '{input_device_id}' not found.")
        if output_device_id is not None and (
            output_device_id not in endpoints or endpoints[output_device_id].direction != "output"
        ):
            raise VoiceServiceError(ErrorCode.NOT_FOUND, f"Output audio device '{output_device_id}' not found.")

        active = self._config.get_active().document
        updated = active.model_copy(
            update={
                "audio": active.audio.model_copy(
                    update={"input_device_id": input_device_id, "output_device_id": output_device_id}
                )
            }
        )
        self._config.save_revision(updated, source="user", correlation_id=correlation_id, actor=actor)
        self._sync_live_runtime_config()
        self._bus.publish(
            event_type="audio.devices_changed",
            correlation_id=correlation_id,
            payload={"input_device_id": input_device_id, "output_device_id": output_device_id},
        )
        return self.get_state()

    def ingest_mic_frame(
        self, pcm16_frame: bytes, *, is_ptt_pressed: bool = False
    ) -> tuple[bool, EchoGuardDecision]:
        """Accept a 16kHz PCM frame into the <=2s RAM ring buffer subject to mute & Echo Guard."""
        cfg = self._config.get_active().document.audio
        output_ep = self._active_output_endpoint()
        decision = self._echo_guard.evaluate(
            output_endpoint=output_ep,
            is_tts_playing=self._is_tts_playing,
            ms_since_tts_ended=self._ms_since_tts_ended,
            echo_guard_enabled=cfg.echo_guard_enabled,
        )
        if cfg.mode == "muted":
            self._ring_buffer.clear()
            return (False, decision)
        if is_ptt_pressed and decision.allow_ptt_or_ui_barge_in:
            self._is_tts_playing = False
            self._ring_buffer.append_frame(pcm16_frame)
            return (True, decision)
        if not decision.allow_mic_wake_or_vad:
            return (False, decision)
        self._ring_buffer.append_frame(pcm16_frame)
        return (True, decision)

    def set_tts_playback_state(self, *, playing: bool, ms_since_ended: float | None = None) -> None:
        self._is_tts_playing = playing
        self._ms_since_tts_ended = None if playing else ms_since_ended

    def on_session_locked(self) -> None:
        """Immediately halt playback and wipe RAM audio pre-roll on OS lock/suspend (BR-13, BR-21)."""
        self._is_tts_playing = False
        self._ring_buffer.clear()
        if self._live_hook is not None:
            self._live_hook.stop_speaking()
            self._live_hook.on_runtime_mode_changed("muted")

    def transcribe_buffer(self, *, language_hint: str | None = None) -> SttResult:
        if self._stt is None:
            raise VoiceServiceError(
                ErrorCode.RUNTIME_UNAVAILABLE, "No STT provider is currently configured."
            )
        pcm = self._ring_buffer.snapshot_bytes()
        if not pcm:
            raise VoiceServiceError(ErrorCode.INVALID_ARGS, "Audio buffer is empty.")
        lang = language_hint or self._config.get_active().document.locale.primary_language
        return self._stt.transcribe_pcm16(pcm, language_hint=lang)

    def synthesize_response(self, text: str, *, voice_id: str | None = None) -> list[TtsResult]:
        """Synthesize short normalized sentences using first available working offline TTS engine (B12)."""
        doc = self._config.get_active().document
        normalized = normalize_text_for_tts(text, language=doc.locale.primary_language)
        sentences = split_sentences_for_streaming_tts(normalized)
        if not sentences:
            return []
        rate = doc.audio.speech_rate
        for provider in self._tts_providers:
            installed = [v for v in provider.list_installed_voices() if v.installed]
            if not installed:
                continue
            chosen_voice = voice_id or installed[0].id
            try:
                return [provider.synthesize(s, voice_id=chosen_voice, rate=rate) for s in sentences]
            except RuntimeError:
                continue
        raise VoiceServiceError(
            ErrorCode.RUNTIME_UNAVAILABLE,
            "No active offline TTS synthesis engine is ready on this device.",
        )

    def run_self_test(self, *, correlation_id: str) -> dict[str, object]:
        state = self.get_state()
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'audio.self_test', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps(
                        {
                            "endpoint_count": len(state.endpoints),
                            "installed_voices": len([v for v in state.installed_voices if v.installed]),
                        }
                    ),
                    now_iso,
                ),
            )
        return {
            "mode": state.mode,
            "endpoint_count": len(state.endpoints),
            "installed_voice_count": len([v for v in state.installed_voices if v.installed]),
            "echo_guard_ready": True,
            "stt_configured": self._stt is not None,
        }
