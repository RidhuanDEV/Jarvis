"""Precision & recall unit probes for 'Hey Jarvis' wake-word gating and multilingual conversational + tool LLM parser."""

from __future__ import annotations

import pytest

from jarvis.domain.router import parse_llm_assistant_or_tool
from jarvis.infrastructure.live_voice_engine import (
    extract_wake_command,
    is_sleep_command,
    is_whisper_hallucination,
    sanitize_for_speech,
    split_sentences_for_tts,
    strip_optional_wake_prefix,
)


@pytest.mark.parametrize(
    "transcript,expected_cmd",
    [
        ("Hey Jarvis", ""),
        ("Hey Jarvis, terjemahkan selamat pagi ke bahasa Jepang", "terjemahkan selamat pagi ke bahasa Jepang"),
        ("Halo Jarvis jam berapa sekarang?", "jam berapa sekarang?"),
        ("Jarvis tolong jelaskan teori relativitas secara singkat", "tolong jelaskan teori relativitas secara singkat"),
        ("Oke Jarvis, ingatkan saya 5 menit lagi untuk istirahat", "ingatkan saya 5 menit lagi untuk istirahat"),
        ("J.A.R.V.I.S. translate good evening to Arabic", "translate good evening to Arabic"),
        ("Hai Jervis buka kalkulator", "buka kalkulator"),
    ],
)
def test_wake_word_recall_wakes_and_strips_phrase(transcript: str, expected_cmd: str) -> None:
    woke, cmd = extract_wake_command(transcript)
    assert woke is True
    assert cmd == expected_cmd


@pytest.mark.parametrize(
    "room_chatter",
    [
        "",
        "   ",
        "tadi pagi aku minum kopi sebelum kerja",
        "hello everyone let us start the meeting",
        "sistem berjalan normal tanpa kendala",
        "coba terjemahkan ini nanti sore",
    ],
)
def test_wake_word_precision_ignores_ordinary_speech(room_chatter: str) -> None:
    woke, cmd = extract_wake_command(room_chatter)
    assert woke is False
    assert cmd == ""


def test_sanitize_for_speech_strips_markdown() -> None:
    assert sanitize_for_speech("**Ohayou gozaimasu** (`selamat pagi`) #1") == "Ohayou gozaimasu ( selamat pagi ) 1"


def test_llm_parser_supports_multilingual_reply_and_strict_tool_validation() -> None:
    # 1. JSON conversational / translation reply
    prop, reply, err = parse_llm_assistant_or_tool('<think>translating</think>{"reply": "Ohayou gozaimasu."}')
    assert prop is None
    assert reply == "Ohayou gozaimasu."
    assert err is None

    # 2. Plain text multilingual reply
    prop2, reply2, err2 = parse_llm_assistant_or_tool("Bahasa Jepang untuk selamat pagi adalah Ohayou gozaimasu.")
    assert prop2 is None
    assert reply2 == "Bahasa Jepang untuk selamat pagi adalah Ohayou gozaimasu."
    assert err2 is None

    # 3. Valid strict tool proposal
    prop3, reply3, err3 = parse_llm_assistant_or_tool(
        '{"steps": [{"tool_id": "os.volume.set", "version": 1, "args": {"percent": 35}}]}'
    )
    assert prop3 is not None and prop3.steps[0].tool_id == "os.volume.set"
    assert reply3 is None and err3 is None

    # 4. Rogue/malformed JSON object with extra keys MUST fail closed!
    prop4, reply4, err4 = parse_llm_assistant_or_tool('{"steps": [{"tool_id": "os.volume.set", "extra_bad": 1}]}')
    assert prop4 is None and reply4 is None and err4 is not None


def test_deterministic_clock_matches_trailing_sekarang_and_now() -> None:
    from datetime import UTC, datetime

    from jarvis.domain.router import DeterministicRouter

    router = DeterministicRouter()
    now = datetime(2026, 11, 27, 5, 0, 0, tzinfo=UTC)
    for phrase in (
        "jam berapa sekarang?",
        "sekarang jam berapa",
        "pukul berapa sekarang?",
        "what time is it now?",
    ):
        m = router.route(phrase, now_utc=now, timezone_iana="UTC", primary_language="id-ID")
        assert m.matched_deterministic is True, f"Expected deterministic match for: {phrase}"
        assert m.proposal is not None
        assert m.proposal.steps[0].tool_id == "system.time.get"


