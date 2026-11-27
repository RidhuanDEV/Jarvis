# 25 — Owner-Reported Issues: Forensic Root-Cause Investigation

> **Document Scope:** Independent root-cause investigation of the five real-world usability problems reported by the system owner after operating the implemented J.A.R.V.I.S. (`v0.2.1`) application on Windows. Each reported problem is treated strictly as an **owner-reported symptom**, traced through actual source code and observed runtime artifacts to separate confirmed defects from suspected contributing factors and unverified surfaces.
>
> **Cross-References:** Deep technical expansions live in [26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md](./26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md), [27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md](./27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md), [28-FILE-SYSTEM-INTELLIGENCE-ASSESSMENT.md](./28-FILE-SYSTEM-INTELLIGENCE-ASSESSMENT.md), [29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md), and [33-CAPABILITY-ENHANCEMENT-OPPORTUNITIES.md](./33-CAPABILITY-ENHANCEMENT-OPPORTUNITIES.md).

---

## 1. Executive Summary Matrix

| Symptom ID | Owner-Reported Symptom | Verification Status | Confirmed Root-Cause Mechanism(s) | Primary Source Files |
| :---: | --- | :---: | --- | --- |
| **ORI-01** | Voice recognition or voice responses are unclear, inaccurate, unnatural, or occasionally nonsensical | `BROKEN` | Monolingual `language="id"` Whisper with zero confidence/no-speech gating; VAD 33-frame noise-inflation bug; `0.58s` wake-greeting echo/collision window; monolingual Indonesian Piper `espeak` TTS fed English/multilingual/unnormalized text; LLM translation-drift on garbled STT + `_session_history` poisoning | `core/jarvis/infrastructure/live_voice_engine.py`, `core/jarvis/domain/router.py`, `core/jarvis/application/turn_orchestrator.py` |
| **ORI-02** | JARVIS sometimes misunderstands simple spoken commands | `BROKEN` | `normalize_utterance()` never strips Whisper trailing punctuation (`.` / `!` / `,`), breaking `_APP_LAUNCH_RE`, `_TIME_RE`, `_VOLUME_MUTE_RE`, `_TASK_LIST_RE`, `_SCREEN_ANALYZE_RE`; zero polite-prefix stripping; forced wake-word repetition when follow-up window expires (`45s`) or barge-in is blocked by naive Echo Guard | `core/jarvis/domain/router.py`, `core/jarvis/infrastructure/live_voice_engine.py` |
| **ORI-03** | Opening ordinary installed applications is unnecessarily rejected by the authorization system | `BROKEN` | Four stacked defects: (1) trailing `.` regex capture misses alias map; (2) `os.app.launch` requires explicit R1 DB grant omitted by 1-Click Onboarding; (3) `WindowsDesktopAutomationAdapter` hardcodes only 3 System32 executables and raises `PermissionError` for all other apps; (4) `app.py:620` hardcodes `allow_live_launch=False`, silently turning allowed launches into fake no-ops | `core/jarvis/platform/windows/desktop_automation.py`, `core/jarvis/transport/app.py`, `core/jarvis/domain/policy.py`, `apps/desktop/src/components/OnboardingWizard.tsx` |
| **ORI-04** | JARVIS does not provide the expected level of awareness of local files, directories, and installed applications | `PARTIAL` / `NOT IMPLEMENTED` | Drive enumeration (`windows/filesystem.py`) is disconnected from AI/tools; `KnowledgePanel` UI is 100% Zustand mock; RAG only indexes manually synced `.txt/.md/.pdf/.docx` via BM25 (`embedding_provider=None`); zero file watchers, zero filename/fuzzy search, zero recent-file tracking, zero file opener, zero Windows installed-app discovery | `core/jarvis/platform/windows/filesystem.py`, `core/jarvis/application/knowledge_service.py`, `apps/desktop/src/components/ProductivityPanels.tsx`, `core/jarvis/transport/app.py` |
| **ORI-05** | The current experience does not yet feel like a comprehensive JARVIS-inspired Personal Intelligence System | `PARTIAL` | Overall maturity `1.35 / 5.0` across 20 pillars: single-turn regex-or-prose loop (no multi-step planner/agentic execution), unwired Memory Vault & Persona Config, zero proactive background scheduler, orphaned R2 approval execution (`execute_approved_file_move` has 0 callers), stubbed Workflow Runner & Extension SDK, and mock-only desktop productivity panels | `core/jarvis/application/turn_orchestrator.py`, `core/jarvis/application/memory_service.py`, `core/jarvis/application/workflow_service.py`, `apps/desktop/src/App.tsx` |

---

## 2. Observed Runtime Evidence Baseline

