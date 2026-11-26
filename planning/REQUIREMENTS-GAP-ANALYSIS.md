# REQUIREMENTS GAP ANALYSIS & `v0.2.1` RECONCILIATION — J.A.R.V.I.S.

**Document ID:** `PLAN-03`  
**Version:** 0.2.1 (Reconciled with `JARVIS-SDLC-v0.2.1` & `DEC-001`–`DEC-025`)  
**Date:** 26 November 2026  
**Status:** All Approved Gaps Promoted into Canonical `02-SRS.md` & `17-TRACEABILITY-MATRIX.md`

---

## 1. Canonical Requirement Evolution (`v0.2.0` → `v0.2.1`)

Following Owner approval (`DEC-001`–`DEC-025`), all **81 original `v0.2.0` requirements (`67 FR + 14 NFR`)** were preserved intact, while **17 new normative requirements (`15 FR + 2 NFR`)** were formally integrated into `02-SRS.md` and `17-TRACEABILITY-MATRIX.md` to support hardware-adaptive discovery, dynamic 11-root storage, 4-mode runtime ownership, 10-step portable onboarding, dynamic personalization, open-source license governance, and 9-port platform isolation.

| Domain / Prefix | `v0.2.0` Count | Added in `v0.2.1` | `v0.2.1` Total | Priority Breakdown (`v0.2.1`) |
| :--- | :---: | :---: | :---: | :--- |
| Voice & Interaction (`FR-VOI-*`) | 5 | `+1` (`FR-VOI-06`) | **6** | `6` P0 (`R1`) |
| Core Intelligence & Locale (`FR-COR-*`) | 6 | `+1` (`FR-COR-07`) | **7** | `7` P0 (`R1`) |
| OS Actions (`FR-OS-*`) | 5 | `+1` (`FR-OS-06`) | **6** | `6` P0 (`R1`) |
| Personal Memory (`FR-MEM-*`) | 5 | `0` | **5** | `5` P0 (`R1`) |
| Scheduling & Power (`FR-SCH-*`) | 4 | `+1` (`FR-SCH-05`) | **5** | `5` P0 (`R1`) |
| Personal Knowledge / RAG (`FR-KNO-*`) | 5 | `0` | **5** | `5` P1 (`R2`) |
| Web Intelligence (`FR-WEB-*`) | 3 | `0` | **3** | `3` P1 (`R2`) |
| Screen Awareness (`FR-SCR-*`) | 3 | `+1` (`FR-SCR-04`) | **4** | `4` P1 (`R2`) |
| Personal Life (`FR-LIF-*`) | 4 | `0` | **4** | `4` P1 (`R2`) |
| Advanced Automation (`FR-AUT-*`) | 3 | `0` | **3** | `3` P1 (`R2`) |
| Environmental & IoT (`FR-IOT-*`) | 4 | `0` | **4** | `4` P2 (`R3`) |
| Remote & Adaptive (`FR-REM-*`) | 4 | `0` | **4** | `4` P2 (`R3`) |
| Admin, Onboarding & Dual-DB (`FR-ADM-*`) | 6 | `+2` (`FR-ADM-07`, `08`) | **8** | `8` P0 (`R1`) |
| Flexible AI & Runtime Ownership (`FR-AIP-*`) | 7 | `+1` (`FR-AIP-08`) | **8** | `6` P0 (`R1`), `2` P1 (`R2`) |
| Adaptive Cinematic UX (`FR-UX-*`) | 3 | `+1` (`FR-UX-04`) | **4** | `4` P0 (`R1`) |
| **System Portability, Storage & Licensing (`FR-SYS-*`, `E15`)** | 0 | **`+6` (`FR-SYS-01`..`06`)** | **6** | `4` P0 (`R1`), `2` P1 (`R2`) |
| **Subtotal Functional (`FR`)** | **67** | **`+15`** | **82** | **`51` P0, `23` P1, `8` P2** |
| **Non-Functional (`NFR-01`..`16`)** | **14** | **`+2` (`NFR-15`, `16`)** | **16** | **`14` P0, `1` P1 (`NFR-08`), `1` P2 (`NFR-11`)** |
| **Grand Total (`RTM` 1-to-1 Mapped)** | **81** | **`+17`** | **98** | **`65` P0 (`R1`), `24` P1 (`R2`), `9` P2 (`R3`)** |

---

## 2. Traceability of All `v0.2.1` Added Requirements to Owner Decisions

