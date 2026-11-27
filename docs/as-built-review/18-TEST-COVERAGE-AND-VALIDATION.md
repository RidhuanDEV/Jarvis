# 18 — Test Coverage and Validation Audit

This audit inventories all **171 automated test cases** across Python (`150`), TypeScript/React (`15`), and Rust (`6`), distinguishing genuinely exercised integration behavior from mocked, shallow, or bug-masking tests.

---

## 1. Complete Test Suite Inventory & Honesty Classification

| Test File | Expanded Cases | Execution Engine | Real Behavior Verified | Mocked / Shallow / Blind Spots |
| --- | :---: | --- | --- | --- |
| `tests/unit/test_policy_and_approvals.py` | 17 | pytest + Hypothesis | **Strong:** `PolicyEngine` precedence, canonical JSON hashing, real SQLite `ApprovalService` atomic single-use consume/expiry/lock-cancel. | Tests `target_snapshot_hash` on service directly, missing that `TurnOrchestrator` & `commands.rs` never pass it! |
| `tests/unit/test_hardware_licensing_crypto_logging.py` | 4 | pytest | **Real logic:** recommendation matrix, SPDX obligations, AES-256-GCM/Argon2id primitives, basic log scrubbing. | Misses traceback redaction order bug, compound keys (`recovery_passphrase`), and Argon2 header DoS. |
| `tests/unit/test_phase3_ai_voice_router.py` | 5 | pytest | Real `DeterministicRouter`, `DynamicResourceGovernor` (dead in prod!), `BoundedAudioRingBuffer`, `EndpointAwareEchoGuard`. | **Mocked:** `httpx.MockTransport` for `LlamaCppServerAdapter` & dead `OllamaAdapter`. |
| `tests/unit/test_phase4_security_rag_and_parsers.py` | 33 | pytest | Real SSRF IP checks, RRF ACL guard, real DOCX ZIP-bomb/macro & blank PDF parser. | Misses live-socket DNS-rebinding TOCTOU and `_SECRET_PATTERNS` inline bypasses. |
| `tests/unit/test_phase5_r3_guards.py` | 31 | pytest | Real pure-domain HA safety bans, private bind IP checks, remote scope ceiling, sliding-window limiter, preference whitelist. | Pure domain functions only; zero runtime integration. |
| `tests/unit/test_voice_wake_and_llm_conversation.py` | 33 | pytest | Regex probes for wake/sleep/hallucination/routes + `submit_turn_streaming` sentence flushing + real SQLite tasks/RAG/screen redaction. | **Mocked:** `_FakeStreamingAdapter`, `_FakeScreenCapture`. **Zero tests** of `LiveVoiceEngine` audio/VAD/OWW/Whisper/Piper runtime! |
| `tests/contract/test_ci_and_release_sbom.py` | 3 | pytest | Real 40-char SHA workflow audit + `generate_release_sbom.py` execution. | Blind spot: does not verify SBOM includes transitive licenses or accurate `scope`. |
| `tests/contract/test_contracts_and_portability_nfr16.py` | 7 | pytest | Real JSON Schema Draft 2020-12 checks, AST boundary scan, static anti-hardcode scan. | Does not test `camera_service.py` emitting invalid event type `"camera.indicator_changed"` against `events.schema.v1.json`. |
| `tests/integration/test_dual_db_storage_backup_api_and_windows.py` | 5 | pytest | Real Dual SQLite WAL + `sqlite-vec` load, real Windows NTFS junction + Win32 Job Object kill. | **BUG-MASKING TEST (`L188`):** inserts test sensitive memory with **`is_encrypted=0`**, hiding the fatal cross-machine backup DEK loss bug! Uses `InMemoryVaultAdapter` in API test. |
| `tests/integration/test_phase3_end_to_end.py` | 3 | pytest | Real SQLite AES-GCM memory, IANA reminder quiet hours, FastAPI `TestClient`. | **Heavily mocked:** `FakeDesktopAutomationAdapter`, `FakeSttAdapter`, `FakeTtsAdapter`, `StaticAudioDeviceAdapter`, `InMemoryVaultAdapter`. Calls `execute_approved_file_move()` directly (hiding that `app.py` never calls it!). |
| `tests/integration/test_phase4_r2_end_to_end.py` | 4 | pytest | Real FTS5+vector generation promotion, workflow dry-run, FastAPI `TestClient`. | **Mocked:** `_MockRagLlm`, `_DeterministicEmbeddingProvider` (no real impl exists!), `_FakeCapture`, `httpx.MockTransport`. Calls dead methods `verify_lan_dispatch` & `authorize_extension_capability` directly! |
| `tests/integration/test_phase5_r3_ecosystem_and_rtm.py` | 5 | pytest | Real SQLite R3 services + FastAPI `TestClient` against unwired `remote_gateway_app.py`. | **Shallow/Mocked:** `_FakeCameraPort`, `_FakeHomeAssistantClient`. RTM test (`L492-525`) only checks that manifest file paths exist on disk! |
| `apps/desktop/src/__tests__/{foundation,phase3,phase4,phase5}.test.tsx` | 15 | Vitest + JSDOM | Real `visualEngine` pacing, Zustand reducer stale-event rejection, `<dialog>` autofocus. | **100% `preview_fixture` mode** (`__TAURI_INTERNALS__` undefined) — zero Tauri IPC, zero backend persistence, zero WebView2 rendering. |
| `apps/desktop/src-tauri/src/{ipc_transport,process_supervisor,single_instance,core_launcher}.rs` | 6 | `cargo test` | Real Win32 Job Object teardown (<5s, spares external PID), real Win32 single-instance mutex, CSPRNG token. | **Shallow (`core_launcher.rs:254-261`):** wraps assertions in `if let Some(spec) = found` so test silently passes even if discovery returns `None`! **0 tests across `commands.rs` (467L) & `lib.rs` (168L).** |

---

## 2. Critical Coverage Blind Spots

1. **`LocalLlmRuntimeManager` (`297` lines): `0` unit/integration tests.**
2. **`LiveVoiceEngine` audio/VAD/OWW/Whisper/Piper threads (`847` lines): `0` runtime tests** (only regex/split helpers tested).
3. **Rust `commands.rs` (`467` lines, 41 IPC commands) & `lib.rs` (`168` lines): `0` tests.**
4. **Real Windows platform adapters (`hardware.py`, `audio.py`, `desktop_automation.py`, `screen_capture.py`, `vault.py`): `0` tests** (all bypassed by fakes in integration suites).
5. **Playwright / WebView2 real browser E2E (`apps/desktop` wired to live Core): `0` tests** (Playwright not in `package.json`).
6. **Concurrency, crash recovery, and negative backup tests:** Zero concurrent approval/pairing replay race tests, zero corrupted-ZIP/Argon2-DoS tests, zero live encrypted-memory cross-machine restore tests, zero clean-machine NSIS installer smoke tests.
7. **UAT Scenarios (`16-USER-ACCEPTANCE-HANDBOOK.md` `U01`–`U26`):** `0/26` formally executed and signed off.
