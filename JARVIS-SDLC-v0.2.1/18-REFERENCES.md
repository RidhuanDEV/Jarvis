# Technical References, Licensing Standards & Verification Notes

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.1 | **Status:** Approved architectural baseline, belum diimplementasikan  
**Tanggal:** 26 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Standar rekayasa, keamanan & tata kelola lisensi
| ID | Sumber referensi | Penerapan pada JARVIS |
|---|---|---|
| REF-01 | [ISO/IEC/IEEE 29148:2018](https://www.iso.org/standard/72089.html) | Atribut persyaratan yang tidak ambigu, dapat diuji, dan tertelusur (abstrak publik; tanpa klaim sertifikasi) |
| REF-02 | [ISO/IEC/IEEE 42010:2022](https://www.iso.org/standard/74393.html) | Pemisahan pemangku kepentingan, kepedulian arsitektur, dan sudut pandang desain (`03-SDD.md`) |
| REF-03 | [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework) | Tata kelola risiko, pengukuran evaluasi AI, dan batasan otonomi |
| REF-04 | [OWASP Top 10 for LLM Applications](https://owasp.org/projects/top-10-for-large-language-model-applications) | Mitigasi prompt injection, *excessive agency*, *improper output handling*, dan *supply chain* |
| REF-26 | [GNU GPL / AGPL Licensing & FAQ (FSF)](https://www.gnu.org/licenses/gpl-faq.html) | Acuan evaluasi kewajiban distribusi kode sumber dan penggunaan jaringan pada pustaka `GPL`/`AGPL` (`DEC-022`) |

## 2. Referensi teknis hulu (*Upstream Technical References*)
| ID | Sumber referensi | Relevansi & hal yang harus diverifikasi di `R0` |
|---|---|---|
| REF-05 | [llama.cpp server documentation](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md) | Adapter referensi lokal GGUF, akselerasi CPU/CUDA/Vulkan, dan output JSON terstruktur |
| REF-06 | [Qwen3-1.7B GGUF](https://huggingface.co/Qwen/Qwen3-1.7B-GGUF) | Kandidat model ringan; verifikasi revisi, hash, lisensi, dan penonaktifan mode *thinking* |
| REF-07 | [Qwen3-4B GGUF](https://huggingface.co/Qwen/Qwen3-4B-GGUF) | Kandidat kualitas lebih tinggi pada GPU ≥4 GB; ukur kecocokan memori & kuantisasi KV cache |
| REF-08 | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Kandidat STT lokal (`int8` CPU / akselerator) dan resolusi wheel `ctranslate2` |
| REF-09 | [openWakeWord](https://github.com/dscripka/openWakeWord) | Kandidat deteksi wake word ONNX; periksa lisensi kode vs model bawaan secara terpisah |
| REF-10 | [Piper TTS (`OHF-Voice/piper1-gpl`)](https://github.com/OHF-Voice/piper1-gpl) | Kandidat engine TTS lokal berlisensi `GPL-3.0`; tinjau kewajiban distribusi bila dibundel |
| REF-11 | [Piper voices & model cards (`rhasspy/piper-voices`)](https://huggingface.co/rhasspy/piper-voices) | Ketersediaan suara Bahasa Indonesia (`id_ID-news_tts-medium`) beserta rujukan lisensi dataset terpisah |
| REF-12 | [Piper licensing documentation](https://github.com/OHF-Voice/piper1-gpl/blob/main/docs/LICENSING.md) | Pemisahan lisensi kode aplikasi vs bobot suara dan dataset pelatihan |
| REF-13 | [SQLite FTS5 Extension](https://www.sqlite.org/fts5.html) | Pencarian leksikal lokal tanpa server tambahan |
| REF-14 | [SQLite Write-Ahead Logging (WAL)](https://www.sqlite.org/wal.html) | Batasan konkurensi penulis tunggal, ketiadaan atomisitas lintas-DB, dan larangan *network filesystem* |
| REF-15 | [SQLite Online Backup API](https://www.sqlite.org/backup.html) | Pembuatan snapshot konsisten pada `jarvis_core.db` saat aplikasi aktif |
| REF-16 | [Tauri v2 Security Capabilities](https://v2.tauri.app/security/capabilities/) | Pembatasan izin perintah IPC per jendela secara eksplisit |
| REF-17 | [Windows UI Automation Overview](https://learn.microsoft.com/en-us/windows/win32/winauto/uiauto-uiautomationoverview) | Pembacaan semantik elemen antarmuka desktop pada `DesktopAutomationPort` |
| REF-18 | [Home Assistant MQTT Integration](https://www.home-assistant.io/integrations/mqtt) | Opsi integrasi perangkat rumah pintar di balik broker ber-ACL (`R3`) |
| REF-19 | [Home Assistant REST API](https://developers.home-assistant.io/docs/api/rest/) | Pembacaan status dan pemanggilan layanan entitas ber-allowlist (`R3`) |
| REF-20 | [Tailscale Access Control](https://tailscale.com/docs/features/access-control) | Kandidat jaringan privat terautentikasi untuk akses mobile (`R3`) |
| REF-21 | [Motion for React Layout Animations](https://motion.dev/docs/react-layout-animations) | Koreografi transisi tata letak dan nilai gerak tanpa memicu *re-render* React berlebih |
| REF-22 | [Motion `useReducedMotion`](https://motion.dev/docs/react-use-reduced-motion) | Kepatuhan aksesibilitas terhadap preferensi pengurangan gerak pengguna/OS |
| REF-23 | [Tauri WebView Versions & Microsoft WebView2 Guidance](https://learn.microsoft.com/en-us/microsoft-edge/webview2/) | Perilaku runtime WebView2, telemetri performa, dan rekomendasi menjaga akselerasi hardware tetap aktif |
| REF-24 | [Ollama API Documentation](https://docs.ollama.com/api) | Adapter referensi lokal kedua (`managed_local` maupun `external_local`); uji skema JSON & mode *thinking* |
| REF-25 | [sherpa-onnx Documentation](https://k2-fsa.github.io/sherpa/onnx/) | Kandidat alternatif *keyword spotting*, VAD, STT, dan VITS TTS berbasis ONNX (`Apache-2.0`) |
| REF-27 | [sqlite-vec Documentation](https://alexgarcia.xyz/sqlite-vec/) | Ekstensi pencarian vektor ringan langsung di dalam SQLite untuk generasi indeks `jarvis_knowledge.db` |
| REF-28 | [Win32 Job Objects (`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`)](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) | Mekanisme pengawasan siklus hidup proses anak `managed_local` pada implementasi Windows `ProcessSupervisorPort` |

## 3. Bukti wajib keluaran `R0` sebelum pembekuan stack
Snapshot kapabilitas perangkat uji; log resolusi dependensi (`uv.lock`, `package-lock.json`); metrik mentah benchmark STT, wake, TTS, dua adapter LLM, dan waktu frame WebView; manifest model terpilih beserta hash SHA-256; inventaris lisensi awal 11 kategori (termasuk *model card* suara dan wake word); bukti tidak adanya koneksi keluar pada mode offline; serta pembaruan `04-TECH-STACK-ADR.md` dan `17-TRACEABILITY-MATRIX.md`.
