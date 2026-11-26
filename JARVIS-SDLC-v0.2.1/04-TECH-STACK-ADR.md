# Technology Stack, Open-Source Licensing & Architecture Decision Records

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline (`DEC-001`–`DEC-025`), versi paket dikunci setelah `R0`  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Candidate stack & pemisahan toolchain vs fleksibilitas produk
Prinsip pemilihan teknologi membedakan secara tegas:
1. **Development Toolchain yang Konsisten & Reproducible:** Pengembang menggunakan versi runtime, package manager, dan lockfile yang ditetapkan (`npm` + `package-lock.json`, `uv` + `Python 3.11.9` baseline awal, `Cargo.lock`) agar build deterministik.
2. **Product Runtime yang Adaptif & Interchangeable:** Pengguna akhir bebas memilih atau mengganti model AI, runtime inferensi, akselerator (`CPU`, `CUDA`, `Vulkan`, dan backend kompatibel lain sesuai dukungan), voice engine, serta lokasi penyimpanan tanpa mengubah kode sumber.

| Layer | Baseline kandidat pengembangan | Alternatif / fleksibilitas pengguna & syarat validasi R0 |
|---|---|---|
| Desktop shell | Tauri 2 + React + TypeScript + Vite + Tailwind CSS | Scaffold resmi; akselerasi hardware WebView2 tetap aktif secara default dan diverifikasi via telemetri |
| Core backend | Python `3.11.9` baseline awal dikelola `uv` + FastAPI + Pydantic v2 + Uvicorn | Dukungan versi Python lain ditambahkan hanya setelah uji resolusi wheel dan regresi lulus |
| Native broker & supervisor | Rust (`tauri`, abstraksi `LocalIpcTransportPort` & `ProcessSupervisorPort`) | Implementasi awal *Windows Named Pipe* + *Windows Job Object*; fallback loopback untuk harness uji |
| LLM runtime adapters | Adapter referensi awal: `llama.cpp` (`llama-server`) dan `Ollama` | Pengguna produksi cukup memasang satu runtime pilihan, memakai runtime lokal/LAN yang sudah ada, atau *Direct Mode* tanpa LLM; mendukung CPU, CUDA, Vulkan sesuai kemampuan runtime |
| Visual & motion | Motion (`motion/react`) + SVG + CSS, opsional Canvas 2D | *Adaptive Visual Rendering Engine* (`Auto/30/60/120/Native` FPS); WebGL/Three.js dapat dievaluasi bila terbukti memberi nilai tambah dalam batas anggaran resource |
| Wake word & VAD | Kandidat evaluasi R0: `openWakeWord` dan `sherpa-onnx` + Silero VAD | Pilih berdasarkan akurasi, latensi, dukungan kustomisasi frasa, dan kepatuhan lisensi; PTT selalu tersedia |
| STT | Kandidat evaluasi R0: `faster-whisper` (`tiny`/`base`/`small` CPU `int8` atau GPU bila dikonfigurasi) & alternatif ONNX | Pilih berdasarkan benchmark WER Bahasa Indonesia/multibahasa dan anggaran resource perangkat |
| TTS | Kandidat evaluasi R0: `Piper` (`piper1-gpl` / `sherpa-onnx` VITS) & fallback suara offline OS (WinRT/SAPI bila terpasang) | Wajib memeriksa ketersediaan voice pack aktual pada OS dan meninjau lisensi engine maupun *model card* suara secara terpisah |
| Storage & RAG | Dual SQLite WAL (`jarvis_core.db` + `jarvis_knowledge.db`), FTS5, kandidat `sqlite-vec` | Enkripsi field sensitif (`DPAPI`/`SecretVault` + `AES-256-GCM`) & backup portabel (`Argon2id`); FTS5 tetap jalan tanpa vektor |
| Embeddings (`R2`) | Kandidat encoder multibahasa ringan (mis. `multilingual-e5-small` ONNX) | Dievaluasi terhadap baseline leksikal FTS5; mendukung isolasi generasi indeks (`FR-AIP-07`) |
| Document parsing (`R2`) | Kandidat evaluasi R0/R2: `PyMuPDF` (`AGPL-3.0`), `pypdfium2` (`Apache-2.0/BSD`), `pypdf`, `python-docx` | Dipilih berdasarkan akurasi ekstraksi, keamanan sandboxing, performa, dan kepatuhan kewajiban lisensi |
| OS, Screen & IoT | Adapter `DesktopAutomationPort` (Win32, `AUMID`, CoreAudio, UIA, WinRT Capture/OCR), Home Assistant (`R3`) | Tanpa shell arbitrer, tanpa hak admin; konektor eksternal *opt-in* |
| QA & Supply chain | `pytest`, `hypothesis`, `Vitest`, `Playwright`, generator CycloneDX SBOM & `NOTICE` | Pemisahan suite CI otomatis (Tier A) dan benchmark perangkat keras berizin pemilik (Tier B) |

