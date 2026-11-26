# R0 TECHNICAL FEASIBILITY & EMPIRICAL BENCHMARK REPORT — J.A.R.V.I.S.

**Document ID:** `PLAN-12`  
**Phase:** Phase 1 — `R0` Feasibility Spike (`B01`, `B22`, `B23` — Gates `G1` & `G2`)  
**Execution Date:** 26 November 2026  
**Status:** `VERIFIED-LOCAL` (All `R0` Empirical Spikes Executed; Zero Orphan Processes; Ready for Phase 2 Scaffolding Gate)

---

## 1. Executive Summary & `R0` Gate Verdict

**GATE `G1` VERDICT: PASS — ALL CORE TECHNICAL, HARDWARE-ADAPTIVE, VOICE, LLM, DATABASE, AND UI TARGETS EMPIRICALLY PROVEN.**

Executing [R0-EXECUTION-PLAN.md](R0-EXECUTION-PLAN.md) inside an isolated `%LOCALAPPDATA%\Jarvis-R0-Sandbox` environment uncovered five high-value empirical findings that would not have been caught by static documentation review alone, and validated our best-fit recommended stack across CPU-only, Vulkan, and CUDA configurations:

1. **Multi-Backend LLM Portability & `--jinja --reasoning-budget 0` Breakthrough (`B22`)**:
   - Without `--jinja --reasoning-budget 0` and an explicit tool-parameter catalog, `Qwen3` models burned tokens on internal reasoning phrasing (`p50 = 1,428 ms` on CUDA, `8,595 ms` on CPU, `30%–50%` strict intent match).
   - Enabling native `llama-server` **`--jinja --reasoning-budget 0` + concise static Tool Catalog** lifted **`Qwen3-4B-Q4_K_M` (`Q8_0` KV) to `100.0%` schema validity and `100.0%` mixed-intent/safety accuracy** at **`p50 = 987.0 ms` (`52.7 tok/s`)** using **`2,914.5 MiB` peak VRAM** (`464 MiB` safely below the `3.30 GiB` `NFR-02` reference ceiling!).
   - **`Qwen3-1.7B-Q4_K_M`** hit **`103.5 tok/s` (`p50 = 477.5 ms`, `p95 = 856.8 ms`, `1,508.5 MiB` peak VRAM)** on CUDA, **`94.7 tok/s`** on the **`37.3 MB` cross-vendor Vulkan backend**, and **`p50 = 3,487.8 ms` (`p95 = 5,852.2 ms <= 12,000 ms` `NFR-01`!)** on **pure 6-thread CPU-only mode**!
2. **Indonesian + Code-Switch STT Selection (`B01`)**:
   - `faster-whisper tiny` (`35.82%` clean WER) and `base` (`27.30%` clean WER) **failed** the `NFR-07` (`≤ 20%` WER) threshold on Indonesian + English app-name commands (e.g., transcribing *"kopi hitam tanpa gula"* as *"copy hitam tanpa Google"*).
   - **`faster-whisper small` (`int8` CPU, `4` threads, `342.8 MiB` RAM delta)** achieved **`14.18%` clean WER and `17.38%` noisy (`15 dB SNR`) WER** (**passing `≤ 20%` in both clean and noisy conditions!** — with most remaining edits being `"30"` vs `"tiga puluh"` digit formatting!) at `p95 = 2,116.8 ms`, keeping end-to-end Direct Voice latency around **`~2.67s <= 4.0s` (`NFR-01`)**.
