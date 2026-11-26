# Product Requirements Document (PRD)

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Product vision
Membangun asisten yang tersedia ketika komputer aktif, dapat mendengar, memahami konteks, mengingat informasi yang disetujui, bertindak melalui tools terbatas, dan memberi pengingat proaktif. Tidak menggantikan keputusan pengguna. Local-first berarti tidak ada pengiriman prompt, audio, screen, atau database ke layanan AI eksternal secara default maupun sebagai fallback tersembunyi.

## 2. Problem statements dan persona
| ID | Problem / job to be done | Hasil yang diharapkan |
|---|---|---|
| G01 | Pemilik komputer berulang kali membuka aplikasi dan melakukan operasi rutin | Selesaikan tindakan terdaftar dengan suara atau teks, konfirmasi sesuai risiko |
| G02 | Informasi pribadi tersebar di file, catatan dan jadwal | Temukan informasi dengan provenance dan kontrol memori |
| G03 | Pengingat sering terlupakan | Pengingat persisten, kontekstual dan tidak mengganggu |
| G04 | Cloud AI menambah biaya dan risiko kebocoran | Fungsi inti offline tanpa biaya token |
| G05 | Pengguna perlu akses dan kontrol lintas perangkat | Integrasi opt-in yang aman dan terverifikasi |

Persona utama: satu pemilik workstation pribadi, pengguna teknis maupun non-teknis. Persona sekunder: pengguna dari HP yang telah dipasangkan. Tamu di dekat mikrofon bukan pengguna terautentikasi. Admin workstation bukan role JARVIS yang diberikan kepada model.

## 3. Product scope dan release strategy
| Epic | Scope | Priority | Acceptance value |
|---|---|---|---|
| E01 Voice & interaction | Wake word, push-to-talk, text, STT/TTS lokal, interruption | P0 | Interaksi Indonesia dan Inggris terbatas, tanpa internet |
| E02 Core intelligence | Intent router, bounded planning, local model, contextual response | P0 | Direct actions tidak memakai LLM; unknown intent ditangani |
| E03 OS actions | Launch aplikasi, volume, file search, safe workflows | P0 | Hasil diverifikasi, no arbitrary shell |
| E04 Memory | Preference, episodic, explicit save/edit/delete, retrieval | P0 | Pengguna mengontrol apa yang diingat |
| E05 Scheduling & proactive | Reminder lokal, event rules, quiet hours, notification history | P0 | Tidak kehilangan reminder saat restart |
| E06 Personal knowledge | Folder opt-in, PDF/text/docx, citations, lexical/semantic search | P1 | Jawaban merujuk file dan halaman/section |
| E07 Web intelligence | Read-only search/fetch, source dates, offline indication | P1 | Tidak menyamar sebagai hasil online ketika offline |
| E08 Screen awareness | Snapshot on request, accessibility tree, OCR, optional vision | P1 | Tidak merekam terus-menerus atau membaca password |
| E09 Personal management | Tasks, kalender lokal, expense tracking, habits | P1 | Data lokal dengan CRUD, no payment/medical decisions |
| E10 Advanced automation | Typed workflow, approval, dry-run, cancellation | P1 | Efek samping tercatat dan duplikasi dicegah |
| E11 Environmental & IoT | Camera on-demand, Home Assistant, status and safe controls | P2 | Indicator aktif, no autonomous dangerous actuation |
| E13 Flexible AI | Provider registry, model manager, role mapping, resource profiles, switching, health and rollback | P0 | Swap verified models/runtimes without core changes; local-first enforced |
| E14 Cinematic experience | Original HUD, animated core, voice-reactive visualization, coordinated transitions, quality tiers | P0 | Responsive, state-driven, accessible UI with measured frame budget |
| E12 Remote & adaptive | Paired mobile access, feedback-driven preference proposals | P2 | Scope akses per device; pemilik menyetujui perubahan |

Out of scope: coding/debugging/deploy agent, unattended terminal, keystroke logging, covert recording, face identification, background biometrics, online financial transactions, medical prescriptions, cloud LLM fallback, multi-tenant SaaS, unrestricted autonomous agent. Tidak ada autonomous self-modification atau instalasi plugin otomatis.

