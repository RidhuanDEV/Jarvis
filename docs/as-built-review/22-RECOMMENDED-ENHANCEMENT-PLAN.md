# 22 — Recommended Enhancement Plan (Substantial Architectural Roadmap)

This plan moves beyond superficial bug patches to address the **fundamental architectural, security, voice, intelligence, and packaging changes** needed to achieve a genuine, trustworthy, hardware-adaptive **J.A.R.V.I.S. Personal Intelligence System**.

---

## Priority Classification
- **`P0` (Phase A — Security, Stability & Clean-Machine Blockers):** Must complete before any external user release or further feature expansion.
- **`P1` (Phase B — Core JARVIS Voice, App/File Intelligence & Memory Coherence):** Required to deliver the intended Tony Stark desktop intelligence experience.
- **`P2` (Phase C — Extensibility via MCP, Proactive Autonomy & Cinematic Polish):** Major capability elevation.
- **`P3` (Phase D — Evaluation-Gated Personalization & Optional Model Adaptation):** Data-driven refinement after non-parametric baseline plateaus.

---

## Detailed Enhancement Specifications (`ENH-01` – `ENH-14`)

### `ENH-01` — Close All Direct-Route Policy Bypasses, SSRF TOCTOU, Backup DEK Loss & Integrity Gaps
- **Priority:** `P0` | **Complexity:** High | **Dependencies:** None
- **Current Implementation & Root Cause:** Direct routes (`storage/migrate`, `storage/cleanup`, `screen/analyze`, `web/*`, `knowledge/query`, `workflows/execute`) bypass `PolicyEngine`/`ApprovalService`; `web_fetch.py` drops `pinned_ip`; `backup_service.py` omits `master_dek`; `local_runtime_manager.py` & `live_voice_engine.py` skip SHA-256; `logging_setup.py` runs `format_exc_info` after redaction; Rust `commands.rs` interpolates unencoded IDs.
- **Recommended Improvement:**
  1. Route every mutating/sensitive HTTP endpoint through `PolicyEngine` + single-use consumed `ApprovalService` challenges; block `storage/locations/cache` from pointing at non-empty/user/root folders; wire `execute_approved_file_move` atomically with `bound_hash` + Win32 handle pinning.
  2. Enforce socket-pinned IP connection in `SafeWebFetchClient` + streamed byte cap (`<= 2 MiB`).
  3. Re-wrap `jarvis.memory.master_dek.v1` inside the Argon2id+AES-GCM backup archive; bound untrusted Argon2id header params (`m <= 256 MiB`, `t <= 10`, `p <= 8`); confine `archive_path` to `backups` root.
  4. Require manifest SHA-256 verification before launching `llama-server.exe` or loading GGUF/ONNX weights + pass ephemeral `--api-key` to `llama-server`.
  5. Fix `logging_setup.py` processor order (redact *after* `format_exc_info`), fix IPv6 `[::1]` Host parsing & chunked cap, percent-encode all Rust `commands.rs` path params, add Win32 `WM_WTSSESSION_CHANGE` OS lock listener persisting server-side lock state.
- **Alternatives:** Move local IPC to actual Windows Named Pipe with current-SID DACL (`DEC-008`), eliminating Host/Origin/port-squatting exposure altogether.
- **Acceptance Criteria:** 100% of `SEC-C01`–`SEC-C07` and `SEC-H01`–`SEC-H12` have failing-then-passing adversarial regression tests; cross-machine restore test uses `is_encrypted=1` sensitive memories and verifies decryption on a new vault DEK.
- **Regression Risks:** Existing test suites invoking direct `/v1/storage/migrate` or `/v1/screen/analyze` without grants/approvals will require updated fixtures.

