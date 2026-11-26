# Risk, Licensing Governance & Change Control Plan

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Normalized RAID Risk Register (`RK01` – `RK22`)
Skor risiko dihitung dari Kemungkinan (`L`, 1–5) × Dampak (`I`, 1–5): `≥ 15` Tinggi, `8–14` Sedang, `≤ 7` Rendah. Seluruh risiko dievaluasi ulang setiap akhir iterasi dan pada gerbang rilis.

| ID | Risiko | L/I | Skor | Mitigasi & rencana kontingensi | Pemilik |
|---|---|---|---|---|---|
| RK01 | Memori GPU terbatas (mis. 4 GB VRAM) atau terpakai aplikasi lain sehingga memicu OOM/lambat | 4/4 | 16 | Pemeriksaan VRAM bebas aktual sebelum muat, kuantisasi KV cache bila didukung, degradasi ke model kecil/CPU/*Direct Mode* | Architect |
| RK02 | Kualitas STT Bahasa Indonesia/campuran atau akurasi wake word kurang memadai di ruang bising | 4/3 | 12 | Benchmark korpus `R0`, normalizer deterministik, proteksi pantulan speaker, fallback PTT & teks selalu siap | AI Engineer |
| RK03 | Indirect prompt injection dari dokumen, halaman web, atau teks layar memicu aksi tool | 4/5 | 20 | Isolasi konteks data, `tools=[]` saat sintesis RAG, validasi skema ketat, Policy Engine `R0`–`R3` + approval `R2` | Security |
| RK04 | Aksi tanpa izin oleh tamu di dekat mikrofon atau sesi remote yang disalahgunakan | 3/5 | 15 | Wake bukan identitas, sesi terkunci/*suspend* mematikan capture, `R2` wajib di UI lokal, cakupan remote sempit | Security |
| RK05 | Kehilangan data saat crash atau bangkitnya kembali memori yang telah dihapus saat *restore* | 3/5 | 15 | Snapshot konsisten Online Backup API + enkripsi `Argon2id/AES-GCM`, pemutaran wajib `deletion_ledger`, latihan *restore* | Operator |
| RK06 | Host desktop tidur/mati sehingga pengingat waktu-nyata dan akses remote tidak tersedia | 4/3 | 12 | Kebijakan rekonsiliasi *missed reminder* saat bangun dan indikator ketidaktersediaan yang jujur (tanpa klaim *always-on*) | Product |
| RK07 | Pelanggaran kewajiban lisensi kode (`GPL`/`AGPL`/`LGPL`) atau *model card*/dataset suara & wake word | 3/4 | 12 | Inventaris lisensi 11 kategori (`FR-SYS-05`), blokir lisensi `Unknown`, pembuatan SBOM/`NOTICE`, tinjauan pra-publikasi (`DEC-022`) | Architect |
| RK08 | Ketidaktersediaan atau batas kuota penyedia pencarian web gratis pada `R2` | 4/3 | 12 | Kontrak `WebSearchProviderPort` pluggable (lokal/LAN/API opsional) + fallback buka peramban pengguna | Product |
| RK09 | Aplikasi pihak ketiga memblokir UI Automation atau tangkapan jendela | 3/3 | 9 | Dukungan peluncuran `AUMID`, penolakan aman pada jendela terproteksi dengan panduan operasi manual | Engineer |
| RK10 | Kebocoran rahasia/memori sensitif melalui log, teks OCR layar, atau partisi disk tanpa enkripsi | 3/5 | 15 | Redaksi terpusat di log & pra-OCR (`FR-SCR-04`), brankas OS Vault, enkripsi kolom sensitif `AES-256-GCM` | Security |
| RK11 | Pembengkakan cakupan ke arah coding agent, shell bebas, atau ketergantungan cloud | 3/3 | 9 | Larangan keras `R3`, pemeriksa skema tool di CI, dan prosedur Change Request formal | Product |
| RK12 | Token integrasi OAuth atau Home Assistant memiliki hak akses berlebihan | 3/5 | 15 | Cakupan read-only minimal, akun khusus terbatas di HA, pemblokiran domain keselamatan, pencabutan instan | Security |
| RK13 | Risiko merek dagang / HKI atas nama kerja `"JARVIS"` atau kemiripan visual film saat rilis publik | 3/3 | 9 | Aset visual & suara 100% orisinal sejak awal; audit nama/merek dagang terpisah sebelum distribusi publik | Product |
| RK14 | Ruang penyimpanan penuh atau pencabutan drive eksternal tempat model/indeks berada | 4/4 | 16 | *Dynamic 11-Root Storage Manager*, pemeriksaan ruang pra-operasi, kuota cache aman (`BR-SYS-02`), degradasi ke *Direct Mode* | Operator |
| RK15 | Ketidakcocokan perilaku output terstruktur atau mode *thinking* antar-runtime AI | 4/4 | 16 | Kontrak kapabilitas terversi, normalisasi kontrol *non-thinking*, dan suite uji konformansi provider | AI Engineer |
| RK16 | Proses worker terkelola tertinggal pasca-crash atau JARVIS tidak sengaja mematikan runtime milik pengguna | 3/4 | 12 | Pemisahan tegas `managed_local` (diawasi *Job Object*) vs `external_local` (dilarang dihentikan sepihak) + uji fault-injection | Engineer |
| RK17 | Kebocoran prompt atau *man-in-the-middle* pada server inferensi *private LAN* (`R2`) | 3/4 | 12 | Pendaftaran eksplisit, verifikasi TLS, persetujuan per cakupan data, dan larangan fallback lintas zona kepercayaan | Security |
| RK18 | Animasi UI menguras CPU/GPU pada monitor *high-refresh-rate* atau mengganggu inferensi AI/game | 3/3 | 9 | *Adaptive Visual Rendering Engine* (`Auto/30/60/120/Native` FPS), suspensi saat tersembunyi, penurunan otomatis saat beban tinggi | Engineer |
| RK19 | Event asinkron terlambat menghidupkan ulang state giliran yang dibatalkan atau membingungkan pengguna | 3/4 | 12 | Reduksi state berbasis nomor urut `(request_id, seq)`, teks status eksplisit, dan dialog `<dialog>` khusus dari Core | Engineer |
| RK20 | Kegagalan resolusi wheel native Python/C++ atau ketidaksesuaian asumsi paket bahasa OS di komputer pengguna | 4/3 | 12 | Pinning baseline dev (`uv` + `Python 3.11.9`), uji resolusi nyata pada `R0`, dan pemeriksaan voice/OCR pack aktual saat runtime | Architect |
| RK21 | Ketidakselarasan status antara `jarvis_core.db` dan `jarvis_knowledge.db` akibat crash lintas-berkas | 3/4 | 12 | `core.db` sebagai satu-satunya sumber otoritas izin/hapus; filter wajib `root_id` pada setiap kueri + rekonsiliasi startup | Architect |
| RK22 | Kebocoran jalur lokal pengembang atau asumsi satu perangkat keras ke dalam kode produk | 3/3 | 9 | Pemisahan konfigurasi `.local` di `.gitignore`, abstraksi 9 port platform, dan pemeriksa otomatis di CI (`NFR-16`) | Engineer |