During live usage prior to this audit, the owner captured a direct runtime screenshot of the Voice-First Command Center ([screenshots/actual-voice-command-center-defect-01.png](./screenshots/actual-voice-command-center-defect-01.png)) demonstrating **ORI-01** and **ORI-02** simultaneously:

- **Owner's Spoken Input:** Indonesian time query ("jam berapa sekarang" following wake phrase "Hey Jarvis").
- **Observed STT Output Displayed (`Anda:`):** `"Hey Jarvis, sekarangnya berapa?"` (phonetic distortion dropping `"jam"`, appending Whisper trailing `?`).
- **Observed Assistant Response Displayed:** `"What is the current time?"` (English echo/translation instead of answering the local time).
- **Observed Active Stack Banner:** `STT: faster-whisper-small | TTS: Piper ID Lokal | Brain: Qwen3-4B-Q4_K_M (cuda)`.
- **Observed Telemetry Strip:** `Event Cursor: seq #0`, `Stale Rejected: 0`, `Deny-by-Default: ENFORCED` — confirming the voice engine mutated UI state via polling/direct channel rather than the core SQLite-backed SSE event cursor (`seq #0` remained zero after a completed turn).

---

## 3. Detailed Per-Symptom Findings

### Finding ORI-01: Unclear, Inaccurate, Unnatural, or Nonsensical Voice Recognition and Responses

#### 1. Source Evidence
- `core/jarvis/infrastructure/live_voice_engine.py:70-84` — `_WHISPER_HALLUCINATION_RE` (only 5 phrases) and static `_BILINGUAL_INITIAL_PROMPT` containing English/Indonesian examples without user vocabulary.
- `core/jarvis/infrastructure/live_voice_engine.py:299-307`, `706-707`, `759`, `793-821` — VAD onset (`rms >= 0.004 and prob >= 0.42`) prepends `10` pre-roll frames (`320ms`) and waits `SILENCE_END_SECONDS = 0.72` (`22` frames), inflating any single 32ms noise spike into `33` frames (`1.056s`) and bypassing `min_speech_blocks = 8`.
- `core/jarvis/infrastructure/live_voice_engine.py:593`, `640`, `673-679` — `sd.InputStream(samplerate=16000, channels=1, dtype="float32", blocksize=512)` and `sd.play(...)` omit `device=`, binding strictly to OS default endpoints; zero DSP (no AGC, no NS, no HPF, no AEC).
- `core/jarvis/infrastructure/live_voice_engine.py:843-851` — `model.transcribe(audio, language="id", beam_size=3, vad_filter=False, ...)` hardcodes Indonesian and discards `seg.no_speech_prob`, `seg.avg_logprob`, and `seg.compression_ratio`.
- `core/jarvis/infrastructure/live_voice_engine.py:75`, `131-143`, `466-499` — Piper TTS (`id_ID-news_tts-medium.onnx`, `espeak voice: "id"`, `22050 Hz`) strips only `[`*_#>\[\]]+` before phonemization; zero normalization for English words, acronyms, URLs, paths, or non-Latin scripts.
- `core/jarvis/domain/router.py:386-410` — System prompt instructs `Qwen3-4B` to respond in multiple languages (including non-Latin scripts) without restricting output to TTS-speakable Indonesian/English or guarding against translating ambiguous STT transcripts.
- `core/jarvis/application/turn_orchestrator.py:113`, `130`, `276-370` — Garbled STT utterances and nonsensical assistant replies are unconditionally appended to `_session_history` (`deque(maxlen=12)`).
- Runtime screenshot: [screenshots/actual-voice-command-center-defect-01.png](./screenshots/actual-voice-command-center-defect-01.png).

#### 2. Current Behavior
1. Raw microphone audio is captured from the Windows default input without noise suppression, gain normalization, or hardware/software acoustic echo cancellation (AEC), ignoring any device selected via `PUT /v1/audio/devices`.
2. Any transient 32ms acoustic click/pop triggers VAD speech capture, pads it to `1.056s`, and sends it to `faster-whisper-small` with `language="id"` and `vad_filter=False`, generating unscreened phonetic hallucinations.
3. Because `"sekarangnya berapa?"` failed `_TIME_RE` (missing `"jam"`), the malformed utterance fell through to `Qwen3-4B`, which interpreted the garbled phrase as a translation/clarification prompt and returned `"What is the current time?"` in English.
4. Piper's Indonesian `news_tts` voice then synthesized English text (`"What is the current time?"`) using Indonesian `espeak` phonemization rules, producing heavily mangled, robotic, unnatural speech.
5. Both the misheard transcript and nonsensical English reply persisted into `_session_history`, contaminating subsequent turns.

