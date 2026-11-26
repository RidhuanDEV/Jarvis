# UX/UI Specification, Onboarding & Adaptive Visual Rendering Design

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Product experience & filosofi antarmuka
JARVIS dirancang sebagai antarmuka *tray-first* dengan *Contextual Compact HUD* dan *Desktop Command Center* penuh beridentitas orisinal **Orbital Precision OS**. Seluruh indikator visual merepresentasikan state mesin dan telemetri sistem aktual tanpa angka atau persentase palsu, tanpa menyalin aset film, serta mendukung penuh aksesibilitas keyboard, pembaca layar, dan *Reduced Motion*. Prinsip ***convention over configuration, with full overrides*** diwujudkan melalui tombol ekspres *Recommended Setup* yang berdampingan dengan pengaturan detail bagi pengguna mahir.

## 2. Information architecture (`13 Screens / Surfaces`)
| Permukaan / Layar | Isi & aksi utama |
|---|---|
| First-Run Onboarding (10 langkah) | Deteksi perangkat keras, pemilihan *Recommended Setup* atau kustomisasi lokasi penyimpanan, runtime, model, anggaran resource, audio/suara, bahasa/persona, visual, izin awal, dan cek kesiapan |
| System Tray | *Mute/Unmute*, *Stop* aktif, mode *Offline*, jeda aturan proaktif, buka HUD/Command Center, ganti profil cepat, keluar |
| Compact Floating HUD | *Intelligence Core* ringkas, indikator mic/offline, transkrip streaming, input teks cadangan, tombol *Stop* |
| Command Center (Home) | *Interactive Intelligence Core* utama, waveform suara nyata, kartu transkrip/aksi/persetujuan, pengingat terdekat, telemetri aktual |
| Session & Conversation | Riwayat sesi aktif (sesuai TTL), sitasi sumber yang dapat diperluas, status tiap langkah eksekusi |
| Memory Vault | Daftar & pencarian fakta eksplisit, provenance, proposal tertunda, sunting/hapus/ekspor, pengaturan retensi |
| Knowledge (`R2`) | *Source roots* terizinkan, antrean indeks, lokator halaman/bagian, pencabutan folder |
| Personal Life (`R2`) | Task, kalender lokal, rekap pengeluaran multi-mata uang, catatan kebiasaan |
| Automation Workflows (`R2`) | Penyusun workflow bertipe (`≤ 5` langkah), *dry-run*, riwayat eksekusi, rekonsiliasi `unknown` |
| Runtime & Model Manager | 4 mode kepemilikan runtime, manifest model, impor model lokal/*shared dir*, parameter GPU/CPU/context/idle, benchmark berizin |
| Storage Manager | 11 lokasi penyimpanan independen, pemantauan kapasitas drive, kuota cache (`10/25/50 GB/Custom/Unlimited`), migrasi antar-drive (`R2`), backup & restore |
| Personalization & Visuals | Bahasa utama/multibahasa, zona waktu IANA, suara/kecepatan/wake phrase, gaya persona/verbositas, *quiet hours*, kualitas visual & target FPS |
| Permissions, Audit & Licenses | Matriks izin `R0`–`R3` per aplikasi/folder/tool/jaringan, jejak audit teredaksi, inventaris lisensi & ekspor SBOM/`NOTICE` |

## 3. Guided 10-step First-Run Onboarding (`DEC-018`, `FR-ADM-07`)
Agar dapat diinstal oleh pengguna mana pun tanpa mengubah kode sumber:
1. **System Capability Discovery:** Menampilkan hasil deteksi CPU, RAM, GPU/VRAM/driver, drive lokal, perangkat audio, resolusi/refresh rate layar, serta status baterai beserta lencana *Recommended Setup* satu klik.
2. **Storage Location Selection:** Menampilkan direktori standar OS dan memungkinkan pengguna memilih drive/folder khusus untuk model, database, cache, dan backup dengan pemeriksaan ruang bebas langsung.
3. **AI Runtime Selection:** Memilih antara *JARVIS-Managed Local Runtime*, *Existing Local Runtime* (mis. mendeteksi Ollama/llama.cpp yang sudah berjalan), *Authorized LAN* (`R2`), atau *Direct Mode Only* (tanpa LLM).
4. **Recommended AI Model Selection:** Menampilkan kandidat model yang sesuai kapasitas memori perangkat beserta ukuran unduhan, ruang disk yang dibutuhkan, status kompatibilitas (`Supported`/`Experimental`/`Unverified`), lisensi, atau opsi impor file model lokal yang sudah dimiliki.
5. **Resource Budget Configuration:** Menetapkan batas maksimum RAM/VRAM/CPU threads, kebijakan *idle unload*, perilaku saat menggunakan baterai, dan pengurangan beban saat bermain game.
6. **Audio Device & Voice Setup:** Memilih mikrofon dan perangkat keluaran, memeriksa voice pack lokal/OS yang benar-benar terpasang, serta menjalankan uji rekam/putar singkat (PTT vs wake word).
7. **Language & Persona Configuration:** Memilih bahasa utama (default Bahasa Indonesia, siap diubah), perilaku multibahasa, zona waktu IANA (terdeteksi otomatis + dapat diubah), gaya bahasa, verbositas, dan *quiet hours*.
8. **Visual Quality & Frame-Rate Selection:** Memilih tier `Cinematic`, `Balanced`, `Lite`, atau `Reduced Motion` serta batas FPS (`Auto`, `30`, `60`, `120`, `Native`).
9. **Permission Configuration:** Seluruh izin sensitif dan jaringan nonaktif secara default; pengguna mencentang aplikasi/folder awal yang ingin diizinkan.
10. **Validation & Readiness Check:** Menjalankan uji kesiapan offline dan langsung masuk ke Command Center (bahkan bila pengguna memilih menunda unduhan model).

## 4. Art direction, token semantik & alur persetujuan `R2`
- **Palet & Tipografi:** Latar permukaan berlapis gelap (`#080D17` / `#101927`), aksen fokus tunggal `#57DFFF` khusus pada elemen aktif utama, amber `#FFBE69` untuk persetujuan `R2` dan status `unknown`, merah `#FF737C` untuk kegagalan nyata, teks `#E6F1FF` dan `#A9B9CC` yang memenuhi rasio kontras WCAG 2.2 AA (`≥ 4.5:1` teks, `≥ 3:1` kontrol UI). Angka telemetri dan waktu memakai *tabular monospace* agar tata letak tidak bergeser. Hindari *glassmorphism* berlebihan (`maks 1–2` permukaan), kartu statistik fiktif, atau titik berkedip tanpa arti.
- **Kartu Persetujuan `R2` (`<dialog>` Native):** Memerangkap fokus keyboard, menempatkan fokus awal pada tombol aman (*Tolak / Periksa*), menampilkan perubahan tepat sebelum→sesudah, label risiko, hitung mundur kedaluwarsa `60s`, serta menolak persetujuan lewat suara.

## 5. Koreografi 12 state & Adaptive Visual Rendering Engine (`DEC-010`, `FR-UX-04`)
State mesin (`Startup`, `Idle`, `Listening`, `Transcribing`, `Thinking/Loading`, `Executing`, `Approval`, `Speaking`, `Success`, `Error/Degraded`, `Muted/Locked`, `Offline`) direduksi secara deterministik menggunakan pasangan `(request_id, seq)` sehingga event terlambat dari permintaan yang sudah dibatalkan langsung dibuang. Lencana privasi mikrofon, kamera, jaringan, dan lokasi eksekusi model selalu ditampilkan sebagai teks/ikon eksplisit, tidak pernah hanya dari warna cincin.

| Pengaturan visual | Perilaku rendering |
|---|---|
| Kualitas Visual | `Cinematic` (geometri penuh, partikel halus, transisi terkoordinasi), `Balanced` (default; SVG core + transisi halus), `Lite` (geometri statis + pembaruan indikator frekuensi rendah, tanpa blur/partikel), `Reduced Motion` (mengikuti preferensi aksesibilitas OS/manual; transisi opasitas singkat tanpa gerak orbital berkelanjutan) |
| Target Frame Rate (`FPS Limit`) | `Auto` (menyesuaikan refresh rate layar yang terdeteksi, sumber daya listrik/baterai, dan beban inferensi aktif), `30`, `60`, `120`, atau `Native` — tidak mengunci produk secara permanen pada 60 FPS |
| Akselerasi GPU & Telemetri | Akselerasi hardware WebView2 tetap aktif secara default sesuai panduan platform; penempatan GPU aktual dan waktu frame (`p50`/`p95`, *dropped frames*) diverifikasi melalui telemetri runtime, bukan diasumsikan selalu berjalan pada satu vendor iGPU tertentu |
| Evolusi Teknologi Render | Implementasi awal menggunakan SVG, `Motion`, dan Canvas 2D berbatas DPR; evaluasi WebGL/Three.js tetap terbuka untuk tier lanjut apabila benchmark membuktikan peningkatan kualitas dalam batas anggaran resource |
| Penghematan Kontekstual | Menghentikan loop animasi kontinu saat jendela tersembunyi/diminimalkan, menurunkan kompleksitas dengan histeresis (`~15s`) saat tekanan CPU/GPU terdeteksi, serta menghormati mode hemat baterai dan mode gaming |

## 6. Aksesibilitas, responsivitas & gerbang kualitas UX
Seluruh layar (termasuk onboarding 10 langkah, Storage Manager, Runtime/Model Manager, dan dialog `R2`) dapat dioperasikan penuh hanya dengan keyboard, memiliki indikator `:focus-visible` kontras tinggi (`≥ 3:1`), kursor interaktif yang jelas, pengumuman `aria-live` untuk perubahan state penting, serta diuji pada resolusi `1024×768` hingga `1920×1080+`, skala DPI `100%–200%`, konfigurasi multi-monitor, dan klien mobile `360px` (`R3`).
