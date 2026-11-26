# JARVIS | SDLC documentation pack

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline (`DEC-001`–`DEC-025`), belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## Tujuan dan orientasi produk
JARVIS adalah **private-first, open-source-ready, hardware-adaptive, local-first Personal Intelligence Operating System**: voice, memory, desktop control, knowledge, proactive automation, vision, personal management, IoT, dan akses jarak jauh. Prinsip desain utama adalah ***convention over configuration, with full configuration overrides***: pengguna awam dapat memilih *Recommended Setup* hasil deteksi kapabilitas perangkat, sementara pengguna lanjut dapat mengatur sendiri model, runtime, akselerator GPU/CPU, lokasi penyimpanan, batas resource, voice engine, bahasa/persona, dan target visual.

Inferensi inti berjalan on-device secara default; server inferensi private LAN atau provider kompatibel tambahan bersifat opt-in dengan persetujuan eksplisit. Internet hanya digunakan untuk retrieval/integrasi yang diaktifkan pengguna. Tidak ada coding agent, eksekusi shell arbitrer, atau ketergantungan API LLM berbayar pada baseline.

Baca `01`–`04` untuk cakupan dan keputusan arsitektur, `05`–`11` untuk kontrak implementasi, `12`–`16` untuk pengujian dan delivery, `17` untuk matriks ketertelusuran (`RTM`), dan `18` untuk referensi teknis. Seluruh angka performa adalah target rekayasa yang harus dibuktikan melalui pengujian, bukan jaminan absolut. File di direktori `JARVIS-SDLC-v0.2.1/` merupakan sumber tunggal (*canonical source*); bundel `JARVIS-SDLC-Complete-v0.2.1.md` dihasilkan otomatis melalui `scripts/build_sdlc_complete.py`.

## Daftar dokumen
| File | Fungsi |
|---|---|
| [01-PRD.md](01-PRD.md) | Visi produk, cakupan `E01`–`E15`, onboarding, profil hardware/AI/UX, KPI |
| [02-SRS.md](02-SRS.md) | Persyaratan fungsional (`82` FR) dan non-fungsional (`16` NFR) yang dapat diuji |
| [03-SDD.md](03-SDD.md) | Arsitektur modular monolith, abstraksi platform, state machine, konsistensi dual-DB |
| [04-TECH-STACK-ADR.md](04-TECH-STACK-ADR.md) | Kandidat teknologi, tata kelola lisensi open-source, `ADR-001`–`ADR-025` |
| [05-BUSINESS-RULES.md](05-BUSINESS-RULES.md) | Otoritas `R0`–`R3`, aturan domain, kepemilikan runtime, kebijakan lisensi dan storage |
| [06-AI-VOICE-DESIGN.md](06-AI-VOICE-DESIGN.md) | Pipeline suara, abstraksi provider, 4 mode kepemilikan runtime, evaluasi model |
| [07-DATA-DESIGN.md](07-DATA-DESIGN.md) | Arsitektur dual SQLite, skema ternormalisasi, konsistensi lintas-DB, migrasi storage & backup |
| [08-INTERFACE-CONTRACTS.md](08-INTERFACE-CONTRACTS.md) | Kontrak IPC/API, discovery/storage/runtime contracts, skema tool dan event |
| [09-SECURITY-PRIVACY.md](09-SECURITY-PRIVACY.md) | Threat model STRIDE/LLM, isolasi proses/file, enkripsi, privasi dan supply chain |
| [10-UX-DESIGN.md](10-UX-DESIGN.md) | Onboarding 10 langkah, Command Center, HUD, Adaptive Visual Rendering Engine, aksesibilitas |
| [11-INTEGRATION-DESIGN.md](11-INTEGRATION-DESIGN.md) | Abstraksi OS, audio dinamis, web, konektor personal, Home Assistant, mobile, LAN |
| [12-TEST-STRATEGY.md](12-TEST-STRATEGY.md) | Strategi QA Tier A/Tier B, konformansi provider/storage/hardware, evaluasi AI dan performa |
| [13-DEPLOYMENT-OPERATIONS.md](13-DEPLOYMENT-OPERATIONS.md) | Installer minimal, manajemen storage/update/rollback, observabilitas, runbook |
| [14-PROJECT-PLAN-BACKLOG.md](14-PROJECT-PLAN-BACKLOG.md) | WBS `R0`–`R3` + Hardening, backlog `B01`–`B34`, jalur kritis terintegrasi, DoR/DoD |
| [15-RISK-GOVERNANCE.md](15-RISK-GOVERNANCE.md) | Register risiko ternormalisasi `RK01`–`RK22`, kontrol perubahan, quality gates `G0`–`G5` |
| [16-USER-ACCEPTANCE-HANDBOOK.md](16-USER-ACCEPTANCE-HANDBOOK.md) | Skenario UAT `U01`–`U26`, panduan penggunaan, troubleshooting, checklist handover |
| [17-TRACEABILITY-MATRIX.md](17-TRACEABILITY-MATRIX.md) | Pemetaan 1-ke-1 `98` requirement → desain → `98` test ID → fase rilis |
| [18-REFERENCES.md](18-REFERENCES.md) | Standar acuan dan dokumentasi hulu `REF-01`–`REF-28` |

