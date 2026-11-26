# Deployment, Provisioning, Storage Operations & Runbook

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Arsitektur paket instalasi portabel (`DEC-018`)
- **Minimal Base Installer:** Paket instalasi per-pengguna (Windows x64 sebagai target produksi pertama, tanpa membutuhkan hak administrator, Docker, atau layanan cloud) hanya memuat shell desktop, broker native, Core runtime, skema migrasi, dan tool deterministik. Aplikasi langsung dapat berjalan offline dalam *Direct Mode* segera setelah dipasang tanpa mewajibkan unduhan multi-GB.
- **Optional Component & Model Provisioning:** Runtime inferensi terkelola, bobot model AI, voice pack, dan model embedding disediakan sebagai komponen opsional yang dipilih pengguna saat onboarding atau melalui *Runtime/Model Manager*, dilengkapi dukungan *offline import* dan pemanfaatan *shared model directory* dari instalasi lokal yang sudah ada.
- **Pemisahan Direktori Bersih:** Biner aplikasi dipasang terpisah dari 11 kategori direktori data/storage pengguna (`07-DATA-DESIGN.md`). Konfigurasi lokal pengembang (`.local`) tidak pernah dibundel ke dalam installer produk.

## 2. Alur CI/CD, manajemen rilis & kepatuhan lisensi (`DEC-022`, `DEC-025`)
Alur CI otomatis (Tier A): pemeriksaan format/lint/ketat tipe → pemeriksa isolasi platform & ketiadaan jalur pribadi (`NFR-16`) → verifikasi sinkronisasi `Complete.md` (`scripts/build_sdlc_complete.py --check`) → unit/contract/DB/security suites → pemindaian rahasia & kerentanan dependensi → validasi inventaris lisensi 11 kategori & pembuatan otomatis berkas CycloneDX **SBOM** serta **`THIRD-PARTY-NOTICES`** → pembuatan artefak bertanda tangan/ber-checksum. Pengujian perangkat keras nyata (Tier B) dan UAT dijalankan terpisah dengan persetujuan eksplisit sebelum tag rilis SemVer diterbitkan.

## 3. Urutan instalasi, pembaruan komponen & rollback independen (`DEC-025`)
1. **Instalasi Awal:** Verifikasi integritas installer → pasang biner aplikasi → jalankan *First-Run Onboarding* 10 langkah (deteksi perangkat keras, pemilihan lokasi storage dengan validasi filesystem lokal & ruang bebas, konfigurasi runtime/model/audio/bahasa/visual/izin) → jalankan *readiness smoke check* offline.
2. **Pembaruan Aplikasi & Komponen:** Pembaruan tidak pernah dijalankan diam-diam dari internet tanpa persetujuan pengguna. Sebelum memperbarui aplikasi atau migrasi skema `jarvis_core.db`, sistem menghentikan permintaan aktif, membuat backup terenkripsi pra-migrasi, memverifikasi tanda tangan/hash paket baru, dan menjalankan migrasi.
3. **Tiga Lapis Rollback Independen:** (a) *Configuration/Profile Rollback* mengembalikan `config_revision` atau `active_ai_profile` ke revisi sehat sebelumnya dalam hitungan detik; (b) *Runtime/Model Rollback* mengalihkan kembali ke manifest/runtime sebelumnya atau *Direct Mode* bila komponen baru gagal *probe*; (c) *Application & Schema Rollback* memulihkan versi aplikasi sebelumnya beserta snapshot pra-migrasi yang kompatibel dan memutar ulang `deletion_ledger`. Saat *uninstall*, data pengguna tidak dihapus paksa tanpa pilihan eksplisit pengguna.

## 4. Observabilitas lokal teredaksi
Log terstruktur berputar otomatis (*rotating JSON logs*, kandidat batas default `30` hari / `100 MiB` pada lokasi `logs` pilihan pengguna) mencatat `correlation_id`, komponen, jenis event, durasi, perubahan tier dukungan/visual, metrik penempatan GPU/RAM/VRAM aktual, dan kode galat tanpa pernah menulis prompt mentah, transkrip pribadi, audio, atau kredensial. Panel diagnostik menampilkan status per komponen (`READY`, `DEGRADED`, `DIRECT_ONLY`, `OFFLINE`, `PAUSED`, `FAILED`) secara jujur tanpa mengunggah telemetri ke luar.

## 5. Runbook insiden operasional
| Gejala | Diagnosis awal | Pemulihan aman | Verifikasi |
|---|---|---|---|
| Wake palsu / pantulan suara TTS | Sensitivitas mic atau keluaran speaker terbuka | Aktifkan *Mute* / mode PTT, periksa profil proteksi echo `AudioDevicePort`, sesuaikan ambang | Uji pemutaran TTS tanpa pemicu wake berulang |
| Model lambat atau gagal dimuat (OOM) | Memori VRAM/RAM bebas terkuras aplikasi lain atau konteks terlalu besar | *Auto-rollback* ke model lebih ringan/CPU atau *Direct Mode*; sesuaikan anggaran di Runtime Manager | Perintah langsung & diagnostik memori sehat |
| Runtime eksternal (`Ollama`) terputus | Layanan milik pengguna dihentikan di luar JARVIS | Tandai `external_local` sebagai `UNAVAILABLE` tanpa mencoba membunuh/mengubahnya; alihkan ke fallback berizin atau *Direct Mode* | Status provider akurat; data domain aman |
| Drive eksternal model/knowledge terlepas | Volume pada `storage_location` berstatus *offline/missing* | Tangguhkan model/indeks pada drive tersebut dan masuk ke *Direct Mode* tanpa merusak `jarvis_core.db` | Sambungkan kembali drive atau ubah lokasi di Storage Manager |
| Ruang disk hampir habis / penuh | Pemeriksaan kuota pada volume aktif | Hentikan pengindeksan latar, bersihkan hanya cache sementara yang diizinkan (`BR-SYS-02`); jangan pernah menghapus data pengguna secara diam-diam | Periksa ruang bebas dan keutuhan `PRAGMA integrity_check` |
| Migrasi penyimpanan terputus di tengah jalan | Status transaksi migrasi belum mencapai komit pointer | Batalkan otomatis, hapus folder `.staging` parsial, dan lanjutkan dari lokasi asal yang masih utuh | Cek checksum & jalankan kueri baca/tulis normal |
| Korupsi berkas database | Kegagalan media penyimpanan pada `integrity_check` | Untuk `knowledge.db`: bangun ulang indeks dari dokumen sumber; untuk `core.db`: simpan salinan rusak untuk inspeksi dan pulihkan snapshot backup terenkripsi + *deletion ledger* | Uji integritas skema & smoke suite `R1` |
| Perangkat mobile terpasangkan hilang (`R3`) | Daftar perangkat di pengaturan keamanan | Cabut token perangkat seketika dan tinjau jejak audit sesi remote terkait | Permintaan dengan token lama ditolak (`401`/`403`) |