@pytest.mark.parametrize(
    "sleep_phrase",
    [
        "cukup Jarvis",
        "tidur dulu",
        "Jarvis tidur",
        "kembali siaga",
        "standby",
        "selesai terima kasih",
        "terima kasih Jarvis",
        "go to sleep",
        "that's all Jarvis",
    ],
)
def test_sleep_command_recall_returns_to_standby(sleep_phrase: str) -> None:
    assert is_sleep_command(sleep_phrase) is True


@pytest.mark.parametrize(
    "non_sleep_sentence",
    [
        "saya belum tidur semalam",
        "apakah penjelasannya cukup jelas?",
        "tolong jelaskan cara kerja mode standby komputer",
        "terima kasih banyak atas bantuannya, sekarang terjemahkan halo ke bahasa Korea",
        "jam berapa sekarang?",
    ],
)
def test_sleep_command_precision_ignores_ordinary_speech(non_sleep_sentence: str) -> None:
    assert is_sleep_command(non_sleep_sentence) is False


def test_strip_wake_prefix_hallucination_filter_and_sentence_split() -> None:
    assert strip_optional_wake_prefix("Hey Jarvis, jam berapa sekarang?") == "jam berapa sekarang?"
    assert strip_optional_wake_prefix("jam berapa sekarang?") == "jam berapa sekarang?"
    assert is_whisper_hallucination("Terima kasih telah menonton!") is True
    assert is_whisper_hallucination("...") is True
    assert is_whisper_hallucination("terima kasih banyak") is False
    assert split_sentences_for_tts("Ya, siap. Sekarang pukul 05:35 pagi! Ada lagi?") == [
        "Ya, siap.",
        "Sekarang pukul 05:35 pagi!",
        "Ada lagi?",
    ]


def test_deterministic_voice_routes_for_tasks_rag_and_screen() -> None:
    from datetime import UTC, datetime

    from jarvis.domain.router import DeterministicRouter

    router = DeterministicRouter()
    now = datetime(2026, 11, 27, 5, 0, 0, tzinfo=UTC)

    m_task = router.route("buat tugas kirim proposal besok pagi", now_utc=now, timezone_iana="UTC", primary_language="id-ID")
    assert m_task.matched_deterministic and m_task.proposal is not None
    assert m_task.proposal.steps[0].tool_id == "life.task.create"
    assert m_task.proposal.steps[0].args["title"] == "kirim proposal besok pagi"

    m_list = router.route("apa saja tugas saya?", now_utc=now, timezone_iana="UTC", primary_language="id-ID")
    assert m_list.matched_deterministic and m_list.proposal is not None
    assert m_list.proposal.steps[0].tool_id == "life.task.list"

    m_rag = router.route("cari di dokumen anggaran kuartal empat", now_utc=now, timezone_iana="UTC", primary_language="id-ID")
    assert m_rag.matched_deterministic and m_rag.proposal is not None
    assert m_rag.proposal.steps[0].tool_id == "knowledge.query"
    assert m_rag.proposal.steps[0].args["query"] == "anggaran kuartal empat"

    m_scr = router.route("baca layar aktif", now_utc=now, timezone_iana="UTC", primary_language="id-ID")
    assert m_scr.matched_deterministic and m_scr.proposal is not None
    assert m_scr.proposal.steps[0].tool_id == "screen.analyze"


