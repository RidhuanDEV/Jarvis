# Requirements Traceability Matrix (RTM)

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Konvensi ketertelusuran
Setiap persyaratan normatif dalam `02-SRS.md` dipetakan secara 1-ke-1 ke Epic terkait, rujukan modul desain, ID kasus uji unik (`TC-*`), dan fase rilis wajib pertamanya (`R1`/`R2`/`R3`). Seluruh status saat ini adalah **Not Run** karena belum ada kode aplikasi yang diimplementasikan maupun diuji. Setiap perubahan persyaratan wajib memperbarui `02-SRS.md`, dokumen desain terkait, `12-TEST-STRATEGY.md`, dan matriks ini secara bersamaan.

| Requirement | Epic | Design Ref | Test ID | Release | Acceptance / expected outcome | Status |
|---|---|---|---|---|---|---|
| FR-VOI-01 | E01 | 03 §3; 06 §1 | TC-FR-VOI-01 | R1 | Mode teks, PTT, dan wake lokal bekerja offline; wake dapat dikonfigurasi/dimatikan dan tidak terpicu saat nonaktif. | Not Run |
| FR-VOI-02 | E01 | 03 §3; 06 §1 | TC-FR-VOI-02 | R1 | Mute menutup stream capture segera tanpa frame baru; indikator status akurat. | Not Run |
| FR-VOI-03 | E01 | 06 §§1–2 | TC-FR-VOI-03 | R1 | STT memproses bahasa aktif & *code-switch* lokal; slot ambigu meminta klarifikasi tanpa eksekusi. | Not Run |
| FR-VOI-04 | E01 | 06 §1 | TC-FR-VOI-04 | R1 | TTS lokal mendukung pengaturan kecepatan/volume, stop, dan *barge-in* bersih. | Not Run |
| FR-VOI-05 | E01 | 03 §3; 06 §1 | TC-FR-VOI-05 | R1 | Kegagalan mikrofon/STT/TTS dialihkan mulus ke interaksi teks penuh. | Not Run |
| FR-VOI-06 | E01 | 06 §1; 11 §1 | TC-FR-VOI-06 | R1 | Hotplug perangkat audio pulih tanpa crash; proteksi pantulan speaker mencegah self-trigger; voice pack diperiksa nyata. | Not Run |
| FR-COR-01 | E02 | 03 §3; 06 §1 | TC-FR-COR-01 | R1 | 100 fixture perintah deterministik dieksekusi dengan nol panggilan LLM. | Not Run |
| FR-COR-02 | E02 | 06 §§4–5; 08 §3 | TC-FR-COR-02 | R1 | Proposal model tak dikenal/properti ekstra/argumen berbahaya ditolak skema & Policy Engine tanpa efek. | Not Run |
| FR-COR-03 | E02 | 05 §2; 06 §4 | TC-FR-COR-03 | R1 | Rencana >5 langkah, perbaikan skema >2 kali, atau lewat batas waktu dihentikan bersih. | Not Run |
| FR-COR-04 | E02 | 05 §2 | TC-FR-COR-04 | R1 | Target atau waktu ambigu memicu klarifikasi sebelum ada mutasi. | Not Run |
| FR-COR-05 | E02 | 03 §5; 08 §2 | TC-FR-COR-05 | R1 | Pembatalan menghentikan langkah belum mulai dan melaporkan status parsial/batal secara akurat. | Not Run |
| FR-COR-06 | E02 | 03 §3; 06 §3 | TC-FR-COR-06 | R1 | Tanpa model/worker LLM aktif, *Direct Mode* (tool langsung, pengingat, memori) tetap berfungsi penuh. | Not Run |
| FR-COR-07 | E02 | 05 §2; 06 §1; 10 §3 | TC-FR-COR-07 | R1 | Perubahan bahasa, zona waktu IANA, gaya persona, dan verbositas berlaku dinamis tanpa hardcode locale/WIB. | Not Run |
| FR-OS-01 | E03 | 08 §3; 11 §1 | TC-FR-OS-01 | R1 | Hanya aplikasi dalam allowlist terbuka tanpa shell; injeksi argumen dan aplikasi asing ditolak. | Not Run |
| FR-OS-02 | E03 | 08 §3; 11 §1 | TC-FR-OS-02 | R1 | Pengaturan volume `0–100` terverifikasi readback `±2`; input di luar batas ditolak. | Not Run |
| FR-OS-03 | E03 | 09 §2; 11 §1 | TC-FR-OS-03 | R1 | Pencarian/buka file terbatas pada *source root* kanonik; traversal, UNC liar, dan junction keluar ditolak. | Not Run |
| FR-OS-04 | E03 | 05 §1; 11 §1 | TC-FR-OS-04 | R1 | Mutasi file sederhana wajib pratinjau `R2`, gagal bila target berubah, menolak timpa, dan melarang hapus permanen. | Not Run |
| FR-OS-05 | E03 | 05 §2; 08 §3 | TC-FR-OS-05 | R1 | Kegagalan adapter/ketidakcocokan readback dilaporkan jujur (`failed`/`unknown`), bukan klaim sukses model. | Not Run |
| FR-OS-06 | E03 | 09 §2; 11 §1 | TC-FR-OS-06 | R1 | Peluncuran `AUMID` maupun path Win32 bekerja tanpa shell; validasi berbasis handle menolak percobaan *TOCTOU*. | Not Run |
| FR-MEM-01 | E04 | 05 §2; 07 §2 | TC-FR-MEM-01 | R1 | Percakapan biasa tidak menjadi fakta permanen; perintah ingat eksplisit menyimpan record bersumber. | Not Run |
| FR-MEM-02 | E04 | 07 §2; 08 §2 | TC-FR-MEM-02 | R1 | Daftar, cari, sunting, hapus, dan ekspor memori akurat dan konsisten pada kueri berikutnya. | Not Run |
| FR-MEM-03 | E04 | 07 §2; 09 §3 | TC-FR-MEM-03 | R1 | Provenance, sensitivitas, dan konflik revisi (`409`) terjaga; log audit bebas teks sensitif mentah. | Not Run |
| FR-MEM-04 | E04 | 07 §§2–3 | TC-FR-MEM-04 | R1 | Riwayat sesi terpisah dari memori jangka panjang dan mematuhi pengaturan TTL/nonaktif saat restart. | Not Run |
| FR-MEM-05 | E04 | 07 §§2–4; 09 §2 | TC-FR-MEM-05 | R1 | Penghapusan membersihkan indeks aktif dan mencatat `deletion_ledger` sehingga tidak hidup lagi pasca-restore. | Not Run |
| FR-SCH-01 | E05 | 05 §2; 07 §2 | TC-FR-SCH-01 | R1 | CRUD pengingat menyimpan UTC + IANA timezone pengguna secara akurat melintasi restart. | Not Run |
| FR-SCH-02 | E05 | 03 §5; 07 §2 | TC-FR-SCH-02 | R1 | Lease dan idempotensi job mencegah pengiriman ganda buta setelah crash/restart. | Not Run |
| FR-SCH-03 | E05 | 05 §2; 10 §2 | TC-FR-SCH-03 | R1 | *Quiet hours*, *snooze*, *dismiss*, dan pelaporan *missed reminder* bekerja sesuai kebijakan. | Not Run |
| FR-SCH-04 | E05 | 05 §2 | TC-FR-SCH-04 | R1 | Aturan proaktif opt-in mematuhi *debounce* serta batas per jam/hari dan berhenti saat dimatikan. | Not Run |
| FR-SCH-05 | E05 | 03 §§3,5; 09 §2 | TC-FR-SCH-05 | R1 | Siklus *suspend/resume* menutup capture/approval; *monotonic timer* & rekonsiliasi tahan perubahan jam sistem. | Not Run |
| FR-KNO-01 | E06 | 07 §3 | TC-FR-KNO-01 | R2 | Indeks TXT/MD/PDF/DOCX dalam root terizinkan; file berlebih/luar root ditolak dan PDF pindai berlabel `ocr_required`. | Not Run |
| FR-KNO-02 | E06 | 07 §§2–3 | TC-FR-KNO-02 | R2 | Pembaruan/penghapusan file memperbarui indeks inkremental SHA-256 dan menghapus *chunk* usang. | Not Run |
| FR-KNO-03 | E06 | 07 §§2–3 | TC-FR-KNO-03 | R2 | Retrieval leksikal FTS5 dan hibrida bekerja dengan lokator valid; leksikal jalan penuh tanpa model vektor. | Not Run |
| FR-KNO-04 | E06 | 06 §4; 07 §3 | TC-FR-KNO-04 | R2 | Jawaban menyertakan nama file & halaman/bagian terverifikasi atau menyatakan bukti kurang secara jujur. | Not Run |
| FR-KNO-05 | E06 | 07 §3; 09 §2 | TC-FR-KNO-05 | R2 | Parser tanpa jaringan/makro dan sintesis RAG dengan `tools=[]` menolak instruksi injeksi di dalam dokumen. | Not Run |
| FR-WEB-01 | E07 | 09 §2; 11 §3 | TC-FR-WEB-01 | R2 | Pencarian web opt-in via provider pluggable; mode offline jujur dan indikasi data privat dipratinjau/disaring. | Not Run |
| FR-WEB-02 | E07 | 09 §2; 11 §3 | TC-FR-WEB-02 | R2 | Fetch memblokir IP privat/loopback/metadata/redirect berbahaya serta menetralkan injeksi halaman web. | Not Run |
| FR-WEB-03 | E07 | 11 §3 | TC-FR-WEB-03 | R2 | Jawaban web mencantumkan URL/waktu ambil dan memberi label *stale* pada cache yang melewati TTL. | Not Run |
| FR-SCR-01 | E08 | 10 §2; 11 §2 | TC-FR-SCR-01 | R2 | Tangkapan layar terbatas pada jendela yang dipilih secara eksplisit dengan indikator aktif dan tombol stop. | Not Run |
| FR-SCR-02 | E08 | 09 §2; 11 §2 | TC-FR-SCR-02 | R2 | Prioritas UIA/OCR lokal; kolom password dan aplikasi terlarang ditolak dengan aman. | Not Run |
| FR-SCR-03 | E08 | 07 §3; 11 §2 | TC-FR-SCR-03 | R2 | Gambar tangkapan mentah hanya di RAM selama permintaan dan bersih dari disk/log setelah selesai/batal. | Not Run |
| FR-SCR-04 | E08 | 09 §2; 11 §2 | TC-FR-SCR-04 | R2 | Pola token/kunci privat/rahasia `.env` pada hasil UIA/OCR disamarkan sebelum masuk ke konteks model. | Not Run |
| FR-LIF-01 | E09 | 07 §2; 08 §2 | TC-FR-LIF-01 | R2 | CRUD lokal task, kalender, pengeluaran, dan kebiasaan tervalidasi beserta pemulihan penghapusan berbasis revisi. | Not Run |
| FR-LIF-02 | E09 | 05 §2; 07 §2 | TC-FR-LIF-02 | R2 | Agregasi pengeluaran memakai integer *minor units* dan memisahkan mata uang secara presisi. | Not Run |
| FR-LIF-03 | E09 | 05 §2 | TC-FR-LIF-03 | R2 | Insight bersifat deskriptif dengan label kelengkapan data; pembayaran otomatis dan keputusan medis ditolak. | Not Run |
| FR-LIF-04 | E09 | 09 §3; 11 §4 | TC-FR-LIF-04 | R2 | Konektor kalender/email opsional memakai OAuth read-only minimal di OS Vault dan berhenti seketika saat dicabut. | Not Run |
| FR-AUT-01 | E10 | 05 §2; 08 §2 | TC-FR-AUT-01 | R2 | Workflow bertipe menolak perulangan, langkah >5, tool tak terdaftar, dan batas waktu tidak valid. | Not Run |
| FR-AUT-02 | E10 | 05 §§1–2 | TC-FR-AUT-02 | R2 | Pratinjau *dry-run* mewajibkan persetujuan baru apabila target atau parameter langkah `R2` berubah. | Not Run |
| FR-AUT-03 | E10 | 03 §5; 05 §2 | TC-FR-AUT-03 | R2 | Audit per langkah, idempotensi, pembatalan, dan rekonsiliasi `unknown` pasca-crash tanpa *blind retry*. | Not Run |
| FR-IOT-01 | E11 | 09 §2; 11 §2 | TC-FR-IOT-01 | R3 | Kamera *on-demand* memerlukan izin sesi, menampilkan indikator, dan langsung berhenti saat batal/terkunci. | Not Run |
| FR-IOT-02 | E11 | 08 §3; 11 §5 | TC-FR-IOT-02 | R3 | Hanya entitas Home Assistant dalam allowlist yang dapat diakses dan diverifikasi melalui readback. | Not Run |
| FR-IOT-03 | E11 | 05 §1; 11 §5 | TC-FR-IOT-03 | R3 | Perintah ke kunci pintu, alarm, pemanas, dan perangkat keselamatan diblokir keras (`R3`). | Not Run |
| FR-IOT-04 | E11 | 05 §2; 11 §5 | TC-FR-IOT-04 | R3 | Koneksi HA putus atau readback timeout dilaporkan `unavailable`/`unknown`, bukan klaim berhasil. | Not Run |
| FR-REM-01 | E12 | 09 §§2–3; 11 §6 | TC-FR-REM-01 | R3 | Gateway remote nonaktif default, wajib pemasangan lokal di jaringan privat/TLS, dan token dapat dicabut. | Not Run |
| FR-REM-02 | E12 | 05 §1; 11 §6 | TC-FR-REM-02 | R3 | Sesi remote dibatasi pada cakupan sempit dan ditolak untuk aksi `R2`, file, layar/kamera, atau pengaturan izin. | Not Run |
| FR-REM-03 | E12 | 05 §2 | TC-FR-REM-03 | R3 | Proposal preferensi dari koreksi lokal tidak mengubah preferensi/policy/model bila ditolak atau diabaikan. | Not Run |
| FR-REM-04 | E12 | 10 §2; 11 §6 | TC-FR-REM-04 | R3 | Saat host tidur/mati, klien mobile menampilkan *unreachable* dan tidak mengulang mutasi secara otomatis. | Not Run |
| FR-ADM-01 | Cross-cutting | 05 §1; 09 §3; 10 §2 | TC-FR-ADM-01 | R1 | Profil baru menerapkan *deny-by-default* untuk aplikasi, folder, tool, perangkat, dan jaringan. | Not Run |
| FR-ADM-02 | Cross-cutting | 05 §§1–2; 09 §2; 10 §4 | TC-FR-ADM-02 | R1 | Persetujuan `R2` hanya diterima dari dialog native lokal dengan nonce & hash valid sebelum kedaluwarsa. | Not Run |
| FR-ADM-03 | Cross-cutting | 05 §§1–2; 09 §2 | TC-FR-ADM-03 | R1 | Penguncian sesi OS menghentikan capture, membatalkan persetujuan tertunda, dan memblokir mutasi sensitif/remote. | Not Run |
| FR-ADM-04 | Cross-cutting | 07 §2; 09 §2; 13 §4 | TC-FR-ADM-04 | R1 | Jejak audit mencatat korelasi dan hasil aksi tanpa membocorkan token, rahasia, atau transkrip mentah. | Not Run |
| FR-ADM-05 | Cross-cutting | 07 §4; 13 §3 | TC-FR-ADM-05 | R1 | Ekspor, backup terenkripsi, pemulihan, dan reset memerlukan konfirmasi lokal serta menolak snapshot rusak/kunci salah. | Not Run |
| FR-ADM-06 | Cross-cutting | 06 §2; 08 §2; 09 §2 | TC-FR-ADM-06 | R1 | Diagnostik kesehatan per komponen akurat dan manifest model tidak terverifikasi ditolak tanpa eksekusi kode. | Not Run |
| FR-ADM-07 | E15 | 10 §3; 13 §1 | TC-FR-ADM-07 | R1 | Installer dasar minimal menyelesaikan onboarding 10 langkah dan bekerja dalam *Direct Mode* tanpa unduhan paksa. | Not Run |
| FR-ADM-08 | E15 | 03 §6; 07 §§1–4; 09 §3 | TC-FR-ADM-08 | R1 | Pemisahan `core.db`/`knowledge.db` menjaga isolasi pencabutan root saat crash dan mendukung *restore* lintas perangkat. | Not Run |
| FR-AIP-01 | E13 | 04 §1; 06 §5; 12 §2 | TC-FR-AIP-01 | R1 | Dua adapter referensi lulus suite konformansi kontrak yang sama; instalasi produksi tidak mewajibkan keduanya. | Not Run |
| FR-AIP-02 | E13 | 06 §§2,4; 07 §2 | TC-FR-AIP-02 | R1 | Registri manifest memvalidasi hash, lisensi, dukungan skema, dan kontrol *thinking* sebelum peran diaktifkan. | Not Run |
| FR-AIP-03 | E13 | 01 §6; 06 §§3,5 | TC-FR-AIP-03 | R1 | Keenam profil AI bekerja sesuai batas resource dan menandai parameter tak didukung secara jujur. | Not Run |
| FR-AIP-04 | E13 | 06 §6; 07 §2 | TC-FR-AIP-04 | R1 | Pergantian model/profil berjalan atomik pasca-*drain/cancel* dan *rollback* ke profil sehat/*Direct Mode* saat gagal. | Not Run |
| FR-AIP-05 | E13 | 05 §3; 06 §6; 10 §2 | TC-FR-AIP-05 | R1 | Benchmark memerlukan izin eksplisit, dapat dibatalkan dengan pelepasan worker, dan melaporkan lokasi/metrik nyata. | Not Run |
| FR-AIP-06 | E13 | 06 §5; 09 §2; 11 §5 | TC-FR-AIP-06 | R2 | Provider *private LAN* menolak endpoint asing/tanpa izin cakupan dan tidak pernah menjadi fallback otomatis. | Not Run |
| FR-AIP-07 | E13 | 06 §2; 07 §2 | TC-FR-AIP-07 | R2 | Pergantian model embedding membangun generasi indeks terpisah dan promosi atomik tanpa mencampur dimensi vektor. | Not Run |
| FR-AIP-08 | E13 | 05 §3; 06 §5; 10 §2 | TC-FR-AIP-08 | R1 | Empat mode kepemilikan runtime dihormati; penutupan JARVIS tidak pernah mematikan proses `external_local` milik pengguna. | Not Run |
| FR-UX-01 | E14 | 08 §4; 10 §5 | TC-FR-UX-01 | R1 | 12 state dan 20 transisi cepat pada HUD/Command Center selaras dengan nomor urut `seq` dan membuang event usang. | Not Run |
| FR-UX-02 | E14 | 08 §4; 10 §5 | TC-FR-UX-02 | R1 | Visualisasi suara mengikuti envelope nyata, berhenti saat mute/lock, dan tidak mencatat PCM mentah di UI. | Not Run |
| FR-UX-03 | E14 | 10 §5 | TC-FR-UX-03 | R1 | Keempat tier visual, penghentian render saat jendela tersembunyi, dan penurunan saat tekanan resource berfungsi utuh. | Not Run |
| FR-UX-04 | E14 | 10 §§3,5 | TC-FR-UX-04 | R1 | Pengatur target FPS (`Auto/30/60/120/Native`), mode hemat baterai/gaming, dan deteksi konflik shortcut global bekerja aman. | Not Run |
| FR-SYS-01 | E15 | 01 §5; 03 §3; 08 §2 | TC-FR-SYS-01 | R1 | *System Capability Discovery* mendeteksi kapabilitas sistem dan memberi label `Supported`/`Experimental`/`Unverified`/`Unsupported` secara akurat. | Not Run |
| FR-SYS-02 | E15 | 04 §3; 07 §2; 08 §2 | TC-FR-SYS-02 | R1 | *Configuration Recommendation Engine*, override berversi, ekspor/impor tanpa rahasia, dan *rollback* konfigurasi bekerja valid. | Not Run |
| FR-SYS-03 | E15 | 05 §3; 07 §1; 10 §2 | TC-FR-SYS-03 | R1 | *Dynamic 11-Root Storage Manager* bebas hardcode drive/username, menegakkan kuota cache, mendukung *shared model dir*, dan menolak SMB/UNC untuk DB WAL. | Not Run |
| FR-SYS-04 | E15 | 03 §5; 07 §4; 13 §5 | TC-FR-SYS-04 | R2 | Migrasi storage lintas-drive bertransaksi dengan verifikasi checksum, *rollback* saat gagal, dan pemulihan saat drive eksternal dicabut. | Not Run |
| FR-SYS-05 | E15 | 04 §2; 05 §3; 13 §2 | TC-FR-SYS-05 | R1 | Inventaris lisensi 11 kategori memblokir status `Unknown` dan menghasilkan berkas SBOM serta `NOTICE` yang lengkap. | Not Run |
| FR-SYS-06 | E15 | 08 §5; 11 §7; 13 §3 | TC-FR-SYS-06 | R2 | Ekstensi tepercaya berversi tunduk pada Policy/Audit yang sama; pembaruan komponen mendukung verifikasi integritas & *rollback*. | Not Run |
| NFR-01 | Cross-cutting | 06 §6; 12 §2 | TC-NFR-01 | R1 | Pengukuran latensi `p50`/`p95` direct (`≤ 4s`) dan warm simple LLM (`≤ 12s`) pada perangkat referensi sesuai protokol Tier B. | Not Run |
| NFR-02 | Cross-cutting | 06 §3; 12 §2 | TC-NFR-02 | R1 | Pengukuran penggunaan RAM/CPU idle dan kepatuhan batas memori aktif serta degradasi aman saat memori terbatas. | Not Run |
| NFR-03 | Cross-cutting | 03 §2; 12 §2 | TC-NFR-03 | R1 | Seluruh fungsi inti `R1` lulus smoke suite saat akses jaringan non-loopback diblokir penuh. | Not Run |
| NFR-04 | Cross-cutting | 09 §§2–3; 12 §2 | TC-NFR-04 | R1 | Suite injeksi, replay, sesi terkunci, TOCTOU, port lokal, dan pemindaian rahasia menghasilkan nol pelanggaran. | Not Run |
| NFR-05 | Cross-cutting | 03 §6; 07 §4; 13 §3 | TC-NFR-05 | R1 | Latihan pemulihan snapshot terenkripsi memenuhi target RTO `≤ 30m`, integritas skema, dan *replay* `deletion_ledger`. | Not Run |
| NFR-06 | Cross-cutting | 10 §§4,6; 12 §2 | TC-NFR-06 | R1 | Audit keyboard penuh, *screen reader*, kontras WCAG 2.2 AA, dan transkrip visual lulus di seluruh layar utama. | Not Run |
| NFR-07 | Cross-cutting | 06 §6; 12 §§2–3 | TC-NFR-07 | R1 | Evaluasi korpus *holdout* STT, wake, dan routing memenuhi target kualitas dengan pelaporan interval kepercayaan. | Not Run |
| NFR-08 | E06 | 07 §3; 12 §§2–3 | TC-NFR-08 | R2 | Evaluasi `≥ 100` kasus *answerable* dan `≥ 50` *unanswerable* memenuhi target `≥ 90%` validitas sitasi & abstensi. | Not Run |
| NFR-09 | Cross-cutting | 04 §§1–2; 13 §2 | TC-NFR-09 | R1 | Kontrak berversi, checksum migrasi, lockfile `uv`/`npm`, SBOM/`NOTICE`, dan verifikasi integritas lulus di CI. | Not Run |
| NFR-10 | Cross-cutting | 07 §§1,3; 09 §3 | TC-NFR-10 | R1 | Inspeksi disk, DB mentah, log, dan jaringan membuktikan nol simpanan media mentah default, enkripsi field sensitif, dan nol telemetri luar. | Not Run |
| NFR-11 | E12 | 09 §2; 11 §6 | TC-NFR-11 | R3 | Sesi remote terenkripsi, ber-*rate-limit*, dapat dicabut seketika, dan tidak membuka listener publik. | Not Run |
| NFR-12 | Cross-cutting | 12 §2; 13 §4 | TC-NFR-12 | R1 | *Soak test* `8 jam` berizin (Tier B) berjalan tanpa crash, penumpukan antrean, atau kenaikan memori `> 20%`. | Not Run |
| NFR-13 | E14 | 10 §5; 12 §2 | TC-NFR-13 | R1 | Jejak performa WebView2 5×60s memenuhi target waktu frame pada mode `Balanced` dan menurunkan kualitas secara terkendali saat beban puncak. | Not Run |
| NFR-14 | E13 | 06 §§5–6; 09 §2 | TC-NFR-14 | R1 | Uji kegagalan pergantian provider/profil membuktikan nol pelanggaran otorisasi, zona kepercayaan, maupun batas sewa resource. | Not Run |
| NFR-15 | E15 | 03 §§2–3; 09 §2; 12 §2 | TC-NFR-15 | R1 | Penghentian paksa aplikasi induk melepaskan proses anak `managed_local` dalam target `≤ 5s` tanpa menghentikan proses `external_local`. | Not Run |
| NFR-16 | E15 | 03 §§3,7; 04 §3; 12 §2 | TC-NFR-16 | R1 | Pemeriksa CI memastikan nol ketergantungan API OS langsung di domain core dan nol konstanta hardcode jalur/perangkat pribadi. | Not Run |

## 2. Rekapitulasi inventaris baseline `v0.2.1`
- **Functional Requirements (`FR`):** `82` (`51` P0 / `R1`, `23` P1 / `R2`, `8` P2 / `R3`).
- **Non-Functional Requirements (`NFR`):** `16` (`14` P0 / `R1`, `1` P1 / `R2`, `1` P2 / `R3`).
- **Total Persyaratan Normatif:** **`98`** → Dipetakan ke **`98` Test ID unik** (`65` P0, `24` P1, `9` P2).
- **Cakupan Pemetaan Rencana:** `100%` menurut ID; **Cakupan Eksekusi Aktual:** `0%` (`Not Run`).
