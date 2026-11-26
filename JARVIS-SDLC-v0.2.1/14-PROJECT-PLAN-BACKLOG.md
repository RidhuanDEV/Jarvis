# SDLC Project Plan, WBS & Prioritized Backlog

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Fase siklus hidup, tanggung jawab & estimasi terintegrasi
Pengembangan menggunakan tahapan bergerbang (*stage-gated iterative SDLC*). Estimasi di bawah bersifat ilustratif (dalam *person-weeks*, bukan janji tanggal kalender) dan diperbarui setelah bukti empiris `R0` diperoleh. Fondasi konfigurasi dinamis, deteksi kapabilitas perangkat keras, dan portabilitas lokasi penyimpanan dirancang sejak awal (`R0`/`R1`), sementara fitur migrasi lanjut dan ekosistem ditambahkan secara bertahap (`R2`/`R3`).

| Fase | Cakupan utama | Estimasi ilustratif | Gerbang keluar (*Exit Gate*) |
|---|---|---|---|
| `R0` Feasibility & Prototype | Validasi resolusi dependensi (`uv`/`npm`), benchmark terukur suara & 2 adapter LLM referensi, purwarupa gaya visual & telemetri render, audit lisensi awal | 1,5–3 *person-weeks* | `G1` & `G2`: bukti `R0`, arah visual, dan kunci dependensi disetujui pemilik |
| `R1` Core & Adaptive Foundation | Shell Tauri 2 + Broker, Dual SQLite + enkripsi, Policy `R0`–`R3`, *Capability Discovery & Recommendation*, *11-Root Storage Manager* dasar, 4 mode kepemilikan runtime, 6 profil AI, onboarding 10 langkah, suara lokal, tool OS aman, memori, pengingat, HUD & *Adaptive Rendering* | 6–10 *person-weeks* | `G3` & `G4` (`R1`): seluruh `65` persyaratan `P0` terverifikasi, *restore drill*, dan UAT `R1` |
| `R2` Productivity & Portability Expansion | Hybrid RAG (`knowledge.db` + generasi embedding atomik), migrasi storage lintas-drive bertransaksi, web pluggable anti-SSRF, layar UIA/OCR + redaksi rahasia, domain personal, workflow bertipe, *private LAN* opt-in, SDK ekstensi & update/rollback | 5–9 *person-weeks* | `G3` & `G4` (`R2`): seluruh `24` persyaratan `P1` + regresi `P0`, evaluasi sitasi & injeksi, UAT `R2` |
| `R3` Full Ecosystem | Kamera *on-demand* & evaluasi vision opsional, konektor Home Assistant ber-allowlist, gateway mobile privat via VPN/TLS, proposal preferensi adaptif | 4–8 *person-weeks* | `G3` & `G4` (`R3`): seluruh `9` persyaratan `P2` + tinjauan keamanan IoT/remote, UAT `R3` |
| Production Hardening | Uji regresi menyeluruh `98` kasus `RTM`, audit aksesibilitas, *soak test* `8h` berizin, pemaketan installer minimal bertanda tangan, SBOM/`NOTICE`, dokumentasi serah terima | 2–4 *person-weeks* | `G5`: nol cacat `S0`/`S1`, paket rilis terverifikasi & *handover* ditandatangani |

