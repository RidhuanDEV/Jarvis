# Test Inventory & Audit Evidence Summary

> **Audit Mode Notice:** Static forensic test inventory enumerated directly from source files. For full qualitative analysis of real vs. mocked/shallow test coverage and validation blind spots, see [../18-TEST-COVERAGE-AND-VALIDATION.md](../18-TEST-COVERAGE-AND-VALIDATION.md).

## Summary Totals (Enumerated From Source)

| Suite | Runner | Test Files | Static Test Function Count | Audit Quality Note |
| --- | --- | :---: | :---: | --- |
| Python Core (`tests/`) | `pytest` | 12 | 62 | Heavy reliance on fakes/mocks for voice, screen, LLM, and workflow execution (`allow_live_launch=False`) |
| Desktop UI (`apps/desktop/`) | `vitest` | 4 | 15 | Component/store unit tests; zero live Playwright/WebView2 E2E against Core |
| Rust Broker (`apps/desktop/src-tauri/`) | `cargo test` | 4 | 6 | IPC/broker unit assertions; zero live OS lock-screen or Windows session tests |
| **Total Enumerated** | — | **20** | **83** | Reported baseline in Doc 18: 171 automated cases (150 pytest + 15 Vitest + 6 Cargo, including parametrized cases) |

## Python Test Files (`tests/`)

| Relative File Path | Runner | `def test_*` Count |
| --- | :---: | :---: |
| `tests/contract/test_ci_and_release_sbom.py` | `pytest` | 3 |
| `tests/contract/test_contracts_and_portability_nfr16.py` | `pytest` | 4 |
| `tests/integration/test_dual_db_storage_backup_api_and_windows.py` | `pytest` | 5 |
| `tests/integration/test_phase3_end_to_end.py` | `pytest` | 3 |
| `tests/integration/test_phase4_r2_end_to_end.py` | `pytest` | 4 |
| `tests/integration/test_phase5_r3_ecosystem_and_rtm.py` | `pytest` | 5 |
| `tests/unit/test_hardware_licensing_crypto_logging.py` | `pytest` | 4 |
| `tests/unit/test_phase3_ai_voice_router.py` | `pytest` | 5 |
| `tests/unit/test_phase4_security_rag_and_parsers.py` | `pytest` | 6 |
| `tests/unit/test_phase5_r3_guards.py` | `pytest` | 7 |
| `tests/unit/test_policy_and_approvals.py` | `pytest` | 6 |
| `tests/unit/test_voice_wake_and_llm_conversation.py` | `pytest` | 10 |

## Frontend TypeScript Test Files (`apps/desktop/`)

| Relative File Path | Runner | `it/test(...)` Count |
| --- | :---: | :---: |
| `apps/desktop/src/__tests__/foundation.test.tsx` | `vitest` | 5 |
| `apps/desktop/src/__tests__/phase3.test.tsx` | `vitest` | 3 |
| `apps/desktop/src/__tests__/phase4.test.tsx` | `vitest` | 3 |
| `apps/desktop/src/__tests__/phase5.test.tsx` | `vitest` | 4 |

## Rust Broker Test Modules (`apps/desktop/src-tauri/src/`)

| Relative File Path | Runner | `#[test]` Count |
| --- | :---: | :---: |
| `apps/desktop/src-tauri/src/core_launcher.rs` | `cargo test` | 2 |
| `apps/desktop/src-tauri/src/ipc_transport.rs` | `cargo test` | 2 |
| `apps/desktop/src-tauri/src/process_supervisor.rs` | `cargo test` | 1 |
| `apps/desktop/src-tauri/src/single_instance.rs` | `cargo test` | 1 |
