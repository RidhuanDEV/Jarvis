# Product Requirements Document (PRD)

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Product vision dan prinsip desain
Membangun sistem inteligensi personal yang tersedia saat komputer aktif, mampu mendengar, memahami konteks, mengingat informasi yang disetujui, bertindak melalui *typed tools* terbatas, memberi pengingat proaktif, serta beradaptasi terhadap perangkat keras dan preferensi setiap pengguna.

1. **Local-first & Privacy-first:** Tidak ada pengiriman prompt, audio, tangkapan layar, atau database ke layanan AI komersial eksternal secara default maupun sebagai fallback tersembunyi.
2. **Private-first, Open-source-ready:** Dirancang pertama-tama untuk keandalan penggunaan pribadi, namun dibangun secara portabel sehingga dapat diinstal oleh pengguna lain pada perangkat berbeda dan siap dipublikasikan sebagai proyek open source setelah audit lisensi dan merek dagang.
3. **Convention over Configuration, with Full Overrides:** Pengguna umum cukup memilih *Recommended Setup* berdasarkan hasil deteksi perangkat keras otomatis, sedangkan pengguna mahir memegang kendali penuh atas model, runtime, akselerator, lokasi penyimpanan, kuota resource, voice engine, bahasa, dan rendering visual.

## 2. Problem statements dan persona
| ID | Problem / job to be done | Hasil yang diharapkan |
|---|---|---|
| G01 | Pengguna berulang kali membuka aplikasi dan menjalankan operasi rutin | Selesaikan tindakan terdaftar melalui suara atau teks dengan verifikasi hasil dan konfirmasi sesuai risiko |
| G02 | Informasi pribadi tersebar di dokumen, catatan, dan jadwal | Temukan informasi lokal dengan provenance, sitasi akurat, dan kontrol penuh atas memori |
| G03 | Pengingat mudah terlewat saat bekerja atau perangkat sempat mati | Pengingat persisten lintas restart, menghormati *quiet hours*, dan melaporkan *missed reminders* secara jujur |
| G04 | Layanan AI cloud menambah biaya berulang dan risiko kebocoran privasi | Kapabilitas inti bekerja offline dengan biaya API Rp0 |
| G05 | Pengguna memiliki spesifikasi perangkat, storage, dan ekosistem berbeda | Instalasi adaptif tanpa mengubah kode sumber; integrasi lintas perangkat bersifat opt-in dan terverifikasi |

Persona utama: pemilik workstation pribadi (pengguna umum maupun pengguna teknis) dengan beragam konfigurasi perangkat keras (CPU-only laptop hingga workstation multi-GPU atau server LAN privat). Persona sekunder: pemilik yang sama mengakses dari perangkat mobile yang telah dipasangkan (`R3`). Tamu di dekat mikrofon diperlakukan sebagai aktor tidak terautentikasi.

