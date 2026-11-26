# PROJECT DISCOVERY — J.A.R.V.I.S. Personal Intelligence System

**Document ID:** `PLAN-01`  
**Version:** 0.2.1 (Revised for Hardware-Adaptive & Open-Source-Ready Orientation)  
**Baseline Evaluated:** `JARVIS-SDLC-v0.2.0` (preserved at Git tag `sdlc-v0.2.0`) → Updated to `JARVIS-SDLC-v0.2.1`  
**Date:** 26 November 2026  
**Status:** Completed & Updated with Owner Architectural Revisions (`DEC-001`–`DEC-025`)

---

## 1. Executive Summary & Product Orientation

JARVIS is engineered as a **private-first, open-source-ready, hardware-adaptive, local-first Personal Intelligence Operating System** governed by the principle:

> **"Convention over configuration, with full configuration overrides."**

Every statement in this discovery baseline carries an explicit epistemic tag (`[EVIDENCE]`, `[ASSUMPTION]`, `[PROPOSAL]`, or `[APPROVED-DIRECTION]`):
1. **Separation of Product Architecture vs. Reference Development Machine `[APPROVED-DIRECTION]`**:
   - **Product Requirement**: JARVIS must install and adapt cleanly across diverse user machines (CPU-only 8–16 GB laptops, 4 GB entry GPUs, 12–24 GB discrete GPUs, AMD/Intel Vulkan/ROCm candidates, or authorized private LAN inference servers) without requiring users to edit source code or match the developer's drives, audio devices, display refresh rate, timezone, or language.
   - **Reference Development Profile `[EVIDENCE]`**: The inspected host workstation (`Windows 11 Home x64 Build 26200`, `Intel Core i5-11400H`, `39.74 GB RAM`, `NVIDIA RTX 3050 Laptop 4 GB VRAM`, `Intel UHD Graphics` driving `1920×1080 @ 200 Hz`, `C:` `79.53 GB` free / `D:` `23.48 GB` free) is treated strictly as **one empirical test profile**, configured locally via gitignored `.local` settings rather than hardcoded into product logic.
2. **Repository & Canonical SDLC Baseline `[EVIDENCE]`**:
   - Local Git repository initialized on branch `main`; original `v0.2.0` pack preserved intact at annotated tag `sdlc-v0.2.0`.
   - Canonical documentation updated to `JARVIS-SDLC-v0.2.1/` (`19` files, `82 FR + 16 NFR = 98` mapped test cases) with `JARVIS-SDLC-Complete-v0.2.1.md` generated deterministically via `scripts/build_sdlc_complete.py`. Zero application runtime code has been scaffolded yet.
3. **Best-Fit Open-Source Licensing Posture `[APPROVED-DIRECTION]`**:
   - Libraries (`MIT`, `Apache-2.0`, `BSD`, `MPL-2.0`, `LGPL`, `GPL`, `AGPL`) are selected on technical quality, security, and maintainability paired with a strict **11-category Artifact & License Inventory** (`DEC-022`), rather than automatic rejection of copyleft packages.

---

## 2. Workspace & Repository State (`[EVIDENCE]`)

| Path | Role & Governance Status |
| :--- | :--- |
| `.git/` (`tag: sdlc-v0.2.0`) | Local Git repository preserving the untouched `v0.2.0` baseline (`0` remote push configured) |
| `.gitignore` | Blocks secrets, `.local` machine configs, SQLite `.db`/`-wal`, `.gguf`/`.onnx` models, runtimes, and build caches |
| `JARVIS-SDLC-v0.2.1/` (`README.md` + `01`..`18`) | Canonical single-source `v0.2.1` SDLC specification suite (`98` requirements, `25` ADRs, `34` backlog items) |
| `JARVIS-SDLC-Complete-v0.2.1.md` | Automatically generated single-file bundle (`python scripts/build_sdlc_complete.py --check`) |
| `scripts/build_sdlc_complete.py` | Pure Python stdlib documentation bundler and CI sync verifier (`DEC-002`) |
| `planning/` (`11` documents) | Phase 0 audit, gap analysis, architecture, technology, hardware, UX, security, master plan, `DEC-001`–`025`, and `R0-EXECUTION-PLAN.md` |

---

## 3. Reference Development Host Inspection vs. Product Portability Design

The table below separates **what was empirically measured on the developer workstation** from **how JARVIS handles arbitrary user environments in production**:

