# 33 — Capability Enhancement Opportunities (Substantial Architectural Blueprint)

> **Document Scope:** High-leverage architectural and intelligence opportunities synthesized from the complete as-built audit (`00`–`32`), designed to guide an independent external reviewer and engineering team in transforming J.A.R.V.I.S. (`v0.2.1`, current maturity `1.35 / 5.0`) into a coherent, trustworthy, local-first **Personal Intelligence OS**—rather than applying superficial band-aid patches.
>
> Every opportunity includes all 8 mandatory Addendum §G fields (`Source Evidence`, `Current Behavior`, `Expected Behavior`, `Probable Root Cause`, `Verification Status`, `Proposed Improvements`, `Security Implications`, and `Acceptance Criteria`).

---

## 1. Strategic Opportunity Matrix (Priority & Architectural Leverage)

| Opportunity ID | Title | Target Maturity Jump | Complexity | Recommended Phase | Primary Value Unlocked |
| :---: | --- | :---: | :---: | :---: | --- |
| **CEO-01** | **Unified Real-Time Full-Duplex Voice Pipeline (WASAPI + DSP/AEC + Streaming)** | Voice `1 -> 4` | High | Phase 1 | Eliminates ORI-01/ORI-02; unlocks natural bilingual voice interaction with barge-in and `< 2s` TTFAR |
| **CEO-02** | **Authoritative 3-Tier Policy Gateway & Zero-Bypass Security Kernel** | Security `2 -> 4.5` | High | Phase 1 | Eliminates all 7 bypasses (`BP-01`–`BP-07`), enforces Tier-3 bans unbreakably, enables frictionless Tier-1 actions |
| **CEO-03** | **Native Windows App Catalog & Safe Desktop Control Suite** | Automation `1 -> 4` | Medium | Phase 1 | Eliminates ORI-03; real discovery & launching of Win32/MSIX apps + volume/media/window/document actions |
| **CEO-04** | **4-Layer Local Filesystem & Hybrid Knowledge Intelligence Engine** | Knowledge `1 -> 4` | High | Phase 2 | Eliminates ORI-04; `< 50ms` metadata/fuzzy/recent search + real FTS5 + selective local ONNX semantic RAG |
| **CEO-05** | **Bounded Multi-Step Tool-Calling Planner & Grounded Context Engine** | Intelligence `1 -> 4` | High | Phase 2 | Replaces brittle regex-or-prose loop with schema-constrained tool calling + live Memory Vault & Entity Working Set |
| **CEO-06** | **Live SSE-Synchronized Desktop Shell (Eliminating Mock Panels & rAF Storm)** | UI/UX `2 -> 4` | Medium | Phase 2 | Removes 100% mock Zustand panels, fixes `seq #0` sync gap and SVG 60fps React re-render storm |
| **CEO-07** | **Proactive Autonomous Background Scheduler & Event-Driven Assistant** | Proactive `0 -> 3.5` | Medium | Phase 3 | Brings reminders, daily briefings, file-change/hardware monitors, and preference proposals to life safely |
| **CEO-08** | **Hardened Opt-In MCP Host & Server Manager** | Extensibility `0 -> 4` | High | Phase 3 | Extends JARVIS safely to Calendar, Email, GitHub, Notion, Home Assistant via isolated, hash-pinned MCP servers |
| **CEO-09** | **Encrypted Persistence, Atomic Recovery & Clean-Machine Packaging** | Ops/Data `1.5 -> 4` | Medium | Phase 1–2 | Fixes plaintext SQLite, backup DEK loss, NSIS clean-machine failure, and hidden GPL-3.0 FFmpeg (`av`) license risk |
| **CEO-10** | **Continuous Local Bilingual Eval Harness & Opt-In Personalization Loop** | AI Quality `0 -> 4` | Medium | Phase 2–4 | Institutionalizes data-driven quality (13 metrics, held-out test set), instant alias/pronunciation learning, and evidence-gated LoRA |

---

## 2. Detailed Architectural Opportunity Specifications