#### 3. Expected Behavior
1. Voice capture binds to a verified, user-selectable low-noise microphone (with level meter, HPF, AGC/clipping guard, noise suppression, and AEC).
2. Non-speech noise spikes are rejected before STT; low-confidence STT segments (`no_speech_prob`, `avg_logprob`, `compression_ratio`) trigger a brief, natural clarification request rather than blind LLM hallucination or history pollution.
3. Spoken questions like `"jam berapa sekarang"` (even with minor phonetic variations) resolve reliably to local clock data and answer naturally in the user's active language.
4. Text sent to TTS passes through a language-aware spoken-text normalizer (acronyms, numbers, time/date, URLs, paths, code-switched English app names) and uses a matched language/prosody voice model.

#### 4. Probable Root Cause
**Confirmed multi-stage compounding failure** (no single component is solely responsible):
- **Confirmed Stage 1–3 (Audio/VAD):** Missing DSP/AEC + VAD `pre_roll + trailing_silence` frame-count inflation bug (`live_voice_engine.py:706-821`) + `POST_WAKE_FOLLOW_SECONDS = 0.58` greeting collision (`L764-791`).
- **Confirmed Stage 4 (STT):** Hardcoded `language="id"`, `vad_filter=False`, absent confidence/logprob rejection, and unadapted `faster-whisper-small` CPU int8 decoding (`L843-851`).
- **Confirmed Stage 5–6 (Routing/LLM):** Missing deterministic time-pattern recall on noisy phrasing + permissive LLM system prompt causing language/translation drift + unfiltered `_session_history` injection (`router.py:386-410`, `turn_orchestrator.py:276-370`).
- **Confirmed Stage 7 (TTS):** Monolingual Indonesian `news_tts` (`espeak id`) speaking raw English/technical strings without text normalization (`L131-143`, `L466-499`).

#### 5. Verification Status
- **`BROKEN`** (Confirmed both by source-code inspection AND owner runtime screenshot [actual-voice-command-center-defect-01.png](./screenshots/actual-voice-command-center-defect-01.png)).

#### 6. Proposed Improvements
1. Fix VAD speech-duration accounting to count **actual voiced frames** (excluding pre-roll and trailing silence) before dispatching to STT; integrate lightweight WebRTC/RNNoise NS + AEC + high-pass filter.
2. Wire `LiveVoiceEngine` to `VoicePipelineService` / `AudioDevicePort` (WASAPI endpoint selection rather than WinMM 32-char truncated names).
3. Remove forced `language="id"` in favor of bilingual ID/EN decoding (`language=None` with ID/EN probability floor or dual-language Whisper prompt) and add `no_speech_prob` / `avg_logprob` / `compression_ratio` confidence gates.
4. Add a dedicated TTS text-normalization layer (numbers, Indonesian clock/date phrasing, acronyms, file paths, English loanwords) and language-matched Piper/Kokoro voice routing.
5. Prevent low-confidence or error turns from entering `_session_history`.
6. Execute baseline diagnostic isolation (see [26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md](./26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md)) **before** considering any STT/LLM/TTS fine-tuning.

#### 7. Security Implications
- Hallucinated or misheard transcripts routed directly to tool dispatch create an **accidental action execution risk** (e.g., noisy audio decoded as an app launch or volume change).
- Unfiltered LLM outputs read aloud or pushed to conversation memory can propagate prompt-injection strings if untrusted screen/document context is later combined with voice turns.
- Confidence gating and deterministic slot validation are security controls as well as usability controls.

#### 8. Acceptance Criteria
- 100 consecutive background-noise clicks/keyboard taps produce `0` spurious Whisper transcriptions or LLM turns (`VAD false-trigger rate = 0%`).
- Audio device selection in UI/API immediately rebinds `LiveVoiceEngine` input and output streams (`audio.devices_changed` subscriber verified).
- On a held-out 100-utterance Indonesian + ID/EN benchmark, STT WER `<= 10%`, zero nonsensical cross-language echo replies, and low-confidence audio (`avg_logprob < threshold`) triggers clarification without polluting `_session_history`.
- Time/date/app-name TTS output passes intelligibility rubric without garbled Indonesian phonemization of English sentences or raw Markdown/symbols.

---

### Finding ORI-02: Misunderstanding Simple Spoken Commands

#### 1. Source Evidence
- `core/jarvis/domain/router.py:27`, `34`, `37`, `66`, `76`, `99-101`, `309` — `normalize_utterance()` only collapses whitespace and lowercases text; it **never strips trailing punctuation** (`.`, `!`, `,`, `?`) emitted by Whisper.
  - Line `37`: `_APP_LAUNCH_RE = re.compile(r"^(?:buka|open|launch|jalankan)\s+([a-z0-9 _.-]{2,40})$")` includes `.` in the capture class, so `"Buka kalkulator."` captures `target = "kalkulator."`, which fails lookup in `_APP_ALIASES` (`L80-87`: `"kalkulator"`, `"calculator"`, `"calc"`, `"notepad"`, `"catatan"`, `"paint"`).
  - Anchored regexes (`_TIME_RE`, `_VOLUME_MUTE_RE`, `_TASK_LIST_RE`, `_SCREEN_ANALYZE_RE`) fail whenever Whisper appends a trailing period `.` or prepends conversational politeness (`"tolong buka kalkulator"`, `"coba cek jam berapa sekarang"`, `"jarvis tolong matikan suara"`).
