# 03 — Complete JARVIS Intelligence Engine Audit

This document audits the implemented perception, routing, context construction, LLM orchestration, multi-step planning, ambiguity handling, and response generation layers (`core/jarvis/domain/router.py`, `core/jarvis/application/turn_orchestrator.py`, `core/jarvis/infrastructure/live_voice_engine.py`, `core/jarvis/platform/windows/screen_capture.py`).

---

## 1. Input & Perception Architecture

| Input Modality | Active Mode | Actual Implementation & Source Evidence | Status |
| --- | --- | --- | --- |
| **Text input** | On-demand (HTTP `POST /v1/requests`) | `apps/desktop/src/App.tsx:239-250` -> Rust `submit_turn` (`commands.rs:169-182`, `10s` timeout) -> `app.py:1380-1425`. Hidden when voice armed unless user clicks `Mode Teks (Fallback)`. | **`PARTIAL`** *(10s Rust timeout + UI reply shadowed by `liveVoice.last_reply` at `App.tsx:595`)* |
| **Microphone input** | Continuously active when armed (`wake`/`active`) | `sounddevice.InputStream(16000 Hz, mono, f32, blocksize=512)` in `live_voice_engine.py:673-679`. Uses OS default mic only; ignores `ConfigService` device selection. | **`VERIFIED`** *(with device-selection & disconnect defects)* |
| **Wake-word detection** | Continuously active in `standby_wake` | `_OpenWakeWordRunner` (`live_voice_engine.py:253-291`, `hey_jarvis_v0.1.onnx`, 80 ms int16 frames, threshold `0.45`, cooldown `1.5s`); fallback to Whisper regex (`extract_wake_command`, `L87-101`). | **`IMPLEMENTED`** *(ONNX load & 0.0 silence verified; live human room FAR/FRR unverified)* |
| **Voice Activity Detection** | Continuously active in `active` session / fallback | `_SileroVadRunner` (`live_voice_engine.py:215-250`, `silero_vad.onnx`, `prob >= 0.42` & `rms >= 0.004`) + 320 ms pre-roll ring buffer. **Confirmed bug (`L793-821`):** 1 voiced 32 ms spike + 10 pre-roll + 22 silence = 33 frames bypasses `min_speech_blocks=8`. | **`BROKEN`** *(noise-spike inflation)* |
| **Speech-to-Text (STT)** | Event-driven (on VAD flush) | `faster-whisper-small` (`device="cpu"`, `compute_type="int8"`, `cpu_threads=4`, hardcoded `language="id"`, `beam_size=3`, `vad_filter=False`, static `_BILINGUAL_INITIAL_PROMPT`, `live_voice_engine.py:450-464, 843-851`). Zero confidence filtering. | **`PARTIAL`** *(works on clean ID; poor ID+EN code-switching & unguarded hallucinations)* |
| **Screen awareness** | On-demand (explicit command/route) | `WindowsActiveWindowCaptureAdapter` (`platform/windows/screen_capture.py:16-55`) reads ONLY `GetForegroundWindow` title + `psutil` process name. Zero UIA tree reading, zero OCR, ignores `window_selector`, hardcodes `has_focused_password_field=False`. | **`PARTIAL`** *(title/process metadata only; falsely tags `extraction_method="uia"`)* |
| **Camera / environmental** | On-demand API only | `OnDemandCameraService` wired with `capture_port=None` (`app.py:691`) -> `UnavailableCameraCaptureAdapter` always raises `UNSUPPORTED`. No ambient sensors. | **`NOT IMPLEMENTED`** *(service shell only; zero live adapter)* |
| **Event & sensor inputs** | None | Zero OS lock (`WM_WTSSESSION_CHANGE`), power (`WM_POWERBROADCAST`), file watcher, clipboard, calendar, or IoT event listeners exist. | **`NOT IMPLEMENTED`** |
| **Context acquisition** | Per-turn minimal | Only live OS clock (`_format_live_local_clock`, `turn_orchestrator.py:135-161`) and RAM 12-message `_session_history` are injected into LLM prompts. Zero active window, zero memory vault, zero tasks/reminders, zero persona style/verbosity. | **`PARTIAL`** |

