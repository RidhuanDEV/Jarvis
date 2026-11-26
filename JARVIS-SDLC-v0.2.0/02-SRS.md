# Software Requirements Specification (SRS)

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Purpose, environment dan konvensi
Spesifikasi normative untuk single-owner local-first JARVIS. Kata "harus" merupakan requirement; setiap ID stabil dan punya acceptance scenario. P0/R1, P1/R2, P2/R3. Model, adapter, OS dan perangkat merupakan proposed baseline. R0 memvalidasi feasibility. Referensi struktur: ISO/IEC/IEEE 29148, tanpa klaim sertifikasi. Input: mic, text, explicitly selected files/screen/camera, scheduler, paired mobile. Output: audio, text, local notifications, verified tool effects. Host mati/tidur berarti fungsi real-time tidak tersedia. Bahasa ID utama, EN sekunder. External endpoints opt-in; tidak ada cloud LLM. User adalah pemilik OS session; trusted UI adalah boundary untuk approval; wake word tidak membuktikan identitas.

## 2. Functional requirements

### VOI
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-VOI-01 | P0 | Sistem harus menerima teks, push-to-talk, dan wake word lokal saat sesi user aktif; wake word dapat dinonaktifkan. | Aktifkan mode satu per satu; offline semua mode bekerja; disable wake tidak memicu dari rekaman. |
| FR-VOI-02 | P0 | Sistem harus menampilkan indikator listening/transcribing/speaking dan menyediakan mute perangkat lunak yang menghentikan capture. | Mute saat capture, verifikasi stream ditutup, tidak ada frame baru; indikator akurat. |
| FR-VOI-03 | P0 | STT harus memproses Bahasa Indonesia dan Inggris lokal dan meminta klarifikasi bila hasil berisiko ambigu. | Uji corpus ID/EN termasuk angka, nama aplikasi dan code-switch; perintah volume ambigu tidak dieksekusi. |
| FR-VOI-04 | P0 | TTS harus membaca respons lokal, dapat dimatikan, dan mendukung stop serta barge-in yang menutup playback lama. | Interupsi respons; playback lama berhenti; tidak ada self-trigger dari suara TTS. |
| FR-VOI-05 | P0 | Sistem harus menyediakan fallback teks jika mic, STT, atau TTS gagal. | Cabut mic, matikan worker TTS; UI tetap bisa melakukan direct action melalui teks. |

### COR
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-COR-01 | P0 | Sistem harus merutekan perintah pasti ke deterministic tools sebelum inferensi LLM. | Instrumentasi 100 direct intents; tidak ada panggilan LLM pada fixture yang cocok. |
| FR-COR-02 | P0 | LLM harus berjalan lokal; model output diperlakukan sebagai proposal yang divalidasi schema dan policy. | Simulasikan tool tidak dikenal, field tambahan dan URL berbahaya; semua ditolak tanpa efek. |
| FR-COR-03 | P0 | Orchestrator harus membatasi plan menjadi maksimal 5 steps, maksimal 2 perbaikan format, dan 60 detik deadline model per request. | Loop atau JSON invalid melebihi batas; sistem berhenti tanpa eksekusi tambahan. |
| FR-COR-04 | P0 | Sistem harus meminta klarifikasi bila target atau waktu ambigu, tanpa menebak tindakan berisiko. | Dua file bernama sama dan waktu tanpa konteks; tidak ada write sebelum disambiguasi. |
| FR-COR-05 | P0 | Sistem harus mendukung cancel per request serta melaporkan completed, failed, canceled, partial atau unknown secara akurat. | Batalkan workflow setelah langkah pertama; laporkan langkah yang sudah terjadi dan hentikan yang belum dimulai. |
| FR-COR-06 | P0 | Sistem harus tetap menyediakan direct tools, reminders dan teks ketika model tidak tersedia. | Kill worker LLM; buka aplikasi dan buat reminder berhasil tanpa LLM. |

### OS
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-OS-01 | P0 | Sistem harus membuka aplikasi dari registry allowlist dengan executable/identifier tetap, tanpa interpolasi shell. | App terdaftar terbuka; parameter command injection dan app tidak dikenal ditolak. |
| FR-OS-02 | P0 | Sistem harus mengatur dan membaca volume dalam 0–100 serta memverifikasi state. | Set 30, readback 30 dengan toleransi ±2; -5 ditolak. |
| FR-OS-03 | P0 | Sistem harus mencari dan membuka file hanya dalam root yang disetujui, dengan canonical path dan pemeriksaan symlink/reparse point. | File dalam root ditemukan; traversal, UNC tidak diizinkan, dan link keluar root ditolak. |
| FR-OS-04 | P0 | Sistem harus menyediakan operasi file sederhana melalui explicit target, preview, dan approval untuk perubahan konten; deletion permanent tidak didukung. | Rename file yang disetujui; target berubah sebelum eksekusi → approval tidak berlaku; overwrite ditolak. |
| FR-OS-05 | P0 | Sistem harus melaporkan hasil tool dari verifikasi aktual, bukan klaim LLM. | Adapter gagal atau readback mismatch; respons tidak menyatakan sukses. |