- `core/jarvis/domain/router.py:80-87` — `_APP_ALIASES` only maps 6 Indonesian/English keys to 3 apps (`calculator`, `notepad`, `paint`).
- `core/jarvis/infrastructure/live_voice_engine.py:300`, `730-741`, `764-791`, `821`, `930-944` —
  - `POST_WAKE_FOLLOW_SECONDS = 0.58`: if the user pauses `>580ms` after `"Hey Jarvis"`, the engine plays `"Ya, siap..."` while the user begins speaking, activating the naive mute Echo Guard (`L730-741`) and clipping the start of the command.
  - `_process_utterance_audio()` executes synchronously inside `_capture_loop`, blocking audio queue drainage during up to 65s LLM + 60s TTS, silently dropping audio frames once `queue.Queue(maxsize=250)` fills (~8s).
  - Follow-up conversation window closes silently after timeout or any missed barge-in, forcing the user to repeat `"Hey Jarvis"` even during an active conversation.

#### 2. Current Behavior
Simple, natural Indonesian and mixed ID-EN commands such as `"Buka kalkulator."`, `"Tolong buka Notepad."`, `"Bisukan suara."`, `"Jam berapa sekarang."`, or `"Buka Chrome"` fail deterministic regex matching because of Whisper's trailing punctuation, conversational prefixes, or tiny 3-app alias table. They fall through to `Qwen3-4B` free-form prose, which either answers conversationally without executing any tool, hallucinates that it cannot perform the action, or misinterprets the intent. Additionally, pausing slightly after `"Hey Jarvis"` causes the greeting TTS to swallow the first syllables of the spoken command.

#### 3. Expected Behavior
1. Spoken commands undergo punctuation stripping, wake-word residual trimming, and polite-prefix normalization (`"tolong"`, `"coba"`, `"bisa"`, `"please"`) before intent classification.
2. Common desktop, media, time, file, and application intents parse reliably regardless of Whisper punctuation or phrasing variations, using structured function/tool calling backed by deterministic slot validation.
3. Wake-word activation cleanly transitions into an active multi-turn listening state (supporting headset barge-in and clear visual/audio cueing) without truncating the user's command or forcing repeated `"Hey Jarvis"` prefixes during active conversation.

#### 4. Probable Root Cause
**Confirmed architectural and parser defects:**
1. Regex fragility in `router.py` (`normalize_utterance` preserves `.` / `!` / `,` while `_APP_LAUNCH_RE` greedily consumes `.` into the app name; rigid `^...$` anchors reject natural Indonesian polite wrappers).
2. Absence of real LLM structured tool-calling (`function_call` / JSON grammar constrained to active tool schemas) as fallback when deterministic fast-path patterns do not match.
3. Synchronous `_capture_loop` blocking and naive 0.58s greeting/echo-guard timing in `live_voice_engine.py`.

#### 5. Verification Status
- **`BROKEN`** (Confirmed directly in `router.py:27-101, 309` and `live_voice_engine.py:730-821, 930-944`, corroborated by owner runtime reports).

#### 6. Proposed Improvements
1. Normalize transcripts before routing (strip leading/trailing punctuation, deduplicate residual wake phrases, strip optional polite prefixes while preserving raw transcript for audit).
2. Decouple audio capture/VAD from STT/LLM/TTS onto dedicated worker threads/queues so live frames are never dropped during inference.
3. Replace hardcoded 3-app regex aliases with a structured Intent + Entity Resolution pipeline (fast deterministic matcher for high-frequency commands + grammar-constrained LLM tool-calling validated strictly against the trusted Tool Registry & Policy Engine).
4. Replace the fixed `0.58s` verbal greeting with an instant non-blocking subtle chime (<=120ms) or full-duplex AEC barge-in, and expose explicit active-conversation state with configurable idle timeout in the UI.

#### 7. Security Implications
- Broadening intent matching MUST NEVER bypass server-side authorization or allow free-form command strings into shells/executors.
- Every resolved entity (app ID, file path, volume delta) must still be validated strictly against canonical trusted registries (Policy Engine + approved scopes) before dispatch.

