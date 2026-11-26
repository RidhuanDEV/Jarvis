"""Phase 3 Unit Tests: Deterministic ID/EN Router, LLM Adapters, Resource Governor, Ring Buffer & Echo Guard."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest

from jarvis.domain.ai_models import (
    ChatMessage,
    DynamicResourceGovernor,
    LlmCompletionRequest,
    ModelResourceEstimate,
    strip_thinking_blocks,
)
from jarvis.domain.models import AudioEndpointInfo, BackendPreference, ErrorCode
from jarvis.domain.router import DeterministicRouter, parse_llm_tool_proposal
from jarvis.domain.voice import (
    MAX_RING_BUFFER_BYTES,
    BoundedAudioRingBuffer,
    EndpointAwareEchoGuard,
    split_sentences_for_streaming_tts,
)
from jarvis.infrastructure.providers.llama_cpp_adapter import (
    LlamaCppServerAdapter,
    build_llama_server_args,
)
from jarvis.infrastructure.providers.ollama_adapter import OllamaAdapter


def test_deterministic_router_precision_recall_and_ambiguity_probes() -> None:
    router = DeterministicRouter()
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

    # Recall probes (0 LLM calls)
    cases = [
        ("jam berapa", "system.time.get"),
        ("what time is it?", "system.time.get"),
        ("atur volume ke 45", "os.volume.set"),
        ("set volume to 30", "os.volume.set"),
        ("bisukan suara", "os.volume.set"),
        ("buka kalkulator", "os.app.launch"),
        ("ingat bahwa saya suka kopi tanpa gula", "memory.create"),
        ("remember that I work best in the morning", "memory.create"),
        ("ingatkan saya 15 menit lagi minum air", "reminder.create"),
        ("remind me in 2 hours to review notes", "reminder.create"),
        ("pindahkan file draft.txt ke final.txt", "fs.file.move"),
        ("jalankan powershell whoami", "os.shell.exec"),
        ("hapus permanen laporan.pdf", "fs.delete_permanent"),
        ("transfer uang ke rekening baru", "payment.transfer"),
        ("buka kunci pintu depan", "iot.lock"),
    ]
    for utterance, expected_tool in cases:
        match = router.route(utterance, now_utc=now, timezone_iana="UTC")
        assert match.matched_deterministic is True, f"Expected deterministic match for: {utterance}"
        assert match.proposal is not None
        assert match.proposal.steps[0].tool_id == expected_tool

    # Precision / Ambiguity probes (BR-02: never guess missing slots)
    for ambiguous in ("atur volume", "atur volume ke 150", "ingatkan saya", ""):
        match = router.route(ambiguous, now_utc=now, timezone_iana="UTC")
        assert match.needs_clarification is True
        assert match.proposal is None

    # Open-ended prose MUST NOT falsely trigger a deterministic tool
    open_q = router.route("jelaskan perbedaan sel tumbuhan dan hewan", now_utc=now, timezone_iana="UTC")
    assert open_q.matched_deterministic is False
    assert open_q.proposal is None


def test_llama_server_args_non_thinking_and_proposal_parser() -> None:
    gpu_args = build_llama_server_args(
        binary_path="llama-server",
        model_path="model.gguf",
        backend=BackendPreference.CUDA,
        gpu_layers=99,
    )
    assert "--jinja" in gpu_args
    assert "--reasoning-budget" in gpu_args
    assert "--no-webui" in gpu_args
    assert "-ctk" in gpu_args and "q8_0" in gpu_args

    cpu_args = build_llama_server_args(
        binary_path="llama-server",
        model_path="model.gguf",
        backend=BackendPreference.CPU,
    )
    assert cpu_args[cpu_args.index("-ngl") + 1] == "0"
    assert "-ctk" not in cpu_args

    # Strip <think> blocks and parse strict JSON proposal
    raw = '<think>internal reasoning</think>\n{"steps":[{"tool_id":"os.volume.set","version":1,"args":{"percent":25}}]}'
    assert strip_thinking_blocks(raw).startswith("{")
    prop, err = parse_llm_tool_proposal(raw)
    assert err is None and prop is not None
    assert prop.steps[0].args["percent"] == 25

    # Reject extra injected keys (extra="forbid", T03)
    hostile = '{"steps":[{"tool_id":"os.volume.set","version":1,"args":{"percent":25},"risk":"R0"}]}'
    bad_prop, bad_err = parse_llm_tool_proposal(hostile)
    assert bad_prop is None and bad_err is not None


@pytest.mark.asyncio
async def test_llama_cpp_and_ollama_adapters_mock_http_and_wildcard_warning() -> None:
    captured_llama: dict[str, object] = {}

    def llama_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if request.url.path == "/v1/models":
            return httpx.Response(200, json={"data": [{"id": "qwen3-4b-q4"}]})
        if request.url.path == "/v1/chat/completions":
            captured_llama.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "model": "qwen3-4b-q4",
                    "choices": [
                        {
                            "message": {
                                "content": '<think>quiet</think>{"steps":[{"tool_id":"system.time.get","version":1,"args":{}}]}'
                            }
                        }
                    ],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 12},
                },
            )
        return httpx.Response(404)

    llama = LlamaCppServerAdapter(
        provider_id="llama-local",
        endpoint_url="http://127.0.0.1:8081",
        transport=httpx.MockTransport(llama_handler),
    )
    probe = await llama.probe()
    assert probe.healthy and "qwen3-4b-q4" in probe.detected_models

    comp = await llama.complete(
        LlmCompletionRequest(
            model_id="qwen3-4b-q4",
            messages=(ChatMessage(role="user", content="jam berapa"),),
            enforce_non_thinking=True,
            expect_json=True,
        )
    )
    assert captured_llama["chat_template_kwargs"] == {"enable_thinking": False}
    assert comp.thinking_stripped is True
    assert "<think>" not in comp.content

    # Ollama adapter: sends think=False & warns on 0.0.0.0 wildcard exposure (FR-AIP-08)
    captured_ollama: dict[str, object] = {}

    def ollama_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3:1.7b"}]})
        if request.url.path == "/api/chat":
            captured_ollama.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={"model": "qwen3:1.7b", "message": {"content": '{"steps":[]}'}},
            )
        return httpx.Response(404)

    ollama = OllamaAdapter(
        provider_id="ollama-ext",
        endpoint_url="http://0.0.0.0:11434",
        transport=httpx.MockTransport(ollama_handler),
    )
    o_probe = await ollama.probe()
    assert o_probe.healthy and "qwen3:1.7b" in o_probe.detected_models
    assert any("0.0.0.0" in w for w in o_probe.warnings)  # noqa: S104

    await ollama.complete(
        LlmCompletionRequest(
            model_id="qwen3:1.7b",
            messages=(ChatMessage(role="user", content="halo"),),
            enforce_non_thinking=True,
            expect_json=True,
        )
    )
    assert captured_ollama["think"] is False
    assert captured_ollama["format"] == "json"


def test_dynamic_resource_governor_same_zone_degradation() -> None:
    est = ModelResourceEstimate(ram_mib=3000, vram_mib=2900, min_context_tokens=1024, max_context_tokens=4096)

    # Ample VRAM -> CUDA
    gpu_ok = DynamicResourceGovernor.evaluate_model_load(
        estimate=est,
        free_ram_mib=16000,
        free_vram_mib=3800,
        max_ram_cap_mib=8192,
        max_vram_cap_mib=3300,
        requested_backend=BackendPreference.CUDA,
        requested_context=4096,
    )
    assert gpu_ok.permitted and gpu_ok.backend == BackendPreference.CUDA

    # Low VRAM, ample RAM -> degrades to CPU within same local zone
    cpu_deg = DynamicResourceGovernor.evaluate_model_load(
        estimate=est,
        free_ram_mib=16000,
        free_vram_mib=1024,
        max_ram_cap_mib=8192,
        max_vram_cap_mib=1024,
        requested_backend=BackendPreference.CUDA,
        requested_context=4096,
    )
    assert cpu_deg.permitted and cpu_deg.backend == BackendPreference.CPU and cpu_deg.degraded

    # Insufficient RAM & VRAM -> Direct Mode (WORKER_OOM, never cloud!)
    oom = DynamicResourceGovernor.evaluate_model_load(
        estimate=est,
        free_ram_mib=1500,
        free_vram_mib=512,
        max_ram_cap_mib=1500,
        max_vram_cap_mib=512,
        requested_backend=BackendPreference.AUTO,
        requested_context=4096,
    )
    assert not oom.permitted and oom.fallback_to_direct and oom.error_code == ErrorCode.WORKER_OOM


def test_audio_ring_buffer_2s_cap_and_endpoint_aware_echo_guard() -> None:
    ring = BoundedAudioRingBuffer()
    # Push 5 seconds of PCM -> must remain strictly capped at <= 2.0s (64,000 bytes, BR-13)
    for _ in range(5):
        ring.append_frame(b"\x01\x02" * 16000)
    assert len(ring.snapshot_bytes()) == MAX_RING_BUFFER_BYTES
    assert ring.duration_seconds() == pytest.approx(2.0, abs=0.01)
    ring.clear()
    assert len(ring.snapshot_bytes()) == 0

    guard = EndpointAwareEchoGuard(post_playback_tail_ms=250.0)
    speakers = AudioEndpointInfo(
        id="out-1", name="Laptop Speakers", direction="output", is_default=True, form_factor="speakers"
    )
    headphones = AudioEndpointInfo(
        id="out-2", name="Studio Headphones", direction="output", is_default=True, form_factor="headphones"
    )

    # Open speaker during TTS & within 250ms tail: 5/5 bleed suppressed, PTT always allowed
    for _ in range(5):
        d_play = guard.evaluate(output_endpoint=speakers, is_tts_playing=True, ms_since_tts_ended=None)
        assert not d_play.allow_mic_wake_or_vad
        assert d_play.allow_ptt_or_ui_barge_in
    d_tail = guard.evaluate(output_endpoint=speakers, is_tts_playing=False, ms_since_tts_ended=120.0)
    assert not d_tail.allow_mic_wake_or_vad
    d_idle = guard.evaluate(output_endpoint=speakers, is_tts_playing=False, ms_since_tts_ended=400.0)
    assert d_idle.allow_mic_wake_or_vad

    # Headphones allow full voice barge-in during playback
    d_hp = guard.evaluate(output_endpoint=headphones, is_tts_playing=True, ms_since_tts_ended=None)
    assert d_hp.allow_voice_barge_in and d_hp.allow_mic_wake_or_vad

    chunks = split_sentences_for_streaming_tts("Halo Monarch. Sistem berjalan lokal. Siap menerima perintah!")
    assert len(chunks) == 3
