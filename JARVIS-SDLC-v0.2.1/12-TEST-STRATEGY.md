# Software Test Plan, Hardware Verification & AI Evaluation Strategy

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Objectives, scope & pemisahan gerbang pengujian (Tier A vs Tier B)
Strategi pengujian memverifikasi kebenaran fungsional, jaminan *local-first*, keamanan batas kepercayaan, konsistensi Dual SQLite, portabilitas konfigurasi/storage/runtime lintas perangkat keras, aksesibilitas, dan kualitas model AI. Seluruh `98` persyaratan pada `02-SRS.md` dipetakan 1-ke-1 ke kasus uji di `17-TRACEABILITY-MATRIX.md` dan berstatus **Not Run** pada tahap dokumentasi ini.

Untuk menghormati aturan persetujuan resource pengguna, eksekusi pengujian dibagi menjadi dua tingkat:
1. **Tier A — Automated Offline CI & Local Safe Verification (`L1`):** Unit, property-based, skema kontrak, migrasi & rollback database sintetis, batas arsitektur platform (`NFR-16`), inventaris lisensi (`FR-SYS-05`), mock adapter conformance, keamanan statis/injeksi sintetis, dan snapshot state UI Playwright. Berjalan otomatis tanpa mengunduh model, tanpa menyentuh perangkat nyata pengguna, dan tanpa beban stres.
2. **Tier B — Owner-Authorized Hardware, Live Runtime & Soak Gate (`L3`/`L4`):** Benchmark model/suara nyata (`R0` & pra-rilis), konformansi live dua runtime lokal, jejak performa WebView di berbagai target FPS, migrasi file ukuran besar lintas-drive, uji penghentian paksa proses anak (`Job Object`), serta uji rendam `8 jam` (`NFR-12`). **Wajib mendapat persetujuan eksplisit pemilik sebelum dijalankan.**

## 2. Test suites and coverage targets
| Suite | Cakupan pengujian | Kriteria kelulusan gerbang |
|---|---|---|
| `UNIT` & `PROPERTY` | Normalisasi angka/waktu per locale, urutan otoritas `BR-01`, hash persetujuan `R2`, matematika pengeluaran integer, reduksi state `seq`, redaksi log, logika rekomendasi hardware | 100% tes policy/keamanan lulus; target cakupan cabang domain `≥ 80%` |
| `CONTRACT` | Validasi JSON Schema, idempotensi, konflik revisi `409`, rekoneksi event `seq`, kontrak 9 port platform, skema konfigurasi berversi & ekspor tanpa rahasia | 100% kontrak kritis lulus; `0` pelanggaran batas impor platform (`NFR-16`) |
| `STORAGE` & `DB` | Migrasi maju & pemulihan pra-migrasi, konsistensi lintas `core.db`/`knowledge.db` saat crash pencabutan root, *replay* `deletion_ledger`, penolakan path SMB/UNC, transaksi migrasi storage & rollback (`FR-SYS-03/04`), pemulihan backup `Argon2id` di profil bersih | `0` korupsi data, `0` kebocoran chunk tercabut, `0` kebangkitan memori terhapus |
| `RUNTIME` & `PORTABILITY` | Discovery kapabilitas tiruan (CPU-only, GPU 4 GB, GPU 12 GB, perangkat tak dikenal), pelabelan `Supported`/`Experimental`/`Unverified`/`Unsupported`, 4 mode kepemilikan runtime (pastikan `external_local` tidak dibunuh saat keluar), konformansi dua adapter referensi, *atomic switch/rollback* | Kepatuhan penuh kontrak `FR-AIP-01`..`08` & `FR-SYS-01/02/05/06` |
| `SECURITY` | Prompt injection dokumen/web/OCR (`SEC-01`), replay persetujuan (`SEC-02`), symlink/junction & *TOCTOU* handle (`SEC-03`), SSRF/DNS rebinding (`SEC-04`), sesi terkunci/*suspend* (`SEC-05`), redaksi rahasia layar (`FR-SCR-04`), cakupan remote (`R3-01`) | `0` efek tanpa otorisasi, `0` kebocoran rahasia, `0` listener publik default |
| `UI`, `MOTION` & `A11Y` | Onboarding 10 langkah (termasuk lewati model → *Direct Mode*), 12 state + 20 transisi cepat, perubahan batas FPS (`Auto/30/60/120/Native`), suspensi saat tersembunyi, telusur keyboard penuh, kontras WCAG 2.2 AA, `Reduced Motion` | Seluruh alur kritis dapat diselesaikan via keyboard; state visual selaras dengan event |
| `AI-EVAL` (Tier B) | Korpus *holdout* STT Bahasa Indonesia/Inggris, wake word positif & audio negatif `≥ 20 jam`, akurasi routing direct vs mixed intent, kepatuhan skema adversarial, validitas sitasi & abstensi RAG (`R2`) | Memenuhi target `NFR-07`/`NFR-08` atau dicatat secara jujur dengan rencana mitigasi/CR |
| `PERF` & `RESILIENCE` (Tier B) | Latensi `p50`/`p95` direct & warm/cold LLM, konsumsi RAM/CPU idle & aktif, telemetri VRAM/GPU WebView aktual, pelepasan proses `Job Object` pasca-kill induk (`≤ 5s`), disk penuh, pencabutan perangkat audio/drive eksternal, *soak test* `8 jam` | Memenuhi target `NFR-01/02/12/13/15` pada perangkat keras referensi tanpa klaim hasil fiktif |
| `UAT` | Skenario penerimaan pengguna `U01`–`U26` (`16-USER-ACCEPTANCE-HANDBOOK.md`) | Tanda tangan persetujuan pemilik per rilis |

## 3. Protokol pengukuran statistik & kejujuran pelaporan
1. Gunakan korpus evaluasi yang terpisah dari data penyetelan prompt (*holdout*). Laporkan ukuran sampel, angka mentah keberhasilan/kegagalan, timeout (dihitung sebagai kegagalan, tidak dibuang sebagai *outlier*), interval kepercayaan statistik (mis. interval Wilson untuk proporsi dan bootstrap untuk `WER`/`p95`), serta spesifikasi perangkat keras, versi driver, versi runtime, dan hash model yang tepat.
2. Pengujian performa memisahkan profil perangkat (mis. *reference host* GPU 4 GB vs profil CPU-only) sehingga hasil pada satu komputer tidak diklaim secara sepihak berlaku identik pada seluruh perangkat keras pengguna lain.
3. Keparahan cacat (*Severity*): `S0` efek tak berizin / kebocoran data / kehilangan data; `S1` fitur inti gagal / crash berulang / gagal pulih backup; `S2` penurunan fungsi dengan jalan memutar (*workaround*); `S3` kosmetik. Gerbang rilis melarang cacat terbuka `S0`/`S1` atau temuan keamanan tinggi/kritis.