## 2. Prioritized product backlog (`B01` – `B34`)
| ID | Deliverable / Story | Fase | Dependensi | Kriteria selesai utama (*Done Criteria*) |
|---|---|---|---|---|
| B01 | Benchmark kelayakan suara, model & perangkat keras referensi (berizin `L3`) | R0 | Gate G0 | Metrik riil STT/TTS/wake/LLM, profil memori, dan draf inventaris lisensi tercatat |
| B02 | Scaffold monorepo resmi (`Tauri 2` + `uv Python 3.11.9`), CI Tier A, kontrak skema & pemeriksa portabilitas (`NFR-16`) | R0→R1 | B01 | Build deterministik dengan lockfile, nol jalur pribadi di kode sumber |
| B03 | Broker native, abstraksi `LocalIpcTransportPort` (Named Pipe/loopback), `ProcessSupervisorPort` (*Job Object*), Dual SQLite & enkripsi | R1 | B02 | `FR-ADM-03/04/06/08`, `NFR-04/09/10/15` lulus uji integrasi |
| B04 | Policy Engine `R0`–`R3`, registri *typed tools*, dan alur persetujuan `R2` ber-nonce/hash | R1 | B03 | `FR-ADM-01/02`, penolakan replay & sesi terkunci terverifikasi |
| B05 | Pipeline audio dinamis (hotplug perangkat, PTT/wake, STT, TTS, proteksi pantulan speaker) | R1 | B01, B03 | `FR-VOI-01`..`06`, `NFR-01/03/07` terverifikasi |
| B06 | Deterministic router, normalizer locale/timezone/persona dinamis, dan *Bounded Planner* | R1 | B04, B05 | `FR-COR-01`..`07`; *Direct Mode* berjalan penuh tanpa LLM |
| B07 | Adapter OS aman (`Win32` + `AUMID`, volume CoreAudio, pencarian & `R2` rename berbasis handle) | R1 | B04, B06 | `FR-OS-01`..`06`, uji anti-*TOCTOU* & readback lulus |
| B08 | Memori personal eksplisit, pemisahan riwayat sesi ber-TTL, dan `deletion_ledger` | R1 | B03, B06 | `FR-MEM-01`..`05` lulus uji hapus & konsistensi indeks |
| B09 | Scheduler pengingat IANA/UTC persisten, *quiet hours*, aturan proaktif, dan rekonsiliasi *suspend/clock* | R1 | B03, B04 | `FR-SCH-01`..`05` lulus skenario restart & *sleep* |
| B10 | Backup/restore terenkripsi lintas instalasi (`Argon2id + AES-GCM`) & installer dasar minimal | R1 | B03–B09, B29–B32 | `FR-ADM-05/07/08`, `NFR-05`, latihan pemulihan & UAT `R1` |
| B11 | Parser dokumen terisolasi & Hybrid RAG pada `jarvis_knowledge.db` (FTS5 + vektor tergenerasi) | R2 | B08, B10 | `FR-KNO-01`..`05`, `FR-AIP-07`, `NFR-08`, uji anti-injeksi lulus |
| B12 | Konektor pencarian web pluggable & klien fetch read-only anti-SSRF | R2 | B04, B10 | `FR-WEB-01`..`03`, pemblokiran IP privat/redirect terverifikasi |
| B13 | Kesadaran layar per jendela (UIA, OCR lokal, dan penyamaran pola rahasia `FR-SCR-04`) | R2 | B07, B10 | `FR-SCR-01`..`04`, nol penyimpanan tangkapan mentah ke disk |
| B14 | Domain manajemen personal (tasks, kalender, pengeluaran integer, habit) & OAuth read-only opsional | R2 | B03, B09 | `FR-LIF-01`..`04`, presisi multi-mata uang & pencabutan token |
| B15 | Editor workflow bertipe, pratinjau *dry-run*, pembatalan, dan rekonsiliasi status `unknown` | R2 | B04, B09 | `FR-AUT-01`..`03` lulus uji gangguan di tengah langkah |
| B16 | Evaluasi kualitas, keamanan & gerbang UAT `R2` | R2 | B11–B15, B27, B33–B34 | Seluruh `24` persyaratan `P1` & regresi `P0` lulus |
| B17 | Kamera *on-demand* & evaluasi kelayakan model vision opsional | R3 | B13, B24 | `FR-IOT-01`, indikator aktif & pelepasan sewa memori terukur |
| B18 | Integrasi Home Assistant ber-allowlist & pemblokiran aktuasi keselamatan | R3 | B04, B16 | `FR-IOT-02`..`04`, readback & penanganan putus koneksi |
| B19 | Gateway remote privat terenkripsi & antarmuka web mobile responsif | R3 | B03, B16 | `FR-REM-01/02/04`, `NFR-11`, pencabutan perangkat instan |
| B20 | Proposal penyesuaian preferensi berbasis koreksi eksplisit lokal | R3 | B08, B16 | `FR-REM-03`, tanpa eskalasi izin otomatis |
| B21 | Penguatan akhir (*hardening*), *soak test* berizin, installer bertanda tangan, SBOM & serah terima | Hardening | B17–B20, B28 | Seluruh `98` kasus `RTM`, pemulihan bencana, dan UAT final lulus |
| B22 | Spike abstraksi provider & uji konformansi dua runtime lokal referensi (`llama.cpp` & `Ollama`) | R0 | B01 | Bukti portabilitas kontrak & normalisasi kontrol *non-thinking* |
| B23 | Purwarupa gaya visual orisinal & spike telemetri *Adaptive Visual Rendering Engine* | R0 | Gate G0 | Persetujuan arah visual pemilik + jejak waktu frame nyata |
| B24 | Registri provider, 4 mode kepemilikan runtime (`FR-AIP-08`), 6 profil AI, dan *atomic switch/rollback* | R1 | B22, B03, B06 | `FR-AIP-01`..`05`, `FR-AIP-08`, `NFR-14`; runtime eksternal pengguna aman |
| B25 | Token desain, *12-state motion reducer*, HUD/Command Center, 4 tier visual & pengatur batas FPS (`FR-UX-04`) | R1 | B23, B05 | `FR-UX-01`..`04`, `NFR-06/13` terverifikasi |
| B26 | Layar manajemen Runtime/Model, Storage, Personalisasi & Izin yang aksesibel | R1 | B24, B25, B29, B30 | Seluruh kontrol dapat dioperasikan via keyboard & *screen reader* |
| B27 | Provider inferensi *private LAN* opt-in & promosi atomik generasi indeks embedding | R2 | B24, B11 | `FR-AIP-06/07` lulus uji keamanan TLS & isolasi vektor |
| B28 | Perluasan sistem visual adaptif ke modul `R2`/`R3` dan mode ringan mobile | R2/R3 | B25 | Konsistensi state visual tanpa menguras resource |
| B29 | *System Capability Discovery* & *Configuration Recommendation Engine* (`DEC-016`, `DEC-017`) | R1 | B03 | `FR-SYS-01/02`; pelabelan tier dukungan & skema berversi bekerja akurat |
| B30 | *Dynamic 11-Root Storage Manager*, kuota cache & dukungan *shared model directory* (`DEC-003`, `DEC-019`) | R1 | B03, B29 | `FR-SYS-03`; bebas hardcode drive/username, penolakan SMB/UNC pada DB WAL |
| B31 | Alur *First-Run Onboarding* 10 langkah dengan opsi *Recommended Setup* & *Offline Direct Mode* (`DEC-018`) | R1 | B25, B29, B30 | `FR-ADM-07`; pengguna baru selesai setup tanpa paksaan unduh model |
| B32 | Inventaris lisensi 11 kategori artefak, pemblokir lisensi `Unknown`, dan generator SBOM/`NOTICE` (`DEC-022`) | R1 | B02, B03 | `FR-SYS-05`, `NFR-09` terverifikasi otomatis di CI |
| B33 | Migrasi lokasi penyimpanan lintas-drive bertransaksi dengan staging, checksum & rollback (`DEC-019`) | R2 | B30, B10 | `FR-SYS-04` lulus uji pemutusan paksa & pelepasan drive eksternal |
| B34 | SDK ekstensi/provider berversi tepercaya & mekanisme pembaruan komponen dengan rollback (`DEC-024`, `DEC-025`) | R2 | B04, B24, B32 | `FR-SYS-06` lulus uji isolasi izin dan pembatalan paket rusak |

## 3. Jalur kritis terintegrasi & definisi kesiapan/selesai (DoR / DoD)
- **Jalur Kritis Utama:** `Gate G0 → B01/B22/B23 (R0) → Gate G1/G2 → B02 → B03 → B04/B29/B30/B32 → Paralel empat fondasi R1 (B05, B06/B24, B07/B08/B09, B25/B26/B31) → B10 (Gate R1) → B11–B15/B27/B33/B34 → B16 (Gate R2) → B17–B20/B28 (Gate R3) → B21 (Gate G5)`.
- **Definition of Ready (DoR):** ID persyaratan & tes `RTM` jelas, skenario 4-jalur (*happy*, validasi negatif, batas otorisasi, pembatalan/pemulihan) tertulis, dampak portabilitas/lisensi diperiksa, dan persetujuan eksplisit pemilik tercatat bila menyentuh aksi berbatas (`L2`–`L4`).
- **Definition of Done (DoD):** Kode mematuhi batas arsitektur & tipe ketat tanpa kode mati, seluruh tes Tier A lulus 100%, tidak ada konstanta jalur/perangkat pribadi yang terkomit, dokumentasi kontrak/`RTM`/inventaris lisensi diperbarui, serta status teruji vs belum terukur dilaporkan secara jujur.
