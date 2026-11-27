# J.A.R.V.I.S. — Stage G0 Remediation Baseline & Evidence Freeze

**Document ID:** `G0-BASELINE-001`  
**Review Authority:** `docs/JARVIS-INDEPENDENT-REVIEW-AND-ENHANCEMENT-PLAN.md` (`JRV-IR-001`, §2.4, §13, §16)  
**Baseline Date (Local):** `2026-11-27`  
**Stage Status:** `G0 COMPLETE — PENDING OWNER GATE G0 → G1 SIGN-OFF` (`0` product source files or `v0.2.1` SDLC documents mutated during G0)

---

## 1. Repository Snapshot & Dirty-Diff Fingerprint

All G1–G5 work is anchored against this exact pre-remediation repository baseline:

| Fingerprint Field | Measured Value |
| --- | --- |
| **Git Branch** | `main` (`main...origin/main`) |
| **Git HEAD Commit** | `455c6aa623fcdfe5f220dc3fda4ce2ae7336f3f5` |
| **Modified Tracked Files (`git status`)** | `19` files (pre-existing local working tree prior to G0) |
| **Tracked Dirty Diff Size & SHA-256** | `169,231` bytes — `ecdd9636f89840f0da8d860a4cedb200ab5c8f78aec6d7ef2dd31125702efa8b` |
| **Untracked Product/Test Files (`5`)** | See SHA-256 table below |
| **Frozen SDLC Baseline** | `JARVIS-SDLC-v0.2.1/` (`v0.2.1`, untouched) & `planning/DECISION-REGISTER.md` (`DEC-001`–`DEC-030`, untouched) |
| **As-Built Audit Archive** | `docs/as-built-review/` (`00`–`33`, `JARVIS-AS-BUILT-REVIEW.zip`, verified `0` errors) |

### Untracked Code File SHA-256 Inventory (Pre-G1)

| Relative Path | Lines | SHA-256 |
| --- | ---: | --- |
| `apps/desktop/src-tauri/src/single_instance.rs` | 100 | `de5b4620c575a146afb3c8a1e63df199119608eed5ce621b596dcf7fa375c1ec` |
| `core/jarvis/infrastructure/live_voice_engine.py` | 974 | `9c0a16e6cc59a66f77389de46ed9754f58eff780935ea6fe71264ed01833ecc3` |
| `core/jarvis/infrastructure/providers/local_runtime_manager.py` | 297 | `f6247b1d9d126a66ff1625a257ba4408514ab2356e5892d78c44b939562f46da` |
| `core/jarvis/platform/windows/screen_capture.py` | 55 | `28c57ec858bf76a0acbb9e65d66597382dc29ef6ea700b0e3385e8c399217beb` |
| `tests/unit/test_voice_wake_and_llm_conversation.py` | 304 | `18a56592f85ce449e0775983ccae889399a7511938c55b4350f039e74219578a` |

---

## 2. Real Measured Baseline Test Runs (Executed `2026-11-27`)

Unlike static counts in `[E-TEST]`, all three test suites were executed directly against the frozen G0 snapshot:

| Test Suite | Exact Command Executed | Result | Elapsed | Evidence Classification (`§2.4`) | Observed Warnings / Caveats |
| --- | --- | :---: | :---: | :---: | --- |
| **Python Core (`pytest`)** | `.\core\.venv\Scripts\python.exe -m pytest tests -q --tb=short` | **`150 passed, 0 failed`** | `64.86s` | `VERIFIED_UNIT` | `PytestDeprecationWarning` (`asyncio_default_fixture_loop_scope` unset); mocks voice/LLM/screen/notifications & uses `allow_live_launch=False` and `is_encrypted=0` in backup test. |
| **Desktop UI (`Vitest`)** | `npm test -- --run` (in `apps/desktop`) | **`15 passed, 0 failed`** (`4` files) | `42.48s` | `VERIFIED_UNIT` | React `act(...)` stderr warnings in `phase3.test.tsx` & `phase5.test.tsx`; jsdom/mocked broker, zero live WebView2 or live SSE E2E. |
| **Rust Broker (`Cargo`)** | `cargo test --quiet` (in `apps/desktop/src-tauri`) | **`6 passed, 0 failed`** | `0.01s` (run) | `VERIFIED_UNIT` | Unit-level tests only; zero live OS lock-screen or clean-VM installer launch checks. |
| **Combined Baseline** | — | **`171 passed, 0 failed`** | — | **`VERIFIED_UNIT` ONLY** | **Does NOT qualify as `VERIFIED_INSTALLED_E2E` or `VERIFIED_HARDWARE_CLASS`.** |

