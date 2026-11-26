# User Acceptance Test (UAT), User Guide & Handover

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Prasyarat penerimaan & matriks skenario UAT (`U01` – `U26`)
Prasyarat UAT: artefak build terverifikasi hash, snapshot kapabilitas perangkat uji tercatat, inventaris lisensi/manifest model tervalidasi, hasil suite QA tersedia, dan nol cacat `S0`/`S1` terbuka. Seluruh skenario di bawah berstatus **Not Run** sampai aplikasi diimplementasikan dan diuji.

| ID | Fase | Skenario pengguna | Hasil penerimaan yang diharapkan |
|---|---|---|---|
| U01 | R1 | Pasang installer dasar minimal dalam kondisi offline dan jalankan alur onboarding 10 langkah menggunakan *Recommended Setup* tanpa mengunduh model | Onboarding selesai mulus; sistem masuk ke *Direct Mode* dan perintah dasar berjalan |
| U02 | R1 | Jalankan perintah teks & suara (PTT/wake) untuk membuka aplikasi terdaftar (Win32 & Store/`AUMID`) serta mengatur volume ke 30% | Transkrip tampil, aplikasi terbuka, readback volume `30 ± 2`, tanpa API berbayar |
| U03 | R1 | Aktifkan *Mute* saat mendengarkan, interupsi ucapan asisten, dan cabut/ganti perangkat audio aktif | Capture/playback berhenti bersih, pergantian perangkat terdeteksi tanpa crash, tanpa *self-trigger* speaker |
| U04 | R1 | Simpan memori preferensi secara eksplisit, cari, sunting, hapus, lalu tanyakan kembali | Hanya nilai terbaru yang muncul sebelum dihapus, dan tidak muncul lagi setelah dihapus |
| U05 | R1 | Buat pengingat pada zona waktu pengguna, mulai ulang aplikasi, uji *snooze*, pembatalan, dan kondisi terlewat (*missed*) | Jadwal bertahan lintas restart dan melaporkan *missed reminder* secara akurat |
| U06 | R1 | Ajukan perintah file yang ambigu atau ubah nama file (`R2`) lalu ubah target sebelum menyetujui | Sistem meminta klarifikasi atau membatalkan persetujuan lama; tidak menimpa file tujuan |
| U07 | R1 | Kunci sesi OS (*Lock*) atau *suspend* saat dialog persetujuan `R2` terbuka lalu buka kembali | Capture berhenti dan persetujuan lama dinyatakan gugur |
| U08 | R1 | Hubungkan ke runtime `external_local` (mis. proses tiruan/Ollama milik pengguna) lalu tutup JARVIS; uji juga penghentian paksa proses `managed_local` | Proses `external_local` tetap hidup utuh, sedangkan worker `managed_local` dibersihkan dan *Direct Mode* tetap jalan bila model dimatikan |
| U09 | R1 | Buat backup terenkripsi (`Argon2id`), hapus satu memori, lalu pulihkan backup lama ke profil/direktori instalasi baru yang bersih | Pemulihan berhasil dengan frasa pemulihan, jalur dipetakan ke lokasi baru, dan `deletion_ledger` mencegah memori terhapus muncul kembali |
| U10 | R2 | Indeks folder dokumen yang diizinkan, ajukan pertanyaan yang ada dan tidak ada jawabannya di dokumen, lalu cabut izin folder | Jawaban memuat sitasi halaman/bagian yang valid, menyatakan bukti kurang bila tak terjawab, dan berhenti mengembalikan data setelah dicabut |
| U11 | R2 | Uji pertanyaan pencarian web saat mode offline dan saat mode online dengan provider pluggable aktif | Status offline jujur; saat online query sensitif disaring/dipratinjau dan sumber bertanggal ditampilkan |
| U12 | R2 | Analisis satu jendela aplikasi yang memuat teks biasa dan contoh token rahasia sintetis | Cakupan jendela jelas, token rahasia tersamarkan (`[REDACTED]`), dan tidak ada tangkapan layar tersisa di disk |
| U13 | R2 | Kelola task, agenda, dan pengeluaran dalam IDR serta USD | Perhitungan integer akurat dan terpisah per mata uang tanpa eksekusi transaksi keuangan |
| U14 | R2 | Buat workflow multi-langkah, jalankan *dry-run*, setujui aksi `R2`, dan batalkan di tengah jalan | Langkah yang selesai dan dibatalkan dilaporkan secara jujur tanpa pengulangan buta |
| U15 | R3 | Gunakan kamera *on-demand* lalu batalkan atau kunci sesi | Indikator kamera tampil jelas dan stream tertutup seketika saat dihentikan |
| U16 | R3 | Kontrol lampu Home Assistant dalam allowlist, uji perangkat terputus, dan coba perintah membuka kunci pintu | Lampu terverifikasi readback, perangkat putus berstatus `unknown`/`unavailable`, dan kunci pintu ditolak keras (`R3`) |
| U17 | R3 | Pasangkan ponsel melalui jaringan privat/TLS, buat pengingat, cabut perangkat, dan uji saat host mati | Akses berhasil sesuai cakupan sempit, langsung ditolak setelah dicabut, dan jujur menampilkan *unreachable* saat host mati |
| U18 | R3 | Tinjau dan tolak proposal penyesuaian preferensi adaptif | Preferensi maupun kebijakan keamanan tetap tidak berubah |
| U19 | R1 | Ubah lokasi penyimpanan model/cache pada *Dynamic Storage Manager*, atur kuota cache, dan coba arahkan `core_db` ke path jaringan | Lokasi lokal valid diterima, kuota ditegakkan aman, dan path jaringan untuk DB WAL ditolak dengan alasan jelas |
| U20 | R1 | Beralih antar enam profil AI (`Eco`..`Custom`), uji kegagalan muat model (*rollback*), dan jalankan benchmark berizin lalu batalkan | Pergantian berlangsung atomik, gagal muat kembali ke profil sehat/*Direct Mode*, dan benchmark berhenti bersih saat dibatalkan |
| U21 | R1 | Uji keempat tier visual (`Cinematic`, `Balanced`, `Lite`, `Reduced Motion`) serta pengatur batas FPS (`Auto/30/60/120/Native`) dan jendela diminimalkan | Animasi mengikuti state mesin nyata, loop berhenti saat tersembunyi, dan seluruh fungsi utuh pada `Reduced Motion` |
| U22 | R1 | Ubah bahasa interaksi, zona waktu IANA, gaya persona/verbositas, dan *quiet hours* dari pengaturan | Perilaku asisten dan penjadwalan langsung beradaptasi tanpa mengubah kode sumber |
| U23 | R1 | Selesaikan alur utama (onboarding, chat, stop/mute, persetujuan `R2`, manajemen memori & model) sepenuhnya hanya menggunakan keyboard | Urutan fokus logis, indikator fokus jelas, dan tidak ada jebakan fokus di luar dialog modal |
| U24 | R1 | Periksa tampilan inventaris lisensi di aplikasi dan ekspor berkas SBOM serta `THIRD-PARTY-NOTICES` | Seluruh komponen perangkat lunak, model, dan aset suara yang aktif tercatat lengkap tanpa status `Unknown` |
| U25 | R2 | Pindahkan lokasi model dan database ke drive/direktori lokal lain melalui fitur *Storage Migration*, termasuk simulasi pembatalan/drive eksternal dicabut | Migrasi utuh memindahkan data dengan checksum valid; gangguan memicu *rollback* bersih tanpa kehilangan data |
| U26 | R2 | Daftarkan server inferensi *private LAN* uji dengan persetujuan cakupan data, cabut izinnya, serta uji penolakan paket ekstensi/update yang hash-nya tidak cocok | LAN bekerja sesuai izin lalu terputus bersih saat dicabut; paket tidak valid ditolak dengan *rollback* aman |

## 2. Ringkasan panduan pengguna & batasan jujur
Setelah memasang JARVIS, ikuti panduan 10 langkah *First-Run Onboarding* (cukup pilih *Recommended Setup* untuk pengaturan otomatis sesuai kemampuan perangkat Anda, atau sesuaikan direktori penyimpanan, runtime AI, bahasa, dan kualitas visual secara mandiri). Gunakan *System Tray* kapan saja untuk *Mute*, *Stop*, atau mengaktifkan mode *Offline* dalam dua klik. JARVIS tidak mengenali identitas pemilik dari suara semata, tidak menjalankan perintah shell bebas atau agen pemrograman, tidak melakukan pembayaran atau diagnosis medis, tidak mengontrol perangkat keselamatan kritis, dan tidak dapat menerima perintah jarak jauh ketika komputer host sedang mati atau tidur.

## 3. Daftar periksa serah terima (*Handover Checklist*)
Installer dasar minimal beserta hash SHA-256, repositori sumber bertag rilis, paket dokumentasi kanonik `JARVIS-SDLC-v0.2.1/` dan bundel tergenerasi, snapshot skema OpenAPI/IPC/konfigurasi dan migrasi SQL, inventaris lisensi 11 kategori beserta SBOM dan `THIRD-PARTY-NOTICES`, laporan hasil pengujian Tier A & Tier B serta status aktual `RTM`, berita acara UAT `U01`–`U26`, panduan pemulihan kunci backup (tanpa menyertakan kunci rahasia pengguna), dan daftar risiko residual.
