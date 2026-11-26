# SDLC AUDIT REPORT & ENGINEERING CORRECTIONS LEDGER — J.A.R.V.I.S.

**Document ID:** `PLAN-02`  
**Version:** 0.2.1 (Includes Post-Review Engineering Corrections & `v0.2.1` Resolution Status)  
**Baseline Audited:** `JARVIS-SDLC-v0.2.0` (tag `sdlc-v0.2.0`) → Remediated in `JARVIS-SDLC-v0.2.1/`  
**Date:** 26 November 2026  
**Status:** Audit Findings Remediated in Canonical `v0.2.1` Documentation

---

## 1. Executive Summary

During Phase 0, an independent audit of the 19 `JARVIS-SDLC-v0.2.0` documents identified **7 cross-document contradictions (`CON-01`–`CON-07`)** and **14 structural/architectural improvement areas (`AUD-01`–`AUD-14`)**. Following the Product Owner's architectural review (`DEC-001`–`DEC-025`), two major refinements were applied:
1. **Product Portability & Open-Source Alignment**: Recommendations that previously leaned too heavily on the developer's specific workstation (`RTX 3050`, `Intel UHD`, `200 Hz` capped at `60 FPS`, `C:/D:` drive split) or enforced a rigid *permissive-only* ban on `GPL`/`AGPL` libraries were elevated into **hardware-adaptive, user-configurable, license-compliant product architectures** (`E15`, `FR-SYS-01`–`06`, `FR-AIP-08`, `FR-UX-04`).
2. **Elimination of Absolute / Unsupported Claims (§2 below)**: Every overstated engineering claim from the initial Phase 0 draft was replaced with **measurable engineering targets, explicit runtime checks, failure-handling mechanisms, and verification tests** across both `JARVIS-SDLC-v0.2.1/` and `planning/`.

---

## 2. Engineering Corrections Ledger (Removal of Overstated Claims)

| Overstated Claim in Initial Draft | Technical Reality & Why It Was Overstated | Corrected Engineering Target & Verification in `v0.2.1` | Updated Docs |
| :--- | :--- | :--- | :--- |
| *"100% Python 3.11/3.12 wheel compatibility"* | Package wheels can fail due to transitive native C/C++ dependencies, OS DLL mismatches, or sub-version updates until resolved and imported. | Pin `Python 3.11.9 + uv` as initial dev baseline (`DEC-004`) and prove compatibility empirically via `uv lock` resolution + import/contract tests in `R0` (`Step R0-A`); claim support for other Python versions only after tested. | `04-TECH`, `PLAN-05`, `PLAN-11` |
| *"Zero database write-lock stalls"* | Even with separate SQLite files in WAL mode, concurrent writes within `jarvis_core.db` or OS disk flush spikes can experience bounded lock waits, and cross-DB WAL writes are **not** 2PC-atomic. | Dual SQLite **reduces write contention** between bulk RAG indexing (`knowledge.db`) and control transactions (`core.db`); residual waits are bounded via single-writer queues + `busy_timeout`, while cross-DB consistency is enforced via `core.db` `root_id`/`deletion_ledger` read-filtering + startup GC (`03-SDD` §6). | `03-SDD`, `07-DATA`, `PLAN-04` |
| *"Zero orphan / zombie worker processes"* | `Windows Job Object` (`KILL_ON_JOB_CLOSE`) handles kernel termination of assigned child processes on parent exit/crash, but edge cases (detached grandchildren, driver hangs, or misclassified external processes) still require verification. | Bind `managed_local` workers to `ProcessSupervisorPort` (`Job Object`) + startup stale-PID check, targeting cleanup within **`≤ 5 seconds`** under fault-injection kill tests (`TC-NFR-15`), while strictly **exempting `external_local`** user runtimes (`FR-AIP-08`). | `02-SRS`, `03-SDD`, `PLAN-04`, `PLAN-08` |
| *"100% / 3,962 MiB dedicated RTX VRAM available"* | Free VRAM fluctuates continuously based on OS version, WDDM reservations, connected monitors, browsers, and games; other users may have `0` discrete VRAM (CPU-only) or `8–24 GB` VRAM. | Treat `3,962 MiB` purely as a single point-in-time snapshot on the dev laptop; `ResourceGovernor` queries **live free VRAM** via `HardwareDiscoveryPort` prior to every load and degrades gracefully to smaller models, partial offload, CPU, or *Direct Mode* (`NFR-02`). | `06-AI`, `PLAN-01`, `PLAN-06` |
| *"Native Windows Indonesian TTS (`Andika`) immediately available"* | Installed Windows OneCore/SAPI voices and WinRT OCR language packs vary by Windows region SKU and user language settings. | `AudioDevicePort` and OCR adapters **probe actually installed OS voices/language packs at runtime** (`FR-VOI-06`); if absent, UI marks the OS fallback `UNAVAILABLE` and offers local neural TTS (`Piper`/`sherpa-onnx`) or text fallback. | `02-SRS`, `04-TECH`, `11-INT`, `PLAN-05` |
| *"WebView2 guaranteed to run on Intel UHD iGPU with 0 MiB dGPU impact"* | Windows Graphics Settings, Optimus/MUX switches, desktop PCs without an iGPU, and Chromium flags determine which GPU accelerates WebView2; Microsoft recommends keeping WebView2 hardware acceleration enabled. | Keep WebView2 hardware acceleration enabled by default, expose configurable rendering quality/FPS (`Auto/30/60/120/Native`), and **verify actual GPU process placement & memory footprint via runtime telemetry** (`FR-UX-04`, `NFR-13`). | `04-TECH`, `10-UX`, `PLAN-07` |
| *"GPL / AGPL libraries must be automatically rejected"* | JARVIS is private-first and open-source-ready; rejecting superior libraries (`PyMuPDF`, `piper1-gpl`) solely for copyleft unnecessarily restricts quality when compliance is manageable. | Adopt **Best-Fit Technology Selection with License Compliance** (`DEC-001`, `DEC-022`): allow `GPL`/`AGPL`/`LGPL`/`MPL` alongside permissive licenses, maintain an 11-category Artifact & License Inventory (`FR-SYS-05`), do not assume subprocesses waive copyleft, and review final repo license before public release. | `04-TECH`, `05-BR`, `PLAN-05`, `PLAN-08` |