### CEO-01: Unified Full-Duplex Bilingual Voice Architecture
- **Source Evidence:** `core/jarvis/infrastructure/live_voice_engine.py:70-84, 299-307, 450-499, 593, 640, 667-851, 930-944`; `core/jarvis/application/voice_service.py:123-155`; `core/jarvis/domain/voice.py:60-114`; `core/jarvis/platform/windows/audio.py:34-93`.
- **Current Behavior:** Two disconnected voice stacks; raw WinMM OS-default mic/speaker capture; zero DSP/AEC; VAD 33-frame noise-inflation bug; hardcoded `language="id"` CPU Whisper discarding confidence scores; blocking `_capture_loop`; monolingual unnormalized Piper TTS.
- **Expected Behavior:** Single unified 4-thread asynchronous pipeline (`WASAPI Capture + Resampler` -> `HPF + NS + WebRTC AEC + Corrected Silero VAD + openWakeWord` -> `Hardware-Adaptive Bilingual Whisper + Hotwords + Confidence Gate` -> `Streaming LLM -> Indonesian/English TextNormalizer -> Sentence-Chunked Piper/Kokoro TTS -> Dedicated Playback`), fully honoring UI device selection, `speech_rate`, headset/AEC barge-in, and continuous multi-turn sessions.
- **Probable Root Cause:** Confirmed rapid bolt-on of `live_voice_engine.py` outside the existing `VoicePipelineService` / `EndpointAwareEchoGuard` architecture.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Unify `LiveVoiceEngine` under `VoicePipelineService`, replace WinMM with WASAPI, integrate C/ONNX front-end DSP + AEC, add dynamic app/alias `hotwords`, implement Indonesian+English TTS normalizer & `pronunciation_lexicon`, and stream sentence chunks over a dedicated cancellable playback worker.
- **Security Implications:** Eliminates acoustic self-trigger loops and noise-hallucinated tool triggers; exposes explicit mic-active & device identity state to the owner.
- **Acceptance Criteria:** Zero VAD triggers on 100 ambient noise impulses; `<= 2.0s` LLM TTFAR on GPU; `<= 600ms` deterministic command TTFAR; live device switch succeeds in `<= 500ms`; clean barge-in interruption in `<= 300ms`.

---

### CEO-02: Authoritative 3-Tier Policy Gateway & Cryptographic GUI Approval Kernel
- **Source Evidence:** `core/jarvis/domain/policy.py:274-331`; `core/jarvis/application/approval_service.py:181-185`; `core/jarvis/application/storage_service.py:158-218, 308, 346-378`; `core/jarvis/application/backup_service.py:101, 165-226`; `core/jarvis/application/workflow_service.py:291`; `core/jarvis/transport/app.py:748, 1162, 1290-1315`; `core/jarvis/domain/models.py:412`.
- **Current Behavior:** Over-blocks safe Tier-1 actions while allowing 7 critical/high bypasses (`BP-01`–`BP-07`), including 2-step permanent user-file deletion via cache repointing, unconfined backup file overwrite, workflow `bound_hash` self-echo, spoofable `TRUSTED_UI` JSON fields, hardcoded `is_os_locked=False`, ignored `grant.scope`, and orphaned `execute_approved_file_move()`.
- **Expected Behavior:** Every internal tool, HTTP route, workflow step, and future MCP call traverses one mandatory `AuthorizedActionGateway` enforcing: (1) frictionless **Tier 1** within canonical `realpath` scopes; (2) cryptographically bound, lock-screen-verified, single-use **Tier 2** GUI approvals with diff/preview (never approvable by voice alone); (3) non-overridable **Tier 3** hard bans (zero user file/DB deletion, zero Recycle Bin move, zero formatting, zero arbitrary shell/LOLBins, zero indirect overwrite destruction); and (4) live `BR-15` untrusted-origin taint propagation.
- **Probable Root Cause:** Confirmed fragmented authorization checks confined to `TurnOrchestrator` instead of service-layer enforcement, plus incomplete R2 approval plumbing.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Implement `AuthorizedActionGateway`, `SafePathBoundary`, sentinel-verified isolated cache maintenance, live Windows `WTSQuerySessionInformation` lock check, Tauri-signed GUI confirmation IPC channel, and complete wiring of `execute_approved_file_move()` with `target_snapshot_hash` verification.
- **Security Implications:** Foundational trust boundary enabling all higher-level autonomy (files, apps, workflows, MCP) without risking user data loss.
- **Acceptance Criteria:** `0.00%` unauthorized execution across all 7 bypass regression suites (`BP-01`–`BP-07`), LOLBin vectors, symlink escapes, and voice-only approval spoofing; `<= 1.5%` false refusal rate on authorized Tier-1 operations.