## 2. Kebijakan lisensi open-source (*Best-Fit with License Compliance* — `DEC-001`, `DEC-022`)
JARVIS menolak kebijakan *permissive-only* yang kaku dan menerapkan evaluasi teknis terbaik disertai kepatuhan hukum lisensi secara transparan:

| Kategori lisensi | Kebijakan pada JARVIS | Kewajiban yang wajib dipenuhi |
|---|---|---|
| `MIT`, `Apache-2.0`, `BSD` | Diizinkan | Sertakan teks hak cipta, lisensi, dan `NOTICE` |
| `MPL-2.0`, `LGPL` | Diizinkan dengan tinjauan kepatuhan | Patuhi batas berkas/penautan dinamis dan penyediaan sumber untuk berkas yang dimodifikasi |
| `GPL` (`v2`/`v3`), `AGPL` (`v3`) | Diizinkan sesuai kewajiban distribusi & penggunaan jaringan | Jangan berasumsi isolasi proses atau unduhan opsional otomatis menghapus kewajiban *copyleft*; selaraskan dengan lisensi distribusi akhir proyek sebelum rilis publik |
| `Non-Commercial` (mis. `CC-BY-NC-SA`) | Opsional sesuai tujuan penggunaan | Boleh untuk penggunaan pribadi non-komersial dengan atribusi; dilarang untuk bundel komersial tanpa lisensi terpisah/pengganti |
| `Proprietary SDK` | Opsional bila diperlukan & diizinkan lisensinya | Hanya jika syarat redistribusi/penggunaan mengizinkan dan tidak mengunci arsitektur inti |
| `Unknown` / Tanpa lisensi jelas | **Diblokir** | Tidak boleh digunakan atau diimpor sebelum status lisensinya terverifikasi |

Inventaris lisensi wajib mencakup **11 kategori artefak**: paket perangkat lunak, pustaka native, runtime AI, bobot model (*weights*), dataset pelatihan yang relevan pada rantai turunan, aset suara (*voice model cards*), model wake-word, font, ikon, efek suara, dan aset UI pihak ketiga. Pemilihan lisensi repositori JARVIS sendiri ditunda hingga arsitektur dependensi final ditetapkan sebelum publikasi repositori.

