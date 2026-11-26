# TECHNOLOGY VALIDATION & OPEN-SOURCE LICENSING GOVERNANCE — J.A.R.V.I.S.

**Document ID:** `PLAN-05`  
**Version:** 0.2.1 (Revised for Best-Fit Licensing Compliance & Portable Toolchain Separation)  
**Baseline Evaluated:** `JARVIS-SDLC-v0.2.1/04-TECH-STACK-ADR.md`, `06-AI-VOICE-DESIGN.md`, `18-REFERENCES.md`  
**Date:** 26 November 2026  
**Status:** Verified Read-Only (Dependency Resolution & Benchmarks Queued for `R0` Approval)

---

## 1. Core Principles: Toolchain Consistency vs. Product Flexibility

Per `DEC-001`, `DEC-004`, `DEC-005`, `DEC-006`, `DEC-009`, and `DEC-022`:
1. **Consistent Reproducible Development Toolchain**: Contributors and CI use pinned toolchains and deterministic lockfiles (`npm` + `package-lock.json`, `uv` + `Python 3.11.9` initial dev baseline with `uv.lock`, `Cargo.lock`). Compatibility on `Python 3.11.9` (`win_amd64`) and any future Python versions is **proven via actual dependency resolution and test execution in `R0`**, never assumed by version number alone.
2. **Interchangeable End-User Runtime Components**: End users install a minimal base application (`DEC-018`) and freely select or swap AI models, inference runtimes (`managed_local`, `external_local`, `authorized_lan`, `custom_compatible`), hardware backends (`CPU`, `CUDA`, `Vulkan`), and voice engines without modifying source code or installing redundant runtimes.
3. **Best-Fit Technology Selection with Rigorous License Compliance (`DEC-022`)**: Libraries are selected on **quality, accuracy, speed, security, and maintenance** paired with explicit legal compliance — **not** rejected reflexively for using `GPL` or `AGPL`. At the same time, JARVIS **never assumes** that subprocess execution or optional post-install downloads automatically waive `GPL`/`AGPL` obligations; final repository licensing is deferred to a pre-publication review once the dependency graph matures.

---

## 2. Candidate Technology & License Compliance Matrix (`v0.2.1`)

### 2.1 Desktop Shell, Adaptive UI & Native Broker

| Layer | Candidate Package / Crate | Inspected Upstream Version | License | Verification & Portability Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Desktop Shell** | `tauri` + `@tauri-apps/cli` + `@tauri-apps/api` | CLI `2.12.6` / API `2.12.5` | `Apache-2.0 OR MIT` | Official scaffold (`DEC-005`). Keeps WebView2 hardware acceleration enabled by default per Microsoft guidance (`REF-23`), verifying actual GPU placement via telemetry (`DEC-010`). |
| **Frontend & Types** | `react` (`19.3.1`), `vite` (`8.3.8`), `typescript` (`7.0.2` / `5.9` LTS), `tailwindcss` (`4.3.5`) | Inspected via `npm view` | `MIT` / `Apache-2.0` | Confirm TypeScript/ESLint/Vite plugin compatibility in `R0` before locking exact minor versions in `package-lock.json`. |
| **Adaptive Motion & Graphics** | `motion` (`14.14.0`) + SVG + Canvas 2D *(WebGL/Three.js open for future benchmarked tier)* | `14.14.0` | `MIT` | Powers *Adaptive Visual Rendering Engine* (`Auto/30/60/120/Native` FPS, `Reduced Motion`, hidden-window suspension, `DEC-010`). |
| **Platform Broker Ports** | `windows-sys` / `windows` behind Rust `LocalIpcTransportPort` & `ProcessSupervisorPort` | Official crates | `MIT OR Apache-2.0` | Implements Windows Named Pipe DACL + `Job Object` (`KILL_ON_JOB_CLOSE` for `managed_local` only) while keeping core IPC traits platform-neutral (`DEC-008`, `DEC-023`). |

### 2.2 Core Backend, Dual SQLite & Security

| Layer | Candidate Package | License | Validation & Portability Requirement |
| :--- | :--- | :--- | :--- |
| **Python Dev Baseline** | CPython `3.11.9` managed via `uv` (`uv.lock`) | `PSF-2.0` | Validate full candidate wheel resolution and C-extension imports in `R0` (`Step R0-A`) before claiming support; gate `3.12`/`3.13` support on separate test evidence (`DEC-004`). |
| **Application & Schemas** | `fastapi`, `pydantic` (v2), `uvicorn`, `httpx`, `structlog` | `MIT` / `BSD-3-Clause` | Strict `extra="forbid"` schemas, platform-independent `domain/` & `application/` layers (`NFR-16`), and central PII/secret log redaction. |
| **Dual SQLite + Vector** | Stdlib `sqlite3` (WAL + FTS5 + Online Backup API) + `sqlite-vec` candidate | `PSF` / `MIT OR Apache-2.0` | Enforces `core.db` (authoritative) vs `knowledge.db` (rebuildable) consistency (`DEC-007`) and rejects SMB/UNC/NFS shares for active WAL files (`DEC-019`). |
| **Vault & Cryptography** | `cryptography` (`AES-256-GCM`, `Argon2id`) + `keyring` / OS Vault behind `SecretVaultAndCryptoPort` | `Apache-2.0 OR BSD-3` / `MIT` | Local `DEK` wrapped in OS Vault; cross-machine backups encrypted with portable `Argon2id` passphrase key (`FR-ADM-08`). |
| **Hardware Telemetry** | `psutil` + `nvidia-ml-py` (optional dynamic load when NVIDIA driver present) + DXGI/OS queries | `BSD-3-Clause` | Gracefully handles CPU-only, AMD, Intel, and NVIDIA hosts without failing import when `nvml.dll` is absent (`DEC-016`). |