---

### CEO-03: Native Windows Application Catalog & Real Desktop Controls
- **Source Evidence:** `core/jarvis/platform/windows/desktop_automation.py:13-45`; `core/jarvis/transport/app.py:620`; `core/jarvis/domain/router.py:37, 80-87`; `apps/desktop/src/components/OnboardingWizard.tsx:99-104`.
- **Current Behavior:** Only 3 System32 apps (`calc`, `notepad`, `paint`) are known, `allow_live_launch=False` silently fakes launches in production, and no real volume/media/window-focus/document-open controls exist in the native tool suite.
- **Expected Behavior:** Non-elevated `WindowsAppDiscoveryService` merging Start Menu `.lnk` (validated targets/args), Registry `App Paths`/`Uninstall`, and `shell:AppsFolder` MSIX AUMIDs; Tier-1 auto-launch for trusted GUI apps with fuzzy + alias matching; native Core Audio (`pycaw`) volume/mute & WinRT media transport controls (`play`/`pause`/`next`/`previous`); safe allowlisted `fs.file.open`.
- **Probable Root Cause:** Confirmed placeholder System32 stub and missing Windows platform adapters.
- **Verification Status:** `BROKEN` / `NOT IMPLEMENTED`.
- **Proposed Improvements:** Build `WindowsAppDiscoveryService`, `AppTrustClassifier` (with strict Tier-3 LOLBin/elevation ban), `AppEntityResolver`, real `CreateProcessW`/`IApplicationActivationManager` launcher, and native WASAPI volume + media controller.
- **Security Implications:** Eliminates arbitrary binary execution via strict catalog resolution, `.lnk` argument sanitization, and immutable LOLBin/UAC-elevation bans.
- **Acceptance Criteria:** Cold discovery indexes standard Win32 + MSIX apps in `< 1.5s`; `"Buka Chrome"`, `"Buka VS Code"`, `"Kecilkan volume ke 30%"`, and `"Pause musik"` execute truthfully on Windows under Tier 1 with `0` confirmation prompts and `0` bypasses on shells/LOLBins.

---

### CEO-04: 4-Layer Local Filesystem & Hybrid Knowledge Intelligence
- **Source Evidence:** `core/jarvis/platform/windows/filesystem.py:169-191`; `core/jarvis/application/knowledge_service.py:72-79, 184-415`; `core/jarvis/infrastructure/document_parser.py:15, 184-189`; `apps/desktop/src/components/ProductivityPanels.tsx:30-38`.
- **Current Behavior:** Drive enumeration is isolated to a storage route; `KnowledgePanel` UI is mocked; `sync_source_root` re-parses full PDFs ignoring SHA-256/`mtime` fast-skip; `embedding_provider=None` everywhere; zero file watchers, filename/fuzzy search, date/ext filters, recent files, or file aliases exist.
- **Expected Behavior:** Strict 4-layer architecture: (1) SQLite metadata + FTS5 trigram index monitored by non-admin `ReadDirectoryChangesW` (plus optional post-filtered Windows Search / Everything adapters); (2) incremental FTS5 body index (`mtime+size` fast-skip + expanded parsers for `.xlsx`/`.pptx`/`.csv`/code); (3) selective local ONNX multilingual embeddings + `sqlite-vec` `vec0` + RRF hybrid ranking strictly on curated Knowledge Roots; (4) personal file/folder aliases + conversation `EntityWorkingSet`.
- **Probable Root Cause:** Confirmed scope limitation of v0.2.1 RAG prototype and unwired frontend UI.
- **Verification Status:** `NOT IMPLEMENTED` / `PARTIAL` / `MOCK`.
- **Proposed Improvements:** Implement `FileIndexWorker` (background I/O priority, voice-turn pause, `volume_serial` offline tracking), `SafePathBoundary` (secret/reparse exclusions), local ONNX `EmbeddingProviderAdapter`, and wire `KnowledgePanel` to live APIs.
- **Security Implications:** Strict canonical containment and hard exclusions (`.ssh`, `.env`, browser credentials, `jarvis_core.db`, untrusted USB defaults) prevent sensitive secret leakage into indexes or LLM context.
- **Acceptance Criteria:** `< 50ms` p95 fuzzy + date + extension search across `100k` files; hybrid semantic query retrieves conceptual Indonesian/English matches absent exact keywords; `0` excluded or symlink-escaped files indexed.