### MEM
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-MEM-01 | P0 | Sistem harus menyimpan fakta/preferensi jangka panjang hanya dari explicit remember atau review proposal yang disetujui. | Percakapan biasa tidak menciptakan fakta permanen; explicit remember menghasilkan record bersumber. |
| FR-MEM-02 | P0 | Sistem harus menyediakan list, search, edit, delete dan export memori. | Edit preferensi kemudian query; hasil baru tampil; hapus dan re-query tidak mengembalikan nilai lama. |
| FR-MEM-03 | P0 | Sistem harus menyimpan provenance, timestamp, sensitivity, status dan revision setiap memori. | Konflik dua preferensi memicu review; audit tidak memuat konten sensitif mentah. |
| FR-MEM-04 | P0 | Sistem harus memisahkan session history dari long-term memory; history memiliki TTL yang dapat diatur. | Restart dengan history disabled; transcript tidak dipulihkan; preferensi explicit tetap ada. |
| FR-MEM-05 | P0 | Sistem harus menghapus record dari retrieval indexes dan cache aktif saat pengguna menghapusnya. | Delete; lexical/vector lookup kosong; backup lama diperingatkan dan ledger deletion dipakai saat restore. |

### SCH
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-SCH-01 | P0 | Sistem harus membuat, melihat, mengubah dan membatalkan reminder dengan waktu absolut dan timezone IANA. | Buat reminder besok jam 8 Asia/Jakarta; restart; due_at UTC sesuai; cancel tidak berbunyi. |
| FR-SCH-02 | P0 | Scheduler harus persist due jobs, menerapkan lease, idempotency dan recovery setelah restart. | Matikan proses sebelum/selama due; restart; satu delivery logis atau status uncertain yang terlihat. |
| FR-SCH-03 | P0 | Sistem harus mendukung quiet hours, snooze, dismiss dan missed reminder. | Reminder due ketika tidur; kembali aktif tampil missed; quiet hours tidak menghasilkan audio kecuali user mengizinkan. |
| FR-SCH-04 | P0 | Proactive engine harus menggunakan aturan opt-in dan event yang terdaftar dengan rate limit. | Rule idle/break diaktifkan; notification muncul maksimal sesuai limit; disable menghentikannya. |

### KNO
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-KNO-01 | P1 | Sistem harus mengindeks file TXT, Markdown, PDF text dan DOCX lokal dari folder opt-in dengan limit ukuran. | Indeks fixture berbagai tipe; file di luar root, file terlalu besar, dan PDF scan unsupported diberi status yang jelas. |
| FR-KNO-02 | P1 | Sistem harus melakukan incremental indexing dengan fingerprint dan menghapus stale chunks saat file berubah/dihapus. | Ubah/hapus file; refresh; retrieval tidak menemukan versi stale. |
| FR-KNO-03 | P1 | Sistem harus menyediakan lexical retrieval dan semantic retrieval opsional dengan provenance. | Query fixture kata persis dan sinonim; locator mengarah ke sumber asli; tanpa embedding lexical tetap bekerja. |
| FR-KNO-04 | P1 | Jawaban knowledge harus menyertakan filename dan locator yang valid atau menyatakan evidence tidak cukup. | Question answerable/unanswerable; citation diverifikasi terhadap snapshot sumber. |
| FR-KNO-05 | P1 | Parser dan konten dokumen tidak boleh mengeksekusi macro, script atau instruksi tool. | Dokumen berisi instruksi untuk upload/hapus; tidak ada tool action atau request jaringan. |

### WEB
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-WEB-01 | P1 | Web search harus opt-in, read-only, mengirim hanya query yang telah diperiksa dari data privat. | Network disabled: offline response; enabled: query sensitif memerlukan preview dan approval atau redaction. |
| FR-WEB-02 | P1 | Web fetch harus membatasi host/scheme, redirects, size, time dan private address access; konten selalu untrusted. | Uji localhost, metadata IP, DNS redirect, file URI dan halaman injection; semua request terlarang diblok. |
| FR-WEB-03 | P1 | Jawaban online harus menyertakan URL, waktu retrieval dan tanggal publikasi bila tersedia; cache stale harus ditandai. | Simulasikan offline dan cache berumur; label stale tampil dan tidak mengklaim live. |

