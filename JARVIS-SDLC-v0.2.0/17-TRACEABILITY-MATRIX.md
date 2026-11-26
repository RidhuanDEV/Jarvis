# Requirements Traceability Matrix (RTM)

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Traceability convention
Each SRS requirement maps to an epic, design module and a uniquely identified acceptance test. Test procedures use the acceptance scenario below plus the environment/recording procedure in 12. Phase is the first required release. All statuses are **Not Run**: this is a specification, not implementation/test evidence. At execution, add build, tester, date, actual result, evidence and defect/waiver IDs. For any requirement change update 02, 03/related design, 12 and this matrix.

| Requirement | Epic | Design | Test ID | Release | Acceptance / expected | Status |
|---|---|---|---|---|---|---|
| FR-VOI-01 | E01 | Voice (03 §3; 06) | TC-FR-VOI-01 | R1 | Aktifkan mode satu per satu; offline semua mode bekerja; disable wake tidak memicu dari rekaman. | Not Run |
| FR-VOI-02 | E01 | Voice (03 §3; 06) | TC-FR-VOI-02 | R1 | Mute saat capture, verifikasi stream ditutup, tidak ada frame baru; indikator akurat. | Not Run |
| FR-VOI-03 | E01 | Voice (03 §3; 06) | TC-FR-VOI-03 | R1 | Uji corpus ID/EN termasuk angka, nama aplikasi dan code-switch; perintah volume ambigu tidak dieksekusi. | Not Run |
| FR-VOI-04 | E01 | Voice (03 §3; 06) | TC-FR-VOI-04 | R1 | Interupsi respons; playback lama berhenti; tidak ada self-trigger dari suara TTS. | Not Run |
| FR-VOI-05 | E01 | Voice (03 §3; 06) | TC-FR-VOI-05 | R1 | Cabut mic, matikan worker TTS; UI tetap bisa melakukan direct action melalui teks. | Not Run |
| FR-COR-01 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-01 | R1 | Instrumentasi 100 direct intents; tidak ada panggilan LLM pada fixture yang cocok. | Not Run |
| FR-COR-02 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-02 | R1 | Simulasikan tool tidak dikenal, field tambahan dan URL berbahaya; semua ditolak tanpa efek. | Not Run |
| FR-COR-03 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-03 | R1 | Loop atau JSON invalid melebihi batas; sistem berhenti tanpa eksekusi tambahan. | Not Run |
| FR-COR-04 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-04 | R1 | Dua file bernama sama dan waktu tanpa konteks; tidak ada write sebelum disambiguasi. | Not Run |
| FR-COR-05 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-05 | R1 | Batalkan workflow setelah langkah pertama; laporkan langkah yang sudah terjadi dan hentikan yang belum dimulai. | Not Run |
| FR-COR-06 | E02 | Orchestrator (03 §3; 06) | TC-FR-COR-06 | R1 | Kill worker LLM; buka aplikasi dan buat reminder berhasil tanpa LLM. | Not Run |
| FR-OS-01 | E03 | Tools/OS (03 §3; 11) | TC-FR-OS-01 | R1 | App terdaftar terbuka; parameter command injection dan app tidak dikenal ditolak. | Not Run |
| FR-OS-02 | E03 | Tools/OS (03 §3; 11) | TC-FR-OS-02 | R1 | Set 30, readback 30 dengan toleransi ±2; -5 ditolak. | Not Run |
| FR-OS-03 | E03 | Tools/OS (03 §3; 11) | TC-FR-OS-03 | R1 | File dalam root ditemukan; traversal, UNC tidak diizinkan, dan link keluar root ditolak. | Not Run |
| FR-OS-04 | E03 | Tools/OS (03 §3; 11) | TC-FR-OS-04 | R1 | Rename file yang disetujui; target berubah sebelum eksekusi → approval tidak berlaku; overwrite ditolak. | Not Run |
| FR-OS-05 | E03 | Tools/OS (03 §3; 11) | TC-FR-OS-05 | R1 | Adapter gagal atau readback mismatch; respons tidak menyatakan sukses. | Not Run |
| FR-MEM-01 | E04 | Memory (07) | TC-FR-MEM-01 | R1 | Percakapan biasa tidak menciptakan fakta permanen; explicit remember menghasilkan record bersumber. | Not Run |
| FR-MEM-02 | E04 | Memory (07) | TC-FR-MEM-02 | R1 | Edit preferensi kemudian query; hasil baru tampil; hapus dan re-query tidak mengembalikan nilai lama. | Not Run |
| FR-MEM-03 | E04 | Memory (07) | TC-FR-MEM-03 | R1 | Konflik dua preferensi memicu review; audit tidak memuat konten sensitif mentah. | Not Run |
| FR-MEM-04 | E04 | Memory (07) | TC-FR-MEM-04 | R1 | Restart dengan history disabled; transcript tidak dipulihkan; preferensi explicit tetap ada. | Not Run |
| FR-MEM-05 | E04 | Memory (07) | TC-FR-MEM-05 | R1 | Delete; lexical/vector lookup kosong; backup lama diperingatkan dan ledger deletion dipakai saat restore. | Not Run |
| FR-SCH-01 | E05 | Scheduler (03 §3; 05) | TC-FR-SCH-01 | R1 | Buat reminder besok jam 8 Asia/Jakarta; restart; due_at UTC sesuai; cancel tidak berbunyi. | Not Run |
| FR-SCH-02 | E05 | Scheduler (03 §3; 05) | TC-FR-SCH-02 | R1 | Matikan proses sebelum/selama due; restart; satu delivery logis atau status uncertain yang terlihat. | Not Run |
| FR-SCH-03 | E05 | Scheduler (03 §3; 05) | TC-FR-SCH-03 | R1 | Reminder due ketika tidur; kembali aktif tampil missed; quiet hours tidak menghasilkan audio kecuali user mengizinkan. | Not Run |
| FR-SCH-04 | E05 | Scheduler (03 §3; 05) | TC-FR-SCH-04 | R1 | Rule idle/break diaktifkan; notification muncul maksimal sesuai limit; disable menghentikannya. | Not Run |
| FR-KNO-01 | E06 | Knowledge/RAG (07) | TC-FR-KNO-01 | R2 | Indeks fixture berbagai tipe; file di luar root, file terlalu besar, dan PDF scan unsupported diberi status yang jelas. | Not Run |
| FR-KNO-02 | E06 | Knowledge/RAG (07) | TC-FR-KNO-02 | R2 | Ubah/hapus file; refresh; retrieval tidak menemukan versi stale. | Not Run |
| FR-KNO-03 | E06 | Knowledge/RAG (07) | TC-FR-KNO-03 | R2 | Query fixture kata persis dan sinonim; locator mengarah ke sumber asli; tanpa embedding lexical tetap bekerja. | Not Run |
| FR-KNO-04 | E06 | Knowledge/RAG (07) | TC-FR-KNO-04 | R2 | Question answerable/unanswerable; citation diverifikasi terhadap snapshot sumber. | Not Run |
| FR-KNO-05 | E06 | Knowledge/RAG (07) | TC-FR-KNO-05 | R2 | Dokumen berisi instruksi untuk upload/hapus; tidak ada tool action atau request jaringan. | Not Run |
| FR-WEB-01 | E07 | Web adapter (11) | TC-FR-WEB-01 | R2 | Network disabled: offline response; enabled: query sensitif memerlukan preview dan approval atau redaction. | Not Run |
| FR-WEB-02 | E07 | Web adapter (11) | TC-FR-WEB-02 | R2 | Uji localhost, metadata IP, DNS redirect, file URI dan halaman injection; semua request terlarang diblok. | Not Run |
| FR-WEB-03 | E07 | Web adapter (11) | TC-FR-WEB-03 | R2 | Simulasikan offline dan cache berumur; label stale tampil dan tidak mengklaim live. | Not Run |
| FR-SCR-01 | E08 | Screen (11; 10) | TC-FR-SCR-01 | R2 | Capture satu window; window lain tidak diambil; stop menutup capture. | Not Run |
| FR-SCR-02 | E08 | Screen (11; 10) | TC-FR-SCR-02 | R2 | Password field atau denylisted app tidak dikirim ke OCR/model; protected content gagal secara aman. | Not Run |
| FR-SCR-03 | E08 | Screen (11; 10) | TC-FR-SCR-03 | R2 | Selesai/cancel/crash recovery; tidak ada screenshot dalam disk cache/log secara default. | Not Run |
| FR-LIF-01 | E09 | Personal domain (07; 11) | TC-FR-LIF-01 | R2 | Buat/edit/hapus entitas melalui UI dan voice dengan validasi serta undo jika tersedia. | Not Run |
| FR-LIF-02 | E09 | Personal domain (07; 11) | TC-FR-LIF-02 | R2 | Fixture IDR dan USD; subtotal akurat, tidak mencampur mata uang. | Not Run |
| FR-LIF-03 | E09 | Personal domain (07; 11) | TC-FR-LIF-03 | R2 | Data incomplete diberi label; permintaan transfer/medication automation ditolak. | Not Run |
| FR-LIF-04 | E09 | Personal domain (07; 11) | TC-FR-LIF-04 | R2 | Revoke token; connector berhenti; no send/delete email atau edit kalender pada baseline. | Not Run |
| FR-AUT-01 | E10 | Workflow (05; 08) | TC-FR-AUT-01 | R2 | Workflow malformed, loop, action tidak terdaftar dan deadline invalid ditolak. | Not Run |
| FR-AUT-02 | E10 | Workflow (05; 08) | TC-FR-AUT-02 | R2 | Preview rename A; ubah target B; approval A tidak dapat digunakan. | Not Run |
| FR-AUT-03 | E10 | Workflow (05; 08) | TC-FR-AUT-03 | R2 | Crash setelah adapter dipanggil; tidak melakukan retry buta, tampilkan status unknown/verify. | Not Run |
| FR-IOT-01 | E11 | IoT/camera (11) | TC-FR-IOT-01 | R3 | Tolak izin; camera tidak terbuka; stop/lock menutup stream. | Not Run |
| FR-IOT-02 | E11 | IoT/camera (11) | TC-FR-IOT-02 | R3 | Set lampu, readback state; entity tidak terdaftar ditolak. | Not Run |
| FR-IOT-03 | E11 | IoT/camera (11) | TC-FR-IOT-03 | R3 | Permintaan buka kunci/ubah alarm ditolak; tidak ada call adapter. | Not Run |
| FR-IOT-04 | E11 | IoT/camera (11) | TC-FR-IOT-04 | R3 | Putus koneksi HA setelah command; hasil unknown/unavailable, bukan success. | Not Run |
| FR-REM-01 | E12 | Remote/adaptive (11; 09) | TC-FR-REM-01 | R3 | Pair via local approval; token salah/revoked gagal; tidak ada public port exposure default. | Not Run |
| FR-REM-02 | E12 | Remote/adaptive (11; 09) | TC-FR-REM-02 | R3 | Remote mencoba file mutation/screen capture; ditolak; reminder create diizinkan sesuai grant. | Not Run |
| FR-REM-03 | E12 | Remote/adaptive (11; 09) | TC-FR-REM-03 | R3 | Repeated feedback menghasilkan proposal; reject tidak mengubah preferensi. | Not Run |
| FR-REM-04 | E12 | Remote/adaptive (11; 09) | TC-FR-REM-04 | R3 | Matikan host; mobile client menampilkan unreachable; tidak mengirim ulang mutation otomatis. | Not Run |
| FR-ADM-01 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-01 | R1 | Install baru tidak dapat akses folder/network/device belum diizinkan. | Not Run |
| FR-ADM-02 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-02 | R1 | Suara rekaman atau model mencoba approve; ditolak; nonce lama tidak berlaku. | Not Run |
| FR-ADM-03 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-03 | R1 | Lock workstation saat dialog approval; setelah unlock harus minta approval baru. | Not Run |
| FR-ADM-04 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-04 | R1 | Periksa audit sukses/gagal/denied; token dan transcript mentah tidak ditemukan. | Not Run |
| FR-ADM-05 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-05 | R1 | Restore snapshot terenkripsi dengan password/key yang benar; corrupt snapshot ditolak; reset membutuhkan konfirmasi. | Not Run |
| FR-ADM-06 | Cross-cutting | Settings/security (09; 10; 13) | TC-FR-ADM-06 | R1 | Model missing, OOM dan DB read-only ditampilkan; unverified model bundle ditolak. | Not Run |
| NFR-01 | Cross-cutting | Performance (06; 12) | TC-NFR-01 | R1 | 100 direct + 100 warm mixed trials; catat p50/p95, timeout termasuk sebagai gagal; ukur cold terpisah. | Not Run |
| NFR-02 | Cross-cutting | Resource manager (06) | TC-NFR-02 | R1 | Sampling 1 Hz idle dan active 30 menit; breach memicu downgrade/fallback; tidak ada OOM tak tertangani. | Not Run |
| NFR-03 | Cross-cutting | Offline (03; 09) | TC-NFR-03 | R1 | Block semua egress non-loopback, restart, jalankan R1 smoke suite. | Not Run |
| NFR-04 | Cross-cutting | Security (09) | TC-NFR-04 | R1 | Injection, replay, locked session, path traversal, port scan dan secret scanning. | Not Run |
| NFR-05 | Cross-cutting | Reliability (03; 13) | TC-NFR-05 | R1 | Restore ke profile bersih; cek checksum, schema, due records, deletion ledger dan RTO. | Not Run |
| NFR-06 | Cross-cutting | Accessibility (10) | TC-NFR-06 | R1 | Keyboard-only walkthrough, focus order, accessible names dan visual transcript. | Not Run |
| NFR-07 | Cross-cutting | Quality (12) | TC-NFR-07 | R1 | Jalankan evaluation corpus independen; laporkan denominators, confidence intervals dan strata. | Not Run |
| NFR-08 | Cross-cutting | Knowledge quality (07; 12) | TC-NFR-08 | R2 | ≥100 answerable + 50 unanswerable dengan human adjudication. | Not Run |
| NFR-09 | Cross-cutting | Maintainability (04; 13) | TC-NFR-09 | R1 | Swap mock adapter; migration forward/restore; signature invalid ditolak. | Not Run |
| NFR-10 | Cross-cutting | Privacy (07; 09) | TC-NFR-10 | R1 | Inspect disk/log/network capture setelah 30 requests dan restart. | Not Run |
| NFR-11 | Cross-cutting | Remote (11) | TC-NFR-11 | R3 | Pair/revoke; replay dan cross-device test; check network binding and encryption. | Not Run |
| NFR-12 | Cross-cutting | Stability (12; 13) | TC-NFR-12 | R1 | 8h approved soak; catat memory slope, queue depth, worker exits dan disk growth. | Not Run |
| FR-AIP-01 | E13 | 06 §6; 04 | TC-FR-AIP-01 | R1 | Jalankan canonical chat/stream/schema/cancel fixtures pada dua runtime; perbedaan capability dilaporkan, policy tetap sama. | Not Run |
| FR-AIP-02 | E13 | 06 §6; 07; 10 §9 | TC-FR-AIP-02 | R1 | Import manifest valid, reject hash mismatch; model tanpa schema support tidak dipakai untuk tool planning. | Not Run |
| FR-AIP-03 | E13 | 06 §6; 10 §9 | TC-FR-AIP-03 | R1 | Uji keenam mode, manual pin dan adaptive selection; tidak ada parameter unsupported yang diam-diam diterapkan. | Not Run |
| FR-AIP-04 | E13 | 06 §6; 07; 08 | TC-FR-AIP-04 | R1 | Ganti model ketika turn aktif; simulasi OOM; profil lama atau direct mode pulih; reminder/memory utuh, tidak ada tool replay. | Not Run |
| FR-AIP-05 | E13 | 06 §6; 10 §9 | TC-FR-AIP-05 | R1 | Tanpa approval benchmark tidak mulai; setelah consent hasil punya config/corpus/metrics; cancel berhenti dan lease dilepas. | Not Run |
| FR-AIP-06 | E13 | 06 §6; 09 | TC-FR-AIP-06 | R2 | Endpoint asing/revoked/redirect ditolak; fallback tidak melewati trust zone; offline tetap dapat menjalankan direct mode. | Not Run |
| FR-AIP-07 | E13 | 06 §6; 07 | TC-FR-AIP-07 | R2 | Ganti embedding dimension; tidak ada vector mixing; FTS tetap bekerja; gagal reindex mempertahankan generation lama. | Not Run |
| FR-UX-01 | E14 | 10 §§6–7; 03 | TC-FR-UX-01 | R1 | Jalankan 12 state fixtures dan 20 rapid transitions; UI cocok dengan event aktual; stale events tidak menghidupkan turn canceled. | Not Run |
| FR-UX-02 | E14 | 10 §7; 08 | TC-FR-UX-02 | R1 | Synthetic amplitude matches animation; mute/cancel/lock mematikan input visualization; tidak ada raw PCM di UI log. | Not Run |
| FR-UX-03 | E14 | 10 §8 | TC-FR-UX-03 | R1 | Toggle OS reduced motion dan pressure; semua kontrol tetap tersedia; minimized tidak menjalankan loop dekoratif. | Not Run |
| NFR-13 | E14 | 10 §8; 12 | TC-NFR-13 | R1 | Trace 5×60s interactive scenarios warm/active inference; report p95, long frames, combined resource; gate tier jika gagal. | Not Run |
| NFR-14 | E13 | 06 §6; 09; 12 | TC-NFR-14 | R1 | Fault injection, revoked scope, fallback, concurrency tests; zero unauthorized effects/transfers; resource governor logs verified. | Not Run |

## 2. Baseline inventory
Functional requirements: 67. Non-functional requirements: 14. Total: 81. Unique test cases mapped: 81. Planned coverage 100% by ID; actual execution coverage 0% (no application test performed).
- P0: 51 requirements.
- P1: 21 requirements.
- P2: 9 requirements.
