# Integration, Platform Abstraction, IoT & Remote Design

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Desktop OS & filesystem adapter (`DesktopAutomationPort`, `FilesystemSafetyPort`)
- **Peluncuran Aplikasi Tanpa Shell:** Menggunakan registri allowlist yang memetakan `app_id` stabil ke path executable terverifikasi (`CreateProcessW` dengan argumen tetap) atau pengenal aplikasi terpaket Windows (`AppUserModelID` melalui `IApplicationActivationManager`) tanpa melibatkan `cmd.exe`/`powershell.exe`.
- **Kontrol Audio & Perangkat Dinamis (`AudioDevicePort`):** Mengatur volume melalui Windows Core Audio API dengan verifikasi readback; mendengarkan notifikasi perubahan perangkat (`IMMNotificationClient`) untuk menangani pencabutan headphone/mikrofon tanpa menjatuhkan proses suara; memeriksa voice pack lokal/OS yang benar-benar terpasang sebelum mengaktifkan fallback TTS sistem.
- **Keamanan Operasi File:** Pencarian dan pembukaan file dibatasi pada `source_root` yang disetujui. Mutasi sederhana seperti `file.rename` (`R2`) memvalidasi handle berkas (`GetFinalPathNameByHandleW`), menolak symlink/junction keluar cakupan, melarang penimpaan file yang sudah ada, dan tidak mendukung penghapusan permanen.
- **UI Automation:** Hanya membaca atau memicu kontrol semantik pada jendela yang diizinkan pengguna secara eksplisit; menolak jendela berhak administrator (UAC), layar kunci, atau kolom kata sandi tanpa melakukan klik koordinat buta atau injeksi ketikan bebas.

## 2. Screen awareness & on-demand camera (`R2` / `R3`)
- **Tangkapan Jendela Terbatas (`R2`):** Menggunakan API tangkapan jendela OS atas permintaan eksplisit per aksi/sesi disertai indikator visual. Mengutamakan pembacaan pohon aksesibilitas (UIA), diikuti OCR lokal (setelah memverifikasi paket bahasa OCR tersedia), dan melakukan pemindaian penyamaran pola rahasia/token (`FR-SCR-04`) sebelum teks dikirim ke model. Frame mentah hanya berada di memori sementara.
- **Kamera On-Demand (`R3`):** Mengambil snapshot hanya setelah persetujuan sesi dengan indikator aktif; langsung menutup perangkat saat dibatalkan, sesi terkunci, atau *suspend*. Tanpa pengenalan wajah maupun pemantauan latar belakang.

## 3. Pluggable web search & anti-SSRF fetch connector (`DEC-011`, `R2`)
Arsitektur konektor web menggunakan `WebSearchProviderPort` yang mendukung: (a) instance pencarian lokal/LAN milik pengguna (mis. `SearXNG`), (b) provider API berkuota gratis/opsional dengan kunci milik pengguna di OS Vault, dan (c) fallback aman pembukaan pencarian di peramban pengguna atau pelaporan ketidaktersediaan tanpa *scraping* liar. Pengambilan halaman berjalan melalui klien HTTP(S) read-only khusus yang memeriksa seluruh IP hasil resolusi DNS dan setiap redirect terhadap daftar blokir alamat privat/loopback/link-local, membatasi ukuran (`2 MiB`) serta waktu (`10s`), membuang skrip aktif, dan menandai usia cache (`TTL 15m` default).

## 4. Personal read-only connectors (`R2`)
Penyimpanan tugas, kalender, pengeluaran, dan kebiasaan bekerja secara lokal penuh terlebih dahulu. Sinkronisasi kalender/email eksternal bersifat opsional dengan alur OAuth *Authorization Code + PKCE* pada peramban sistem, cakupan *read-only* minimal, penyimpanan token di OS Credential Vault, penghormatan batas *rate limit*, serta pencabutan instan yang menghapus cache terkait.

## 5. Home Assistant (`R3`) & Private LAN Inference (`R2`)
- **Home Assistant (`R3`):** Berkomunikasi melalui REST/WebSocket di jaringan privat/TLS menggunakan akun/token khusus berhak terbatas. Hanya entitas aman dalam allowlist (seperti lampu, media, atau colokan non-kritis yang diverifikasi) yang dapat diakses; kunci pintu, alarm, pemanas, dan perangkat keselamatan diblokir di Policy Engine (`R3`). Tidak pernah melakukan *retry* buta jenis *toggle*; selalu mengirim target state eksplisit dan memverifikasi readback.
- **Authorized Private-LAN Inference (`R2`):** Adapter provider terpisah dari gateway mobile. Memerlukan pendaftaran host eksplisit, verifikasi identitas TLS, kredensial di OS Vault, persetujuan cakupan data per jenis input, dan pengungkapan bahwa kebijakan retensi di sisi server LAN berada di bawah kendali pengelola server tersebut.

## 6. Scoped remote mobile gateway (`R3`)
Dijalankan sebagai pendengar terpisah yang nonaktif secara default, hanya diikat pada antarmuka VPN/jaringan privat terautentikasi dengan TLS (tanpa UPnP atau pembukaan port publik otomatis). Pemasangan perangkat memerlukan konfirmasi tantangan pendek pada layar desktop lokal, mengeluarkan token berbatas waktu dan laju (`~30 req/menit`) yang dapat dicabut seketika, serta membatasi kemampuan hanya pada status, percakapan berizin, dan pengingat — tanpa akses ke layar, kamera, file, pengaturan keamanan, maupun persetujuan `R2`.

## 7. Trusted extension & integration reliability contract (`DEC-024`)
Setiap adapter internal maupun paket ekstensi tepercaya mendeklarasikan versi SDK, kapabilitas yang diminta, kelas risiko, batas waktu, sifat idempotensi, metode verifikasi, dan pemeriksaan kesehatan. Ekstensi tidak pernah boleh mengakses database inti secara langsung, melewati Policy Engine, atau mematikan pencatatan audit.