### SCR
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-SCR-01 | P1 | Sistem harus mengambil snapshot screen/window hanya dengan permintaan eksplisit, indikator dan preview scope. | Capture satu window; window lain tidak diambil; stop menutup capture. |
| FR-SCR-02 | P1 | Sistem harus mencoba accessibility tree/OCR lokal sebelum optional vision, dan menolak capture konteks sensitif. | Password field atau denylisted app tidak dikirim ke OCR/model; protected content gagal secara aman. |
| FR-SCR-03 | P1 | Sistem harus menghapus screenshot mentah setelah request kecuali pengguna menyetujui penyimpanan terpisah. | Selesai/cancel/crash recovery; tidak ada screenshot dalam disk cache/log secara default. |

### LIF
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-LIF-01 | P1 | Sistem harus menyediakan CRUD task, event kalender lokal, expense dan habit log. | Buat/edit/hapus entitas melalui UI dan voice dengan validasi serta undo jika tersedia. |
| FR-LIF-02 | P1 | Sistem harus menghitung agregat expense dengan integer minor units dan currency terpisah. | Fixture IDR dan USD; subtotal akurat, tidak mencampur mata uang. |
| FR-LIF-03 | P1 | Sistem harus memberi insight deskriptif berdasarkan data yang ada dan tidak mengeksekusi pembayaran atau memberi keputusan medis otomatis. | Data incomplete diberi label; permintaan transfer/medication automation ditolak. |
| FR-LIF-04 | P1 | Integrasi kalender atau email eksternal harus opsional dengan OAuth scope minimal, read-only baseline. | Revoke token; connector berhenti; no send/delete email atau edit kalender pada baseline. |

### AUT
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-AUT-01 | P1 | Pengguna harus dapat membuat workflow dari daftar typed tools, trigger, kondisi dan batas yang tervalidasi. | Workflow malformed, loop, action tidak terdaftar dan deadline invalid ditolak. |
| FR-AUT-02 | P1 | Sistem harus menampilkan dry-run dan meminta persetujuan untuk efek samping yang memerlukannya, termasuk reapproval bila parameter berubah. | Preview rename A; ubah target B; approval A tidak dapat digunakan. |
| FR-AUT-03 | P1 | Workflow harus memiliki idempotency, audit per step, stop, dan recovery dengan reconciliation untuk efek tidak pasti. | Crash setelah adapter dipanggil; tidak melakukan retry buta, tampilkan status unknown/verify. |

### IOT
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-IOT-01 | P2 | Sistem harus mendukung camera snapshot on-demand dengan consent per sesi dan indikator; default off. | Tolak izin; camera tidak terbuka; stop/lock menutup stream. |
| FR-IOT-02 | P2 | Sistem harus membaca dan mengontrol Home Assistant entities dari allowlist terpisah. | Set lampu, readback state; entity tidak terdaftar ditolak. |
| FR-IOT-03 | P2 | Sistem harus memblokir autonomous/high-risk actuation termasuk lock, alarm, heater dan perangkat keselamatan. | Permintaan buka kunci/ubah alarm ditolak; tidak ada call adapter. |
| FR-IOT-04 | P2 | Sistem harus menangani device unavailable dan stale telemetry tanpa mengarang status. | Putus koneksi HA setelah command; hasil unknown/unavailable, bukan success. |

### REM
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-REM-01 | P2 | Sistem harus menyediakan remote access opt-in melalui paired device, encrypted transport, scoped credentials dan revocation. | Pair via local approval; token salah/revoked gagal; tidak ada public port exposure default. |
| FR-REM-02 | P2 | Remote actions harus mengikuti policy yang sama dan scope lebih sempit; local-only controls tidak boleh dieksekusi remote. | Remote mencoba file mutation/screen capture; ditolak; reminder create diizinkan sesuai grant. |
| FR-REM-03 | P2 | Sistem harus menawarkan proposal perubahan preferensi dari feedback lokal tanpa mengubah policy atau model otomatis. | Repeated feedback menghasilkan proposal; reject tidak mengubah preferensi. |
| FR-REM-04 | P2 | Sistem harus menampilkan kondisi host offline/sleep dan tidak mengklaim telah mengeksekusi perintah remote. | Matikan host; mobile client menampilkan unreachable; tidak mengirim ulang mutation otomatis. |