## 4. User journeys
- J01: pemilik mengatakan "Jarvis, buka Spotify dan kecilkan volume ke 30 persen" → wake → transcript → dua typed actions → policy check → execute & verify → respons per tindakan. Bila Spotify tidak tersedia, status parsial disampaikan.
- J02: "Ingatkan saya besok jam 8 untuk rapat" → resolve zona waktu lokal → tampilkan tanggal absolut → simpan reminder → alarm tetap tersimpan saat restart; jika perangkat mati, tampilkan missed reminder ketika kembali aktif.
- J03: "Apa yang kamu ingat tentang preferensi saya?" → daftar dengan sumber → pengguna edit/hapus → retrieval tidak mengembalikan data terhapus.
- J04: "Ringkas dokumen ini" → pilih file → retrieve bagian relevan → kutip filename/page/section → unknown apabila sumber kurang.
- J05: "Apa berita hari ini?" → izin network → search query tanpa data privat → tampilkan sumber/tanggal → content diperlakukan sebagai data tidak tepercaya.
- J06: "Matikan lampu kamar" → resolve device → policy allowlist → execute → verifikasi state aktual; jika tidak terkonfirmasi, status unknown.
- J07: pengguna di HP membuat reminder → paired TLS session → policy remote scope → job persist → acknowledgment dari desktop. Desktop tidur/mati berarti unavailable, bukan dijanjikan always-on.

## 5. Success metrics (target, bukan hasil)
| KPI | Definisi | Target awal |
|---|---|---|
| K01 Task success | Intent fixtures yang selesai benar / semua fixtures valid, termasuk error yang diharapkan | ≥95% direct actions; ≥85% mixed intent |
| K02 Voice usability | WER corpus ID bersih dan false wakes per jam | ≤20% WER; ≤0,2 false wake/jam |
| K03 Responsiveness | p95 end-of-utterance → start audio | ≤4s direct; ≤12s warm LLM simple |
| K04 Reliability | Pengingat due yang disampaikan/ditandai missed saat host kembali aktif | 100% pada skenario uji |
| K05 Privacy | Unauthorized external AI requests; unauthorized effects | 0 pada suite pengujian |
| K06 Grounding | Jawaban berbasis dokumen dengan locator yang valid | ≥90% sampel answerable |
| K07 Local cost | Paid LLM charges baseline | Rp0; listrik, perangkat dan layanan eksternal tidak dijamin gratis |
| K08 Control | Permintaan stop/mute berhasil menghentikan aktivitas terkait | 100% pada skenario uji |

## 6. Release gates
R0 membuktikan audio, model, GPU/CPU, licensing dan baseline latency. R1 mengirim E01–E05, E13, E14 dan privacy/security foundation; R2/R3 memperluas motion language dan provider roles seiring fitur terkait. R2 menambah E06–E10 dengan evaluasi grounding dan prompt injection. R3 menambah E11–E12 setelah device dan remote threat review. Tidak ada rilis apabila tindakan tidak terotorisasi, data leak, restore gagal, atau test kritis belum lulus. Lihat 14 dan 16.

## 7. Product decisions pending
OS dan hardware aktual; bahasa/karakter suara yang disukai; folder dan aplikasi yang diperbolehkan; kebutuhan kalender eksternal; device IoT; retention preference; apakah HP perlu native app atau web client; apakah distribusi hanya pribadi atau publik. Default: private, on-device AI, seluruh external integration disabled. LAN inference opsional hanya ke server milik/tepercaya pengguna melalui explicit enrollment; tanpa public cloud fallback. Semua keputusan ini dapat diubah melalui change request.

## 8. Flexible AI: product requirements and user control
**Product promise:** ganti model, runtime atau hardware tanpa fork core, reinstall aplikasi, kehilangan memory, atau mengubah policy tools. Kualitas setiap provider tidak dianggap setara. Local on-device adalah default; private LAN adalah perluasan opt-in, bukan syarat atau fallback otomatis. No paid cloud AI; external commercial inference is out of scope. Internet tetap untuk retrieval/integrasi yang diizinkan.

