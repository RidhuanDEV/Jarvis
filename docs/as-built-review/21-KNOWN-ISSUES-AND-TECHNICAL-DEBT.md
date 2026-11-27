# 21 — Known Issues and Technical Debt Ledger

This consolidated ledger separates **Confirmed Defects** (proven directly in source code or observed runtime behavior), **Suspected Risks** (architectural hazards not yet triggered in live soak), and **Unverified Surfaces** (Tier-B metrics requiring authorized execution).

---

## 1. Confirmed Defects (`P0` Critical Blockers — 14 Items)

| ID | Category | Source Location | Confirmed Issue |
| --- | --- | --- | --- |
| **DEF-01** | Packaging | `tauri.conf.json:32-45`; `core_launcher.rs:130-192` | Released NSIS installer bundles no Python Core/venv/migrations/contracts — fails completely on clean Windows workstations. |
| **DEF-02** | Security | `app.py:1099, 1771, 1780, 1815, 1992`; `workflow_service.py:291` | Direct REST endpoints bypass `PolicyEngine`/`ApprovalService`; workflow execute allows self-echoing `bound_hash` from dry-run without consuming a single-use nonce. |
| **DEF-03** | Security | `storage_service.py:158-218, 346-378` | 2-step permanent user-file deletion bypass (zero R2 approval): point `cache` to any writable user folder via `PUT /v1/storage/locations/cache`, then call `POST /v1/storage/cleanup` (`max_bytes=0`). |
| **DEF-04** | Security | `web_fetch.py:149-182` | TOCTOU DNS-rebinding SSRF (`pinned_ip` computed then unused by `httpx`) + unbounded `response.content` RAM read before checking 2 MiB limit. |
| **DEF-05** | Security | `local_runtime_manager.py:154-196`; `live_voice_engine.py:168-212` | Zero SHA-256 verification before executing `llama-server.exe` or loading `.gguf`/Whisper/ONNX models. |
| **DEF-06** | Data Loss | `backup_service.py:76-99`; `vault.py:32-40` | Portable encrypted backup omits per-machine `jarvis.memory.master_dek.v1`, permanently bricking all `sensitive` memories on cross-machine restore (masked by `is_encrypted=0` in test). |
| **DEF-07** | Licensing | `pyproject.toml:34-40`; `license_service.py:153-161` | Hidden **GPL-3.0-or-later** FFmpeg (`libx264`/`libx265`, `73.50 MiB` `av.libs/`) bundled via `faster-whisper -> av==18.1.1` inside supposedly permissive `[voice]` extra. |
| **DEF-08** | Rust Broker | `lib.rs:45-49, 95-98, 161-165`; `process_supervisor.rs:212, 311` | Global `10s` `reqwest` timeout kills `60s` LLM turns; Tray `Stop Active Action` kills Python Core & destroys Job Object; Window `X` exits app; Core `stdout/stderr` discarded to `null`. |
| **DEF-09** | Core Actions | `app.py:620-621`; `desktop_automation.py:13-39`; `turn_orchestrator.py:733`; `workflow_service.py:351` | `os.app.launch` hardcoded `allow_live_launch=False` (no-op returning `verified=True`); `NotificationPort` uses `FakeNotificationAdapter`; `execute_approved_file_move()` is orphaned (0 callers); `execute_workflow()` is a complete no-op stub. |
| **DEF-10** | Crash Bug | `ecosystem_service.py:110-136` vs `ai_registry_service.py:283` | Registering any Private LAN provider inserts extra keys into `model_provider.capabilities_json`, permanently crashing `GET /v1/providers` with HTTP 500 `ValidationError`. |
| **DEF-11** | AI Lifecycle | `app.py:1497-1513` vs `local_runtime_manager.py:254` | Activating profile `balanced` defaults to `revision=1` (`role_bindings={}`), disconnecting `local_llama_cpp` (`revision=2`); user-registered providers are never bound to adapters (`404` on probe). |
| **DEF-12** | Voice Engine | `live_voice_engine.py:793-821, 821, 930`; `router.py:37, 99` | Silero VAD single 32 ms click inflates to 33 frames (`1.05s`) defeating `min_speech_blocks=8`; `_capture_loop` blocks synchronously during 65s LLM+TTS (queue overflow); Whisper trailing `.` breaks `DeterministicRouter` regexes. |
| **DEF-13** | Remote Sec | `remote_gateway_service.py:87, 151, 302`; `remote_gateway_app.py` | Remote Gateway is unwired dead code with 0 TLS enforcement, bare unsalted SHA-256 on 6-digit pairing code (0 Argon2id/attempt limit), and TOCTOU pairing replay race. |
| **DEF-14** | Storage | `storage_service.py:295`; `app.py:623` | `migrate_location` copies open SQLite WAL files via `shutil.copy2`, never reopens `DualSqliteManager`, and Core restart ignores migrated DB paths. |