3. **TTS Engine & `MODEL_CARD` Discovery (`DEC-009`, `DEC-022`)**:
   - `sherpa-onnx 2.0.3` stripped embedded `GPL-3.0` `espeak-ng` from its prebuilt wheel, causing raw Piper VITS synthesis in `sherpa-onnx` to fail without an external phonemizer (`no frontend available`).
   - Meanwhile, **`piper-tts 1.8.0` (`OHF-Voice/piper1-gpl`, `GPL-3.0-or-later`)** installed cleanly via prebuilt Windows wheel and synthesized `id_ID-news_tts-medium` at **`p50 = 167.03 ms` (`p95 = 199.91 ms`, `RTF = 0.0408` — 24.5× real-time)**, while dynamically probed OS **WinRT `Microsoft Andika (id-ID)`** synthesized at **`p50 = 8.55 ms`**.
   - Inspecting the upstream `id_ID-news_tts-medium` `MODEL_CARD` confirmed `License: See URL` (referencing a Kaggle speech corpus notebook) — proving why voice weights must remain **user-approved optional downloads with explicit model-card attribution** rather than bundled blindly into base installers!
4. **Dynamic OS OCR Language-Pack Discovery**:
   - Runtime probing of `Windows.Media.Ocr.OcrEngine` revealed **only `en-US` OCR** is installed on the reference Windows 11 Home host (`id-ID` OCR pack absent), validating the requirement to probe OS packs dynamically and fall back to Latin-script `en-US` WinRT OCR or local ONNX OCR rather than hardcoding `Language("id-ID")`.
5. **PDF Parser & Adaptive UI Rendering Telemetry (`B23`)**:
   - **`pypdfium2 5.15.2` (`Apache-2.0 OR BSD-3-Clause`)** extracted 34 pages across 10 PDFs in **`21.83 ms`** (**4.25× faster** than `PyMuPDF 2.2` at `92.90 ms` and **3.0× faster** than `pypdf 7.1.1` at `65.07 ms`), while `pypdf` matched `PyMuPDF`'s exact `10,764` character layout count (`100%` scanned-PDF `ocr_required` detection across all three).
   - Live Edge/WebView2 (`ANGLE Direct3D11` on `Intel UHD Graphics`) telemetry proved **`200.0 FPS` (`p50 = 5.0 ms`)** in `Native` VSync mode, **`28.6 FPS` (`p50 = 35.0 ms`)** in `Lite` mode, **`0` loop frames** in `ReducedMotion` and hidden states, safe initial focus on `Tolak (Esc)` in the `<dialog>` `R2` modal, stale event rejection after `Stop`, and **`0 MiB` discrete NVIDIA VRAM usage** (`0` orphan processes post-run).

---

## 2. Empirical Measurement Tables

### 2.1 Multi-Backend LLM Performance, VRAM & Process Supervision (`Step R0-D`)
*Reference Host: Intel Core i5-11400H (6C/12T), 39.74 GB RAM, NVIDIA RTX 3050 Laptop GPU (4,096 MiB VRAM, 134 MiB baseline WDDM usage).*

| Configuration (`llama-server b12774`) | Peak Total VRAM (`MiB`) | VRAM Delta (`MiB`) | Process RSS (`MiB`) | Speed (`tok/s`) | TTFT `p50` (`ms`) | Plan `p50` / `p95` (`ms`) | Schema Valid | Intent Match | Job Object Kill (`ms`) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | ---: |
| `Qwen3-1.7B` CPU-Only *(Untuned baseline)* | `203.9` | `+69.9` | `1,591.3` | `15.5` | `307.1` | `8,595 / 12,470` | `100%` | `30%` | `246.2` |
| **`Qwen3-1.7B` CPU-Only (`--jinja --reasoning-budget 0`)** | **`205.1`** | **`+71.1`** | **`1,555.1`** | **`15.7`** | **`299.0`** | **`3,488 / 5,852`** | **`100%`** | **`80%`** | **`199.6`** |
| `Qwen3-1.7B` Vulkan Cross-Vendor *(Untuned)* | `1,594.1` | `+1,460.1` | `1,262.6` | **`94.7`** | `48.2` | `1,629 / 2,720` | `100%` | `30%` | `274.8` |
| **`Qwen3-1.7B` CUDA Balanced (`--jinja --reasoning-budget 0`, `Q8_0` KV)** | **`1,508.5`** | **`+1,374.5`** | **`1,520.2`** | **`103.5`** | **`36.7`** | **`478 / 857`** | **`100%`** | **`80%`** | **`201.3`** |
| **`Qwen3-4B` CUDA Quality (`--jinja --reasoning-budget 0`, `Q8_0` KV)** | **`2,914.5`** | **`+2,780.5`** | **`2,853.2`** | **`52.7`** | **`53.1`** | **`987 / 1,856`** | **`100%`** | **`100%`** | **`383.3`** |