| Dimension | Measured on Reference Dev Host (`26 Nov 2026`) `[EVIDENCE]` | Portable Product Behavior Across User Machines (`DEC-016`–`DEC-023`) |
| :--- | :--- | :--- |
| **OS & Platform** | Windows 11 Home Single Language x64 (`Build 26200`) | Windows 11 x64 first production target; all OS specifics isolated behind 9 typed platform ports (`NFR-16`). Sensitive DB columns use app-layer `AES-256-GCM` so privacy does not depend on OS edition BitLocker availability. |
| **CPU** | Intel Core i5-11400H (`6C / 12T` @ 2.70 GHz) | `HardwareDiscoveryPort` detects core/thread counts and instruction sets at runtime to recommend thread budgets and CPU-only vs GPU profiles. |
| **System RAM** | `39.74 GB` total (`18.18 GB` free at snapshot) | Dynamic RAM discovery scales recommendations from `8 GB` CPU-only (`Lite` + tiny/direct mode) up to `16 GB`, `24 GB`, `32 GB+` systems. |
| **GPUs & VRAM** | `NVIDIA RTX 3050 Laptop` (`4,096 MiB` total, `3,962 MiB` free at snapshot, `CUDA 13.3`) + `Intel UHD Graphics` | Never assumes 4 GB VRAM or 100% free GPU memory: queries live free VRAM before model admission, supports CPU-only, NVIDIA CUDA, and extension points for Vulkan/ROCm/Intel accelerators labeled honestly (`Supported`/`Experimental`/`Unverified`). |
| **Display & Refresh Rate** | `1920 × 1080 @ 200 Hz` (`Mi Monitor` on Intel UHD at snapshot) | *Adaptive Visual Rendering Engine* detects connected displays/DPI/Hz, keeps WebView2 hardware acceleration enabled, verifies GPU usage via telemetry, and offers `Auto`, `30`, `60`, `120`, and `Native` FPS targets (`FR-UX-04`). |
| **Storage Volumes** | `C:` `79.53 GB` free; `D:` (workspace) `23.48 GB` free | *Dynamic 11-Root Storage Manager* defaults to OS user app directories (`%LOCALAPPDATA%\Jarvis`), never hardcodes `C:`/`D:` or usernames, blocks SMB/UNC for SQLite WAL, supports shared model directories, and provides staged cross-drive migration (`FR-SYS-03`/`04`). |
| **Audio & OS Voices** | 2 mics (`Realtek Array`, `Xiaomi Type-C`), 3 outputs, WinRT `MSTTS_V110_idID_Andika` (`id-ID`) + English voices | Dynamically enumerates endpoints, handles hotplug, adapts speaker vs headphone barge-in, and **probes actually installed OS voices/OCR language packs at runtime** rather than assuming `Andika` exists on every Windows PC (`FR-VOI-06`). |
| **Dev Toolchains** | Rust/Cargo `1.99.0`, VS 2022 C++ BuildTools, WinSDK `26100`, WebView2 `158.0`, Node `v24.22.1`, npm `11.19.1`, FFmpeg `9.0.2`, Git `2.45.1`, Python `3.11.9` (`+ 3.13/3.13t`); `uv`/`ollama`/`nvcc`/`cmake` not installed | Dev builds pin `Python 3.11.9 + uv` (`DEC-004`) and `npm` lockfiles (`DEC-005`), verified through actual `R0` dependency resolution tests rather than unverified wheel claims. End users receive a self-contained minimal installer (`DEC-018`). |

---

## 4. Stakeholder, Actor & Runtime Ownership Matrix

| Principal / Component | Trust & Authority Scope | Key Invariants |
| :--- | :--- | :--- |
| **Local Workstation Owner (Unlocked Native UI)** | Sole trusted authority for `R2` approvals, permission grants, onboarding, storage migrations, LAN enrollment, and mobile pairing | Cannot bypass hard `R3` bans without code/CR change; guided by *Recommended Setup* with full manual override (`BR-SYS-01`). |
| **Open-Mic Voice Input (Owner or Guest)** | Untrusted identity (`wake != authentication`) | Allowed `R0` and granted `R1` actions while unlocked; **zero voice `R2` approval**; muted/canceled immediately on OS lock or suspend. |
| **Managed vs. External AI Runtimes (`DEC-020`)** | Untrusted proposal generators (`0` direct tool/DB/network authority) | JARVIS supervises/stops `managed_local` child workers (`Job Object`), but **never terminates or reconfigures `external_local` runtimes** (e.g., user's existing Ollama) without explicit user authorization (`FR-AIP-08`). |
| **External Content (Docs, Web, Screen OCR) & Paired Mobile (`R3`)** | Untrusted passive data (`RAG tools=[]`, pre-OCR secret redaction) / Narrow authenticated remote channel (`no R2/file/screen`) | Prevents indirect prompt injection (`T02`) and stolen-phone privilege escalation (`T11`). |

---

## 5. Prioritized Assumption Matrix Queued for `R0` Validation

| ID | Assumption Statement | Risk if Falsified | `R0` Verification Procedure ([R0-EXECUTION-PLAN.md](R0-EXECUTION-PLAN.md)) |
| :--- | :--- | :--- | :--- |
| `ASM-01` | Candidate Python `3.11.9` audio, STT, TTS, PDF, and SQLite-vector packages resolve cleanly via `uv` and pass import/smoke checks on Windows x64. | Medium (Wheel conflict requires alternative package or version pin) | Execute `Step R0-A` `uv lock` + automated import & license inventory check. |
| `ASM-02` | Candidate local STT (`faster-whisper` `base`/`small` `int8`) and TTS (`Piper` / `sherpa-onnx` / probed OS voices) meet `≤ 20%` ID WER and `≤ 4s` direct `p95` latency on reference hardware without speaker self-triggering. | High (Degrades voice UX) | Execute `Step R0-C` across holdout ID/EN utterances and open-speaker playback loop. |
| `ASM-03` | `Qwen3-1.7B` (CPU & GPU) and `Qwen3-4B` (`Q8_0` KV on 4 GB GPU) with `enable_thinking=false` pass `≥ 85%` mixed-intent schema conformance across reference adapters (`llama-server` & `Ollama`). | High (Schema failures or VRAM spillover) | Execute `Step R0-D` across 150 intent/adversarial fixtures on CPU and CUDA modes. |
| `ASM-04` | WebView2 SVG + `Motion` + Canvas 2D with configurable FPS targets (`Auto/30/60/120/Native`) meets `p95 ≤ 20 ms` frame pacing (`Balanced @ 60 FPS`) during active inference without starving GPU memory. | Medium (Requires earlier auto-downgrade to `Lite`) | Execute `Step R0-E` Chromium/WebView2 frame & GPU process telemetry trace. |
