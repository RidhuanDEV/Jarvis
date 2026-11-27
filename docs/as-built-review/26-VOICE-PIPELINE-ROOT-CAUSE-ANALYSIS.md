# 26 — Voice Pipeline Root-Cause Analysis (Stage-by-Stage Forensic Audit)

> **Document Scope:** End-to-end engineering trace of J.A.R.V.I.S.'s actual voice pipeline across all twelve signal and processing stages (`Microphone Capture` -> `Noise Suppression` -> `Echo Cancellation` -> `VAD` -> `STT` -> `Transcript Normalization` -> `Intent Recognition` -> `Deterministic / LLM Routing` -> `Response Generation` -> `Text Normalization` -> `TTS` -> `Audio Playback`), covering every Addendum §E diagnostic topic and defining a rigorous isolation protocol to separate STT, intent, LLM, and TTS failures **before** considering any model fine-tuning.
>
> **Companion Diagram:** [diagrams/10-voice-pipeline-actual-vs-target.mmd](./diagrams/10-voice-pipeline-actual-vs-target.mmd).

---

## 1. Architectural Split: Two Disconnected Voice Subsystems

A critical finding of this audit is that J.A.R.V.I.S. currently contains **two disconnected voice stacks**:

1. **Control-Plane Stub (`VoicePipelineService`):** `core/jarvis/application/voice_service.py` + `core/jarvis/platform/windows/audio.py` + HTTP endpoints (`PUT /v1/audio/devices` at `app.py:1559-1575`). Saves selected WinMM device IDs to `config_revision` and emits `audio.devices_changed` on the Event Bus, **which zero components subscribe to**.
2. **Actual Runtime Audio Engine (`LiveVoiceEngine`):** `core/jarvis/infrastructure/live_voice_engine.py` (instantiated directly in `app.py:750-754` with **zero reference** to `VoicePipelineService`, `ConfigService`, `AudioDevicePort`, or `EndpointAwareEchoGuard`).

Because these two stacks never communicate, UI/API configuration changes have zero effect on live voice capture, echo suppression, speech rate, or playback device selection.

---

## 2. Complete 12-Stage Pipeline Trace (Actual Implementation & Config)