- **Deterministic Router (`30` direct command trials):** `30/30` (`100%`) matched in **`1.38 µs/turn`** with **`0` LLM calls** (`FR-COR-01`).
- **Adversarial Schema Gate:** `4/4` (`100%`) shell/extra-key/`>5`-step payloads rejected with `0` side effects (`FR-COR-02/03`).
- **Runtime Ownership Isolation (`FR-AIP-08`, `NFR-15`):** `managed_local` terminated in `0.20–0.38s` (`<< 5.0s` target), `external_local` process survived `100%` untouched, and post-suite GPU VRAM returned to exact baseline (`134.0 MiB` used / `3,962.0 MiB` free).

---

### 2.2 Voice Pipeline (`STT`, `TTS`, `Wake/Echo`) & PDF Parser Benchmarks (`Step R0-C`)

| Component & Variant | Clean WER (`%`) | Noisy `15dB` WER (`%`) | Latency `p50` / `p95` (`ms`) | Mean RTF | RAM Delta (`MiB`) | `R0` Gate Decision |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- |
| `faster-whisper tiny` (`int8` CPU, 4T) | `35.82%` | `44.33%` | `304.1 / 337.0` | `0.075` | `+140.6` | **Fail `NFR-07`** (Reserve strictly for ultra-constrained 8 GB fallback with confirmation) |
| `faster-whisper base` (`int8` CPU, 4T) | `27.30%` | `36.88%` | `637.4 / 735.7` | `0.152` | `+148.8` | **Borderline** (Optional fast English/Eco option) |
| **`faster-whisper small` (`int8` CPU, 4T)** | **`14.18%`** | **`17.38%`** | **`1,945.2 / 2,116.8`** | **`0.468`** | **`+342.8`** | **SELECTED DEFAULT** (`Passes ≤ 20% WER` in both Clean & Noisy!) |
| **`piper-tts 1.8.0` (`id_ID-news_tts-medium`)** | — | — | **`167.0 / 199.9`** | **`0.041`** | Lightweight | **SELECTED NEURAL TTS** (`GPL-3.0-or-later`; optional user-consented voice download) |
| **WinRT `Microsoft Andika` (`id-ID` OS Voice)** | — | — | **`8.55 / 12.26`** | `< 0.005` | OS Shared | **SELECTED ZERO-DOWNLOAD FALLBACK** (when dynamically detected on OS) |
| **`openWakeWord` (`hey_jarvis_v0.1.onnx`)** | — | — | **`1.64 ms / 80ms frame`** | `0.020` | Lightweight | **SELECTED INITIAL WAKE** (`CC-BY-NC-SA 4.0` weights logged in inventory; PTT always active) |
| **Open-Speaker Echo Guard (`Silero VAD`)** | — | — | `5/5` unprotected bleed triggers → **`0/5` guarded** | — | — | **MANDATORY IN `R1`** (`5/5` PTT barge-in preserved) |

| PDF Extractor (`34` Pages / `10` Fixtures) | License | Total Time (`ms`) | Extracted Chars | Scanned `ocr_required` Check | `R0` Recommendation (`DEC-009` / `DEC-022`) |
| :--- | :--- | ---: | ---: | :---: | :--- |
| **`pypdfium2 5.15.2`** | `Apache-2.0 OR BSD-3` | **`21.83 ms`** | `10,029` | `PASS` | **PRIMARY FAST EXTRACTOR** (Fastest C/PDFium speed + permissive license) |
| **`pypdf 7.1.1`** | `BSD-3-Clause` | `65.07 ms` | `10,764` | `PASS` | **BUILT-IN FALLBACK** (Pure Python safety + exact char parity) |
| `PyMuPDF 2.2` (`pymupdf`) | `AGPL-3.0-or-later` | `92.90 ms` | `10,764` | `PASS` | **OPTIONAL ADAPTER** (Supported via `DocumentExtractorPort` when complex layout/tables needed, with `AGPL-3.0` obligations tracked in `license_artifact`) |