---

## 2. Intelligence & Decision-Making Pipeline

### 2.1 Does JARVIS Genuinely Understand and Orchestrate Requests, or Rely on Hardcoded Keywords?

**Forensic Conclusion: Hybrid — Brittle Regex First, Single-Shot Untrusted LLM Second, Zero Agentic Orchestration.**

1. **Stage 1 — Deterministic Keyword/Regex Router (`core/jarvis/domain/router.py:120-383`):**
   Every turn passes through **10 hardcoded regex rules** before any LLM is consulted:
   - `_R3_INTENT_PATTERNS` (`L18-24`, `.search()`): blocks 5 dangerous phrase families (`powershell|bash|terminal`, `hapus permanen|shred`, `transfer uang|payment`, `kirim email`, `unlock door|disable alarm`). **Defect:** substring `.search()` false-positives on innocent educational questions like *"apa itu bash?"* or *"terminal bandara"*.
   - `_TIME_RE` (`L26-29`), `_VOLUME_SET_RE`/`_MUTE`/`_AMBIGUOUS` (`L30-35`), `_MEMORY_CREATE_RE` (`L39-42`), `_REMINDER_RELATIVE_ID_RE`/`_EN_RE`/`_AMBIGUOUS` (`L44-52`), `_FILE_MOVE_RE` (`L54-57`), `_APP_LAUNCH_RE` (`L37`, 3-app `_APP_ALIASES` at `L80-87`), `_TASK_CREATE_RE`/`_TASK_LIST_RE` (`L59-68`), `_KNOWLEDGE_QUERY_RE` (`L70-73`), `_SCREEN_ANALYZE_RE` (`L75-78`).
   - **Critical Whisper Punctuation Defect (`router.py:99-101`):** `normalize_utterance()` only collapses whitespace and never strips trailing `.`, `!`, `,`, `?`. Because Whisper emits trailing periods (`"Buka kalkulator."`, `"Jam berapa sekarang."`), `_APP_LAUNCH_RE` captures `"kalkulator."` (missing `_APP_ALIASES`), and `$`-anchored patterns fail silently into the LLM.
   - **False-Positive Interception:** `"buka pintu"` or `"open google"` matches `_APP_LAUNCH_RE` deterministically and immediately fails with `PermissionError` rather than escalating to the LLM.

2. **Stage 2 — Single-Shot Local LLM Planner (`core/jarvis/application/turn_orchestrator.py:249-384`):**
   - Triggered ONLY when `DeterministicRouter` returns `proposal=None` AND `active_prof.mode != DIRECT` AND `adapter is not None`.
   - Constructs prompt (`L275-281`):
     ```python
     live_clock_ctx = self._format_live_local_clock(now, tz_iana)
     history_msgs = self._get_history_snapshot(session.session_id)
     prompt_messages: tuple[ChatMessage, ...] = (
         ChatMessage(role="system", content=build_static_tool_catalog_prompt(live_clock_ctx)),
         *history_msgs,
         ChatMessage(role="user", content=utterance),
     )
     ```
   - `build_static_tool_catalog_prompt()` (`router.py:386-410`) gives Qwen3 an Indonesian-first persona, live local clock, and 10 allowed tool schemas (instructing JSON `{"steps":[...]}` ONLY for explicit local device actions, else plain prose).
   - **Entity extraction:** Purely regex capture groups in Stage 1, or zero-shot LLM JSON generation in Stage 2. No dedicated NER, fuzzy entity resolver, or file/app resolver exists.
   - **Ambiguity resolution:** Implemented ONLY for 2 exact strings (`"atur volume"` -> asks 0..100; `"ingatkan saya"` -> asks time & message, `router.py:171-180, 239-247`) plus empty input. Zero general LLM clarification protocol (`FR-COR-04`).

