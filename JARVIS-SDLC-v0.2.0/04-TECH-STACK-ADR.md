# Technology Stack & Architecture Decision Records

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Candidate stack (versions pinned after R0)
| Layer | Preferred | Alternative / constraint |
|---|---|---|
| Desktop | Tauri 2 + React + TypeScript + Vite | Native Qt if WebView integration fails; official scaffold only |
| Core | Python 3.11/3.12 candidate + FastAPI/Pydantic + Uvicorn | Confirm all wheels/OS support; choose one version in R0 |
| Native broker | Rust/Tauri command layer | Named pipes ACL if replacing loopback HTTP |
| LLM | Provider abstraction; llama.cpp CUDA and Ollama local candidates; verified GGUF Q4 models | Local compatible API; optional approved private LAN R2; capability tests before use |
| Motion | Motion for React + CSS/SVG, optional Canvas 2D | WebGL/Three.js only after R0 budget proof; reduced motion mandatory |
| Wake/VAD | openWakeWord + Silero VAD candidate | English wake phrase "Hey Jarvis"; PTT fallback; custom model/license test |
| STT | faster-whisper tiny/base multilingual, CPU int8 | small only after benchmark; verify Indonesian quality |
| TTS | Piper local id_ID/en voice candidate | Windows installed offline voice fallback if available; verify voice and GPL obligations |
| Storage | SQLite WAL, FTS5, migration runner | Optional vector extension or brute-force normalized embeddings; no separate vector DB R1 |
| Embedding | Small multilingual CPU encoder (candidate multilingual-e5-small) | FTS-only fallback, benchmark before enabling |
| OS | Win32/Core Audio/UI Automation, native adapters | No admin, no arbitrary shell |
| Document parsing | PyMuPDF or pypdf (license review), python-docx, plaintext | OCR later, cap and isolate parser |
| Screen | Windows capture + local OCR, optional VLM | UIA first, no background capture |
| IoT | Home Assistant REST / MQTT via HA | No broker requirement R1; scoped allowlist proxy |
| Mobile | Responsive private web client over authenticated VPN/TLS | Native mobile later; never expose local core |
| QA | pytest, Vitest, Playwright UI, synthetic adapter fixtures | Hardware E2E on controlled host |
| Distribution | Signed Windows installer, hashes/model manifests, SBOM | Offline install bundle when license permits |

## 2. Decision records
| ADR | Decision / rationale | Rejected or deferred | Consequence / revisit trigger |
|---|---|---|---|
| ADR-001 | Local-first hybrid; no paid LLM, external network opt-in | Cloud-first LLM | Smaller model quality; revisit only with explicit scope change |
| ADR-002 | Modular monolith + isolated model workers | Microservices, Kafka, Redis | Simpler deployment; split only for measured isolation/scale needs |
| ADR-003 | Windows-first desktop UI | Cross-platform parity at launch | OS adapters modular; confirm actual host in R0 |
| ADR-004 | Deterministic routing then LLM | LLM for every command | Better latency/safety; add regression fixtures for phrase coverage |
| ADR-005 | SQLite single owner, FTS-first | PostgreSQL/Chroma required | Local ops simple; revisit if corpus benchmark misses target |
| ADR-006 | Typed tool registry + policy checks | Arbitrary code/shell or agent autonomy | Lower flexibility, predictable scope |
| ADR-007 | CPU audio; one heavy GPU worker at a time | All models resident | Cold-start cost; resource scheduler required |
| ADR-008 | Explicit permanent memory and bounded session history | Save all transcripts by default | Less passive personalization; proposals need review |
| ADR-009 | Authenticated local broker, separated remote gateway | Public HTTP and direct UI-to-worker | More boundary code, narrower exposed surface |
| ADR-010 | Signed manifests and manual model selection | Automatic install/update of models/plugins | Safer but maintenance workflow required |
| ADR-011 | No remote mutation by default; allow narrow grants | Remote full desktop control | Mobile initially chat/reminders/status only |
| ADR-012 | Local OCR/UIA first | Always-on screen/camera VLM | Limited scene reasoning; privacy and resource preservation |

All ADRs are proposed except product direction in ADR-001 and coding-agent exclusion. Confirm dependency versions, licenses, native binaries and actual hardware. Record date, decision owner, alternatives, evidence, consequences and supersession for each change. No framework choice warrants overriding security or OS constraints. Use official source repositories and signed release artifacts; no scratch recreation of runtime libraries.

## 3. ADR additions v0.2.0
- ADR-013: role-based provider abstraction with versioned capability contracts, no fixed model family. Supersedes any implied single-runtime lock; ADR-001/007/010 remain in force. Initial local adapters llama.cpp and Ollama; generic compatible endpoint and private LAN require separate validation. Consequence: normalization and adapter conformance tests mandatory.
- ADR-014: state-driven cinematic interface using Motion for React, SVG and CSS first; optional Canvas 2D. WebGL/Three.js not required; choose only after R0 resource benchmark. Consequence: animation state controller, reduced motion, performance tiers and resource priority enforced before R1.
- ADR-015: atomic model/profile activation and rollback; preserve model-independent domain state and version embeddings. No unapproved download or auto trust-zone changes. Consequence: switch downtime acceptable on 4 GB GPU, explicit UI progress and direct-mode fallback.