## 3. Product scope dan release strategy
| Epic | Scope | Priority | Acceptance value |
|---|---|---|---|
| E01 Voice & interaction | Wake word opsional, push-to-talk, teks, STT/TTS lokal, barge-in adaptif, hotplug perangkat audio | P0 (`R1`) | Interaksi suara dan teks berjalan offline dengan fallback aman |
| E02 Core intelligence | Deterministic router, normalisasi locale dinamis, bounded planning, kontekstualisasi | P0 (`R1`) | Perintah pasti berjalan tanpa LLM; ambiguitas meminta klarifikasi |
| E03 OS actions | Launch aplikasi (`Win32`/`AUMID`), volume, pencarian & operasi file berbasis handle aman | P0 (`R1`) | Efek diverifikasi secara aktual, tanpa evaluasi shell arbitrer |
| E04 Memory | Preferensi & memori episodik eksplisit, edit/hapus/ekspor, pemisahan riwayat sesi | P0 (`R1`) | Pengguna mengendalikan penuh apa yang diingat dan dihapus |
| E05 Scheduling & proactive | Reminder IANA timezone dinamis, aturan proaktif opt-in, *quiet hours*, rekonsiliasi daya/jam | P0 (`R1`) | Reminder persisten melintasi restart dan perubahan daya |
| E06 Personal knowledge | Folder opt-in, TXT/MD/PDF/DOCX, sitasi terverifikasi, pencarian leksikal & semantik | P1 (`R2`) | Jawaban merujuk file serta halaman/bagian atau menyatakan bukti kurang |
| E07 Web intelligence | Pencarian/fetch read-only pluggable, tanggal sumber, proteksi SSRF, status offline jujur | P1 (`R2`) | Tidak menyamarkan cache/offline sebagai data langsung |
| E08 Screen awareness | Snapshot per permintaan, UI Automation, OCR lokal, redaksi rahasia, vision opsional | P1 (`R2`) | Tanpa perekaman latar belakang; kredensial tidak dikirim ke model |
| E09 Personal management | Tasks, kalender lokal, pencatatan pengeluaran integer multi-mata uang, habit, OAuth read-only opsional | P1 (`R2`) | CRUD akurat secara lokal tanpa eksekusi pembayaran atau keputusan medis |
| E10 Advanced automation | Workflow bertipe (`≤ 5` langkah), dry-run, persetujuan terikat parameter, pembatalan & rekonsiliasi | P1 (`R2`) | Efek samping tercatat dan tidak diulang secara buta pasca-gagal |
| E11 Environmental & IoT | Kamera on-demand, Home Assistant allowlist, verifikasi state dan pemblokiran aktuasi berbahaya | P2 (`R3`) | Indikator perangkat keras jelas; kunci/alarm/pemanas diblokir |
| E12 Remote & adaptive | Akses mobile terpasangkan via jaringan privat/TLS, proposal preferensi berbasis umpan balik lokal | P2 (`R3`) | Cakupan akses sempit per perangkat; tanpa perubahan kebijakan otomatis |
| E13 Flexible AI | Abstraksi provider/runtime, 4 mode kepemilikan runtime, 6 profil AI, manajemen model & switching aman | P0 (`R1` / perluasan `R2`) | Ganti model/runtime tanpa ubah core; pengguna hanya menginstal komponen yang dibutuhkan |
| E14 Cinematic experience | HUD & Command Center orisinal, Intelligence Core reaktif, Adaptive Visual Rendering Engine, 4 tier visual | P0 (`R1`) | UI sinematik berbasis state nyata, aksesibel, dan adaptif terhadap refresh rate & beban |
| E15 Hardware-adaptive portability & storage | System Capability Discovery, Configuration Recommendation Engine, 11-root Dynamic Storage Manager, 10-step onboarding, inventaris lisensi, abstraksi platform | P0 (`R1` fondasi / migrasi & ekstensi `R2`) | Instalasi portabel lintas spesifikasi hardware dan drive tanpa hardcode mesin pengembang |

**Out of scope (Hard Bans):** Coding/debugging/deployment agent, terminal tak terawasi, keylogger, perekaman tersembunyi, identifikasi wajah/biometrik suara latar, penghapusan file permanen, transaksi pembayaran online, pengiriman/penghapusan email otomatis, diagnosis/resep medis, fallback cloud LLM diam-diam, multi-tenant SaaS, modifikasi diri otonom, dan eksekusi plugin unduhan tak terverifikasi.

## 4. User journeys
- **J00 (Onboarding portabel):** Pengguna baru memasang installer minimal JARVIS → sistem memindai CPU/RAM/GPU/disk/audio/layar → merekomendasikan lokasi penyimpanan, profil AI (mis. CPU-only ringan atau GPU lokal), dan tier visual → pengguna menyetujui *Recommended Setup* atau memilih direktori/runtime yang sudah ada (mis. *Existing Ollama*) → menguji mikrofon/suara dan memilih aplikasi yang diizinkan → siap digunakan offline bahkan jika unduhan model ditunda (*Direct Mode*).
- **J01:** Pengguna mengucapkan perintah pembukaan aplikasi terdaftar dan pengaturan volume → wake/PTT → transkrip → dua *typed actions* → pemeriksaan policy → eksekusi & readback → laporan per langkah (termasuk status parsial bila salah satu aplikasi belum tersedia).
- **J02:** Pengguna membuat pengingat relatif terhadap waktu lokal → sistem meresolusi terhadap zona waktu IANA aktif pengguna → menampilkan waktu absolut → menyimpan secara persisten → menampilkan *missed reminder* bila perangkat sempat mati saat jatuh tempo.
- **J03:** Pengguna menanyakan, menyunting, atau menghapus memori preferensi → perubahan segera berlaku dan data terhapus dikeluarkan dari indeks aktif serta dicatat pada *deletion ledger*.
- **J04 (`R2`):** Pengguna meminta ringkasan dokumen pada folder yang diizinkan → retrieval leksikal/hibrida mengambil potongan relevan → jawaban mencantumkan nama file dan halaman/bagian yang valid atau menyatakan bukti tidak cukup.
- **J05 (`R2`):** Pengguna meminta informasi terkini saat mode online diaktifkan → query diperiksa dari data privat → hasil menampilkan URL sumber dan waktu pengambilan serta diperlakukan sebagai data tidak tepercaya.
- **J06 (`R3`):** Pengguna mengontrol entitas lampu Home Assistant yang diizinkan → eksekusi → readback status aktual; bila koneksi terputus, hasil dilaporkan `unknown`/`unavailable`, bukan klaim sukses.
- **J07 (`R3`):** Pengguna membuat pengingat dari ponsel terpasangkan melalui sesi terenkripsi → policy cakupan remote memvalidasi → pengingat tersimpan atau status *host unreachable* ditampilkan secara jujur bila desktop tidur/mati.