### ADM
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-ADM-01 | P0 | Sistem harus menyediakan per-app, per-folder, per-tool dan network permission settings dengan deny-by-default. | Install baru tidak dapat akses folder/network/device belum diizinkan. |
| FR-ADM-02 | P0 | Sistem harus meminta approval melalui trusted UI untuk tindakan kelas R2, dengan target/parameter/expiry binding. | Suara rekaman atau model mencoba approve; ditolak; nonce lama tidak berlaku. |
| FR-ADM-03 | P0 | Sistem harus mengunci sensitive actions saat OS lock, stop capture, membatalkan approval dan menonaktifkan remote mutation. | Lock workstation saat dialog approval; setelah unlock harus minta approval baru. |
| FR-ADM-04 | P0 | Sistem harus menyediakan audit trail berisi tindakan, outcome, actor, timestamp dan correlation ID dengan redaction. | Periksa audit sukses/gagal/denied; token dan transcript mentah tidak ditemukan. |
| FR-ADM-05 | P0 | Sistem harus menyediakan export, backup, restore dan reset melalui explicit local approval. | Restore snapshot terenkripsi dengan password/key yang benar; corrupt snapshot ditolak; reset membutuhkan konfirmasi. |
| FR-ADM-06 | P0 | Sistem harus mendukung health status dan model/device configuration tanpa menjalankan downloaded code. | Model missing, OOM dan DB read-only ditampilkan; unverified model bundle ditolak. |

### Flexible AI / cinematic UX
| ID | Priority | Requirement | Acceptance scenario |
|---|---|---|---|
| FR-AIP-01 | P0 | Sistem harus mendukung dua adapter LLM lokal tervalidasi melalui kontrak yang sama, tanpa perubahan policy core. | Jalankan canonical chat/stream/schema/cancel fixtures pada dua runtime; perbedaan capability dilaporkan, policy tetap sama. |
| FR-AIP-02 | P0 | Sistem harus menyediakan model/provider registry, role mapping, manifest verification dan capability discovery. | Import manifest valid, reject hash mismatch; model tanpa schema support tidak dipakai untuk tool planning. |
| FR-AIP-03 | P0 | Sistem harus menyediakan enam AI profiles dengan batas resource dan fallback allowlist. | Uji keenam mode, manual pin dan adaptive selection; tidak ada parameter unsupported yang diam-diam diterapkan. |
| FR-AIP-04 | P0 | Sistem harus melakukan atomic model switch setelah drain/cancel, rollback jika gagal, dan mempertahankan data domain. | Ganti model ketika turn aktif; simulasi OOM; profil lama atau direct mode pulih; reminder/memory utuh, tidak ada tool replay. |
| FR-AIP-05 | P0 | Sistem harus menyediakan benchmark opt-in yang cancelable dan menunjukkan provider/model/location serta hasil aktual. | Tanpa approval benchmark tidak mulai; setelah consent hasil punya config/corpus/metrics; cancel berhenti dan lease dilepas. |
| FR-AIP-06 | P1 | Private LAN provider hanya boleh diaktifkan melalui explicit enrollment, endpoint authentication dan scope consent. | Endpoint asing/revoked/redirect ditolak; fallback tidak melewati trust zone; offline tetap dapat menjalankan direct mode. |
| FR-AIP-07 | P1 | Perubahan embedding model harus menggunakan index generation yang terpisah dan atomic promotion. | Ganti embedding dimension; tidak ada vector mixing; FTS tetap bekerja; gagal reindex mempertahankan generation lama. |
| FR-UX-01 | P0 | Sistem harus menyediakan Command Center dan compact HUD dengan original animated core, state-driven feedback, transcript dan stop. | Jalankan 12 state fixtures dan 20 rapid transitions; UI cocok dengan event aktual; stale events tidak menghidupkan turn canceled. |
| FR-UX-02 | P0 | Voice visualization harus berasal dari envelope mic atau playback aktual, tanpa menyimpan raw audio tambahan. | Synthetic amplitude matches animation; mute/cancel/lock mematikan input visualization; tidak ada raw PCM di UI log. |
| FR-UX-03 | P0 | Sistem harus mendukung Cinematic/Balanced/Lite/Reduced Motion, pause render saat hidden dan downgrade under pressure. | Toggle OS reduced motion dan pressure; semua kontrol tetap tersedia; minimized tidak menjalankan loop dekoratif. |

