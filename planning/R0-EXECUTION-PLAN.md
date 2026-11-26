# R0 TECHNICAL FEASIBILITY EXECUTION PLAN — J.A.R.V.I.S.

**Document ID:** `PLAN-11`  
**Phase:** Transition Gate `G0 → R0` (`DEC-014` Explicit Pre-Execution Proposal)  
**Date:** 26 November 2026  
**Authorization Required:** Explicit Owner Approval (`L2` Tooling/Deps + `L3` Model Downloads & Bounded Benchmarks)  
**Status:** Prepared & Ready — **NO Downloads, Installations, or Benchmarks Executed Yet**

---

## 1. Purpose & Strict Execution Boundaries

Per `DEC-014`, this document specifies the **exact installation requirements, download sizes, commands, directory layout, benchmark scope, resource ceilings, and rollback procedure** for the **Phase 1 / `R0` Technical Feasibility Spike (`B01`, `B22`, `B23`)**.

### Safety & Portability Commitments for `R0`
1. **Zero System-Wide Pollution**: All temporary `R0` virtual environments, runtime binaries, candidate models, and benchmark logs are isolated inside a single configurable sandbox directory (proposed machine-local dev path: `%LOCALAPPDATA%\Jarvis-R0-Sandbox\`, keeping the workspace drive untouched and keeping personal paths out of Git via `.jarvis.dev.local.toml`).
2. **Bounded Resource Caps (No Stress/Soak Tests in `R0`)**:
   - Maximum single benchmark run duration: **`≤ 5 minutes`** per sub-spike (immediately cancelable via `Ctrl+C` + `Job Object` / `bounded_exec` timeout).
   - CPU thread cap during CPU spikes: **`≤ 6` logical threads** (`50%` of the 12-thread i5-11400H) at `BelowNormal` priority so desktop responsiveness is never degraded.
   - GPU VRAM ceiling during CUDA spikes: abort test cleanly if NVML process VRAM exceeds **`3,350 MiB`**.
   - **Zero `8-hour` soak tests** (`NFR-12` is deferred strictly to Phase 6 Release Gate).
3. **Zero Uncommitted Secrets or Binaries**: `.gitignore` blocks all `.gguf`, `.onnx`, `.venv`, `node_modules`, and `.local` files; only redacted Markdown/JSON summary metrics and license inventories enter `planning/r0-evidence/`.

---

## 2. Exact Installation & Download Budget

### 2.1 Development Toolchain & Sandbox Dependencies (`L2`)

| Component | Purpose in `R0` | Install Method (Proposed) | Approx. Download | Approx. Disk Installed | License |
| :--- | :--- | :--- | ---: | ---: | :--- |
| **`uv`** (Astral Python pkg manager) | Lock & manage isolated `Python 3.11.9` R0 venv (`DEC-004`) | `winget install --id=Astral-sh.uv -e` *(or standalone zip into sandbox)* | `~18 MB` | `~42 MB` | `Apache-2.0 OR MIT` |
| **R0 Python `3.11.9` Venv Wheels** | `faster-whisper`, `sherpa-onnx`, `openwakeword` (`--no-deps`), `onnxruntime`, `sounddevice`, `pycaw`, `winrt-Windows.Media.SpeechSynthesis`, `pymupdf`, `pypdfium2`, `pypdf`, `sqlite-vec`, `nvidia-ml-py`, `httpx`, `pydantic` | `uv venv --python 3.11.9` + `uv pip install ...` inside `Jarvis-R0-Sandbox\.venv` | `~260 MB` | `~620 MB` | Mixed (`MIT`, `Apache-2.0`, `BSD`, `AGPL-3.0` evaluated under `DEC-022`) |
| **`llama.cpp` Prebuilt Binaries** | Reference Adapter 1 (`llama-server.exe` CPU/Vulkan + CUDA 12.4/13.x x64 official GitHub release zip) | Download official `ggml-org/llama.cpp` release zip + verify SHA-256 into `Jarvis-R0-Sandbox\runtimes\llama-cpp\` | `~95 MB` *(CUDA DLLs + server)* | `~240 MB` | `MIT` (+ NVIDIA CUDA runtime redistributable EULA) |
| **`Ollama` Local Runtime** *(Optional in R0)* | Reference Adapter 2 (`DEC-006` portability proof); **skip if you prefer testing `llama-server` CPU vs CUDA/Vulkan first** | Official `OllamaSetup.exe` *(or portable zip into sandbox)* | `~680 MB` | `~1,450 MB` | `MIT` |
| **R0 UI Render Spike (`B23`)** | Measure `Motion` + SVG + Canvas 2D across `Auto/30/60/120/Native` FPS in WebView2 / Chromium | Isolated `Jarvis-R0-Sandbox\ui-spike` (`npm ci` with `vite`, `react`, `motion`) | `~65 MB` | `~180 MB` | `MIT` |
| **Subtotal Tooling & Runtimes** | — | — | **`~0.44 GB`** *(without Ollama)* / **`~1.12 GB`** *(with Ollama)* | **`~1.08 GB` – `2.53 GB`** | — |

### 2.2 Candidate AI & Voice Models for `R0` Evaluation (`L3`)

All downloads verify upstream Hugging Face commit revision + `SHA-256` digest and record `MODEL_CARD` licenses before execution:

| Role | Candidate Artifact | Upstream Source | Download Size | License (Code / Weights / Dataset Check) | Required in R0? |
| :--- | :--- | :--- | ---: | :--- | :---: |
| **LLM Small (CPU & GPU)** | `Qwen3-1.7B-Q4_K_M.gguf` | `Qwen/Qwen3-1.7B-GGUF` | `~1.13 GB` | `Apache-2.0` | **Yes** |
| **LLM Medium (4 GB GPU Ceiling Check)** | `Qwen3-4B-Q4_K_M.gguf` | `Qwen/Qwen3-4B-GGUF` | `~2.50 GB` | `Apache-2.0` | **Optional** *(recommended to verify 4 GB VRAM ceiling; can run after 1.7B passes)* |
| **STT Candidate A & B** | `faster-whisper-base` & `faster-whisper-small` (`int8` CTranslate2) | `Systran/faster-whisper-{base,small}` | `~145 MB` + `~484 MB` | `MIT` | **Yes** |
| **Wake & VAD** | `silero_vad.onnx` + `openWakeWord` ONNX (`hey_jarvis`) + `sherpa-onnx` keyword spotter tiny | Official HF / GitHub releases | `~65 MB` total | `MIT` / `Apache-2.0` / **`CC-BY-NC-SA 4.0`** (`openWakeWord` weights — logged in inventory) | **Yes** |
| **TTS Indonesian & English** | `id_ID-news_tts-medium.onnx` + `en_US-lessac-medium.onnx` (+ `piper` standalone CLI zip for comparison vs `sherpa-onnx`) | `rhasspy/piper-voices` & `OHF-Voice/piper1-gpl` | `~155 MB` total | Engine: `GPL-3.0` (`piper`) vs `Apache-2.0` (`sherpa-onnx`); Voice card inspected in R0 | **Yes** |
| **Subtotal Candidate Models** | — | — | **`~2.04 GB`** *(core set)* / **`~4.54 GB`** *(with `Qwen3-4B`)* | — | — |

### Total `R0` Sandbox Footprint Summary
- **Minimum Core `R0` (`1.7B` + Voice + `llama-server` CPU/CUDA, without `Ollama`/`4B`)**: **`~2.48 GB` download**, **`~3.2 GB` disk** on `C:` (`79.53 GB` currently free → `~76.3 GB` remaining).
- **Full `R0` (`1.7B` + `4B` + `Ollama` + Voice + UI Spike)**: **`~5.66 GB` download**, **`~7.1 GB` disk** on `C:` (`79.53 GB` currently free → `~72.4 GB` remaining; **`0 MB` added to `D:`**).

---

## 3. Step-by-Step `R0` Spike Scope & Exact Proposed Commands

Nothing below runs until approved:

### Step `R0-A`: Sandbox Directory & Reproducible Python `3.11.9` Lock (`B01` / `DEC-004`)
```powershell
$Sandbox = Join-Path $env:LOCALAPPDATA "Jarvis-R0-Sandbox"
New-Item -ItemType Directory -Force -Path "$Sandbox\models", "$Sandbox\runtimes", "$Sandbox\results"
# Create isolated Python 3.11.9 virtual environment via uv and resolve exact lockfile
uv venv "$Sandbox\.venv" --python 3.11.9
```
- **Verification Output**: Exact resolved versions, wheel tags (`cp311-win_amd64`), import health check, and initial 11-category license table (`FR-SYS-05`).

### Step `R0-B`: Hardware Capability Discovery & Storage Validator Prototype (`DEC-016`, `DEC-019`)
- Run read-only Python capability probe detecting CPU/ISA, total/free RAM, NVML/DXGI GPUs, local vs network volumes, installed WinRT/SAPI voices (verifying `MSTTS_V110_idID_Andika` dynamically rather than assuming), and display refresh rates (`200 Hz`), outputting a sample `HardwareSnapshot` + `ConfigRecommendation` JSON (`CPU-only` simulated vs `GPU` detected).

### Step `R0-C`: Voice Pipeline & Document Parser Quality/License Benchmark (`B01` / `DEC-009`)
- **STT**: Run synthetic/recorded consented 50–200 utterance Indonesian + English app-name test set on `faster-whisper` `base` vs `small` (`int8`, `4` CPU threads), measuring WER, p50/p95 latency, and peak RAM.
- **TTS & Echo**: Compare `Piper id_ID-news_tts-medium` via `piper.exe` (`GPL-3.0`) vs `sherpa-onnx` (`Apache-2.0`) vs dynamically probed WinRT `Andika`, plus open-speaker playback self-trigger check.
- **PDF Extraction (`DEC-022`)**: Compare `PyMuPDF` (`AGPL-3.0`) vs `pypdfium2` (`Apache-2.0/BSD-3`) + `pypdf` on 10 multi-layout PDF fixtures (speed, heading/page locator fidelity, and exact license compliance matrix).

### Step `R0-D`: Dual-Backend / Dual-Adapter LLM Conformance & Memory Envelope (`B22` / `DEC-006`)
- Test `Qwen3-1.7B-Q4_K_M` on **both CPU-only mode** (validating portable CPU-only user experience!) and **CUDA mode** (and `Qwen3-4B-Q4_K_M` with `-fa -ctk q8_0 -ctv q8_0` if approved), plus `Ollama` conformance if approved.
- Execute 50 deterministic + 50 mixed Indonesian/English intents + 50 adversarial schema/injection prompts (`enable_thinking=false` + JSON Schema `extra="forbid"`), recording TTFT, `tok/s`, schema pass rate, peak RAM/VRAM, and graceful fallback when simulated VRAM ceiling is lowered.

### Step `R0-E`: Adaptive Visual Rendering Engine & Styleframe Prototype (`B23` / `DEC-010`)
- Launch minimal isolated Vite + React + `Motion` + SVG/Canvas 2D prototype demonstrating the **Orbital Precision** 12-state Intelligence Core, 10-step Onboarding preview, Storage/Runtime Manager wireframes, `<dialog>` `R2` approval card, and configurable FPS governor (`Auto`, `30`, `60`, `120`, `Native`).
- Capture Chromium/WebView2 frame-interval traces (`p50`/`p95`, GPU process placement telemetry, hidden-window `0` loop check) with and without concurrent local LLM generation.

---

## 4. Clean Rollback & Teardown Procedure

At any point during or after `R0`:
1. Every spawned `R0` worker runs under bounded timeout + Windows Job Object (`KILL_ON_JOB_CLOSE`), ensuring zero lingering background processes once the benchmark script exits.
2. Deleting the single sandbox folder completely removes all `R0` wheels, downloaded models, and temporary binaries without touching the Git repository or Windows registry:
   ```powershell
   Remove-Item -LiteralPath (Join-Path $env:LOCALAPPDATA "Jarvis-R0-Sandbox") -Recurse -Force
   ```
3. If `Ollama` or `uv` was installed via `winget` and is no longer desired, `winget uninstall` removes it cleanly.