---

### 2.3 Adaptive Visual Rendering Telemetry (`Step R0-E`)
*Measured in headed hardware-accelerated Edge/WebView2 Chromium (`1440×900` on `200 Hz` display, `ANGLE Intel UHD Direct3D11`):*
- **`Native` FPS Mode (`Balanced`):** `p50 = 5.0 ms`, `p95 = 5.1 ms`, **`200.0 FPS`**, `0` hidden frames rendered.
- **`Auto` FPS Mode (`Balanced`):** `p50 = 20.0 ms`, `p95 = 20.1 ms` (`50 FPS` on `4 × 5ms` VSync multiple; tuning sub-frame epsilon to `0.55 × VSync` snaps to `3 × 5ms = 15.0 ms` / `66.7 FPS` on `200 Hz` panels!).
- **`Lite` @ `30` FPS:** `p50 = 35.0 ms`, `p95 = 35.1 ms` (`28.6 FPS`).
- **`Reduced Motion`:** `0` continuous `rAF` frames rendered; `100%` of controls active.
- **Safety UX:** Native `<dialog>` `R2` modal trapped focus on **`Tolak (Esc)`**; `Stop` button immediately canceled active state and rejected injected stale out-of-order events (`staleEventsRejected = 1`).

---

## 3. Verified Artifact SHA-256 Manifests (`R0` Sandbox)