---

## 3. Resolution Status of Baseline Contradictions (`CON-01` – `CON-07`) in `v0.2.1`

| ID | Original `v0.2.0` Defect | How Remediated in Canonical `JARVIS-SDLC-v0.2.1` | Status |
| :--- | :--- | :--- | :---: |
| `CON-01` | Duplicate conflicting `model_manifest` vs `model_manifests` tables in `07-DATA-DESIGN.md` | Unified into single normalized `model_manifest` entity linked to `model_provider` (`ownership_mode`, `support_tier`) and `model_benchmark` in `07-DATA-DESIGN.md` §2.1. | **RESOLVED (`v0.2.1`)** |
| `CON-02` | `embedding` table lacked `generation_id` required for atomic index swaps (`FR-AIP-07`) | Replaced with `embedding_index_generation` + `chunk_embedding(generation_id, chunk_id)` in `jarvis_knowledge.db` (`07-DATA-DESIGN.md` §2.2). | **RESOLVED (`v0.2.1`)** |
| `CON-03` | `Qwen3` default `<think>` mode conflicted with `512`-token cap & strict JSON tool schema | Normalized explicit `supports_thinking_control` / *non-thinking* enforcement on tool proposals & fast modes in `06-AI-VOICE-DESIGN.md` §4 and `FR-AIP-02`. | **RESOLVED (`v0.2.1`)** |
| `CON-04` | `Quality` AI mode (`P0/R1`) referenced `R2` Private LAN without clear `R1` local behavior | Clarified `Quality` in `01-PRD.md` §6 and `06-AI-VOICE-DESIGN.md` as largest validated local config on host capacity in `R1`, unlocking opt-in LAN in `R2`. | **RESOLVED (`v0.2.1`)** |
| `CON-05` | `14-PROJECT-PLAN-BACKLOG.md` critical path omitted `B22`–`B28` | Integrated `B01`–`B34` into a single unified table and critical path in `14-PROJECT-PLAN-BACKLOG.md` §§2–3. | **RESOLVED (`v0.2.1`)** |
| `CON-06` | `NFR-12` (`8h` soak) mixed into `R1` gate alongside prohibition on unapproved stress tests | Formally split QA into **Tier A Automated Offline CI (`L1`)** and **Tier B Owner-Authorized Hardware Gate (`L3`/`L4`)** in `12-TEST-STRATEGY.md` §1. | **RESOLVED (`v0.2.1`)** |
| `CON-07` | Duplicate `## 8.` in `03-SDD.md`, unnumbered risks/UAT/refs, and manual `Complete.md` drift | Normalized all headers, `RK01`–`RK22`, `U01`–`U26`, `REF-01`–`REF-28`, and automated `JARVIS-SDLC-Complete-v0.2.1.md` via `scripts/build_sdlc_complete.py`. | **RESOLVED (`v0.2.1`)** |