| Mode | User goal | Behavior |
|---|---|---|
| Eco | Bekerja/gaming tanpa gangguan | Direct tools + model ringan bila perlu, GPU cap, unload on pressure, low motion |
| Performance | Voice cepat | Model kecil approved, short context, warm jika budget cukup, non-thinking bila tersedia |
| Balanced (default) | Harian | Pilih profile tervalidasi dengan kualitas/latency seimbang |
| Quality | Analisis lebih sulit | Model lebih besar atau private LAN yang dipilih pengguna, progress nyata, bounded deadline |
| Adaptive | Otomatis | Route by task/capability and measured resources dalam allowlist dan trust zone yang disetujui |
| Custom | Advanced user | Pilih provider, role, model, quantization, context, CPU/GPU settings dan keep-warm sesuai dukungan |

Model Manager: discover installed provider, inspect capabilities, import signed/verified model manifest, show storage and measured memory, run explicit benchmark, set role/profile, switch with active request drain or user cancellation, rollback last healthy config. No automatic download, executable install, remote code, or silent LAN routing. Show current model, provider, location and effective settings on each request detail. Defaults must work after offline installation. User may pin profile; unsupported capabilities disable relevant features with explanation rather than pretending equivalence. Settings edits persist atomically; embeddings changes trigger versioned reindex, not incompatible vector mixing. Audio, embeddings and vision adapters also replaceable; each requires role-specific quality gates. LAN adapter R2 optional; R1 requires native local provider + second local adapter demonstrated. Model family Qwen/Llama/Gemma etc. candidates only, not promises of compatibility.

## 9. Experience vision: cinematic, not decorative
Original sci-fi industrial interface inspired by the interaction feel of Tony Stark's assistant, not reproduction of Marvel assets, logos, voice or soundtrack. Visual direction: deep graphite/navy, electric cyan and warm amber accents, luminous concentric intelligence core, modular radial geometry, subtle depth, restrained glass, crisp technical typography. Avoid template dashboard grid, excessive glow, fake data, excessive rounded cards, blocking intro and constant flashing. Dashboard focuses on voice center, agenda, real activities and system health. Tray-first + compact HUD + full Command Center, optional fullscreen cinematic scene; chat and detailed settings remain straightforward.

Core animation is a first-class feature from R1: Idle, Listening, Transcribing, Thinking, Executing, Awaiting approval, Speaking, Error, Offline, Muted, Degraded; visual state derived from real engine events. Listening uses measured mic envelope; speaking uses actual playback amplitude; thinking uses indeterminate motion, no fake percentages. User can interrupt immediately, disable audio visualization or motion, and select Cinematic / Balanced / Lite / Reduced Motion visual settings independently of AI mode. All information accessible via text and keyboard. Cinematic features yield resources to voice inference and other apps; no mandatory 3D engine. Detailed motion and acceptance spec: [10-UX-DESIGN.md](10-UX-DESIGN.md).

## 10. Additional measurable success metrics
| KPI | Target / verification |
|---|---|
| K09 Model portability | Two approved local adapters complete same direct/chat/tool-proposal contracts, no changes to core policy; switch/rollback and offline tests pass |
| K10 Resource-aware switching | No concurrent heavyweight model leases on reference GPU; no unapproved trust-zone crossing; failed load restores prior config or direct mode |
| K11 Motion responsiveness | On reference 60 Hz display, Balanced UI p95 frame interval ≤20 ms during scripted foreground animation; p95 input→visible feedback ≤100 ms; report concurrently loaded AI separately |
| K12 Visual integrity | All voice/action states match engine events, no fake progress, no hidden mic; Reduced Motion retains full functional coverage |
| K13 Experience efficiency | ≥90% of agreed usability tasks complete unassisted; mute/stop available within two interactions; no blocking decorative sequence |

These are engineering/product targets, not measured outcomes. R0 establishes display refresh, CPU/GPU headroom, WebView behavior, actual visual and model benchmarks. R1 must ship working motion system, not postpone visual identity to R3. Any threshold change requires explicit approval and evidence.