@pytest.mark.asyncio
async def test_turn_orchestrator_streams_sentences_and_executes_voice_tasks_rag_screen(tmp_path) -> None:
    from collections.abc import AsyncIterator
    from pathlib import Path

    from jarvis.application.screen_service import RawWindowObservation
    from jarvis.domain.ai_models import (
        AiProfileRecord,
        LlmCompletionRequest,
        LlmCompletionResponse,
        ProviderProbeResult,
    )
    from jarvis.domain.models import (
        ActionOutcomeState,
        AiProfileMode,
        ChannelKind,
        InputModality,
        RuntimeOwnershipMode,
        SessionContext,
        TrustZone,
    )
    from jarvis.transport.app import build_default_container
    from jarvis.transport.settings import CoreStartupSettings

    class _FakeStreamingAdapter:
        provider_id = "fake_stream"
        ownership_mode = RuntimeOwnershipMode.MANAGED_LOCAL
        trust_zone = TrustZone.LOCAL_DEVICE

        async def probe(self) -> ProviderProbeResult:
            return ProviderProbeResult(healthy=True, health_code="ok", latency_ms=1.0)

        async def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
            return LlmCompletionResponse(
                content="Halo Monarch. Sistem siap.",
                raw_content="Halo Monarch. Sistem siap.",
                model_id=request.model_id,
                provider_id=self.provider_id,
                elapsed_ms=2.0,
            )

        async def stream_complete(self, request: LlmCompletionRequest) -> AsyncIterator[str]:
            for tok in ("Halo ", "Monarch. ", "Sistem ", "siap ", "bekerja!"):
                yield tok

    class _FakeScreenCapture:
        def observe_window(self, window_selector: str) -> RawWindowObservation:
            return RawWindowObservation(
                window_title="Editor Proyek",
                process_name="code.exe",
                extraction_method="uia",
                extracted_text="Kode sedang terbuka dengan token rahasia sk-1234567890abcdefghijklmnop.",
                raw_frame_bytes=None,
            )

    settings = CoreStartupSettings(
        env="test",
        bind_port=0,
        base_data_dir=Path(tmp_path) / "data",
        base_cache_dir=Path(tmp_path) / "cache",
        auto_start_local_llm=False,
    )
    c = build_default_container(settings)
    c.screen_service.bind_capture_port(_FakeScreenCapture())
    c.ai_registry.bind_adapter(_FakeStreamingAdapter())
    c.ai_registry.upsert_profile(
        AiProfileRecord(
            id="balanced",
            revision=2,
            mode=AiProfileMode.BALANCED,
            role_bindings={"llm_provider": "fake_stream", "llm_model": "qwen-test"},
        )
    )
    c.ai_registry.switch_profile_atomic("balanced", target_revision=2, correlation_id="t-stream")

    # 1. Verify SSE streaming flushes sentence-by-sentence in real time
    emitted: list[str] = []
    sess = SessionContext(
        session_id="s-voice-1",
        actor_ref="local_owner",
        channel=ChannelKind.LOCAL,
        modality=InputModality.VOICE,
    )
    res_stream = await c.turn_orchestrator.submit_turn_streaming(
        "apa kabar hari ini?",
        session=sess,
        correlation_id="c-stream",
        on_sentence=emitted.append,
    )
    assert res_stream.state == ActionOutcomeState.COMPLETED
    assert emitted == ["Halo Monarch.", "Sistem siap bekerja!"]

    # 2. Grant safe capabilities and verify Tasks + RAG + Redacted Screen via voice!
    with c.db.core_tx() as conn:
        for idx, cap in enumerate(("life.task", "knowledge.read", "screen.read")):
            conn.execute(
                "INSERT INTO grant(id, subject_type, subject_id, capability, scope_json, expires_at, revoked_at, revision) "
                "VALUES (?, 'local_owner', 'local_owner', ?, '{}', NULL, NULL, 1)",
                (f"g-{idx}", cap),
            )

    r_create = await c.turn_orchestrator.submit_turn(
        "buat tugas review arsitektur voice", session=sess, correlation_id="c-t1"
    )
    assert r_create.state == ActionOutcomeState.COMPLETED
    assert "review arsitektur voice" in r_create.reply

    r_list = await c.turn_orchestrator.submit_turn(
        "apa saja tugas saya?", session=sess, correlation_id="c-t2"
    )
    assert r_list.state == ActionOutcomeState.COMPLETED
    assert "review arsitektur voice" in r_list.reply

    # Ingest a real opt-in doc and query it by voice RAG!
    docs_dir = Path(tmp_path) / "docs"
    docs_dir.mkdir()
    (docs_dir / "anggaran.txt").write_text("Anggaran riset Q4 adalah 250 juta rupiah.", encoding="utf-8")
    root = c.knowledge_service.add_source_root(str(docs_dir), correlation_id="c-kb1")
    c.knowledge_service.sync_source_root(root.id, correlation_id="c-kb2")
    r_kb = await c.turn_orchestrator.submit_turn(
        "cari di dokumen anggaran riset Q4", session=sess, correlation_id="c-kb3"
    )
    assert r_kb.state == ActionOutcomeState.COMPLETED
    assert "anggaran.txt" in r_kb.reply

    # Verify screen awareness redacts sk-... secret automatically!
    r_scr = await c.turn_orchestrator.submit_turn(
        "baca layar aktif", session=sess, correlation_id="c-scr"
    )
    assert r_scr.state == ActionOutcomeState.COMPLETED
    assert "sk-1234567890" not in r_scr.reply
    assert "[REDACTED" in r_scr.reply