### `ENH-02` — Self-Contained Portable Windows Installer & License Remediation
- **Priority:** `P0` | **Complexity:** High | **Dependencies:** `ENH-01`
- **Current Implementation & Root Cause:** NSIS bundles only `jarvis-desktop.exe` (`tauri.conf.json:32-45`); `contracts/` & `migrations/` live outside Python wheel; `faster-whisper -> av==18.1.1` pulls undisclosed GPL-3.0 `libx264`/`libx265`; SBOM omits transitive licenses; root `LICENSE`/`SECURITY.md` missing.
- **Recommended Improvement:**
  1. Package `contracts/` and `migrations/` inside `core/jarvis/` via `importlib.resources`.
  2. Bundle relocatable `python-build-standalone` (`3.11.9`) + minimal base `jarvis-core` inside Tauri `"resources"` so clean Windows 11 machines boot into Direct Mode immediately with 0 git/uv prerequisites.
  3. Replace PyAV dependency for in-RAM Whisper PCM (or isolate `[voice]`/`[tts-piper]` with explicit GPL-3.0-or-later license compliance, corresponding source offer, and user-consented in-app runtime/model downloader with SHA-256 verification); eliminate `144.65 MiB` `scipy`/`sklearn` bloat by running `openWakeWord`'s 3 ONNX files directly via `onnxruntime`.
  4. Extract real transitive licenses in `generate_release_sbom.py`, add root `LICENSE`/`SECURITY.md`/`THIRD-PARTY-NOTICES.txt`, fix OneCore license label, and add clean-VM NSIS smoke test + GitHub Release publishing in `release-windows.yml`.
- **Acceptance Criteria:** Fresh Windows 11 VM with zero developer tools installs `JARVIS_*-setup.exe`, boots Core live in `< 5s`, and passes offline Direct Mode smoke checks; SBOM contains valid SPDX licenses on 100% of components.
- **Regression Risks:** Base installer size grows from `~3 MiB` to `~45–65 MiB` (still minimal vs `>2 GB` AI bundles).

### `ENH-03` — Fix Rust Broker Lifecycle, Timeouts, Tray Residency & Real-Time SSE Event Bridge
- **Priority:** `P0` | **Complexity:** Medium | **Dependencies:** None
- **Current Implementation & Root Cause:** Global `10s` `reqwest` timeout kills `60s` LLM turns (`lib.rs:46`); Tray `stop_all` kills Python Core (`lib.rs:95`); Window `X` terminates app (`lib.rs:161`); Core `stdout/stderr` sent to `null`; zero SSE `/v1/events` bridge (`Event Cursor` stuck `seq #0`).
- **Recommended Improvement:**
  1. Split `reqwest` timeouts (`10s` fast endpoints, `70s` LLM/migration endpoints); wire `/v1/requests/{id}/cancel` for Tray `Stop Active Action` (never killing Core!).
  2. Intercept `WindowEvent::CloseRequested` to hide window to tray (only Tray `Quit` exits), add `Mute` & `Offline` tray items (`BR-22`), route Core `stdout/stderr` to rotating log file in `roots.logs`, and add Core crash watchdog with bounded restart backoff.
  3. Add Rust background SSE client subscribing to `GET /v1/events?after_seq=...` and emitting `tauri::Emitter` events to WebView (`applySequencedEvent`), eliminating 350 ms HTTP polling for state/approvals.
- **Acceptance Criteria:** 25s cold LLM turn completes without timeout; Tray `Stop` cancels active turn while keeping Core alive; Window `X` minimizes to tray; voice R2 approval immediately opens native `<dialog>` via SSE; `Event Cursor` increments monotonically.
- **Regression Risks:** SSE reconnect loop must respect graceful shutdown so app exits `< 2s` on Quit.

### `ENH-04` — Unify & Harden End-to-End Voice Pipeline (`Mic → DSP → VAD → STT → TTS → Speaker`)
- **Priority:** `P1` | **Complexity:** High | **Dependencies:** `ENH-03` (see Doc `26` for full RCA)
- **Current Implementation & Root Cause:** Disconnected `VoicePipelineService` vs `LiveVoiceEngine`; ignores user audio device selection; VAD single-click noise inflation (`live_voice_engine.py:793-821`); blocking `_capture_loop`; hardcoded `language="id"`; zero Whisper confidence filtering; Whisper trailing `.` breaking router; monolingual Indonesian `espeak` mangling English/Romaji/non-Latin; zero AEC.
- **Recommended Improvement:**
  1. Retire duplicate stack: make `VoicePipelineService` own `LiveVoiceEngine`, unify on WASAPI/PortAudio device enumeration with hotplug recovery, and pass selected `input_device_id`/`output_device_id` + `speech_rate` + `primary_language` cleanly.
  2. Decouple `_capture_loop` (producer) from async STT/LLM/TTS worker (consumer); fix VAD speech-frame counter (`voiced_frames >= min_speech_blocks`, excluding pre-roll & silence!); add high-pass filter + AGC + RNNoise/WebRTC NS + WebRTC AEC (enabling true voice barge-in!).
  3. Strip trailing punctuation in `DeterministicRouter.normalize_utterance()`; gate Whisper segments on `no_speech_prob` / `avg_logprob` / `compression_ratio`; support auto/bilingual language mode + optional GPU `faster-whisper-large-v3-turbo` (`float16`/`int8_float16`) when VRAM allows.
  4. Add TTS text normalizer (strip non-Latin scripts when Romaji exists, expand acronyms/times/numbers, apply pronunciation dictionary) + optional bilingual EN/ID voice routing (`Kokoro-82M` / English Piper voice alongside Indonesian Piper).