| Stage | Target Function | Actual Implementation & Exact Source | Actual Runtime Config | Stage Status |
| :---: | --- | --- | --- | :---: |
| **1. Mic Capture** | Capture selected mic at matched sample rate | `LiveVoiceEngine._capture_loop` (`live_voice_engine.py:667-679`) via `sounddevice.InputStream` | `samplerate=16000`, `channels=1`, `dtype="float32"`, `blocksize=512` (32ms), **`device=None`** (OS default only), `queue.Queue(maxsize=250)` (~8s; drops silently on `Full`) | `BROKEN` |
| **2. Noise Suppression** | Suppress fan/ambient/keyboard noise, HPF, AGC | **None implemented** (`indata[:, 0].copy()` passed raw at `L668`) | Zero HPF, zero RNNoise/WebRTC NS, zero AGC, zero clipping detector/limiter | `NOT IMPLEMENTED` |
| **3. Echo Cancellation (AEC)** | Subtract speaker output to allow clean full-duplex barge-in | Naive mute timer `self._echo_guard_until` (`L730-741`, `L602`); `EndpointAwareEchoGuard` (`domain/voice.py:60-114`) is **unwired** | Full mic drop during TTS playback + `0.30s` fixed tail (`ECHO_TAIL_SECONDS = 0.30`); ignores headset vs speaker topology | `BROKEN` |
| **4. Wake-Word + VAD** | Detect `"Hey Jarvis"` & clean utterance boundaries | `openWakeWord` (`hey_jarvis_v0.1.onnx`) + Silero VAD (`silero_vad.onnx`, `L299-307`, `706-821`) | Wake `threshold=0.50` (`L299`); VAD `rms>=0.004 & prob>=0.42`, `pre_roll=10` (320ms), `min_speech_blocks=8` (256ms), `SILENCE_END_SECONDS=0.72` (22 frames), `POST_WAKE_FOLLOW_SECONDS=0.58` | `BROKEN` |
| **5. STT** | Accurate bilingual ID+EN transcription | `faster-whisper` (`small`, CPU `int8`, `cpu_threads=4`, `L450-464`, `843-851`) | **Hardcoded `language="id"`**, `beam_size=3`, **`vad_filter=False`**, static `_BILINGUAL_INITIAL_PROMPT` (`L78-84`), **discards all segment confidence scores** | `BROKEN` |
| **6. Transcript Normalization** | Clean punctuation, hallucinations, wake prefix, polite fillers | `_WHISPER_HALLUCINATION_RE` (`L70-73`, 5 phrases) + `normalize_utterance()` (`router.py:99-101`, lower + whitespace collapse only) | **Trailing `.`, `!`, `,`, `?` NOT stripped**; polite prefixes (`tolong`, `coba`) NOT stripped; no custom alias/phonetic correction | `BROKEN` |
| **7. Intent Recognition** | Classify user intent & extract canonical entities | Regex matchers in `router.py:27-87, 309-350` | 6-key `_APP_ALIASES` -> 3 apps; `_APP_LAUNCH_RE` includes `.` in `[a-z0-9 _.-]{2,40}`; anchored `^...$` breaks on Whisper punctuation | `BROKEN` |
| **8. Deterministic vs LLM Routing** | Route commands to tools or conversational LLM | `TurnOrchestrator.process_turn()` (`turn_orchestrator.py:219-410`) | Single-shot binary branch: regex tool match **OR** free-form LLM prose; **zero LLM tool-calling**, voice R2 approvals dropped (`app.py:748`) | `PARTIAL` |
| **9. Response Generation** | Generate accurate, grounded, concise spoken reply | Local `llama-server` (`Qwen3-4B-Q4_K_M`, CUDA) via `router.py:386-410` | Prompt asks for multilingual support including non-Latin scripts; 65s HTTP timeout; garbled turns enter `_session_history` (`maxlen=12`); Memory Vault & Persona unwired | `PARTIAL` |
| **10. Text Normalization (TTS)** | Convert numbers, acronyms, paths, English terms to speakable prose | `_MARKDOWN_CLEAN_RE` (`live_voice_engine.py:75, 131-143`) | Strips ONLY `` [`*_#>\[\]]+ ``; zero expansion for URLs, paths, acronyms (`CPU`, `GPU`, `SSE`), numbers/times, or code-switched English | `PARTIAL` |
| **11. TTS Synthesis** | Natural, intelligible Indonesian + English speech | Piper ONNX (`id_ID-news_tts-medium.onnx`, `L466-499`) | Monolingual `espeak` `voice: "id"`, `22050 Hz`, 60s timeout; **ignores `speech_rate` config**; no English voice switching | `PARTIAL` |
| **12. Audio Playback** | Clean, low-latency, non-blocking output to selected speaker | `sounddevice.play(samples, samplerate=22050)` + `sd.wait()` (`L593, 640`) | **`device=None`** (OS default only); **blocks `_capture_loop` synchronously** (`L821, 930, 944`), causing capture queue overflow during long replies | `BROKEN` |

---

## 3. Forensic Investigation of All 17 Addendum §E Voice Factors

### Factor 1 & 2: Incorrect Microphone Selection & Sample-Rate Mismatch
- **Source Evidence:** `live_voice_engine.py:673-679` (`device=None`, `samplerate=16000`); `core/jarvis/platform/windows/audio.py:34, 46, 57-93` (enumerates legacy WinMM devices with 32-char truncated names, emitting `winmm-in-{idx}` / `winmm-out-{idx}`); `core/jarvis/platform/windows/hardware.py:215-216` (`audio_endpoints=()` hardcoded); `apps/desktop/src-tauri/src/commands.rs` (zero audio device command).
- **Current Behavior:** `LiveVoiceEngine` unconditionally opens Windows' default recording and playback devices at `16000 Hz` (capture) and `22050 Hz` (playback). Selecting a headset or studio USB microphone via `PUT /v1/audio/devices` updates SQLite only and has zero effect on live audio. On Windows Bluetooth HFP/HSP headsets or 48kHz-only USB interfaces, implicit PortAudio/MME resampling or Windows default-device drift (e.g., picking a webcam mic or stereo mix) degrades SNR catastrophically or triggers sample-rate open errors.
- **Expected Behavior:** Enumerate WASAPI audio endpoints with full untruncated names, native sample rates, and form-factor metadata (`headset` vs `speaker`); persist selection and live-rebind `LiveVoiceEngine` streams via explicit high-quality polyphase resampling (`48kHz/44.1kHz -> 16kHz`) when native 16kHz is unsupported.
- **Probable Root Cause:** Confirmed architectural disconnect between `VoicePipelineService` and `LiveVoiceEngine` + reliance on legacy WinMM instead of WASAPI.
- **Verification Status:** `BROKEN` (device selection is completely dead on runtime engine; resampling behavior on non-16kHz hardware `UNVERIFIED` pending multi-device test).
- **Proposed Improvements:** Migrate `windows/audio.py` to WASAPI (`pycaw`/Core Audio or PortAudio WASAPI host API), subscribe `LiveVoiceEngine` to `audio.devices_changed`, expose mic/speaker picker + live RMS meter in Desktop Settings, and resample explicitly from native device rate (`48000 Hz`) using `scipy.signal.resample_poly` or `soxr`.
- **Security Implications:** Selecting the wrong microphone (e.g., ambient room mic instead of push-to-talk headset) increases unintended ambient voice capture. Expose explicit active device name & mute hardware indicator in UI.
- **Acceptance Criteria:** Switching input/output devices in UI rebinds `LiveVoiceEngine` within `<= 500ms` without process restart; 48kHz USB mics and Bluetooth headsets capture cleanly with zero PortAudio stream failures.

### Factor 3 & 4: Clipping, Gain Control, and Background Noise
- **Source Evidence:** `live_voice_engine.py:667-671` (raw `float32` copy), `L706` (`rms >= 0.004`). Zero peak-clipping detection, zero DC-offset removal, zero high-pass filter, zero AGC, zero noise suppressor.
- **Current Behavior:** Close-mic speech clipping (`|sample| >= 0.99`) distorts Whisper mel-spectrograms; conversely, quiet speech below `rms=0.004` is silently ignored, while stationary AC/fan noise or keyboard clicks above `rms=0.004` continuously trip VAD.
- **Expected Behavior:** Deterministic front-end DSP chain: 80Hz high-pass filter -> soft-knee AGC/clipping warning -> real-time lightweight noise suppression (WebRTC NS / RNNoise) -> calibrated VAD operating on cleaned frames.
- **Probable Root Cause:** Confirmed total absence of audio DSP preprocessing.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Add a zero-cloud C/ONNX front-end DSP stage (`webrtc-audio-processing` / `rnnoise` / `speexdsp` or ONNX GTCRN) running per 10ms/32ms frame with `< 3ms` CPU cost, plus live clipping/SNR telemetry emitted to the diagnostics view.
- **Security Implications:** Telemetry must report scalar RMS/SNR/clipping metrics only—never raw audio frames in logs.
- **Acceptance Criteria:** Steady 55 dB fan noise yields `< 1%` VAD false onset rate; peak clipping >3% of frames surfaces a non-intrusive mic-gain warning in UI.

### Factor 5 & 16: Echo, Self-Triggering, Barge-In, and Continuous Conversation
- **Source Evidence:** `live_voice_engine.py:593, 602, 640, 730-741, 764-791`; `core/jarvis/domain/voice.py:60-114` (`EndpointAwareEchoGuard` exists in domain layer but is **never instantiated** in `live_voice_engine.py`).
- **Current Behavior:**
  1. During TTS playback + `0.30s` tail, the mic is unconditionally muted—**preventing voice barge-in even when the owner wears headphones**.
  2. On open desktop speakers with room reverb `>300ms` (or PortAudio output buffer latency `>150ms`), speaker tail leaks past `0.30s` and self-triggers VAD/STT.
  3. After wake word, `POST_WAKE_FOLLOW_SECONDS = 0.58` triggers a spoken `"Ya, siap..."` greeting that overlaps the user's command if they pause `0.5s–0.7s`, activating Echo Guard and swallowing the start of their sentence.
  4. When follow-up window expires or barge-in fails, the user is forced back to repeating `"Hey Jarvis"` before every question.
- **Expected Behavior:**
  - Wire `EndpointAwareEchoGuard` with real WASAPI device-topology awareness (`headset` -> full-duplex barge-in enabled; `speaker` -> real software AEC subtracting reference playback buffer from mic input).
  - Replace spoken `"Ya, siap..."` after wake word with an ultra-short (`<= 100ms`) non-verbal chime or immediate listening indicator so user speech is never collided with.
  - Maintain clear continuous multi-turn listening state (e.g., 15–30s configurable conversational window with explicit UI state & instant `"stop"`/`"diam"` barge-in).
- **Probable Root Cause:** Confirmed naive time-based mute flag, unwired `EndpointAwareEchoGuard`, missing reference-signal AEC, and `0.58s` verbal wake acknowledgment race.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Implement WebRTC AEC3 / Speex AEC fed by the actual TTS playback ring buffer; wire `EndpointAwareEchoGuard`; switch wake acknowledgment to a configurable subtle earcon; decouple playback thread so barge-in immediately calls `sd.stop()` and drains stale audio.
- **Security Implications:** Self-triggering loops where TTS output is transcribed as a new user command can trigger unintended autonomous tool invocations. AEC + playback-reference suppression closes this self-actuation loop.
- **Acceptance Criteria:** `0` self-triggered turns over 50 loud speaker replies; barge-in interrupts TTS playback within `<= 250ms` on headphones and `<= 400ms` on AEC-enabled desktop speakers; zero clipped command openings after `"Hey Jarvis"`.

### Factor 6 & 11: Premature Utterance Termination & VAD Configuration Bug
- **Source Evidence:** `live_voice_engine.py:299-307, 706-707, 759, 793-821`:
  - `SILENCE_END_SECONDS = 0.72` (`22` frames of 32ms) cuts off natural mid-sentence Indonesian pauses (e.g., `"Buka file..."` [0.8s pause to recall filename] `"...laporan Q4"`).
  - **Confirmed Frame-Inflation Bug:** When a single 32ms noise frame meets `rms >= 0.004 and prob >= 0.42`, `live_voice_engine.py` copies `10` pre-roll frames + `1` voiced frame + `22` trailing silence frames = **`33` total frames**, which unconditionally satisfies `len(buffered) >= min_speech_blocks (8)`! Thus `min_speech_blocks` is **mathematically dead code**—every transient click is sent to Whisper.
- **Current Behavior:** Both extremes occur simultaneously: transient clicks are falsely accepted as 1.05s utterances, while deliberate natural pauses >0.72s prematurely chop compound commands in half.
- **Expected Behavior:** Track `voiced_frame_count` separately from `pre_roll` and `trailing_silence`; require `>= 8` consecutive/clustered voiced frames (`256ms`) before committing to STT; use adaptive endpointing (`0.9s–1.3s` trailing silence, extended briefly after trailing conjunctions or wake-only utterances).
- **Probable Root Cause:** Confirmed logic bug comparing `len(buffered)` instead of actual voiced frames, paired with overly aggressive static `0.72s` endpointing.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Fix `voiced_frame_count` gating, separate wake-to-command wait timeout (`2.5s` silence before returning to standby) from mid-utterance endpointing (`1.0s`–`1.2s`), and add configurable speech endpointing profile (`Fast` / `Balanced` / `Patient`).
- **Security Implications:** Premature truncation can slice an utterance before a qualifying condition (e.g., `"Jangan buka..."` / `"Buka..."` boundary errors).
- **Acceptance Criteria:** Unit & audio-fixture tests verify single 32ms–160ms noise impulses yield `0` STT calls; compound commands with `0.9s` mid-sentence pause transcribe as one intact utterance.

### Factor 7, 8, 9 & 10: Speech Hallucinations, Code-Switching, Technical Vocabulary & STT Model Limitations
- **Source Evidence:** `live_voice_engine.py:70-84, 450-464, 843-851`.
  - Model: `faster-whisper-small` (244M params, CPU `int8`, `cpu_threads=4`, `beam_size=3`).
  - `language="id"` hardcoded (`L845`).
  - `vad_filter=False` (`L846`).
  - `_WHISPER_HALLUCINATION_RE` (`L70-73`) only checks 5 YouTube-subtitle strings; ignores Whisper's native quality signals (`seg.no_speech_prob`, `seg.avg_logprob`, `seg.compression_ratio`).
  - `_BILINGUAL_INITIAL_PROMPT` (`L78-84`) is static and contains zero user installed app names, folder names, or aliases.
- **Current Behavior:**
  1. Forcing `language="id"` coerces English commands and app/tech terms (*"Visual Studio Code"*, *"Spotify"*, *"WhatsApp"*, *"Docker"*, *"PDF"*, *"Pull Request"*) into garbled Indonesian homophones.
  2. On silence or noise-inflated buffers (`vad_filter=False`), Whisper hallucinates phantom phrases (`"Terima kasih telah menonton"`, `"Oke."`, `"Ya."`, or fragments of `_BILINGUAL_INITIAL_PROMPT`), which pass directly to the Router/LLM because `no_speech_prob` and `avg_logprob` are discarded.
  3. On hardware with CUDA GPUs (confirmed present in the owner's screenshot: `Qwen3-4B-Q4_K_M (cuda)`!), `faster-whisper-small` still runs CPU-only `int8` instead of utilizing GPU-accelerated `faster-whisper-medium` or `whisper-large-v3-turbo` (`float16`/`int8_float16`) when VRAM budget permits.
- **Expected Behavior:** Hardware-adaptive STT tiering (`small` CPU on CPU-only hosts; `large-v3-turbo` / `medium` CUDA when VRAM permits), bilingual ID+EN decoding without monolingual lock, dynamic `initial_prompt` / hotwords populated from the user's top installed apps & folder aliases, and strict segment confidence gating (`no_speech_prob > 0.6`, `avg_logprob < -1.0`, `compression_ratio > 2.4` rejected).
- **Probable Root Cause:** Confirmed suboptimal STT configuration (`language="id"`, `vad_filter=False`, ignored confidence metadata, CPU-only static model choice, zero dynamic hotwords).
- **Verification Status:** `BROKEN` (confirmed in code and live screenshot `"jam berapa sekarang"` -> `"sekarangnya berapa?"`).
- **Proposed Improvements:**
  1. Enable `vad_filter=True` (or fix upstream Silero VAD + voiced-frame gating) and enforce confidence thresholds (`no_speech_prob`, `avg_logprob`, `compression_ratio`).
  2. Support `language="auto"` constrained to `{id, en}` (two-pass language prob check or multilingual `large-v3-turbo` on CUDA / `small`/`medium` on CPU).
  3. Inject dynamic `hotwords` (`faster-whisper` supports `hotwords=` natively in recent CTranslate2 builds) derived from discovered installed app names and user aliases (capped to prevent prompt bloat/echo).
- **Security Implications:** Dynamic hotwords MUST only contain trusted app names and user-configured aliases—never secrets, private filenames from sensitive folders, or untrusted web text.
- **Acceptance Criteria:** Code-switched benchmark (*"Buka Visual Studio Code"*, *"Cari file invoice PDF di Downloads"*, *"Jam berapa sekarang?"*) improves WER by `>= 40%` over current baseline without cloud APIs; silence/noise hallucination rate `< 0.5%`.

### Factor 12 & 13: Intent Routing Failures & LLM Hallucination
- **Source Evidence:** `core/jarvis/domain/router.py:27-101, 309-410`; `core/jarvis/application/turn_orchestrator.py:113, 130, 219-410`.
- **Current Behavior:**
  - Because `normalize_utterance()` preserves Whisper trailing punctuation (`.` / `?` / `!`), regex command patterns fail silently and dump clear commands into unconstrained `Qwen3-4B` text generation.
  - Once in `Qwen3-4B`, the system prompt (`router.py:386-410`) does **not** supply current local clock/date, installed app catalog, or tool-calling schemas, AND instructs multilingual flexibility—leading `Qwen3-4B` to hallucinate capability refusals, invent fake results, or translate garbled Indonesian queries into English (exact observed failure: `"Hey Jarvis, sekarangnya berapa?"` -> `"What is the current time?"`).
  - Failed/garbled turns remain inside `_session_history`, biasing the next 6 turns.
- **Expected Behavior:**
  - Deterministic pre-normalization + fast-path high-precision matcher for unambiguous commands, backed by schema-constrained LLM tool-calling (`function_call` JSON grammar) with grounded runtime context (current local timestamp/timezone, active workspace/app summary, memory facts).
  - Explicit clarification turn when STT confidence is borderline or intent/entity is ambiguous—never silent hallucination or unsolicited translation.
- **Probable Root Cause:** Confirmed punctuation-normalization bug + absence of grounded context and structured tool-calling + unfiltered session-history retention.
- **Verification Status:** `BROKEN` (verified in source code and owner runtime screenshot).
- **Proposed Improvements:** Fix `normalize_utterance()`, inject current local time/date & user language lock into system context, add grammar-constrained tool-calling, add ambiguity clarification state, and exclude rejected/error turns from `_session_history`.
- **Security Implications:** Tool calls produced by the LLM MUST be treated as untrusted proposals—parsed against strict JSON Schema and authorized by deterministic Python Policy Engine before execution.
- **Acceptance Criteria:** `0` translation-echo hallucinations across 100 noisy Indonesian queries; deterministic command recognition accuracy `>= 97%` on clean audio and `>= 90%` under 50 dB ambient noise.

### Factor 14 & 15: TTS Pronunciation, Naturalness, and Audio Playback Quality
- **Source Evidence:** `live_voice_engine.py:75, 131-143, 466-499, 593, 640`; `id_ID-news_tts-medium.onnx.json` (`espeak voice: "id"`, `22050 Hz`).
- **Current Behavior:**
  - Single monolingual Indonesian `news_tts` model pronounces English words, app names (*"Chrome"*, *"Visual Studio Code"*, *"WhatsApp"*), acronyms (*"CPU"*, *"RAM"*, *"PDF"*), numbers, timestamps (`14:30`), file paths (`C:\...`), and non-Latin scripts unnaturally or drops characters completely.
  - `_MARKDOWN_CLEAN_RE` strips only 7 punctuation chars; code blocks, URLs, bullet symbols, emoji, and JSON artifacts are read literally (`"titik dua garis miring..."`).
  - `speech_rate` setting in `VoicePipelineService` is ignored; playback runs synchronously on `_capture_loop` with no streaming sentence chunking (full TTS synthesis completes before the first sample plays).
- **Expected Behavior:**
  - Dedicated TTS text-normalization stage: strip Markdown/code blocks cleanly, verbalize times/dates/units in natural Indonesian (*"pukul dua siang lewat tiga puluh menit"* or *"jam 14.30"*), apply user pronunciation lexicon for technical/English loanwords (e.g., `Chrome` -> phonetic hint or bilingual segment routing), and shorten verbose paths/URLs.
  - Sentence-level streaming TTS (synthesize sentence 1 while LLM streams sentence 2) on a dedicated playback worker thread bound to the selected WASAPI output device.
- **Probable Root Cause:** Confirmed missing text normalizer, monolingual voice lock, ignored speech-rate config, and non-streaming synchronous playback.
- **Verification Status:** `BROKEN` / `PARTIAL`.
- **Proposed Improvements:** Implement deterministic Indonesian+English TTS normalizer + local pronunciation lexicon (`pronunciation_lexicon` table), wire `speech_rate`/`length_scale` into Piper `SynthesisConfig`, add optional local English voice (e.g., `en_US-lessac-medium` or Kokoro-82M) for English responses, and stream sentence-by-sentence playback.
- **Security Implications:** TTS normalizer must sanitize control characters and cap maximum utterance duration to prevent denial-of-speech from runaway LLM output or malicious document text.
- **Acceptance Criteria:** Zero raw Markdown/URL/path spelling-out during spoken replies; human/MOS intelligibility rubric `>= 4.0 / 5.0` on bilingual ID+EN command confirmations; `speech_rate` updates reflect immediately on next spoken sentence.

### Factor 17: End-to-End Response Latency & Synchronous Loop Blocking
- **Source Evidence:** `live_voice_engine.py:821, 930-944` (`_process_utterance_audio` invoked synchronously inside `_capture_loop`; LLM timeout `65s`, TTS timeout `60s`; queue `maxsize=250` = `8.0s`).
- **Current Behavior:** End-to-end voice latency is purely serial (`0.72s` VAD silence wait + CPU `faster-whisper-small` full-utterance decode + full non-streamed LLM generation + full Piper synthesis of entire reply + `sd.wait()`). Meanwhile, `_capture_loop` stops draining PortAudio frames during inference and playback, discarding incoming audio after 8 seconds.
- **Expected Behavior:** Pipeline parallelism: non-blocking capture thread -> VAD/Wake thread -> GPU-accelerated STT -> streaming LLM -> sentence-chunked streaming TTS -> dedicated playback thread, targeting **Time to First Audible Response (TTFAR) `<= 1.8s` (GPU) / `<= 3.5s` (CPU)** for standard queries and **`<= 600ms`** for local deterministic commands.
- **Probable Root Cause:** Confirmed single-threaded synchronous pipeline execution inside `_capture_loop` plus lack of LLM->TTS sentence streaming.
- **Verification Status:** `BROKEN` (blocking capture loop verified in source; live p50/p95 latency `UNVERIFIED` pending instrumented benchmark).
- **Proposed Improvements:** Decouple into 4 bounded producer-consumer queues with cancellation tokens (enabling instant barge-in cancellation of in-flight LLM and TTS synthesis), stream LLM tokens into sentence boundaries for immediate Piper synthesis, and emit stage-by-stage timing telemetry (`t_vad_end`, `t_stt_done`, `t_route_done`, `t_llm_first_token`, `t_tts_first_audio`).
- **Security Implications:** Cancellation tokens must never interrupt an already-committed atomic state change mid-write; cancellation applies strictly to perception/generation/playback stages.
- **Acceptance Criteria:** Capture queue drop counter stays `0` under 30-minute continuous session; deterministic command TTFAR `<= 600ms` p95; conversational LLM TTFAR `<= 2.0s` p95 on CUDA hardware.

---

## 4. Diagnostic Isolation Methodology (Separating STT, Intent, LLM & TTS Errors)

To prevent misdiagnosing downstream symptoms as upstream model defects (or prematurely jumping to expensive fine-tuning), every reported voice failure MUST be isolated using a **4-stage deterministic replay harness** (read-only offline trace replay against captured opt-in fixtures):

| Stage Boundary | Diagnostic Probe / Replay Test | Error Attribution Rule |
| :---: | --- | --- |
| **Probe A: Audio/VAD vs STT** | Inspect captured pre-STT 16kHz WAV waveform (SNR, clipping %, voiced-duration ratio) & compare human ground-truth transcript against `faster-whisper` output + `no_speech_prob` / `avg_logprob`. | If waveform is clipped, silent, echo-contaminated, or cut off -> **Audio/VAD defect**. If waveform is clean (`SNR > 15 dB`) but transcript has wrong words -> **STT defect**. |
| **Probe B: STT vs Intent Router** | Feed **human ground-truth text** (both with and without Whisper trailing punctuation `.` `?`) directly into `router.py` / `TurnOrchestrator` bypassing microphone and STT. | If ground-truth text routes correctly without `.` but fails with `.` or polite prefix -> **Normalizer/Router defect**. If ground-truth fails even cleanly formatted -> **Intent/Entity/Catalog defect**. |
| **Probe C: Intent vs LLM Generation** | Feed exact assembled LLM prompt (system prompt + context + history + clean user turn) into `llama-server` with fixed seed (`temperature=0`) and inspect raw JSON/text output. | If prompt lacks clock/app/memory context -> **Context-Injection defect**. If prompt has clean context yet model still hallucinates/drifts language -> **Prompting or Base LLM capability defect**. |
| **Probe D: LLM vs TextNorm/TTS** | Feed known clean Indonesian & ID+EN test sentences directly into `_MARKDOWN_CLEAN_RE` -> Piper -> WAV and evaluate intelligibility & phoneme trace. | If clean text produces garbled pronunciation or drops English words -> **Text Normalizer / Piper TTS defect** (not LLM or STT). |

### Baseline-First Conclusion (Why Fine-Tuning Must NOT Start Yet)

> **Audit Verdict on Fine-Tuning Prematurity:** Based on concrete source evidence, **>80% of the owner's observed voice failures are caused by deterministic engineering defects** (VAD 33-frame noise inflation, hardcoded `language="id"`, discarded Whisper confidence scores, unstripped trailing `.` breaking regexes, absent DSP/AEC, unwired device selection, missing clock/catalog context, and unnormalized monolingual TTS)—**not** by fundamental weights deficiencies requiring immediate LLM/STT fine-tuning.
>
> Fine-tuning models on top of a broken capture/VAD/router/normalizer pipeline would waste compute, overfit to pipeline bugs, and fail to fix root causes. **Mandatory sequencing:** (1) fix deterministic pipeline bugs and establish baseline metrics via the evaluation harness ([32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)); (2) upgrade inference config & pretrained model tier where hardware permits; (3) evaluate fine-tuning/LoRA ONLY for residual error classes proven by held-out benchmark deltas (see [31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md](./31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md)).