## 3. Architecture Decision Records (`ADR-001` – `ADR-025`)
| ADR / DEC | Keputusan & rasional utama | Alternatif yang ditolak / ditunda | Konsekuensi & pemicu peninjauan ulang |
|---|---|---|---|
| ADR-001 (`DEC-001`) | Local-first, private-first, open-source-ready; tanpa API LLM berbayar wajib; kebijakan lisensi *best-fit with compliance* | Cloud-first LLM; kebijakan *permissive-only* kaku | Review lisensi akhir & merek dagang wajib sebelum rilis publik |
| ADR-002 | Modular monolith Core + isolated child workers | Microservices, Docker wajib, Redis/Kafka | Operasi lokal sederhana; pisahkan proses hanya untuk isolasi kegagalan/resource |
| ADR-003 (`DEC-023`) | Windows 11 sebagai platform produksi pertama dengan 9 port abstraksi platform di Core | Implementasi penuh Linux/macOS sejak hari pertama; ketergantungan Win32 langsung di domain | Fokus kualitas R1 terjaga sementara portabilitas lintas-OS tetap terbuka |
| ADR-004 | Deterministic-first intent routing sebelum inferensi LLM | Memanggil LLM untuk setiap perintah | Latensi dan keamanan lebih baik; butuh korpus regresi pola perintah |
| ADR-005 (`DEC-007`) | Dual SQLite WAL (`jarvis_core.db` otoritatif + `jarvis_knowledge.db` indeks turunan) di filesystem lokal + enkripsi field sensitif & backup portabel | Server DB eksternal; satu file DB tunggal untuk semua beban RAG; SQLite di atas SMB/NFS | Mengurangi kontensi tulis saat indexing; wajib menjaga invarian konsistensi lintas-DB (`03-SDD` §6) |
| ADR-006 | Registri *typed tools* + Policy Engine `R0`–`R3` + verifikasi readback | Eksekusi shell/kode bebas atau agen otonom | Cakupan tindakan terkendali dan dapat diaudit |
| ADR-007 | Tata kelola resource dinamis (CPU/RAM/VRAM) berdasarkan telemetri aktual | Memuat semua model bersamaan di memori | Membutuhkan *Resource Governor*, antrean sewa, dan degradasi ke model kecil/CPU/Direct Mode |
| ADR-008 (`DEC-012`) | Memori jangka panjang eksplisit, riwayat sesi ber-TTL, izin *deny-by-default* | Menyimpan seluruh transkrip dan memberi izin default | Privasi kuat; dilengkapi alur onboarding 10 langkah yang mudah |
| ADR-009 (`DEC-008`) | Transport lokal terautentikasi (`Windows Named Pipe` + token 256-bit) & gateway remote terpisah (`R3`) di balik abstraksi transport | Port HTTP publik tanpa autentikasi; ekspos langsung Core ke jaringan | Permukaan serangan sempit; tetap sediakan mode loopback terautentikasi untuk pengujian |
| ADR-010 (`DEC-021`) | Manajemen model berbasis manifest terverifikasi (hash, lisensi, kapabilitas) & impor model lokal | Unduhan dan eksekusi kode model otomatis tanpa verifikasi | Aman dan mendukung direktori model bersama (*shared model dir*) |
| ADR-011 | Cakupan remote sempit (`R0`/`R1` terbatas) melalui jaringan privat/TLS; tanpa persetujuan `R2` jarak jauh | Kendali penuh desktop dari jarak jauh | Risiko kebocoran perangkat mobile terkendali |
| ADR-012 | Prioritas struktur UIA dan OCR lokal dengan redaksi rahasia sebelum vision model opsional | Perekaman layar/kamera latar belakang terus-menerus | Menjaga privasi kredensial dan efisiensi memori GPU/CPU |
| ADR-013 (`DEC-006`) | Abstraksi provider berbasis peran; `llama.cpp` dan `Ollama` sebagai adapter referensi awal, bukan instalasi ganda wajib | Mengunci produk pada satu model atau mewajibkan semua runtime dipasang | Pengguna cukup memasang komponen yang diperlukan |
| ADR-014 (`DEC-010`) | *Adaptive Visual Rendering Engine* (SVG + Motion + Canvas 2D awal; target FPS konfigurabel `Auto/30/60/120/Native`; WebGL terbuka pasca-benchmark) | Mengunci permanen pada satu GPU/60 FPS atau mewajibkan 3D berat di R1 | Halus di layar standar maupun tinggi, hemat daya saat idle/tersembunyi |
| ADR-015 | Aktivasi profil/model atomik dengan *drain/cancel* dan *rollback* otomatis, serta isolasi generasi indeks embedding | Pergantian model tanpa koordinasi request/vektor | Mencegah pencampuran vektor dan pengulangan efek tool saat gagal muat |
| ADR-016 (`DEC-016`) | *System Capability Discovery* & *Configuration Recommendation Engine* dengan label tier dukungan jujur | Konfigurasi statis khusus satu PC pengembang | Pengalaman *Recommended Setup* otomatis bagi pengguna umum + override manual penuh |
| ADR-017 (`DEC-017`) | Skema konfigurasi berversi dengan profil, ekspor/impor tanpa rahasia, dan riwayat *rollback* | Berkas konfigurasi tak berversi atau hardcode jalur lokal | Pembaruan aman dan pemisahan tegas antara profil mesin dev (`.local`) vs produk |
| ADR-018 (`DEC-018`) | Installer dasar minimal + provisi komponen/model opsional atas persetujuan pengguna & dukungan *offline import* | Installer monolitik multi-GB yang memaksa unduhan saat pertama dibuka | Ukuran awal ringan dan langsung berguna dalam *Direct Mode* |
| ADR-019 (`DEC-003`/`019`) | *Dynamic 11-Root Storage Manager* dengan pemantauan kuota, *shared model dir*, dan migrasi bertransaksi + *rollback* | Hardcode huruf drive (`C:`/`D:`) atau username Windows | Pengguna dapat memindahkan model/DB antar-drive langsung dari aplikasi |
| ADR-020 (`DEC-020`) | Empat mode kepemilikan runtime (`managed_local`, `external_local`, `authorized_lan`, `custom_compatible`) + pengawasan *Job Object* khusus proses terkelola | Mematikan paksa seluruh proses runtime lokal tanpa melihat kepemilikan | Menghormati layanan eksternal pengguna (seperti Ollama yang dipakai aplikasi lain) |
| ADR-021 (`DEC-004`/`005`) | Pinning toolchain pengembangan (`uv` + `Python 3.11.9` awal; `npm` + lockfile) terpisah dari fleksibilitas runtime pengguna | Membiarkan versi paket mengambang tanpa lockfile atau mengklaim kompatibilitas tanpa uji | Build pengembangan konsisten; dukungan versi baru dibuka melalui bukti pengujian |
| ADR-022 (`DEC-009`/`022`) | Evaluasi engine suara & parser dokumen berbasis kualitas, performa, keamanan, dan kepatuhan lisensi pada `R0` | Menolak pustaka bagus semata karena `GPL`/`AGPL` atau mengabaikan *model card* suara | Kualitas teknis optimal dengan jejak kepatuhan lisensi dan SBOM yang rapi |
| ADR-023 (`DEC-011`/`013`/`015`) | Konektor pencarian web pluggable, adaptasi endpoint audio/AEC dinamis, dan personalisasi bahasa/zona waktu/persona penuh | Hardcode satu API pencarian, satu mikrofon, Bahasa Indonesia saja, atau `WIB` | Siap digunakan lintas wilayah, perangkat audio, dan preferensi interaksi |
| ADR-024 (`DEC-024`) | SDK ekstensi/provider berversi melalui registri tepercaya yang tunduk penuh pada Policy Engine & Audit | Eksekusi skrip/plugin pihak ketiga tanpa batas keamanan | Ekstensibel bagi komunitas open source tanpa membuka celah *excessive agency* |
| ADR-025 (`DEC-002`/`014`/`025`) | Tata kelola Git lokal (tag `sdlc-v0.2.0` utuh, kanonik `v0.2.1` + generator `Complete.md`), gerbang persetujuan eksekusi `R0`, serta mekanisme update & *rollback* komponen | Menimpa dokumen awal tanpa jejak versi atau menginstal/mengunduh beban besar tanpa izin | Ketertelusuran penuh dan keamanan operasional pada mesin pengguna maupun pengembang |