#### 8. Acceptance Criteria
- `"Buka kalkulator."`, `"Tolong buka kalkulator!"`, `"Buka Google Chrome."`, `"Jam berapa sekarang."`, and `"Tolong bisukan suara."` achieve `>= 98%` intent + entity resolution accuracy on the evaluation dataset ([32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)).
- Speaking a command `0.2s`–`2.0s` after `"Hey Jarvis"` never drops initial syllables.
- Multi-turn follow-up commands work without repeating `"Hey Jarvis"` while the conversation session is active, and revert to wake-word standby cleanly on timeout or explicit `"selesai"` / `"terima kasih"`.

---

### Finding ORI-03: Opening Ordinary Installed Applications Unnecessarily Rejected (or Silently Faked)

#### 1. Source Evidence
- `core/jarvis/domain/router.py:37`, `80-87`, `401` — Regex captures trailing `.` and alias table only knows `calculator`, `notepad`, `paint`.
- `core/jarvis/domain/policy.py:274-282` & `core/jarvis/transport/app.py:143` — `os.app.launch` is classified `R1` (`requires_grant=True`), triggering `403 DENIED` whenever no active `permission_grant` row exists for `os.app.launch`.
- `apps/desktop/src/lib/brokerClient.ts:273-278` & `apps/desktop/src/components/OnboardingWizard.tsx:99-104` — `"1-Click Recommended Setup"` skips Step 9 (`allowAppGrant` defaults to `false`), and desktop bootstrap auto-grants only `screen.read`, never `os.app.launch`.
- `core/jarvis/platform/windows/desktop_automation.py:13-17`, `27-37` — Hardcodes a 3-entry dictionary:
  ```python
  _ALLOWLISTED_WINDOWS_APPS = {
      "calculator": "calc.exe",
      "notepad": "notepad.exe",
      "paint": "mspaint.exe",
  }
  ```
  All binaries must reside in `SYSTEMROOT\System32`; any other installed application (Chrome, Edge, VS Code, Spotify, Word, Excel, Discord, Explorer, etc.) raises `PermissionError` -> mapped to authorization rejection.
- `core/jarvis/transport/app.py:620` & `core/jarvis/platform/windows/desktop_automation.py:38-39` — Production wiring instantiates **`WindowsDesktopAutomationAdapter(allow_live_launch=False)`**, causing even an explicitly granted `calculator` launch to return a synthetic `verified=True` success dictionary **without calling `subprocess.Popen` or launching any process!**

#### 2. Current Behavior
1. On a freshly onboarded desktop install, attempting to open *any* application fails with an authorization denial because `os.app.launch` lacks a DB grant.
2. Even if the user manually grants `os.app.launch` in Settings, requesting any ordinary installed application outside `calc.exe`/`notepad.exe`/`mspaint.exe` is unconditionally rejected by `desktop_automation.py`.
3. Even if the user requests `calculator` with an active grant and zero trailing punctuation, `app.py:620` passes `allow_live_launch=False`, so JARVIS claims the app opened while **nothing launches on Windows**.

#### 3. Expected Behavior
Under the owner's revised authorization policy (Addendum §B):
- Discovering ordinary installed applications and launching trusted, non-elevated installed applications (e.g., Chrome, VS Code, Calculator, Spotify, Office apps) is **Tier 1 (automatically allowed within authorized scopes)** with zero repetitive confirmation prompts.
- Dangerous binaries, shells, script hosts, and elevation/admin tools (`cmd.exe`, `powershell.exe`, `pwsh.exe`, `wscript.exe`, `cscript.exe`, `mshta.exe`, `regedit.exe`, `rundll32.exe`, `msiexec.exe`, etc.) remain **Tier 3 (strictly prohibited)** or require explicit non-bypassable policy blocks.
- Launches execute real non-elevated Windows process creation with verified PID/window confirmation (never fake `allow_live_launch=False` stubs in production).

#### 4. Probable Root Cause
**Confirmed four-layer stack failure:**
1. Policy model misclassified ordinary read/launch desktop actions as deny-by-default R1 requiring manual per-capability DB grants (`policy.py:274`).
2. Onboarding flow defaulted `allowAppGrant = false` (`OnboardingWizard.tsx:99-104`).
3. Platform adapter replaced dynamic installed-app discovery with a 3-entry System32 test stub (`desktop_automation.py:13-17`).
4. Production composition root left the test safety toggle `allow_live_launch=False` hardcoded (`app.py:620`).

#### 5. Verification Status
- **`BROKEN`** (All four root-cause layers directly verified in source code).