---

### CEO-05: Bounded Multi-Step Tool-Calling Planner & Grounded Context Engine
- **Source Evidence:** `core/jarvis/application/turn_orchestrator.py:113-410`; `core/jarvis/domain/router.py:27-410`; `core/jarvis/application/memory_service.py`; `core/jarvis/application/workflow_service.py:351-359`.
- **Current Behavior:** Binary single-turn regex-or-prose execution; zero multi-step reasoning; Memory Vault, Preferences, and Persona never enter LLM prompts; `WorkflowService` mocks step execution; garbled turns pollute `_session_history`.
- **Expected Behavior:** Hybrid two-tier intelligence engine: (a) `< 50ms` deterministic fast-path for high-confidence everyday commands; (b) bounded multi-step tool-calling loop (max `5` tool hops, wall-clock budget `<= 15s`, JSON/GBNF grammar-constrained tool schemas) powered by a `ContextAssembler` injecting live local clock, Persona, relevant Memory Vault facts, and `EntityWorkingSet`. Real `WorkflowService` executor running policy-checked steps rather than mock loops.
- **Probable Root Cause:** Confirmed absence of agentic tool-calling orchestration and missing context wiring.
- **Verification Status:** `PARTIAL` / `MOCK`.
- **Proposed Improvements:** Replace ad-hoc regex fallthrough with structured `llama.cpp` JSON-schema tool calling, wire `ContextAssembler` + `EntityWorkingSet`, filter error turns out of history, and replace `workflow_service.py:351-359` mock loop with real `AuthorizedActionGateway` step dispatch.
- **Security Implications:** Every tool call emitted by the planner is untrusted until validated against strict JSON Schema and `AuthorizedActionGateway`; loop budgets prevent runaway resource exhaustion; `untrusted_origin` taints the remaining hops of any turn that reads external/document content.
- **Acceptance Criteria:** Compound 3-step scenario (*"cari PDF terbaru -> ringkas -> buka"*) completes deterministically end-to-end; Memory Vault & Persona govern answers across restarts; `0` unconstrained infinite tool loops.

---

