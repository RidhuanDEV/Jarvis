# SDLC Project Plan, WBS & Product Backlog

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Lifecycle and responsibilities
Iterative SDLC with stage gates; one developer/owner may fill multiple roles but record explicit approval. Product Owner owns scope and UAT; Architect owns ADR/SRS/SDD; Engineer implements; QA verifies independently when possible; Security reviewer approves risk gates; Operator owns backup/recovery. No effort or dates guaranteed: estimates below are person-weeks for planning, not commitment, depend on hardware, skills, device access and test findings. R0 must happen before final stack freeze.

| Phase | Deliverables | Estimated effort | Exit gate |
|---|---|---|---|
| R0 Feasibility | hardware survey, model benchmarks, voice spike, official scaffolds/ADR, threat review | 1–2 person-weeks | baseline proven, model/license decisions recorded |
| R1 Core | local desktop, voice/text, router, safe OS tools, explicit memory, reminders, settings/security | 4–7 person-weeks | all P0 mandatory tests, restore and UAT |
| R2 Productivity | knowledge, web, screen OCR/UIA, personal domains, workflows | 4–8 person-weeks | all P1 mandatory tests, citation and injection eval |
| R3 Ecosystem | camera, optional vision, HA, paired mobile, adaptive proposals | 4–8 person-weeks | all P2 mandatory tests, remote/IoT security review |
| Hardening | regression, accessibility, soak, packaging, runbooks | 2–4 person-weeks | signed release and handover |

Sequential illustrative total 15–29 person-weeks; overlaps possible only if dependencies/gates allow. Re-estimate after R0. No actual sprint dates selected.

## 2. Work breakdown and prioritized backlog
| ID | Story / deliverable | Phase | Dependencies | Done criteria |
|---|---|---|---|---|
| B01 | Host and model feasibility benchmark | R0 | none | model manifest, latency/resource baseline, license report |
| B02 | Official desktop/core scaffold, CI, contracts | R0 | B01 | reproducible build, no secrets, ADR freeze |
| B03 | Local IPC broker, auth, health, audit, DB migrations | R1 | B02 | FR-ADM foundations, NFR-04/09 |
| B04 | Policy engine and typed tool registry | R1 | B03 | R0–R3 rules, replay and denial tests |
| B05 | Audio capture, PTT/wake, STT, TTS | R1 | B01/B03 | FR-VOI, ID benchmark, stop/mute |
| B06 | Intent router, LLM worker/resource manager | R1 | B04/B05 | FR-COR, latency/VRAM targets or formal resolution |
| B07 | App/volume/file adapters | R1 | B04/B06 | FR-OS, path safety and readback |
| B08 | Explicit memory, privacy controls | R1 | B03/B06 | FR-MEM, delete/retrieval consistency |
| B09 | Scheduler and proactive rules | R1 | B03/B04 | FR-SCH, restart/missed scenarios |
| B10 | Onboarding, tray, dashboard, backup, installer | R1 | B03–B09 | FR-ADM, offline and UAT gate |
| B11 | Document parser, FTS/hybrid RAG | R2 | B08/B10 | FR-KNO, NFR-08, injection cases |
| B12 | Web read-only adapter | R2 | B04/B10 | FR-WEB, SSRF/redaction and provider approval |
| B13 | Screen scope and local OCR/UIA | R2 | B07/B10 | FR-SCR, no raw persistence |
| B14 | Tasks/calendar/expenses/habits + optional read-only connectors | R2 | B03/B09 | FR-LIF, arithmetic and revoke |
| B15 | Typed workflow editor and recovery | R2 | B04/B09 | FR-AUT, dry-run and unknown effect reconciliation |
| B16 | R2 evaluation and UAT | R2 | B11–B15 | P1 gate, regression P0 |
| B17 | Camera on-demand and vision feasibility | R3 | B13/B01 | FR-IOT-01, privacy and resource measurements |
| B18 | Home Assistant integration and allowlists | R3 | B04/B16 | FR-IOT-02–04, safety review |
| B19 | Private remote gateway and mobile UI | R3 | B03/B16 | FR-REM-01/02/04, NFR-11 |
| B20 | Adaptive preference proposals | R3 | B08/B16 | FR-REM-03, no autonomous policy change |
| B21 | Final hardening, signed release, handover | R3 | B17–B20 | RTM, security, restore, UAT, licenses |

## 3. Critical path and sprint planning
B01→B02→B03→B04→B06→B07/B08/B09→B10→B16→B19→B21. Parallelize independent UI/fixture work after contracts stable; do not parallelize heavy model workloads on 4 GB GPU during benchmark. Suggested 1–2 week sprint cadence; each sprint includes acceptance criteria, demo, risk review, retrospective and updated RTM. Start with PTT/text before wake; implement policy before effectful tools; implement reminders before advanced automation; build read-only remote before narrow mutation. New features cannot bypass gates.

## 4. Definition of ready and done
Ready: scoped story, requirement IDs, expected user behavior, negative cases, privacy/risk impact, dependencies, mock test data, estimate, acceptance criteria. Done: reviewed source follows existing architecture, tests pass, contract/migration updated, no secrets, permissions and error handling validated, docs/RTM updated, evidence stored, demo accepted; hardware tests only with permission. No unapproved destructive migration, broad refactor, dependency update or stress test. R0 technical spikes are evidence not production implementation.

## 5. First implementation sequence
Day/sprint ordering only: confirm OS/CPU/disk/mic and distribution scope; benchmark approved models in isolation; choose dependency versions; create repository via official tooling; implement settings/auth/SQLite and mock adapters; direct text command through policy; add PTT/STT/TTS; then wake, local LLM fallback, memory, scheduler, UAT. Start no external integrations until core offline and security gates pass. Full roadmap retained even if R1 is usable first.

## Backlog delta v0.2.0 (mandatory R0/R1 unless stated)
| ID | Story | Phase | Dependencies / acceptance |
|---|---|---|---|
| B22 | Provider abstraction spike + two local runtimes | R0 | B01; canonical adapter and licensing proof |
| B23 | Original cinematic styleframes and interactive renderer spike | R0 | B02; user approval + measured renderer/inference budget |
| B24 | Model registry, profile routing, switching and rollback | R1 | B22/B03/B06; FR-AIP-01–05, NFR-14 |
| B25 | Design tokens, motion state controller, core, HUD, quality tiers | R1 | B23/B05; FR-UX-01–03, NFR-13 |
| B26 | Model Manager screens and usability/accessibility | R1 | B24/B25; consent, benchmark, switch, stop, visual gates |
| B27 | Private LAN provider and embedding generation migration | R2 | B24/B11; FR-AIP-06/07 and security review |
| B28 | Extend motion language to R2/R3 modules | R2/R3 | B25; regression and mobile lite mode |
Prior 15–29 person-week estimate predates scope expansion; provisional additional 2–5 person-weeks, not commitment. Re-estimate after R0 proof and user approves styleframes. R1 release requires E13/E14 and applicable new tests; cinematic polish is not deferred wholesale to R3.