#### 6. Proposed Improvements
1. Implement a real Windows Installed Application Catalog (Registry `Uninstall` + `App Paths`, Start Menu `.lnk` resolved & validated, AppX/MSIX AUMID discovery — detailed in [29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md)).
2. Enforce a trusted-application classification policy: auto-allow ordinary non-elevated user/GUI apps under Tier 1; hard-ban shells, script engines, installers, and LOLBins under Tier 3; block `runas`/UAC elevation.
3. Remove `allow_live_launch=False` from production runtime wiring (keep dry-run strictly isolated to unit test fixtures).
4. Expose an Application Alias & Trust Manager in Settings so the owner can add aliases (e.g., `"browser"` -> Edge/Chrome, `"koding"` -> VS Code) or block specific apps.

#### 7. Security Implications
- Naively allowing arbitrary executable paths or shell commands would create an immediate **arbitrary command execution / Tier-3 policy bypass** (including via prompt injection).
- Launching MUST resolve strictly against a verified, canonicalized, non-elevated Application Catalog entry (never passing user/LLM text to `shell=True`, `cmd /c`, or unvalidated `.lnk` target arguments containing LOLBins).
- Full security analysis appears in [27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md](./27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md) and [29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md).

#### 8. Acceptance Criteria
- Freshly onboarded JARVIS discovers `>= 90%` of standard installed Windows GUI apps (Win32 + MSIX/Store) without admin privileges.
- Saying `"Buka Chrome"` or `"Buka kalkulator"` launches the actual non-elevated Windows process in `< 1.0s` without prompting for confirmation and emits a truthful audit event containing canonical app ID and PID.
- Attempting `"Buka PowerShell"`, `"Jalankan cmd"`, `"Buka regedit"`, or a crafted `.lnk` pointing to `powershell.exe -enc ...` is deterministically blocked by trusted Python policy code with audit logging (`0%` unauthorized execution rate).

---

### Finding ORI-04: Lack of Awareness of Local Files, Directories, and Installed Applications

#### 1. Source Evidence
- `core/jarvis/platform/windows/filesystem.py:169-191` — `list_volumes()` exists for `GET /v1/storage/volumes`, but has **0 references** in `TurnOrchestrator`, `Router`, `ToolRegistry`, or `KnowledgeService`.
- `apps/desktop/src/App.tsx:727-733` & `apps/desktop/src/components/ProductivityPanels.tsx:30-38` — `KnowledgePanel` UI is **100% Zustand local mock state** (`addDocument`, `documents` fixture); never calls `/v1/knowledge/roots`, `/v1/knowledge/sync`, or `/v1/knowledge/query`.
- `core/jarvis/application/knowledge_service.py:184-350` & `core/jarvis/infrastructure/document_parser.py:15`, `184-189` — `sync_source_root` only indexes manually registered roots and only 4 text-like formats (`.txt`, `.md`, `.pdf`, `.docx`, `<= 25 MiB`), parses full PDFs on every sync before checking SHA-256, and ignores `scope_json` extension filters.
- `core/jarvis/application/knowledge_service.py:72-79`, `core/jarvis/transport/app.py:610-619` — `embedding_provider=None` everywhere; zero `EmbeddingProviderPort` implementation; zero `sqlite-vec` `vec0` tables (BM25 lexical search only).
- `core/jarvis/transport/app.py:120-255` (`default_tool_registry()`, all 13 registered tools) — Zero tools exist for: listing drives/folders, filename search (exact or fuzzy), extension/date/size filtering, recent files, opening documents via registered OS app (`ShellExecuteW`/`os.startfile`), discovering installed apps, or resolving user file/folder aliases.
- Repository-wide search confirms zero filesystem watchers (`watchdog`, `ReadDirectoryChangesW`, USN Journal), zero Windows Search / Everything SDK bridges, and zero Windows Registry app enumeration (`winreg` is only imported in `core/jarvis/platform/windows/audio.py:106`).

#### 2. Current Behavior
JARVIS cannot answer basic local-awareness questions such as *"Aplikasi apa saja yang terinstall?"*, *"Cari file laporan PDF minggu ini"*, *"Buka folder proyek Jarvis"*, or *"File apa yang barusan saya edit?"*. Its only file capability is searching manually registered text/PDF/DOCX chunks through a backend API that the desktop Knowledge UI does not even call, plus a single regex-bound `fs.file.move` dry-run whose execution handler is orphaned.

#### 3. Expected Behavior
Within owner-authorized scopes (and strictly honoring exclusion boundaries and non-deletion rules):
- JARVIS maintains a fast, incrementally updated **Filesystem Metadata Index** (paths, names, extensions, sizes, modified times, recent-file signals) separated cleanly from on-demand **Full-Text Search (FTS5)**, selective **Semantic Document Retrieval**, and **Personal Memory**.
- JARVIS dynamically discovers authorized drives/folders and installed applications, supports exact + fuzzy search, date/extension filters, conversation-aware file resolution (*"buka file yang tadi"*), user-defined file/folder/app aliases, and safe document opening via registered Windows apps.

