# JARVIS | SDLC documentation pack

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## Tujuan dan cara menggunakan paket
JARVIS adalah personal AI assistant local-first hybrid: voice, memory, desktop control, knowledge, proactive automation, vision, personal management, IoT dan akses jarak jauh. Inferensi inti on-device secara default; private LAN opsional pada R2 dengan persetujuan eksplisit. Internet merupakan alat retrieval/integrasi yang dapat dimatikan. Tidak ada coding agent, eksekusi shell arbitrer, atau API LLM berbayar pada baseline.

Baca 01–04 untuk menyepakati scope dan desain, 05–11 untuk kontrak implementasi, 12–16 untuk delivery, 17 untuk traceability, 18 untuk referensi. Semua persyaratan adalah target desain, bukan hasil pengujian. Gunakan file sumber dalam version control; setiap perubahan requirement harus memperbarui RTM dan test.

## Daftar dokumen
| File | Fungsi |
|---|---|
| [01-PRD.md](01-PRD.md) | Visi produk, scope, journey, KPI |
| [02-SRS.md](02-SRS.md) | Requirements yang dapat diuji |
| [03-SDD.md](03-SDD.md) | Arsitektur dan desain komponen |
| [04-TECH-STACK-ADR.md](04-TECH-STACK-ADR.md) | Stack, keputusan, alternatif |
| [05-BUSINESS-RULES.md](05-BUSINESS-RULES.md) | Izin, otomasi, state, aturan domain |
| [06-AI-VOICE-DESIGN.md](06-AI-VOICE-DESIGN.md) | Local inference, voice, model evaluation |
| [07-DATA-DESIGN.md](07-DATA-DESIGN.md) | ERD, skema, lifecycle, RAG |
| [08-INTERFACE-CONTRACTS.md](08-INTERFACE-CONTRACTS.md) | API/IPC, event, tool contracts |
| [09-SECURITY-PRIVACY.md](09-SECURITY-PRIVACY.md) | Threat model, controls, privacy |
| [10-UX-DESIGN.md](10-UX-DESIGN.md) | UX flows, state, accessibility |
| [11-INTEGRATION-DESIGN.md](11-INTEGRATION-DESIGN.md) | OS, web, personal apps, IoT, mobile |
| [12-TEST-STRATEGY.md](12-TEST-STRATEGY.md) | QA, benchmark, acceptance |
| [13-DEPLOYMENT-OPERATIONS.md](13-DEPLOYMENT-OPERATIONS.md) | CI/CD, instalasi, rollback, runbook |
| [14-PROJECT-PLAN-BACKLOG.md](14-PROJECT-PLAN-BACKLOG.md) | WBS, fase, backlog, release gates |
| [15-RISK-GOVERNANCE.md](15-RISK-GOVERNANCE.md) | RAID, change management, quality gates |
| [16-USER-ACCEPTANCE-HANDBOOK.md](16-USER-ACCEPTANCE-HANDBOOK.md) | UAT, onboarding, handover |
| [17-TRACEABILITY-MATRIX.md](17-TRACEABILITY-MATRIX.md) | Requirement → desain → test → fase |
| [18-REFERENCES.md](18-REFERENCES.md) | Sumber teknis dan standar |

## Keputusan dan batasan
- Confirmed: Full JARVIS, tanpa coding agent; local-first hybrid, tanpa API LLM berbayar. Online search dan integrasi boleh saat diaktifkan.
- Proposed: Windows 11 x64, single owner, desktop-first, Bahasa Indonesia utama dan Inggris sekunder, RTX 3050 4 GB VRAM / RAM 24 GB sebagai reference machine (konfirmasi spesifikasi aktual). Tidak diasumsikan CPU, OS edition, disk, mikrofon, atau device IoT tertentu.
- P0 = R1 fondasi; P1 = R2 produktivitas; P2 = R3 ekosistem. P2 adalah scope target, bukan fitur yang boleh dilupakan. R0 adalah feasibility spike.
- Model, OS support, latency, biaya listrik, lisensi, dan kompatibilitas device perlu dibuktikan sebelum release. Tidak ada kode aplikasi yang dibuat dalam paket ini.
- Penggunaan nama JARVIS bersifat working title internal; branding publik memerlukan clearance IP.

## Release notes v0.2.0
Expanded PRD with E13 Flexible AI and E14 Cinematic UX, six AI modes and four visual quality tiers. New model/provider contracts, model manager, original reactive HUD and motion system. 67 FR + 14 NFR = 81 mapped tests, all Not Run. Default on-device AI; optional explicitly enrolled private LAN R2; no paid cloud or coding agent. 19 documents; v0.1.0 original preserved. New profile and visual thresholds, LAN scope and candidate technologies are design decisions for owner review; R0 must validate hardware and approve prototype. See 01, 06, 10 and 17 first.