- **Acceptance Criteria:** Zero noise-click false triggers over 1h ambient room test; `"Buka kalkulator."` and `"Jam berapa sekarang."` match deterministically 100%; switching mic/speaker takes effect immediately without restart; unplugging mic degrades cleanly to text mode without HTTP 500.
- **Regression Risks:** Adding WebRTC AEC requires synchronized playback reference frames (must stream Piper PCM through PortAudio callback rather than blocking `sd.play`).

### `ENH-05` — Implement Revised 3-Tier Authorization Policy + Dynamic App & File Intelligence
- **Priority:** `P1` | **Complexity:** High | **Dependencies:** `ENH-01` (see Docs `27`, `28`, `29`)
- **Current Implementation & Root Cause:** `allow_live_launch=False` + 3-app System32 list; zero installed-app discovery; zero general file metadata index, filename search, or shell-open; `grant.scope` ignored; `brokerClient.ts` silently auto-grants `screen.read` w/ duplicate rows; WinMM volume broken.
- **Recommended Improvement:**
  1. Refactor `PolicyEngine` into Owner's **3-Tier Model**: **Tier 1 (Auto-Allowed within authorized scopes)** for read-only discovery/search/open, ordinary non-elevated app launch, system stats, WASAPI master volume & media playback; **Tier 2 (Explicit GUI Approval)** for all file create/modify/rename/move/config/outbound actions; **Tier 3 (Strictly Prohibited)** blocking all user-file deletion, Recycle Bin deletion, formatting, shell execution, credential theft, and indirect destruction.
  2. Implement **Windows Application Discovery** (Registry `Uninstall` + `App Paths` + Start Menu `.lnk` target resolution + `Get-AppxPackage`/Shell AppsFolder AUMID) with strict LOLBin/shell/installer denylist (`cmd`, `powershell`, `pwsh`, `mshta`, `wscript`, `regedit`, `rundll32`, etc.) + fuzzy alias matching + user aliases.
  3. Implement **4-Layer File System Intelligence**: (a) Dynamic Drive & Authorized Root Discovery; (b) Lightweight SQLite **File Metadata Index** (path, name, ext, size, mtime, trigram/fuzzy filename search + `ReadDirectoryChangesW` watcher); (c) FTS5 full-text index (4+ text/office formats); (d) Semantic Vector RAG (local ONNX embeddings + `sqlite-vec` `vec0`), plus safe `ShellExecuteW` file open.
  4. Replace WinMM volume with Windows WASAPI `IAudioEndpointVolume` + enable live launching.
- **Acceptance Criteria:** `"Buka Chrome"`, `"Buka VS Code"`, `"Cari file proposal pdf"`, and `"Buka folder Downloads"` succeed within `< 300 ms` without repetitive prompts; `"Buka PowerShell"` and `"Hapus file X"` are deterministically blocked (`403 DENIED`) at `PolicyEngine`; modifying/moving any file always requires scoped GUI `<dialog>` preview.
- **Regression Risks:** Dynamic `.lnk` launching must resolve shortcut targets & arguments against the LOLBin denylist to prevent shell bypass via crafted shortcuts.