#### 4. Probable Root Cause
**Confirmed capability omission & UI disconnection:**
- Core v0.2.1 implementation focused on minimal RAG chunk storage for 4 document types and 3 hardcoded System32 apps, leaving filesystem metadata indexing, file watchers, OS file-open verbs, application discovery, semantic embeddings, and frontend Knowledge wiring unimplemented or mocked.

#### 5. Verification Status
- **`NOT IMPLEMENTED`** for metadata indexing, file watching, filename/fuzzy/recent search, file opening, semantic embeddings, app discovery, and aliases; **`PARTIAL`** for manual 4-format BM25 RAG; **`MOCK`** for desktop `KnowledgePanel` UI.

#### 6. Proposed Improvements
1. Implement the 4-layer knowledge & awareness architecture detailed in [28-FILE-SYSTEM-INTELLIGENCE-ASSESSMENT.md](./28-FILE-SYSTEM-INTELLIGENCE-ASSESSMENT.md):
   - Layer 1: Lightweight SQLite metadata + trigram/FTS5 filename index fed by non-admin `ReadDirectoryChangesW`/`watchdog` + optional Windows Search / Everything read-only adapters.
   - Layer 2: Selective FTS5 full-text extraction for authorized document roots.
   - Layer 3: Local ONNX embedding + `sqlite-vec` semantic retrieval only for curated knowledge scopes (never blind whole-disk embedding).
   - Layer 4: Personal memory & user-defined file/folder/app aliases.
2. Implement Windows Installed Application Discovery ([29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md)).
3. Replace Zustand mock state in `ProductivityPanels.tsx` with real Core API integration.