---

## 2. Confirmed Defects (`P1` High-Impact — 18 Items)

| ID | Category | Source Location | Confirmed Issue |
| --- | --- | --- | --- |
| **DEF-15** | Intelligence | `turn_orchestrator.py:276-281` | `MemoryVaultService.list_memories()` & `PersonaConfig` (`style`/`verbosity`) are NEVER injected into LLM prompts. |
| **DEF-16** | Proactive | `app.py:808-830`; `reminder_service.py:62, 182` | Zero background scheduler loop exists; reminders never fire automatically; `ProactiveRateLimiter` is dead code. |
| **DEF-17** | Voice Split | `voice_service.py` vs `live_voice_engine.py`; `windows/audio.py:147` | Two disconnected voice stacks; `LiveVoiceEngine` ignores configured mic/speaker/language/speech_rate; OneCore `synthesize()` is 44B silent stub; zero audio disconnect recovery. |
| **DEF-18** | Desktop UI | `brokerClient.ts:119-186`; `App.tsx:595, 746, 802` | Zero user-data hydration on boot; 5s cold-boot cliff to permanent preview mode; `liveVoice.last_reply` hides text replies; `delete_memory` sends fake ID (`404`); `record_expense` corrupts category to `'general'`; `KnowledgePanel`/`WorkflowsPanel`/`RuntimeVisualPanel`/`Storage` quotas are UI mocks. |
| **DEF-19** | Desktop UI | `App.tsx:75, 161, 658`; `OrbitalCore.tsx:101` | Zero SSE `/v1/events` bridge (`Event Cursor` frozen `seq #0`, voice R2 approvals dropped); DOM `<svg>` `setState` in `rAF` + whole-store `App` subscription + 350 ms poll = ~9 full-app re-renders/s. |
| **DEF-20** | Security | `brokerClient.ts:273-278`; `commands.rs:195`; `policy.py:315` | Arming mic silently grants `screen.read` & inserts 4 duplicate UUID grant rows on every toggle (breaking single-row revocation); `grant.scope` completely ignored by `PolicyEngine`. |
| **DEF-21** | Security | `commands.rs:133, 151, 282, 321, 382, 398, 454` | Raw path interpolation in 7 Rust Tauri commands (zero percent-encoding / traversal guard). |
| **DEF-22** | Security | `app.py:854-890, 2401` | IPv6 `[::1]` Host check broken (`"["` → 403); empty Host bypass; chunked transfer bypasses 256 KiB cap; 422 validation errors not mapped to `ErrorEnvelope`. |
| **DEF-23** | Security | `logging_setup.py:13-30, 61-70` | `format_exc_info` runs AFTER redaction processor (leaking secrets in tracebacks); `^...$` regex misses `recovery_passphrase`, `bearer_token`, `pairing_code`. |
| **DEF-24** | Security | `crypto.py:129-139`; `app.py:2332` | Unbounded untrusted Argon2id header params (OOM DoS); `POST /v1/backups/create` overwrites arbitrary writable paths. |
| **DEF-25** | Security | `domain/knowledge.py:192`; `turn_orchestrator.py:473`; `screen_capture.py:40-55` | Unescaped `</untrusted_document_data>` breakout + second-order injection via `_session_history`; `screen_capture` reads title-only, hardcodes `has_focused_password_field=False`, elevated apps bypass blocklist via `AccessDenied`. |
| **DEF-26** | Security | `app.py:1314`; `lib.rs` | No Win32 OS lock/suspend listener (`WM_WTSSESSION_CHANGE`/`WM_POWERBROADCAST`); `/v1/session/lock` does not persist server-side lock flag; endpoints trust client `is_os_locked=False`. |
| **DEF-27** | Hardware | `windows/hardware.py:161-216`; `local_runtime_manager.py:67, 111` | AMD/Intel GPUs report `0 MiB` VRAM; NVIDIA vanishes without `pynvml`; `audio_endpoints=()` empty; CPU-only launches Vulkan/CUDA binary; hardcoded `"4b"`/`"qwen"` rank. |
| **DEF-28** | Knowledge | `knowledge_service.py`; `app.py:659, 1773` | 100% BM25-only (0 `EmbeddingProviderPort` impl, 0 `vec0` tables); `/v1/knowledge/query` omits LLM; `scope_json` extensions ignored; 0 file watchers. |
| **DEF-29** | Performance | `app.py:959-2366`; `dual_db.py:50, 119` | ~90 `async def` routes execute blocking sync I/O/Argon2/SHA-256/`PRAGMA integrity_check` directly on Uvicorn's event loop; single SQLite connection serializes readers. |
| **DEF-30** | Packaging | `pyproject.toml:55`; `config_service.py:31`; `dual_db.py:21`; `release-windows.yml` | Python wheel excludes `contracts/` & `migrations/`; release workflow never publishes GitHub Releases; binaries unsigned; zero auto-updater. |
| **DEF-31** | Supply Chain | `generate_release_sbom.py:148-196`; repo root | SBOM omits all transitive licenses & marks dev/optional deps `"required"`; missing root `LICENSE`, `SECURITY.md`, `THIRD-PARTY-NOTICES.txt`; Microsoft OneCore falsely labeled `BSD-3-Clause`. |
| **DEF-32** | OS Control | `desktop_automation.py:49-73` | `winmm.waveOutSetVolume` does not control Windows master system volume & fakes readback via `_software_volume_fallback`. |