## 5. Hardware-adaptive & storage product capabilities (`E15`)

### 5.1 Profil rekomendasi perangkat keras ilustratif
Tabel berikut adalah **ilustrasi logika rekomendasi awal** dari *Configuration Recommendation Engine*, bukan jaminan kompatibilitas tanpa verifikasi kapabilitas model, driver, dan memori bebas aktual saat runtime:

| Kelas perangkat pengguna | Rekomendasi awal konfigurasi AI | Rekomendasi awal visual | Klasifikasi dukungan awal |
|---|---|---|---|
| CPU-only, RAM 8 GB | Direct tools + model kuantisasi sangat ringan on-demand | `Lite` | `Supported` (Direct) / `Experimental` (LLM CPU) |
| CPU-only, RAM ≥16 GB | Model kecil dengan inferensi CPU thread terukur | `Balanced` | `Supported` (setelah verifikasi R0) |
| NVIDIA GPU VRAM ~4 GB (reference dev class) | Model kuantisasi 1.7B–4B sesuai kuota VRAM & KV cache | `Balanced` | `Supported` (target validasi utama R0/R1) |
| NVIDIA GPU VRAM ≥12 GB | Model lokal menengah (mis. 7B–14B Q4) sesuai memori bebas | `Cinematic` | `Unverified` hingga diuji pada perangkat terkait |
| NVIDIA GPU VRAM ≥24 GB | Model lokal lebih besar / konteks lebih panjang | `Cinematic` | `Unverified` hingga diuji pada perangkat terkait |
| AMD / Intel GPU (Vulkan / ROCm / kompatibel) | Backend akselerator kompatibel melalui runtime yang mendukung | `Adaptive` | `Experimental` / `Unverified` sesuai status uji adapter |
| Server AI private LAN terotorisasi (`R2`) | Inferensi jaringan privat opt-in dengan persetujuan cakupan data | `Cinematic` / `Balanced` | `Supported` pada `R2` setelah uji keamanan |

Setiap konfigurasi diberi label eksplisit **`Supported`**, **`Experimental`**, **`Unverified`**, atau **`Unsupported`**, dan seluruh rekomendasi dapat di-override pengguna selama tidak melanggar batas keamanan atau integritas data.

### 5.2 Dynamic Storage Manager & Runtime Ownership
- **11 lokasi penyimpanan independen yang dapat dikonfigurasi:** `app_data`, `models`, `runtimes`, `core_db`, `knowledge_db`, `logs`, `temp`, `cache`, `backups`, `imported_docs`, dan `extensions`, dengan kuota cache konfigurabel (`10 GB`, `25 GB`, `50 GB`, `Custom`, `Unlimited`), dukungan *shared model directory* lintas runtime agar tidak menduplikasi file multi-GB, serta migrasi antar-drive bertransaksi dengan checksum dan rollback (`R2`).
- **4 mode kepemilikan runtime (`DEC-020`):** (1) *JARVIS-Managed Local Runtime*, (2) *Existing User-Managed Local Runtime* (mis. memakai instalasi Ollama/llama.cpp milik pengguna tanpa dimatikan sepihak oleh JARVIS), (3) *Authorized Private-LAN Runtime* (`R2`), dan (4) *Custom Compatible Provider*. Pengguna produksi hanya memasang runtime yang dipilih, tidak diwajibkan menginstal lebih dari satu runtime.

## 6. Flexible AI modes & Adaptive Cinematic UX (`E13`, `E14`)
Enam mode AI tetap dipertahankan: **`Eco`** (hemat resource/gaming), **`Performance`** (respons suara cepat), **`Balanced`** (default harian), **`Quality`** (model lokal terbesar yang tervalidasi pada kapasitas perangkat atau private LAN opt-in pada `R2`), **`Adaptive`** (pemilihan otomatis berbasis tugas dan telemetri resource aktual dalam zona kepercayaan yang disetujui), dan **`Custom`** (kendali penuh parameter backend, GPU offload, CPU threads, context, idle timeout, prioritas, kebijakan baterai dan gaming).