---

## 4. Updated Register of Architectural Improvements (`AUD-01` – `AUD-14` Revised)

| ID | Summary of Revised Recommendation (`v0.2.1`) | Affected SDLC Docs | Priority & Status |
| :--- | :--- | :--- | :---: |
| `AUD-01` | Single-source canonical `JARVIS-SDLC-v0.2.1/`, Git tag `sdlc-v0.2.0` preservation, normalized IDs, and `build_sdlc_complete.py` automation (`DEC-002`). | All 19 docs, `scripts/` | **P0 — Applied** |
| `AUD-02` | Unified `model_manifest` + `model_provider` (`ownership_mode`, `support_tier`, `license_spdx`, `dataset_license_note`). | `06`, `07`, `08` | **P0 — Applied** |
| `AUD-03` | Generation-isolated `chunk_embedding` bound to `embedding_index_generation` for atomic swap (`FR-AIP-07`). | `02`, `06`, `07` | **P0/P1 — Applied** |
| `AUD-04` | Dual SQLite (`jarvis_core.db` authoritative + `jarvis_knowledge.db` rebuildable) with explicit non-2PC cross-DB read-filtering, startup orphan GC, and coordinated `Argon2id` backup (`DEC-007`). | `02`, `03`, `07`, `13` | **P0 — Applied** |
| `AUD-05` | Adapter-normalized *non-thinking* control for hybrid reasoning models (`Qwen3`) on structured tool proposals & low-latency profiles. | `06`, `08`, `12` | **P0 — Applied** |
| `AUD-06` | Hardware-adaptive `Quality` profile definition + Tier A (automated CI) vs Tier B (owner-approved hardware/soak) test gate split. | `01`, `06`, `12`, `17` | **P0 — Applied** |
| `AUD-07` | Separate sequenced SSE domain events from `≤ 30 Hz` ephemeral envelope channel + *Adaptive Visual Rendering Engine* (`Auto/30/60/120/Native` FPS, telemetry-verified GPU, `DEC-010`). | `02`, `08`, `10`, `12` | **P0 — Applied** |
| `AUD-08` | Dynamic 11-Root Storage Manager (`DEC-003`/`019`, zero hardcoded drives) + `ProcessSupervisorPort` (`Job Object` for `managed_local` only, protecting `external_local`, `DEC-008`/`020`). | `02`, `03`, `07`, `13` | **P0 — Applied** |
| `AUD-09` | Best-Fit Licensing Policy + 11-category Artifact Inventory (`DEC-001`/`009`/`022`), `Python 3.11.9 + uv` dev baseline (`DEC-004`), and runtime check for installed OS voice/OCR packs (`FR-VOI-06`). | `02`, `04`, `05`, `15`, `18` | **P0 — Applied** |
| `AUD-10` | Lightweight ONNX embedding runtime + `sqlite-vec` candidate without mandatory multi-GB PyTorch dependency in Core. | `04`, `06`, `07`, `18` | **P0/P1 — Applied** |
| `AUD-11` | Empirical `R0` voice benchmark (`tiny`/`base`/`small` STT, wake engines, TTS engines) + dynamic audio hotplug & speaker echo/AEC protection (`DEC-013`). | `02`, `06`, `11`, `12` | **P0 — Applied** |
| `AUD-12` | Platform-abstracted `LocalIpcTransportPort` (Windows Named Pipe DACL + 256-bit pipe-inherited secret, loopback test fallback, `DEC-008`/`023`). | `03`, `04`, `08`, `09` | **P0 — Applied** |
| `AUD-13` | Handle-pinned file verification (`FilesystemSafetyPort`) mitigating NTFS junction/symlink TOCTOU + `AUMID` packaged app launch (`FR-OS-06`). | `02`, `09`, `11`, `12` | **P0 — Applied** |
| `AUD-14` | `SecretVaultAndCryptoPort` (`AES-256-GCM` sensitive field encryption + `Argon2id` cross-machine portable backup envelopes, `DEC-007`/`023`). | `02`, `03`, `07`, `09` | **P0 — Applied** |