3. **Stage 3 — Single-Shot Execution (NO ReAct / NO Multi-Step Reasoning Loop):**
   - `parse_llm_assistant_or_tool()` (`router.py:429-460`) accepts either plain prose (conversational reply) or a strict `ToolProposal` (`1..5` steps, `extra="forbid"`).
   - If a `ToolProposal` is returned, `turn_orchestrator.py:389-465` validates bounds (`<= 5` steps), checks `PolicyEngine` per step, executes steps sequentially, stops on first failure/R2 approval, and concatenates raw step summaries (`" ".join(s.summary for s in step_results)`, `L472`).
   - **Zero ReAct / Observation Feedback:** Tool outputs (`life.task.list`, `screen.analyze`, `knowledge.query`) are **never fed back to the LLM** to synthesize an intelligent answer or decide a follow-up step.
   - **Zero Schema-Repair Loop:** `FR-COR-03` mandates up to `2` bounded schema-repair retries when LLM JSON fails validation; `turn_orchestrator.py:356-367` immediately fails on attempt 1 (`0` repair attempts).
   - **Zero Confidence Handling:** Neither STT (`seg.avg_logprob`/`no_speech_prob`) nor LLM responses carry confidence scores or abstention thresholds (except RAG empty-hit check).

---

## 3. Conversation State, Streaming & Error Recovery Flaws

| Aspect | Actual Behavior & Source Evidence | Confirmed Weakness |
| --- | --- | --- |
| **Conversation state** | `self._session_history: dict[str, deque[ChatMessage]]` (`maxlen=12`, `turn_orchestrator.py:113, 130`). Cleared on `/v1/session/lock` (`app.py:1320`). | Volatile RAM-only (SQLite `session`/`message` tables 100% unused); unbounded session dictionary keys; garbled STT turns poison future LLM turns; untrusted RAG/screen replies stored as `assistant` turns (`L473`) causing second-order prompt injection. |
| **Long-term memory recall** | `self._memory` is called ONLY for `create_memory()` (`L554`). | **`MemoryVaultService.list_memories()` is NEVER called in `TurnOrchestratorService`.** Stored personal facts/preferences have 0% influence on answers. |
| **Persona configuration** | `PersonaConfig` (`style`, `verbosity`) stored in `config_revision`. | Never read in `TurnOrchestratorService` or `build_static_tool_catalog_prompt()`. |
| **Streaming vs JSON conflict** | `turn_orchestrator.py:294-326` locks `stream_mode="prose"` on first char != `{` or `` ` ``. | Mixed prose + fenced JSON streams raw JSON to TTS AND executes the tool; code answers containing fenced `{...}` fail `json.loads` at `router.py:438-445` and reject valid replies with `INVALID_ARGS`. |
| **Tool argument crashes** | `turn_orchestrator.py:515, 532, 556, 570, 598, 663` index `args["..."]` directly. | Missing/wrong-type LLM tool args raise unhandled `KeyError`/`ValueError` (HTTP 500) instead of `ErrorCode.INVALID_ARGS`. |
| **State machine stuck on error** | `turn_orchestrator.py:327-384, 453-464` return `FAILED` without emitting `request.state_changed("Error")`. | SSE consumers remain stuck in `"Thinking"` on LLM/adapter failures. |
| **Cancellation** | Zero cancel endpoint, zero `asyncio.Event`/abort token on `submit_turn_streaming`. | `FR-COR-05` per-request cancellation is **NOT IMPLEMENTED**. |

---

## 4. Exact Limitations Summary of the Current Intelligence Engine

1. **No memory-grounded reasoning:** Cannot recall saved user preferences, past sessions, or personal facts during conversation.
2. **No agentic multi-step planning:** Single-shot proposal only; cannot observe a search/screen/task result and reason about the next step.
3. **No entity resolution:** Cannot resolve fuzzy app names, local filenames, pronouns referencing prior files ("buka file tadi"), or relative/absolute Indonesian date expressions ("besok jam 7 malam").
4. **Brittle deterministic boundary:** Trailing Whisper punctuation breaks deterministic commands while `.search()` R3 patterns false-positive on harmless words.
5. **No schema-repair or request cancellation:** Single malformed JSON fails the turn immediately; slow LLM generations cannot be aborted mid-flight.