### `ENH-06` — Wire Cohesive Intelligence: Memory Recall, ReAct Loop, Real UIA/OCR Screen & Background Scheduler
- **Priority:** `P1` | **Complexity:** High | **Dependencies:** `ENH-03`, `ENH-05`
- **Current Implementation & Root Cause:** `MemoryVaultService` never queried by LLM; `PersonaConfig` unused; single-shot 0-ReAct planner; `screen_capture` reads title only; zero background scheduler; `FakeNotificationAdapter`; `execute_workflow` stub; Private LAN crashes `/v1/providers`; profile rev-1 bug; zero idle VRAM unload.
- **Recommended Improvement:**
  1. Inject top-K relevant `MemoryVaultService` facts (via FTS5 index, excluding `sensitive` unless explicitly requested) + active `PersonaConfig` (`style`/`verbosity`) into `TurnOrchestratorService` prompt; persist opt-in multi-turn sessions in `session`/`message` tables; isolate untrusted RAG/screen observations so they cannot trigger second-order prompt injection.
  2. Add bounded ReAct loop (`<= 3` observation steps) + `<= 2` schema-repair retries + per-tool Pydantic/JSON Schema arg validation.
  3. Upgrade `WindowsActiveWindowCaptureAdapter` to real Windows UIA accessibility tree + local WinRT OCR + `IsPassword` + `TokenElevation` checks + title redaction.
  4. Add lifespan asyncio scheduler ticking `ReminderSchedulerService` (with real Windows Toast notifications via `winotify`/`winrt`) and `WorkflowEngineService` (wired to real `TurnOrchestrator` executors + `ProactiveRateLimiter`).
  5. Fix AI lifecycle: hydrate/bind dynamic providers (`OllamaAdapter`, `LlamaCppServerAdapter`), fix `balanced` rev activation, fix LAN `capabilities_json` schema crash, wire `DynamicResourceGovernor` + `idle_unload_seconds` VRAM release + post-crash watchdog, fix AMD/Intel VRAM discovery via DXGI/WMI, and offload sync I/O/Argon2/integrity checks via `asyncio.to_thread()`.
- **Acceptance Criteria:** Stored memory *"saya suka kopi hitam"* influences subsequent LLM replies across restarts; due reminder pops a real Windows Toast notification automatically; idle VRAM drops after `idle_unload_seconds`; `GET /v1/providers` returns 200 after registering a LAN provider.

### `ENH-07` — Complete Frontend Persistence Hydration, Canvas 2D Motion & Cinematic HUD Consolidation
- **Priority:** `P1` | **Complexity:** Medium | **Dependencies:** `ENH-03`, `ENH-06`
- **Current Implementation & Root Cause:** Zero user-data hydration on startup; 5s boot cliff; broken `delete_memory` (`404`) & `record_expense` (`'general'`); `KnowledgePanel`/`WorkflowsPanel`/`RuntimeVisualPanel`/`Storage` quotas mocked; DOM `<svg>` `setState` in `rAF` + full-store `App` subscription causing ~9 full re-renders/s; no Model/Runtime/Settings/Grants UI; no Compact Floating HUD.
- **Recommended Improvement:**
  1. Hydrate all persisted entities (`config`, `memories`, `reminders`, `tasks`, `expenses`, `roots`, `workflows`, `ha`, `devices`, `proposals`, `profiles`) on live Core connect with automatic reconnect backoff; delete hardcoded fake store seeds.
  2. Wire every panel (`Knowledge`, `Workflows`, `Storage`, `Runtime/Model Manager`, `Settings`, `Permissions/Grants`, `Backups`) to real Tauri IPC with proper `.catch()` error banners (`role="alert"`).
  3. Refactor `OrbitalCore` to pure DPR-capped HTML5 Canvas 2D (0 React `setState` in `rAF`), split `App` into narrow Zustand selectors, wire `onBattery` throttling, add live streaming multi-turn transcript, add Compact Floating Overlay window + global hotkey, and fix WCAG 2.2 AA violations (`OnboardingWizard` buttons, `color-scheme: dark`).

### `ENH-08` — Hardened Model Context Protocol (MCP) Host & Client Architecture
- **Priority:** `P2` | **Complexity:** High | **Dependencies:** `ENH-01`, `ENH-05` (full blueprint in Doc `30`)
- **Recommended Improvement:** Replace the dead `extension_package` stub with an opt-in **MCP Host/Client** supporting local stdio servers (supervised under Win32 Job Object with stripped env & per-server capability/tool pinning) + optional Streamable HTTP/SSE servers (gating behind `offline_mode`, anti-SSRF, TLS pinning, Tier-2 GUI approval by default, Tier-3 hard bans, and `BR-15` untrusted-output isolation), while keeping fast built-in desktop/file/app tools native.

### `ENH-09` — Opt-In Local Evaluation Harness & Non-Parametric Personalization (Before Any Weight Training)
- **Priority:** `P3` | **Complexity:** Medium | **Dependencies:** `ENH-04`, `ENH-06` (full design in Docs `31`, `32`)
- **Recommended Improvement:** Implement the 3-split bilingual ID+EN evaluation harness (`model_benchmark` table), opt-in local transcript/intent correction logging, user-managed alias & pronunciation dictionaries, and hybrid prompt/context optimization. Defer QLoRA/LoRA fine-tuning strictly until non-parametric baselines plateau with statistically verified error distributions.