| Artifact | Upstream Source | Size (Bytes) | Verified `SHA-256` |
| :--- | :--- | ---: | :--- |
| `llama-vulkan.zip` | `ggml-org/llama.cpp b12774` | `39,160,850` | `d29a16265d26ef7598209caaf1a544cbfa6abe2858c24b0ce4ae6bff87a76f22` |
| `llama-cuda.zip` | `ggml-org/llama.cpp b12774` | `357,985,904` | `7c2f8e99f7ffe244e5cba92e6c2b65f1d04fbabe8d4eb304d3fa200778ccf8f3` |
| `cudart-cuda.zip` | `ggml-org/llama.cpp b12774` | `391,443,627` | `8c79a9b226de4b3cacfd1f83d24f962d0773be79f1e7b75c6af4ded7e32ae1d6` |
| `silero_vad.onnx` | `k2-fsa/sherpa-onnx` | `643,854` | `9e2449e1087496d8d4caba907f23e0bd3f78d91fa552479bb9c23ac09cbb1fd6` |
| `piper-id.tar.bz2` | `rhasspy/piper-voices id_ID-news_tts-medium` | `67,243,848` | `634b0169fe41c368e9fafe128f30647f9e0301e852ce503cd78146db524f1f12` |
| `Qwen3-1.7B-Q4_K_M.gguf` | `bartowski/Qwen_Qwen3-1.7B-GGUF` | `1,282,439,584` | `72c5c3cb38fa32d5256e2fe30d03e7a64c6c79e668ad84057e3bd66e250b24fb` |
| `Qwen3-4B-Q4_K_M.gguf` | `Qwen/Qwen3-4B-GGUF` | `2,497,280,256` | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` |

---

## 4. Final Locked `R0` Recommended Stack Decisions (`DEC-026` – `DEC-030`)

Per Owner directive to adopt the best empirically proven recommendations:
- **`DEC-026` (Python & Wheel Lock):** Lock development baseline on **`CPython 3.11.9` + `uv 0.13+`** (`76+` core/voice/PDF/vector wheels verified resolved and imported on `win_amd64`). Include explicit `requests` + `scikit-learn` alongside `openwakeword --no-deps` when `openWakeWord` adapter is enabled.
- **`DEC-027` (Default Multi-Backend LLM Provisioning):** Ship `LlamaCppServerAdapter` (supporting **`Vulkan`** `~37 MB` universal GPU/CPU binary as lightweight cross-vendor default + optional **`CUDA`** binary for maximum NVIDIA throughput, always passing **`--jinja --reasoning-budget 0`** on non-thinking/tool turns) AND `OllamaAdapter` (`external_local` / `managed_local`) behind `LlmProviderPort`. Recommend `Qwen3-1.7B-Q4_K_M` (`Balanced` / CPU-only `≥ 16 GB`) and `Qwen3-4B-Q4_K_M` (`Q8_0` KV `Quality` on `≥ 4 GB` free VRAM).
- **`DEC-028` (Voice Engine Selection & Compliance):** Default STT to **`faster-whisper small` (`int8`)** on `≥ 16 GB` RAM hosts (`base` optional for low-RAM `Eco`), neural TTS to **`piper-tts` (`GPL-3.0-or-later`)** with optional user-downloaded voices (displaying upstream `MODEL_CARD` dataset attribution) + dynamically probed **WinRT OneCore** instant offline fallback, and enforce **Endpoint-Aware Open-Speaker Echo Guard**.
- **`DEC-029` (Document Extraction & Vector Storage):** Default `R2` PDF extraction to **`pypdfium2` + `pypdf` fallback** (`4.25×` faster, permissive `Apache-2.0/BSD-3`), keeping `PyMuPDF` (`AGPL-3.0`) as an optional pluggable extractor tracked in `license_artifact`; lock **`sqlite-vec v0.1.9`** for `jarvis_knowledge.db` generation-scoped vector search.
- **`DEC-030` (UI Frame Pacing Refinement):** Adopt the **Orbital Precision** SVG + `Motion` + DPR-capped Canvas 2D design system, refining the `Auto`/`60` VSync sub-multiple threshold (`targetMs - 0.55 × estimatedVsyncMs`) so `200 Hz` monitors snap to `66.7 FPS` (`15.0 ms <= 20.0 ms` `NFR-13`) rather than `50.0 FPS` (`20.0 ms`).

---

## 5. Proposed Phase 2 Scaffolding Scope (Awaiting Gate `G1`/`G2` Go-Ahead)

Before creating production application directories (`DEC-014`), the exact Phase 2 (`Wave 2 — Project Foundation: B02, B03, B04, B29, B30, B32`) actions proposed next are:
1. Scaffold `apps/desktop/` (official Tauri 2 + React 19 + TypeScript + Tailwind v4 + `Motion` with `package-lock.json`, routing Rust `CARGO_TARGET_DIR` via gitignored `.cargo/config.toml` / `.jarvis.dev.local.toml` to `%LOCALAPPDATA%\Jarvis-Build-Cache` so workspace `D:` stays clean).
2. Scaffold `core/` (`uv` Python `3.11.9` package with `domain/`, `application/`, `providers/`, `platform/windows/`, `workers/`, `transport/`, and checksummed SQL migrations for `jarvis_core.db` & `jarvis_knowledge.db`).
3. Implement and test (`100%` Tier A offline `pytest` + `vitest` green):
   - The 9 Platform Portability Ports (`NFR-16` CI boundary check)
   - Named Pipe + 256-bit token `LocalIpcTransportPort` & `Job Object` `ProcessSupervisorPort` (`B03`)
   - Dual SQLite WAL + `AES-256-GCM` sensitive field encryption + `Argon2id` backup core (`B03`)
   - Deterministic `R0`–`R3` Policy Engine & `R2` nonce/hash approval core (`B04`)
   - `SystemCapabilityDiscovery`, `ConfigRecommendationEngine`, `11-Root Dynamic Storage Manager`, and `11-Category License Inventory + SBOM` (`B29`, `B30`, `B32`).