Antarmuka **Orbital Precision OS** menghadirkan *Interactive Intelligence Core* orisinal tanpa menyalin aset film maupun pola dashboard AI generik. Empat profil kualitas visual independen (**`Cinematic`**, **`Balanced`**, **`Lite`**, **`Reduced Motion`**) dipadukan dengan pengatur batas *frame rate* (**`Auto`**, **`30`**, **`60`**, **`120`**, **`Native`**) dan verifikasi telemetri GPU/WebView sehingga tampilan halus pada monitor standar maupun *high-refresh-rate* tanpa memonopoli resource inferensi AI.

## 7. Measurable success metrics (engineering targets, bukan klaim hasil)
| KPI | Definisi pengukuran | Target rekayasa awal |
|---|---|---|
| K01 Task success | Proporsi intent fixture valid yang selesai benar (termasuk penolakan/klarifikasi yang diharapkan) | ≥95% direct actions; ≥85% mixed intent |
| K02 Voice usability | WER pada korpus uji Bahasa Indonesia bersih dan *false wake* per jam audio negatif | ≤20% WER bersih; ≤0,2 false wake/jam |
| K03 Responsiveness | Latensi `p95` akhir ucapan → awal audio respons pada *reference machine* | ≤4s direct path; ≤12s warm simple LLM |
| K04 Schedule reliability | Pengingat jatuh tempo yang terkirim atau ditandai *missed* secara akurat pasca-restart/sleep | 100% pada skenario uji deterministik |
| K05 Privacy & safety | Permintaan AI eksternal tak berizin atau efek tool tanpa otorisasi pada suite keamanan | 0 kejadian pada suite pengujian |
| K06 Knowledge grounding | Jawaban berbasis dokumen dengan sitasi halaman/bagian yang terverifikasi (`R2`) | ≥90% sampel *answerable*; ≥90% abstensi tepat |
| K07 Mandatory cloud cost | Biaya langganan/token API LLM berbayar pada konfigurasi baseline | Rp0 |
| K08 User control | Perintah *Stop* / *Mute* menghentikan capture, playback, atau langkah yang belum dimulai | 100% pada skenario uji kontrol |
| K09 Runtime portability | Dua adapter lokal referensi menyelesaikan kontrak chat/stream/schema/cancel yang sama di `R0`/`R1` | Lulus suite konformansi tanpa perubahan policy core |
| K10 Resource governance | Kepatuhan terhadap batas sewa GPU/RAM yang dikonfigurasi dan pemulihan saat gagal muat model | Rollback ke profil sehat terakhir atau Direct Mode tercatat |
| K11 Adaptive frame pacing | Interval frame `p95` UI saat mode `Balanced` (`target 60 FPS`) aktif di foreground pada *reference host* | `p95` ≤20 ms; input→umpan balik visual `p95` ≤100 ms |
| K12 Visual truthfulness | Kesesuaian indikator UI terhadap event mesin dan status perangkat keras aktual | 0 *fake progress*; cakupan fungsi penuh pada `Reduced Motion` |
| K13 Onboarding & usability | Penyelesaian alur onboarding *Recommended Setup* dan akses *Mute/Stop* dari tray | ≥90% skenario uji tanpa bantuan; *Mute/Stop* ≤2 interaksi |

## 8. Release gates & tata kelola keputusan
- **`R0` (Feasibility Spike):** Membuktikan kompatibilitas dependensi aktual, kualitas suara/STT/TTS, kecocokan model/VRAM, dua adapter referensi, telemetri WebView, serta inventaris lisensi sebelum *stack freeze*.
- **`R1` (`P0`):** Mengirim `E01`–`E05`, `E13`, `E14`, fondasi `E15` (discovery, rekomendasi, konfigurasi storage/runtime/personalisasi, onboarding 10 langkah, inventaris lisensi), dan keamanan/backup inti.
- **`R2` (`P1`):** Menambah `E06`–`E10`, migrasi storage bertransaksi lintas-drive penuh, private LAN provider opt-in, generasi indeks embedding terisolasi, dan SDK ekstensi tepercaya.
- **`R3` (`P2`):** Menambah `E11`–`E12` (kamera/vision opsional, Home Assistant allowlist, gateway mobile privat, proposal preferensi adaptif).
- Keputusan produk, lisensi open-source, dan portabilitas dicatat dalam `04-TECH-STACK-ADR.md` (`ADR-001`–`ADR-025`). Peninjauan lisensi repositori publik dan klirens merek dagang dilakukan pada gerbang terpisah sebelum distribusi publik.