### CEO-06: Live SSE-Synchronized Desktop Shell & Rendering Performance Hygiene
- **Source Evidence:** `apps/desktop/src/App.tsx:727-755`; `apps/desktop/src/components/ProductivityPanels.tsx:30-38`; `apps/desktop/src/components/OrbitalCore.tsx` (60fps React state updates in `requestAnimationFrame`); `screenshots/actual-voice-command-center-defect-01.png` (`Event Cursor: seq #0` after live voice turn).
- **Current Behavior:** Several desktop panels display hardcoded Zustand mocks; voice turns bypass the SQLite SSE event cursor (`seq #0`); the ambient orb animation drives 60fps React re-renders; `OnboardingWizard` 1-Click setup omits essential Tier-1 desktop wiring.
- **Expected Behavior:** All 12 desktop tabs reflect real Core API + SSE state (`Event Cursor` monotonically increments on voice, tool, file, and approval events); orb/audio visualizer renders purely on imperative `<canvas>` / CSS transform layers with `0` React state mutations per frame and respects `prefers-reduced-motion`; GUI approval `<dialog>` cleanly surfaces voice-initiated Tier-2 proposals with diff/preview and countdown.
- **Probable Root Cause:** Confirmed incomplete frontend-to-backend integration and animation state anti-pattern.
- **Verification Status:** `PARTIAL` / `MOCK` / `BROKEN`.
- **Proposed Improvements:** Remove all Zustand mock fixtures, route `LiveVoiceEngine` turn & approval events through Core's persistent Event Bus -> SSE stream, refactor `OrbitalCore` off React state (`useRef` + `<canvas>`), and add Audio Device Picker + Mic Meter + App Alias Manager to Settings.
- **Security Implications:** Ensures users see truthful live permission, mic-active, and approval state rather than stale or synthetic UI widgets.
- **Acceptance Criteria:** `0` mock data fixtures in production desktop bundle; `Event Cursor` increments on every live voice turn; React Profiler confirms `0` component re-renders/sec during idle orb animation; Lighthouse/WCAG contrast & keyboard focus checks pass on approval `<dialog>`.

---

### CEO-07: Proactive Autonomous Background Scheduler
- **Source Evidence:** `core/jarvis/application/reminder_service.py:62-85, 182-281` (zero background worker/timer loop; `ProactiveRateLimiter` dead code); `core/jarvis/application/preference_proposal_service.py` (manual API trigger only).
- **Current Behavior:** Reminders never fire when due, daily briefings never trigger automatically, system-resource alerts never notify, and preference proposals never generate autonomously.
- **Expected Behavior:** Lightweight asyncio `ProactiveScheduler` inside Core with persistent due-time polling, quiet-hours awareness, dead-code `RateLimiter` activated (preventing notification spam), hardware-health watchdogs (disk low / GPU thermal / runaway process alerts), and non-intrusive desktop toast + optional voice announcement.
- **Probable Root Cause:** Confirmed missing background scheduler loop in FastAPI lifespan (`app.py`).
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Wire `ProactiveScheduler` into Core lifespan with graceful shutdown, quiet-hours & DND respect, rate-limited notification queue, and explicit read-only posture (proactive triggers may notify or prepare drafts/proposals, never execute Tier-2 mutations silently).
- **Security Implications:** Proactive autonomy MUST remain strictly Tier-1 / read-only unless explicitly confirmed via Tier-2 GUI approval, preventing surprise background changes.
- **Acceptance Criteria:** A reminder scheduled for `+60s` fires within `<= 2s` of due time and persists across Core restart; notification flood bursts are capped deterministically by `RateLimiter`.

---

### CEO-08: Hardened Opt-In MCP Host & Server Manager
- **Source Evidence:** `core/jarvis/application/ecosystem_service.py:228-381`; `0001_initial_core.sql:355-363`.
- **Current Behavior:** Dead SQLite metadata stub with zero plugin execution or MCP support.
- **Expected Behavior:** Standards-compliant MCP Host/Client with Job Object process isolation, stripped env, DPAPI per-server credentials, SHA-256 artifact + tool-schema rug-pull pinning, `mcp.<server>.<tool>` namespacing, Tier-2 default approval, Tier-3 hard bans, `BR-15` output tainting, and Desktop MCP Manager UI with instant Kill Switch (full architecture in [30-MCP-ARCHITECTURE-ASSESSMENT.md](./30-MCP-ARCHITECTURE-ASSESSMENT.md)).
- **Probable Root Cause:** Confirmed unimplemented extensibility layer.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement after CEO-02 (Policy Gateway) is verified; ship 2–3 audited read-first reference integrations before enabling custom owner-approved servers.
- **Security Implications:** Strict process, network, credential, and taint isolation are mandatory to prevent MCP servers from becoming Tier-3 bypass vectors.
- **Acceptance Criteria:** Native tools operate independently with `0` MCP servers; tool-schema tampering triggers `100%` automatic quarantine; Core exit leaves `0` orphaned MCP processes.

