"""Stage G3 Voice Reconstruction Integration & Precision/Recall Suite (B11, B12, U-V01, U-V02)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.domain.models import AudioEndpointInfo
from jarvis.domain.voice import (
    SttAcousticEvidence,
    VoiceUtteranceSegmenter,
    build_scoped_stt_prompt,
    detect_text_language,
    evaluate_stt_confidence,
    normalize_text_for_tts,
)
from jarvis.platform.portable_mock import (
    FakeDesktopAutomationAdapter,
    FakeFileOpenerAdapter,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    StaticApplicationCatalogAdapter,
    StaticAudioDeviceAdapter,
)
from jarvis.platform.windows.audio import WindowsOneCoreVoiceProbeAdapter
from jarvis.transport.app import build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings


def test_b11_u_v01_voiced_only_segmenter_blocks_clicks_and_passes_real_speech() -> None:
    """DEF-17 regression: 1..3-frame clicks padded with pre-roll & trailing silence MUST NOT fire STT."""
    seg = VoiceUtteranceSegmenter(
        frame_ms=32.0,
        pre_roll_frames=10,
        min_voiced_frames=9,  # 288ms real speech
        silence_end_frames=22,
        max_utterance_frames=375,
    )

    # 1. Pre-roll silence (10 frames) + short mouse click (2 voiced frames) + 22 silence frames = 34 total frames!
    for _ in range(10):
        assert seg.push_frame(b"sil", is_voice=False) is None
    for _ in range(2):
        assert seg.push_frame(b"clk", is_voice=True) is None

    flush = None
    for _ in range(22):
        res = seg.push_frame(b"sil", is_voice=False)
        if res is not None:
            flush = res
            break

    assert flush is not None
    assert flush.accepted is False
    assert flush.voiced_frames == 2
    assert flush.total_frames == 34  # Old buggy code checked len(buffered) >= 9 -> FALSE TRIGGER!
    assert flush.reason == "below_min_voiced_duration"

    # 2. Real speech (12 voiced frames with brief 3-frame mid-word pause) + 22 silence frames -> ACCEPTED with pre-roll!
    for _ in range(5):
        assert seg.push_frame(b"pre", is_voice=False) is None
    for _ in range(6):
        assert seg.push_frame(b"v1", is_voice=True) is None
    for _ in range(3):
        assert seg.push_frame(b"gap", is_voice=False) is None
    for _ in range(6):
        assert seg.push_frame(b"v2", is_voice=True) is None

    speech_flush = None
    for _ in range(22):
        res = seg.push_frame(b"end", is_voice=False)
        if res is not None:
            speech_flush = res
            break

    assert speech_flush is not None
    assert speech_flush.accepted is True
    assert speech_flush.voiced_frames == 12
    assert speech_flush.voiced_duration_ms == pytest.approx(384.0, abs=0.5)
    assert speech_flush.frames[:5] == (b"pre",) * 5  # Pre-roll intact!


def test_b11_stt_confidence_gate_precision_recall_and_scoped_hotwords() -> None:
    # 1. High no_speech_prob or Whisper hallucination -> silent discard (0 action, 0 apology spam)
    d_hall = evaluate_stt_confidence(
        SttAcousticEvidence(
            text="Terima kasih telah menonton!",
            detected_language="id",
            avg_logprob=-0.2,
            no_speech_prob=0.1,
            voiced_duration_ms=900.0,
        ),
        is_actionable_intent=False,
    )
    assert d_hall.action == "discard"

    d_nospeech = evaluate_stt_confidence(
        SttAcousticEvidence(
            text="buka chrome",
            detected_language="id",
            avg_logprob=-0.4,
            no_speech_prob=0.81,
            voiced_duration_ms=500.0,
        ),
        is_actionable_intent=True,
    )
    assert d_nospeech.action == "discard"

    # 2. Marginal confidence on actionable command -> ask clarification (NEVER guess!)
    d_clarify = evaluate_stt_confidence(
        SttAcousticEvidence(
            text="buka catatan",
            detected_language="id",
            avg_logprob=-0.95,
            no_speech_prob=0.35,
            voiced_duration_ms=450.0,
        ),
        is_actionable_intent=True,
    )
    assert d_clarify.action == "clarify"
    assert d_clarify.clarification_prompt is not None and "buka catatan" in d_clarify.clarification_prompt

    # 3. Clean speech -> accept
    d_ok = evaluate_stt_confidence(
        SttAcousticEvidence(
            text="Buka kalkulator.",
            detected_language="id",
            avg_logprob=-0.22,
            no_speech_prob=0.04,
            voiced_duration_ms=640.0,
        ),
        is_actionable_intent=True,
    )
    assert d_ok.action == "accept"
    assert d_ok.confidence >= 0.85

    # 4. Scoped hotwords bounded cleanly (never dumps full disk!)
    prompt = build_scoped_stt_prompt(
        tuple(f"App{i}" for i in range(50)),
        tuple(f"Doc{i}.pdf" for i in range(20)),
        max_chars=420,
    )
    assert len(prompt) <= 420
    assert "App0" in prompt and "App49" not in prompt


def test_b12_bilingual_tts_normalizer_and_honest_onecore_provider() -> None:
    # 1. Strips markdown, raw paths, URLs, <think> tags, and raw tool JSON cleanly
    assert normalize_text_for_tts('<think>hidden</think>{"steps":[{"tool_id":"os.volume.set"}]}') == ""

    id_spoken = normalize_text_for_tts(
        "**J.A.R.V.I.S.** membuka `C:\\Users\\Demo\\Documents\\Laporan_Pajak_2026.pdf` pukul 05:35 (45% CPU) di https://docs.example.com/guide.",
        language="id-ID",
    )
    assert "**" not in id_spoken and "`" not in id_spoken
    assert "C:\\" not in id_spoken and "\\" not in id_spoken
    assert "Jarvis" in id_spoken
    assert "file Laporan Pajak 2026 P D F" in id_spoken
    assert "05 lewat 35" in id_spoken
    assert "45 persen" in id_spoken
    assert "C P U" in id_spoken
    assert "tautan docs.example.com" in id_spoken

    en_spoken = normalize_text_for_tts(
        "Opened Finance/Budget_Q4.pdf at 75% GPU usage — see [Report](https://example.org/r).",
        language="en-US",
    )
    assert "[" not in en_spoken and "](" not in en_spoken
    assert "file Budget Q4 P D F" in en_spoken
    assert "75 percent" in en_spoken
    assert "G P U" in en_spoken

    # 2. Language detection distinguishes Indonesian vs English cleanly
    assert detect_text_language("Aplikasi Kalkulator berhasil dibuka untuk Anda.") == "id"
    assert detect_text_language("The current local time is ready for your request.") == "en"

    # 3. Honest Windows OneCore provider: NEVER returns 44-byte fake silent WAV & fixes BSD mislabel!
    onecore = WindowsOneCoreVoiceProbeAdapter()
    for voice in onecore.list_installed_voices():
        assert voice.license_spdx == "Proprietary-Windows-OS"
    with pytest.raises(RuntimeError, match="unavailable"):
        onecore.synthesize("Halo Monarch")


def test_b11_u_v02_unified_voice_service_device_switch_barge_in_lock_and_replay(tmp_path: Path) -> None:
    token = "v" * 64
    settings = CoreStartupSettings(
        env="test",
        log_level="WARNING",
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
        auth_token=token,
    )
    audio_adapter = StaticAudioDeviceAdapter(
        endpoints=(
            AudioEndpointInfo(id="mic-usb", name="USB Desk Mic", direction="input", is_default=True, form_factor="microphone"),
            AudioEndpointInfo(id="mic-headset", name="Bluetooth Headset Mic", direction="input", is_default=False, form_factor="headset"),
            AudioEndpointInfo(id="spk-open", name="Desktop Speakers", direction="output", is_default=True, form_factor="speakers"),
            AudioEndpointInfo(id="hp-studio", name="Studio Headphones", direction="output", is_default=False, form_factor="headphones"),
        )
    )
    fake_desktop = FakeDesktopAutomationAdapter()
    container = build_default_container(
        settings,
        fs_port=PortableFilesystemSafetyAdapter(),
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
        audio_port=audio_adapter,
        desktop_port=fake_desktop,
        app_catalog=StaticApplicationCatalogAdapter(),
        file_opener=FakeFileOpenerAdapter(),
        tier1_auto_allow=True,
    )
    app = create_app(container)
    headers = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:47123"}

    with TestClient(app) as client:
        # 1. Initial Voice Lab diagnostics show speakers (open-speaker echo guard active, voice barge-in False)
        diag1 = client.get("/v1/voice/diagnostics", headers=headers)
        assert diag1.status_code == 200
        d1 = diag1.json()["diagnostics"]
        assert d1["output_form_factor"] == "speakers"
        assert d1["voice_barge_in_allowed"] is False

        # 2. Switch devices via /v1/audio/devices -> unified live engine updates <= 500ms & enables headset barge-in!
        t0 = time.perf_counter()
        sw = client.put(
            "/v1/audio/devices",
            headers=headers,
            json={"input_device_id": "mic-headset", "output_device_id": "hp-studio"},
        )
        switch_ms = (time.perf_counter() - t0) * 1000.0
        assert sw.status_code == 200
        assert switch_ms <= 500.0

        diag2 = client.get("/v1/voice/diagnostics", headers=headers)
        d2 = diag2.json()["diagnostics"]
        assert d2["selected_input_device"] == "Bluetooth Headset Mic"
        assert d2["selected_output_device"] == "Studio Headphones"
        assert d2["output_form_factor"] == "headphones"
        assert d2["voice_barge_in_allowed"] is True

        # 3. Speech rate syncs cleanly to unified live engine
        sr = client.put("/v1/audio/speech-rate", headers=headers, json={"speech_rate": 1.25})
        assert sr.status_code == 200
        assert client.get("/v1/voice/diagnostics", headers=headers).json()["diagnostics"]["speech_rate"] == 1.25

        # 4. Barge-in stop increments playback_generation immediately (<= 250ms target)
        gen_before = container.live_voice_engine.playback_generation
        t_stop = time.perf_counter()
        stop_r = client.post("/v1/voice/stop-speaking", headers=headers, json={})
        stop_ms = (time.perf_counter() - t_stop) * 1000.0
        assert stop_r.status_code == 200
        assert stop_r.json()["playback_generation"] == gen_before + 1
        assert stop_ms <= 250.0

        # 5. Typed vs spoken replay equivalence via /v1/voice/replay-transcript (shared TurnOrchestrator + PolicyEngine)
        rep = client.post(
            "/v1/voice/replay-transcript",
            headers=headers,
            json={"transcript": "Buka kalkulator.", "session_id": "sess-v-1", "speak_reply": False},
        )
        assert rep.status_code == 200
        assert rep.json()["steps"][0]["verified"] is True
        assert fake_desktop.launched_apps == ["calculator"]

        # Tier-3 command via replay MUST STILL be 403 DENIED
        rep_evil = client.post(
            "/v1/voice/replay-transcript",
            headers=headers,
            json={"transcript": "Buka powershell", "session_id": "sess-v-1", "speak_reply": False},
        )
        assert rep_evil.status_code == 403
        assert rep_evil.json()["code"] == "DENIED"

        # 6. OS lock halts voice, clears RAM ring buffer, and blocks subsequent voice replay!
        container.voice_service.ingest_mic_frame(b"\x01\x02" * 1600, is_ptt_pressed=True)
        lock_r = client.post("/v1/session/lock", headers=headers, json={"reason": "win_lock"})
        assert lock_r.status_code == 200
        assert container.voice_service.get_state().ring_buffer_seconds == 0.0

        rep_locked = client.post(
            "/v1/voice/replay-transcript",
            headers=headers,
            json={"transcript": "Buka kalkulator.", "session_id": "sess-v-1", "speak_reply": False},
        )
        assert rep_locked.status_code == 403
        assert rep_locked.json()["code"] == "DENIED"