| Canonical `v0.2.1` ID | Release | Governing Decision | Capability & Portability Gap Closed | Mapped Test ID |
| :--- | :---: | :--- | :--- | :--- |
| `FR-VOI-06` | `R1` (P0) | `DEC-009`, `DEC-013` | Dynamic audio endpoint hotplug recovery, headphone vs open-speaker echo/barge-in adaptation, and runtime verification of actually installed OS voice packs. | `TC-FR-VOI-06` |
| `FR-COR-07` | `R1` (P0) | `DEC-015` | Configurable primary language, multilingual behavior, dynamic IANA timezone (zero hardcoded `WIB`), persona tone/verbosity, and locale-aware number/time normalization. | `TC-FR-COR-07` |
| `FR-OS-06` | `R1` (P0) | `DEC-023`, `AUD-13` | Dual `Win32` executable + packaged `AppUserModelID` (`AUMID`) app launching without shell, plus handle-pinned file safety against NTFS junction *TOCTOU*. | `TC-FR-OS-06` |
| `FR-SCH-05` | `R1` (P0) | `AUD-08` | OS `Suspend`/`Resume` capture/approval shutdown, monotonic execution deadlines, and system clock-jump schedule reconciliation. | `TC-FR-SCH-05` |
| `FR-SCR-04` | `R2` (P1) | `AUD-10`/`T07` | Pre-inference regex redaction of high-risk secrets/tokens/`.env` values in UIA/OCR text before model context entry. | `TC-FR-SCR-04` |
| `FR-ADM-07` | `R1` (P0) | `DEC-012`, `DEC-018` | Minimal base installer working offline in *Direct Mode* + guided 10-step First-Run Onboarding with transparent size/disk/license disclosure. | `TC-FR-ADM-07` |
| `FR-ADM-08` | `R1` (P0) | `DEC-007` | Dual-SQLite (`core.db` + rebuildable `knowledge.db`) explicit cross-DB consistency (`root_id` + `deletion_ledger` filter + startup GC), sensitive field encryption, and `Argon2id` cross-machine backup/restore. | `TC-FR-ADM-08` |
| `FR-AIP-08` | `R1` (P0) | `DEC-006`, `DEC-020` | Four runtime ownership modes (`managed_local`, `external_local`, `authorized_lan`, `custom_compatible`), single-runtime production sufficiency, GPU/CPU/battery/gaming knobs, and strict non-termination of external user runtimes. | `TC-FR-AIP-08` |
| `FR-UX-04` | `R1` (P0) | `DEC-010` | Adaptive Visual Rendering Engine with configurable FPS targets (`Auto`, `30`, `60`, `120`, `Native`), telemetry-verified GPU placement, contextual battery/gaming/hidden throttling, and safe global shortcut conflict detection. | `TC-FR-UX-04` |
| `FR-SYS-01` | `R1` (P0) | `DEC-016` | *System Capability Discovery* across CPU/RAM/GPU/disk/audio/display/power + honest support classification (`Supported`, `Experimental`, `Unverified`, `Unsupported`). | `TC-FR-SYS-01` |
| `FR-SYS-02` | `R1` (P0) | `DEC-016`, `DEC-017` | *Configuration Recommendation Engine* (*Recommended Setup* + manual overrides) backed by a versioned config schema with secret-free export/import and rollback. | `TC-FR-SYS-02` |
| `FR-SYS-03` | `R1` (P0) | `DEC-003`, `DEC-019` | *Dynamic 11-Root Storage Manager* with OS-standard defaults (zero hardcoded drives/usernames), cache quotas, shared external model directories, and SMB/UNC WAL rejection. | `TC-FR-SYS-03` |
| `FR-SYS-04` | `R2` (P1) | `DEC-019` | Transactional storage migration across directories/drives (preflight, write pause, `.staging` copy, checksum/`integrity_check`, atomic pointer swap, rollback) + disconnected external drive recovery. | `TC-FR-SYS-04` |
| `FR-SYS-05` | `R1` (P0) | `DEC-001`, `DEC-022` | 11-category Artifact & License Inventory blocking `Unknown` licenses and auto-generating CycloneDX SBOM + `THIRD-PARTY-NOTICES`. | `TC-FR-SYS-05` |
| `FR-SYS-06` | `R2` (P1) | `DEC-024`, `DEC-025` | Versioned trusted extension/provider SDK governed by Policy/Governor/Audit + verified application/component update & independent rollback. | `TC-FR-SYS-06` |
| `NFR-15` | `R1` (P0) | `DEC-008`, `DEC-020` | Process supervision (`Job Object` on Windows) targeting `≤ 5s` release of `managed_local` child processes upon forced parent kill while leaving `external_local` processes untouched. | `TC-NFR-15` |
| `NFR-16` | `R1` (P0) | `DEC-023` | CI-enforced platform boundary isolation: zero direct OS API imports in `domain/` & `application/` and zero hardcoded developer paths, drives, usernames, single timezones, or hardware constants. | `TC-NFR-16` |

---

## 3. Progressive Delivery Strategy (Architectural Support Day 1, Feature Rollout Staged)

Per Owner instruction (*"Dynamic configuration must be architecturally supported from the beginning, but advanced functionality may be implemented progressively"*):
- **Day 1 (`R1` / `P0`)**: Full versioned configuration schema (`FR-SYS-02`), capability discovery & *Recommended Setup* (`FR-SYS-01`), configurable 11-root paths & shared model directory (`FR-SYS-03`), 10-step onboarding (`FR-ADM-07`), 4 runtime ownership modes (`FR-AIP-08`), dynamic language/timezone/persona (`FR-COR-07`), adaptive FPS/visual engine (`FR-UX-04`), Dual-SQLite consistency (`FR-ADM-08`), and 11-category license inventory (`FR-SYS-05`).
- **Progressive Expansion (`R2` / `P1`)**: Live Automated Cross-Drive Data/DB Migration wizard (`FR-SYS-04`), Enrolled Private LAN inference (`FR-AIP-06`), Generation-swapped vector embeddings (`FR-AIP-07`), Trusted Extension SDK & Component Updater (`FR-SYS-06`), plus RAG/Web/Screen/Life/Workflow epics (`E06`–`E10`).
- **Full Ecosystem (`R3` / `P2`)**: On-demand Camera/Vision (`FR-IOT-01`), Home Assistant (`FR-IOT-02`–`04`), Scoped Mobile Remote Gateway (`FR-REM-01`–`02`, `04`), and Adaptive Preference Proposals (`FR-REM-03`).