### 2.3 Interchangeable AI, Voice & Document Candidates (Evaluated Under `DEC-009` & `DEC-022`)

| Role | Candidates Evaluated in `R0` | License Profile (Engine vs. Weights/Assets) | Compliance & Selection Criteria |
| :--- | :--- | :--- | :--- |
| **LLM Reference Adapters** | 1. `llama.cpp` (`llama-server` CPU / CUDA / Vulkan)<br>2. `Ollama` (`managed_local` or `external_local`) | Code: `MIT`<br>CUDA runtime DLLs: NVIDIA Redistributable EULA | Reference adapters proving `ProviderPort` portability (`DEC-006`). Production users install **only** the runtime they need (or `0` runtimes for *Direct Mode*). |
| **LLM Candidate Weights** | `Qwen3-1.7B-GGUF`, `Qwen3-4B-GGUF`, plus user-selected models (`0.5B` CPU to `14B+` high-VRAM/LAN) | `Qwen3`: `Apache-2.0`<br>Other families: check per-model community license (`Llama`, `Gemma`) | Enforce manifest `SHA-256`, `license_spdx`, `structured_output`, and `thinking` control probe (`FR-AIP-02`). |
| **Wake Word & VAD** | `openWakeWord` (ONNX) vs `sherpa-onnx` Keyword Spotter + `Silero VAD` | Code: `Apache-2.0` / `MIT`<br>**`openWakeWord` default weights: `CC-BY-NC-SA 4.0`** | Compare accuracy & custom wake-phrase support in `R0`. `CC-BY-NC-SA 4.0` weights are valid for private/non-commercial use with attribution, and flagged in the License Inventory if commercial distribution is ever pursued. |
| **Speech-to-Text (STT)** | `faster-whisper` (`ctranslate2` `int8` CPU / CUDA) & `sherpa-onnx` Whisper/SenseVoice | `MIT` / `Apache-2.0` (verify individual model cards) | Benchmark Indonesian + multilingual WER and CPU/GPU latency across hardware classes in `R0`. |
| **Text-to-Speech (TTS)** | 1. `OHF-Voice/piper1-gpl` (`piper`)<br>2. `sherpa-onnx` VITS TTS<br>3. Probed OS voices (`WinRT` / `SAPI`) | `piper1-gpl`: **`GPL-3.0-or-later`**<br>`sherpa-onnx`: `Apache-2.0`<br>`piper-voices` (`id_ID-news_tts`): **Separate dataset/model card license!** | Evaluate audio naturalness, latency, and stability in `R0`. **Runtime check mandatory** for OS voices (never assume `Andika` is installed). Record both engine license (`GPL-3.0` vs `Apache-2.0`) and voice `MODEL_CARD` lineage in `license_artifact`. |
| **Document Parsing (`R2`)** | 1. `PyMuPDF` (`fitz`)<br>2. `pypdfium2` + `pypdf`<br>3. `python-docx` | `PyMuPDF`: **`AGPL-3.0`**<br>`pypdfium2`: `Apache-2.0 OR BSD-3`<br>`pypdf`: `BSD-3`<br>`python-docx`: `MIT` | Benchmark layout/table/locator extraction quality in `R0` (`Step R0-C`). Under `DEC-009`/`022`, `PyMuPDF` is eligible if its extraction accuracy materially outperforms permissive alternatives, with its `AGPL-3.0` source/network obligations recorded for pre-publication repo licensing review. |

---

## 3. Eleven-Category Artifact & License Compliance Inventory (`DEC-022`, `FR-SYS-05`)

Every component shipped, configured, or imported into JARVIS is tracked in `license_artifact` across all **11 mandatory categories**:
1. **Software packages** (`npm`, `PyPI`, `crates.io` transitive lockfile graph)
2. **Native shared libraries / redistributables** (e.g., PortAudio, PDFium, ONNX Runtime, CUDA/Vulkan runtime DLLs)
3. **AI inference runtimes** (`llama-server`, `Ollama`, etc.)
4. **AI model weights** (`GGUF`, `ONNX` LLM/embedding/VLM checkpoints)
5. **Relevant training dataset terms** (where upstream model/voice cards propagate dataset attribution or non-commercial clauses)
6. **Voice assets & TTS model cards** (e.g., `rhasspy/piper-voices` `MODEL_CARD` per voice)
7. **Wake-word models** (e.g., `CC-BY-NC-SA 4.0` vs `Apache-2.0` checkpoints)
8. **Fonts** (`OFL-1.1` / system font licensing)
9. **Icons** (`MIT` / `ISC` / original vector assets)
10. **Sound effects / earcons** (100% original synthesized or verified open-licensed audio)
11. **Third-party UI assets** (if any)

**Hard Governance Gate**: Any artifact with `license_spdx = 'UNKNOWN'` is blocked from activation and fails CI SBOM/`THIRD-PARTY-NOTICES` generation (`TC-FR-SYS-05`).