---

## 3. Confirmed Medium/Low Debt (`P2`–`P3` — 10 Items)

- **DEF-33 (`P2`):** `turn_orchestrator.py:515-663` direct `args["..."]` indexing causes HTTP 500 `KeyError` on malformed LLM JSON.
- **DEF-34 (`P2`):** `turn_orchestrator.py:294-326` + `router.py:438` streaming/JSON conflict + code-block `{}` false rejection + zero schema-repair loop (`FR-COR-03`).
- **DEF-35 (`P2`):** `local_runtime_manager.py` zero idle VRAM unload (`idle_unload_seconds=300` dead) + zero post-boot crash watchdog + `llama-server` lacks `--api-key`.
- **DEF-36 (`P2`):** `migrations.py:102` `executescript()` implicit COMMIT makes SQL migrations non-atomic; plaintext pre-migration backup.
- **DEF-37 (`P2`):** `live_voice_engine.py:684` unjoined `_worker_thread` race + `speak_async` collision + `L785` 580 ms post-wake greeting collision.
- **DEF-38 (`P2`):** `apps/desktop/src/components/OnboardingWizard.tsx:114` ARIA `progressbar` button nesting + 8 px targets; missing `color-scheme: dark`; raw hardcoded hexes; missing `role="alert"`.
- **DEF-39 (`P2`):** Heavy/bloated `.venv` (`579.63 MiB`): `scipy`+`sklearn` (`144.65 MiB`) via `openwakeword`, `av.libs` (`73.50 MiB`), duplicate `httpx2`, Linux `tflite-runtime` locked.
- **DEF-40 (`P3`):** Dead code modules/tables: `OllamaAdapter`, `DynamicResourceGovernor`, `ProactiveRateLimiter`, `session`/`message`/`model_benchmark` SQL tables, 22 dead Tauri commands, `WindowsNamedPipe` enum.
- **DEF-41 (`P3`):** Documentation status drift (`JARVIS-SDLC-v0.2.1/` still says `"belum diimplementasikan"`; `rtm_verification_manifest.json` mis-maps `FR-SYS-01` & overstates 72+ rows; `planning/r0-evidence/` missing).
- **DEF-42 (`P3`):** Uncommitted local working tree (`19` modified + `5` untracked files) not yet verified on GitHub Actions CI; floating `stable` Rust / Node `24` in CI; missing `pip-audit`/`cargo-audit`/`clippy`.

---

## 4. Suspected Risks & Unverified Behaviors

- **SUS-01 (Soak Memory Leak — `NFR-12`):** Unbounded key growth in `TurnOrchestratorService._session_history`, `SafeWebFetchClient._cache`, and `RemoteGatewayService._limiter` over multi-day uptime.
- **SUS-02 (SQLite Lock Contention):** Single shared connection + `RLock` under concurrent voice, SSE, and heavy document sync.
- **SUS-03 (Real-Room Wake-Word FAR/FRR & Indonesian Accents):** `OWW_WAKE_THRESHOLD=0.45` and `faster-whisper-small` have never been measured on diverse real human Indonesian/code-switched recordings or 20h ambient TV/music audio.
- **SUS-04 (Clean-Machine WebView2 / VCRedist Prerequisites):** Target workstations without Visual C++ Redistributable may fail to load `onnxruntime`/`ctranslate2`/`llama-server` CUDA/Vulkan DLLs.
- **UNV-01..07:** Tier-B `NFR-01`, `NFR-02`, `NFR-07`, `NFR-12`, `NFR-13`, `NFR-08` (150-case RAG), `NFR-06` (full axe-core audit), and all 26 UAT scenarios (`U01`–`U26`).