---

## 3. Reconciled Schema, Config & RTM Baseline

1. **Dual SQLite Actual Schema (`40` Tables Total):**
   - `jarvis_core.db`: `core/migrations/core/0001_initial_core.sql` (`30` regular tables) + `core/migrations/core/0002_r3_ecosystem.sql` (`5` regular tables) = **`35` regular tables**.
   - `jarvis_knowledge.db`: `core/migrations/knowledge/0001_initial_knowledge.sql` = **`4` regular tables** (`document`, `chunk`, `embedding_index_generation`, `chunk_embedding`) + **`1` virtual FTS5 table (`chunk_fts`)**.
2. **Active Wake-Word Threshold Reconciled:**
   - `core/jarvis/infrastructure/live_voice_engine.py:301`: `OWW_WAKE_THRESHOLD = 0.45` (authoritative active code value).
3. **Documentary RTM Baseline (`98` Requirements: `82 FR`, `16 NFR` from `docs/as-built-review/evidence/rtm-audit-summary.json`):**
   - `VERIFIED`: `11` | `IMPLEMENTED`: `7` | `PARTIAL`: `51` | `MOCK`: `4` | `BROKEN`: `11` | `NOT IMPLEMENTED`: `8` | `UNVERIFIED`: `6`.
   - Zero requirements will be promoted manually; every status upgrade in G1–G5 requires an Evidence Record defined in Section 4.

---

## 4. Mandatory Evidence-Derived Governance Schema (`JRV-IR-001` §2.4)

Starting with **Stage G1**, every verification claim appended to the remediation log MUST follow this exact structured record:

```json
{
  "evidence_id": "EV-G1-001",
  "stage": "G1",
  "backlog_id": "B03",
  "mapped_ids": ["IR-01", "DEF-03", "FR-SYS-03", "DEC-019"],
  "git_head": "455c6aa623fcdfe5f220dc3fda4ce2ae7336f3f5",
  "dirty_diff_sha256": "<sha256-of-git-diff>",
  "verification_level": "VERIFIED_INTEGRATION",
  "test_id": "tests/security/test_g1_safety_kernel.py::test_cache_repoint_cannot_delete_user_files",
  "fixture_id": "sandbox_tmp_user_dir_and_ntfs_junction",
  "expected": "HTTP 403/400 rejected; 0 user files removed",
  "actual": "HTTP 403 DENIED; all 3 fixture files intact",
  "result": "PASS",
  "timestamp_utc": "2026-11-27T00:00:00Z",
  "environment": "Windows 11 x64, Python 3.11.9, pytest (isolated tmp_path)"
}
```

Valid `verification_level` taxonomy (strictly enforced): `IMPLEMENTED_SOURCE`, `VERIFIED_UNIT`, `VERIFIED_INTEGRATION`, `VERIFIED_INSTALLED_E2E`, `VERIFIED_HARDWARE_CLASS`, `MOCK`, `PARTIAL`, `BLOCKED`, `NOT_IMPLEMENTED`.

---

## 5. Companion G0 Deliverables

- [IR-FINDING-VALIDATION.md](./IR-FINDING-VALIDATION.md) — Live source confirmation of all `IR-01`–`IR-22` findings + sound modules preserved.
- [SDLC-v0.2.2-CHANGE-PROPOSAL.md](./SDLC-v0.2.2-CHANGE-PROPOSAL.md) — Proposed targeted amendments to `DEC-001`–`DEC-030` + new `DEC-031`/`DEC-032` + 4 owner policy questions.
- [IMPLEMENTATION-BACKLOG.md](./IMPLEMENTATION-BACKLOG.md) — Complete `B01`–`B26` crosswalk and detailed **Stage G1 (Safety Kernel)** 5-slice isolation & execution plan.