---

### CEO-09: Persistence Encryption, Atomic Backup/Restore & Clean-Machine Distribution
- **Source Evidence:** `core/jarvis/infrastructure/dual_db.py` (plaintext SQLite, zero SQLCipher); `core/jarvis/application/backup_service.py:101, 165-226` (lost DEK on restore + unconfined path overwrite); `apps/desktop/src-tauri/tauri.conf.json` & NSIS installer (missing bundled Python runtime/wheels on clean machines); `core/pyproject.toml` / lockfiles (`faster-whisper` pulls `av` bundling **GPL-3.0 FFmpeg** binaries).
- **Current Behavior:** Databases are plaintext on disk; restoring a backup on a new machine cannot decrypt DPAPI-wrapped secrets; NSIS installer fails on machines lacking pre-installed Python/CUDA environments; redistributing `av` (PyAV/FFmpeg GPL) creates a copyleft license compliance defect.
- **Expected Behavior:** Encrypted SQLite at rest (SQLCipher with Windows DPAPI-protected master key + passphrase-wrapped portable backup KEK); atomic quiesced restore with tombstone replay; self-contained standalone installer bundling embedded Python + pinned wheels (or pre-flight model/runtime bootstrapper) tested on a clean Windows VM; replace/decouple `av` (PyAV) with MIT/BSD/Apache audio decoding (`soundfile` + `scipy` / `soxr` / Media Foundation, since `LiveVoiceEngine` already passes NumPy `float32` PCM arrays directly to `faster-whisper`!).
- **Probable Root Cause:** Confirmed shortcuts in security-at-rest, packaging pipeline, and transitive dependency license review.
- **Verification Status:** `BROKEN` / `PARTIAL`.
- **Proposed Improvements:** Remediate GPL-3.0 `av` dependency (verify `faster-whisper` clean PCM path without shipping GPL FFmpeg binaries or isolate cleanly per legal review), enable SQLCipher + portable backup passphrase KEK, and add clean-VM NSIS smoke test to CI.
- **Security Implications:** Protects personal memory, transcripts, and audit logs against offline disk theft and closes legal/supply-chain exposure.
- **Acceptance Criteria:** `strings jarvis_core.db` reveals `0` plaintext memory/transcript tokens; backup created on Machine A restores cleanly on Machine B with passphrase and `0` resurrected tombstones; clean Windows sandbox VM installs and launches without pre-installed Python; SBOM reports `0` unapproved copyleft binaries.

---

### CEO-10: Continuous Bilingual Evaluation Harness & Opt-In Personalization Loop
- **Source Evidence:** `tests/unit/test_voice_wake_and_llm_conversation.py` (mocked voice unit tests only); `0001_initial_core.sql` (`model_benchmark` unused).
- **Current Behavior:** Changes to voice, prompts, or models are evaluated purely anecdotally without quantitative WER, intent accuracy, refusal rate, latency, or unauthorized-execution gates.
- **Expected Behavior:** Versioned local `jarvis_bench_v1` evaluation harness (`train`/`val`/`held_out_test` across all 8 categories and 13 metrics in [32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)) paired with opt-in local alias/pronunciation/feedback capture and versioned artifact rollback ([31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md](./31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md)).
- **Probable Root Cause:** Confirmed missing evaluation infrastructure and feedback schema.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement offline eval harness before Phase 2/3 AI tuning; enforce automated regression gate (`0.00%` unauthorized execution, WER/intent/refusal thresholds) before promoting any prompt, model tier, or future LoRA adapter.
- **Security Implications:** Prevents silent regression of Tier-3 bans or prompt-injection defenses across model or prompt updates; keeps all owner feedback strictly local, PII-scrubbed, and opt-in.
- **Acceptance Criteria:** Single command generates reproducible 13-metric JSON scorecard on `held_out_test`; any regression in unauthorized execution (`> 0%`) fails the gate deterministically.