## 3. Non-functional requirements
| ID | Priority | Requirement | Verification |
|---|---|---|---|
| NFR-01 | P0 | p95 direct voice end-of-utterance sampai audio pertama ≤4 detik; warm LLM simple ≤12 detik pada reference machine. | 100 direct + 100 warm mixed trials; catat p50/p95, timeout termasuk sebagai gagal; ukur cold terpisah. |
| NFR-02 | P0 | Saat idle tanpa LLM loaded, target RAM proses keluarga ≤1 GB dan CPU rata-rata ≤3% total selama 10 menit; puncak combined working set ≤16 GB dan dedicated GPU ≤3,3 GiB pada reference machine, diukur bukan dijamin. | Sampling 1 Hz idle dan active 30 menit; breach memicu downgrade/fallback; tidak ada OOM tak tertangani. |
| NFR-03 | P0 | Core voice, chat, OS, memory dan reminder harus berfungsi tanpa internet setelah model terinstal. | Block semua egress non-loopback, restart, jalankan R1 smoke suite. |
| NFR-04 | P0 | Tidak ada tindakan tak berizin pada security suite; tidak ada secrets mentah di log; tidak ada non-loopback listener baseline. | Injection, replay, locked session, path traversal, port scan dan secret scanning. |
| NFR-05 | P0 | RPO backup ≤24 jam jika backup harian diaktifkan dan host aktif; RTO target ≤30 menit untuk fixture 1 GB; reminder state tetap persisten setelah crash. | Restore ke profile bersih; cek checksum, schema, due records, deletion ledger dan RTO. |
| NFR-06 | P0 | Semua primary action dan approval dapat diakses keyboard dan screen reader; UI tidak hanya bergantung pada warna/audio. | Keyboard-only walkthrough, focus order, accessible names dan visual transcript. |
| NFR-07 | P0 | Direct action correctness ≥95%, mixed intent ≥85%, WER ID ≤20% clean, false wake ≤0,2/jam dan false reject ≤10% pada corpus terdefinisi. | Jalankan evaluation corpus independen; laporkan denominators, confidence intervals dan strata. |
| NFR-08 | P1 | ≥90% jawaban answerable memiliki citation valid; ≥90% unanswerable abstain atau menyatakan evidence tidak cukup. | ≥100 answerable + 50 unanswerable dengan human adjudication. |
| NFR-09 | P0 | Adapter harus interchangeable melalui versioned contracts; DB migration, pinned deps, SBOM dan signed update diperlukan sebelum release. | Swap mock adapter; migration forward/restore; signature invalid ditolak. |
| NFR-10 | P0 | Default tidak menyimpan raw audio/screenshot, tidak ada external AI request dan tidak ada telemetry upload. | Inspect disk/log/network capture setelah 30 requests dan restart. |
| NFR-11 | P2 | Remote session harus revocable, rate-limited, encrypted dan tidak mengandalkan exposed public listener. | Pair/revoke; replay dan cross-device test; check network binding and encryption. |
| NFR-12 | P0 | Target 8 jam soak tanpa unhandled crash, runaway queue atau memory growth >20% pada workload tetap setelah warm-up. | 8h approved soak; catat memory slope, queue depth, worker exits dan disk growth. |
| NFR-13 | P0 | Balanced pada reference 60Hz harus menargetkan p95 frame interval ≤20ms dan p95 input-to-visible feedback ≤100ms pada workload terdefinisi. | Trace 5×60s interactive scenarios warm/active inference; report p95, long frames, combined resource; gate tier jika gagal. |
| NFR-14 | P0 | Provider switching tidak boleh mengubah authorization, menimbulkan unapproved external data transfer atau melebihi satu heavy GPU lease milik JARVIS pada reference host. | Fault injection, revoked scope, fallback, concurrency tests; zero unauthorized effects/transfers; resource governor logs verified. |

## 4. External interface and constraints
Desktop UI: trusted app shell, keyboard, tray, overlay. Internal interface: authenticated loopback API behind native broker, SSE for events; private workers use per-process credentials. Remote gateway separate and off by default. SQLite single writer with local data directory; no shared network database. File access limited to user-defined roots; parsing untrusted. No administrator service, shell arbitrary, coding tools, credential collection, unattended dangerous actuation or paid LLM dependency.

## 5. Acceptance and traceability
Release only after applicable requirements verified (17), security blockers resolved, model/licenses approved, backup/restore verified, and UAT sign-off (16). Changes to thresholds require recorded evidence and explicit approval, not silent relaxation. Tests in this document are specification cases, not execution reports.