#### 7. Security Implications
- Broad filesystem awareness MUST enforce strict canonical path boundaries (`RealPath` containment), hard exclusion lists (`Windows`, `ProgramData`, browser cookie/token stores, `.ssh`, `.env`, `.aws`, `.git` credentials, `jarvis_core.db`), reparse-point/symlink loop & escape defenses, and strict read-only separation so discovery never grants modification or deletion capability.
- Opening documents via Windows Shell MUST denylist executable/script extensions (`.exe`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`, `.hta`, `.msi`, `.scr`, `.lnk`, `.reg`) so "open document" cannot be abused as arbitrary code execution.

#### 8. Acceptance Criteria
- Fuzzy filename + extension + date search across `100,000` indexed user files completes in `< 50ms` p95 with `< 150 MB` RAM overhead.
- Symlink/junction pointing outside an authorized scope or into excluded credential directories is blocked and logged.
- Opening an authorized `.pdf`/`.docx`/`.xlsx`/`.png` launches its registered default app under Tier 1; attempting to "open" a `.ps1`/`.bat`/`.exe` via document-open is strictly blocked under Tier 3.
- Follow-up utterance *"buka file kedua tadi"* resolves deterministically via conversation entity state.

---

### Finding ORI-05: Overall Experience Does Not Yet Feel Like a Comprehensive JARVIS Personal Intelligence System

#### 1. Source Evidence
- Cross-system maturity audit in [20-JARVIS-CAPABILITY-MATURITY.md](./20-JARVIS-CAPABILITY-MATURITY.md) — Overall composite maturity is **`1.35 / 5.0`** (between Prototype and Early Functional), with `8` of `20` pillars at Level `0` or `1`.
- `core/jarvis/application/turn_orchestrator.py:219-410` — Single-pass execution model: either a deterministic regex fires **one** tool OR `Qwen3-4B` generates plain prose. Zero multi-step planning, zero tool-calling loop, zero observation-reflection cycle.
- `core/jarvis/application/memory_service.py` & `core/jarvis/application/preference_proposal_service.py` & `core/jarvis/domain/models.py` (`PersonaConfig`) — Memory Vault, approved preference proposals, and persona settings are stored in SQLite but **never injected into `TurnOrchestrator` LLM prompts** (`0` calls from `turn_orchestrator.py` / `router.py`).
- `core/jarvis/application/reminder_service.py` — Zero background daemon/scheduler loop; reminders, health nudges, and daily briefings never trigger autonomously; `ProactiveRateLimiter` (`L62-85`) is dead code.
- `core/jarvis/application/turn_orchestrator.py:733-813` — `execute_approved_file_move()` has **zero callers** in `app.py`; approving an R2 file move in UI updates DB state without executing the move.
- `core/jarvis/application/workflow_service.py:351-359` — Multi-step workflow execution is a hardcoded mock loop returning synthetic step success without invoking real tools.
- `apps/desktop/src/App.tsx:727-755` & `ProductivityPanels.tsx` — Multiple flagship tabs (Knowledge, Tasks, Calendar/Reminders, Automation/Workflows, Extensions) rely on mock Zustand fixtures or unbacked stubs.
- `core/jarvis/application/ecosystem_service.py:228-381` — Extension SDK is a SQLite metadata table only; zero plugin runtime or MCP extensibility.

#### 2. Current Behavior
In live use, J.A.R.V.I.S. behaves as a fragile single-turn voice-to-local-LLM wrapper paired with a visually styled dashboard whose backend intelligence loops are disconnected. It forgets user preferences across turns, cannot chain multi-step actions (e.g., *"cari laporan Q4 terbaru, ringkas poin risikonya, lalu buka file-nya"*), cannot act proactively on reminders or system anomalies, cannot execute approved workflows or file operations end-to-end, and cannot integrate external tools via MCP.

#### 3. Expected Behavior
A cohesive, local-first Personal Intelligence OS that:
1. Converses fluidly in Indonesian and English (voice + text) with reliable barge-in, accurate intent/entity resolution, and natural speech synthesis.
2. Grounds answers in live system awareness (installed apps, authorized files/documents, active workspace context, persistent personal memory, and explicit user preferences).
3. Plans and executes multi-step read/analyze/act workflows seamlessly under the 3-tier authorization boundary (zero friction for safe read/launch operations; transparent diff/preview GUI approvals for state changes; unbreakable enforcement of non-destructive bans).
4. Runs lightweight background intelligence (reminders, file-index updates, hardware/resource monitors) without degrading desktop responsiveness, and extends cleanly to external tools via hardened MCP servers.

#### 4. Probable Root Cause
**Confirmed architectural fragmentation ("Vertical-Slice Disconnect"):**
Substantial domain scaffolding was built horizontally across 35 SQLite tables, 96 HTTP routes, and 12 UI tabs to satisfy specification checklists, but the **end-to-end vertical execution loops** (Audio Device -> LiveVoice -> Router/Tool-Calling LLM -> Memory/File/App Context -> Policy/Approval -> Real Executor -> SSE Event Bus -> Real UI State) were never unified or validated under live non-mocked workflows.

#### 5. Verification Status
- **`PARTIAL`** (Core local LLM runtime, SQLite persistence, and desktop shell exist, but the integrated JARVIS intelligence experience is severely degraded by disconnected subsystems, mocked UI panels, and absent agentic/proactive/awareness engines).

#### 6. Proposed Improvements
Prioritized transformation sequence (detailed in [22-RECOMMENDED-ENHANCEMENT-PLAN.md](./22-RECOMMENDED-ENHANCEMENT-PLAN.md) and [33-CAPABILITY-ENHANCEMENT-OPPORTUNITIES.md](./33-CAPABILITY-ENHANCEMENT-OPPORTUNITIES.md)):
1. **Phase 1 (Core Reliability & Trust):** Fix voice DSP/VAD/STT/TTS pipeline, fix authorization bypasses & 3-tier policy enforcement, fix `allow_live_launch` + Windows App Discovery, wire orphaned R2 execution.
2. **Phase 2 (Local Awareness & Memory):** Build 4-layer Filesystem/Knowledge Intelligence + wire Memory Vault & Persona Config into LLM context + replace all mock UI panels with live SSE-synchronized APIs.
3. **Phase 3 (Agentic Reasoning & Extensibility):** Introduce bounded multi-step tool-calling planner (with strict policy mediation per tool call), real Workflow execution, proactive background scheduler, and hardened MCP Host/Client.
4. **Phase 4 (Evaluation & Controlled Personalization):** Stand up bilingual evaluation harness ([32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)) and opt-in local alias/pronunciation/preference learning ([31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md](./31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md)).

#### 7. Security Implications
- Adding multi-step planning, memory injection, file awareness, and MCP extensibility significantly enlarges the attack surface (indirect prompt injection via files/web/MCP tool outputs, memory poisoning, confused-deputy tool chaining).
- Therefore, **Phase 1 policy enforcement (trusted Python policy engine + Tier-3 hard bans + scoped GUI R2 approval + untrusted-content tainting)** is a mandatory prerequisite before enabling multi-step agentic execution or MCP tools.

#### 8. Acceptance Criteria
- End-to-end multi-step scenario (*"Cari file PDF budget terbaru di folder Documents, ringkas 3 angka utamanya, lalu buka filenya"*) succeeds reliably via voice with zero mock fallbacks and zero unnecessary confirmation prompts.
- User preferences and Memory Vault facts persist across restarts and measurably govern responses.
- All 12 desktop UI tabs reflect live Core state via SSE (`Event Cursor` increments on every turn; zero Zustand mock fixtures remain).
- Independent re-audit elevates composite JARVIS capability maturity from `1.35 / 5.0` to `>= 3.8 / 5.0` with `0` open `CRITICAL` security bypasses.