## Keputusan inti dan batasan produk
- **Confirmed (`LOCKED`):** Visi penuh JARVIS tanpa pengurangan kapabilitas; tanpa coding agent, tanpa shell arbitrer, tanpa API LLM berbayar wajib. Local-first hybrid dengan internet/integrasi eksternal opt-in.
- **Orientasi Produk (`DEC-001`):** *Private-first, open-source-ready*. Pemilihan pustaka menggunakan prinsip *best-fit technology with license compliance* (`MIT`, `Apache-2.0`, `BSD`, `MPL-2.0`, `LGPL`, `GPL`, `AGPL` diizinkan dengan kepatuhan lisensi penuh; lisensi repositori akhir dan peninjauan merek dagang dilakukan sebelum rilis publik).
- **Hardware-Adaptive & Portable (`DEC-016`–`DEC-023`):** Workstation pengembang (Windows 11 x64, Core i5-11400H, RTX 3050 Laptop 4 GB VRAM) berfungsi semata-mata sebagai *reference development profile* lokal, **bukan** batas permanen produk. Produk wajib dapat diinstal pengguna lain pada CPU-only, NVIDIA, AMD, Intel, atau server LAN privat yang didukung tanpa mengubah kode sumber, serta bebas dari hardcode huruf drive, username, zona waktu `WIB`, bahasa tunggal, atau batas permanen `60 FPS`.
- **Release Priorities:** `R0` membuktikan kelayakan teknis/benchmark secara terkendali; `P0 = R1` mengirim fondasi inti + konfigurasi dinamis; `P1 = R2` menambah produktivitas, RAG, migrasi storage penuh, dan LAN opsional; `P2 = R3` menambah IoT, kamera, akses mobile, dan adaptasi preferensi.

## Release notes v0.2.1
Revisi arsitektur pasca-audit Fase 0 (`DEC-001`–`DEC-025`; baseline asli `v0.2.0` disimpan utuh pada tag Git `sdlc-v0.2.0`). Menambahkan Epic `E15` (*Hardware-Adaptive Portability, Storage & Provisioning*), 10-step First-Run Onboarding, Dynamic 11-Root Storage Manager dengan migrasi bertransaksi, 4 mode kepemilikan runtime (`managed_local`, `external_local`, `authorized_lan`, `custom_compatible`), kebijakan lisensi *best-fit with compliance* beserta inventaris artefak 11 kategori, Adaptive Visual Rendering Engine (`Auto/30/60/120/Native` FPS), personalisasi multibahasa/timezone/persona dinamis, 9 port abstraksi platform, dan definisi konsistensi lintas-DB pada arsitektur Dual SQLite. Mengoreksi kontradiksi skema v0.2.0 (`model_manifest`, `embedding_index_generation`), menormalisasi seluruh ID (`82 FR + 16 NFR = 98 TC-*`, `ADR-001`–`025`, `RK01`–`22`, `U01`–`26`, `REF-01`–`28`, `B01`–`34`), dan mengganti klaim teknis absolut menjadi target terukur beserta prosedur verifikasi.