## 2. Change control & quality gates (`G0` – `G5`)
Setiap perubahan terhadap cakupan, kontrak antarmuka, kebijakan izin, skema database, ambang metrik, atau kebijakan lisensi wajib melalui **Change Request (CR)** yang memperbarui `02-SRS.md`, dokumen desain terkait, dan `17-TRACEABILITY-MATRIX.md` secara bersamaan serta menjalankan ulang `scripts/build_sdlc_complete.py`.
- **`G0` (Baseline & Revision Approval):** Persetujuan arah arsitektur `v0.2.1` (`DEC-001`–`DEC-025`) dan rencana `R0`.
- **`G1` (`R0` Feasibility Evidence):** Bukti empiris kompatibilitas dependensi, benchmark suara/model/render, dan tinjauan lisensi awal disetujui pemilik.
- **`G2` (Architecture & Threat Gate):** Kontrak skema, migrasi, dan kontrol keamanan STRIDE terkunci per fase rilis.
- **`G3` (Implementation & Automated CI Gate):** Seluruh tes otomatis Tier A lulus 100% tanpa pelanggaran batas keamanan/portabilitas.
- **`G4` (Release Hardware, Restore & UAT Gate):** Pengujian Tier B yang diizinkan pemilik, latihan pemulihan backup lintas-profil, dan skenario UAT fase terkait lulus tanpa cacat `S0`/`S1`.
- **`G5` (Handover & Pre-Publication Gate):** Paket installer terverifikasi, SBOM/`NOTICE` lengkap, runbook operasional, serta (bila akan dipublikasikan secara terbuka) keputusan akhir lisensi repositori dan peninjauan merek dagang selesai.
