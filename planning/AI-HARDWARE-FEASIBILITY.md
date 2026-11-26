# HARDWARE-ADAPTIVE AI FEASIBILITY & RESOURCE GOVERNANCE — J.A.R.V.I.S.

**Document ID:** `PLAN-06`  
**Version:** 0.2.1 (Revised for Hardware-Agnostic Adaptation Across User Machines)  
**Baseline Evaluated:** `JARVIS-SDLC-v0.2.1/01-PRD.md`, `06-AI-VOICE-DESIGN.md`, `12-TEST-STRATEGY.md`  
**Date:** 26 November 2026  
**Status:** Analytical Multi-Tier Feasibility Complete (Empirical `R0` Execution Pending Approval of [R0-EXECUTION-PLAN.md](R0-EXECUTION-PLAN.md))

---

## 1. Hardware-Adaptive Philosophy (`DEC-016`, `DEC-020`)

JARVIS is designed to run across a wide spectrum of personal computers — **not** exclusively on the developer's `RTX 3050 Laptop 4 GB` workstation:
1. **Dynamic Capability Discovery Over Static Assumptions**: Available RAM and GPU VRAM are never static constants. OS compositors (`WDDM`), multi-monitor setups, web browsers, games, and external AI daemons consume variable memory at any moment. `HardwareDiscoveryPort` and `ResourceGovernor` inspect **currently available** RAM/VRAM before every model admission.
2. **Full Support Spectrum**:
   - **Zero-Model *Direct Mode*** works on **any** supported Windows x64 PC (`0` VRAM, minimal RAM) for deterministic OS control, reminders, memory, and life management (`FR-COR-06`).
   - **CPU-Only Inference** enables full local voice + compact LLM capabilities on laptops without discrete GPUs.
   - **Discrete & Integrated Accelerators** scale smoothly across entry `4 GB` GPUs, `8–16 GB` mid-range GPUs, `24 GB+` enthusiast GPUs, compatible `Vulkan`/`ROCm`/Intel runtimes, and `R2` authorized private LAN servers.
3. **Honest Support Labels**: Every hardware/backend combination is surfaced in the UI as **`Supported`**, **`Experimental`**, **`Unverified`**, or **`Unsupported`** based on actual test evidence — never claimed universally without verification.

---

## 2. Multi-Tier Hardware Adaptation Matrix (Illustrative Targets, Not Unverified Guarantees)

| User Hardware Class | Backend Candidate | Recommended Model Tier | Visual Default | Support Classification (Initial) | Key Engineering Notes |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Low-Spec CPU-Only**<br>`8 GB` System RAM | `CPU` (`int8`/`Q4`, `2–4` threads) | *Direct Mode* primary + on-demand `0.5B–1.7B` Q4 (`2048` ctx, immediate `0s` idle unload) + `whisper-tiny/base` | `Lite` | `Supported` (Direct) / `Experimental` (LLM) | Aggressive idle unload prevents OS swap thrashing. |
| **Standard CPU-Only**<br>`≥ 16 GB` System RAM | `CPU` (`AVX2`/`AVX-512`, `4–8` threads) | `1.7B` Q4 (`2048–4096` ctx) + `whisper-base/small int8` | `Balanced` | `Supported` *(verify in R0 CPU mode)* | Uses `Step R0-D` CPU-only benchmark to establish honest latency expectations. |
| **Entry Discrete GPU *(Ref Dev Class)***<br>`~4 GB` VRAM + `≥ 16–24 GB` RAM | `CUDA` (or `Vulkan`) + CPU audio | `1.7B` Q4 (`Balanced`, ~1.7 GiB est.) up to `4B` Q4 (`Quality` with `Q8_0` KV cache ~3.1 GiB est. **only when live free VRAM permits**) | `Balanced` | `Supported` *(primary R0/R1 hardware gate)* | If another app/game occupies VRAM, `ResourceGovernor` automatically falls back to partial offload, `1.7B`, CPU, or *Direct Mode*. |
| **Mid-Range Discrete GPU**<br>`8–12 GB` VRAM | `CUDA` / `Vulkan` | `4B–8B` Q4/Q5 (`4096–8192` ctx); concurrent warm retention comfortable | `Cinematic` | `Unverified` *(until tested on 8–12 GB host)* | Configurable via *Recommended Setup* + Model Manager without code changes. |
| **High-VRAM Workstation**<br>`≥ 16–24 GB` VRAM | `CUDA` / compatible | `14B+` quantized models, extended context, local vision without immediate eviction | `Cinematic` | `Unverified` *(until tested on 24 GB host)* | Unlocked automatically via `HardwareDiscoveryPort` VRAM capacity probe. |
| **AMD / Intel GPUs** | Runtime `Vulkan` / `ROCm` / SYCL adapters | Sized to detected dedicated/shared GPU memory budget | `Adaptive` | `Experimental` / `Unverified` | Supported cleanly through `llama-server` Vulkan/hipBLAS or `Ollama` without changing JARVIS Core. |
| **Authorized Private LAN (`R2`)** | `HTTPS` to enrolled LAN AI server | User-selected server model (with explicit data-scope consent) | `Cinematic` / `Balanced` | `Supported` in `R2` | Zero local GPU load; never used as a silent fallback (`FR-AIP-06`). |

---

## 3. Reference Development Host Analytical Envelope (`RTX 3050 Laptop 4 GB` + `i5-11400H`)

On the inspected developer machine (`39.74 GB` RAM installed; `4,096 MiB` total RTX 3050 VRAM with `3,962 MiB` free at idle snapshot; `i5-11400H` 6C/12T), analytical memory and latency budgets (to be empirically verified in `R0`) are:

### 3.1 Analytical VRAM Estimates on 4 GB Class GPUs (`[ASSUMPTION — VERIFY IN R0]`)
- **`Qwen3-1.7B-Q4_K_M` (`4096` ctx, `Q8_0` KV)**: `~1.13 GiB` weights + `~0.23 GiB` KV + `~0.32 GiB` compute buffer ≈ **`~1.68 GiB`**. Leaves ample headroom on a 4 GB card under normal desktop usage.
- **`Qwen3-4B-Q4_K_M` (`3072–4096` ctx)**: With `FP16` KV cache (`~3.43 GiB`), peak usage risks exceeding `3.3 GiB` (`NFR-02`) and triggering WDDM PCIe paging if browsers/WebView2 use discrete VRAM. With **`Q8_0` KV cache + FlashAttention (`~3.05–3.12 GiB`)** and live NVML free-VRAM admission gating, it fits when the GPU is otherwise lightly loaded, and degrades cleanly to partial CPU layer offload or `1.7B` when VRAM is busy.
- **Non-Thinking Mode Requirement**: Disabling default `<think>` generation (`enable_thinking=false` / `think=false`) on `Qwen3` models keeps structured tool-proposal output compact (`~25–45` tokens instead of `400+` reasoning tokens), preventing `512`-token truncation and preserving low voice latency.

### 3.2 Stage-by-Stage Voice Latency Target Model (`Reference Host`, `NFR-01`)
- **Direct Deterministic Path (`target p95 ≤ 4.0s`)**: VAD silence tail (`~0.35s`) + local CPU `int8` STT (`~0.5–1.3s`) + deterministic router & policy (`~0.02s`) + OS action & readback (`~0.1–0.3s`) + local TTS first clause (`~0.15–0.25s`) ≈ **`~1.2–2.3s` projected**.
- **Warm Simple LLM Path (`target p95 ≤ 12.0s`)**: Adds compact prompt + non-thinking JSON/first-sentence generation (`~0.6–1.6s` on GPU; `~2.5–5.5s` on CPU-only `1.7B`), keeping both GPU reference (`~2.0–4.0s`) and modern multi-core CPU (`~4.5–8.5s`) within interactive voice usability targets (measured and reported separately per hardware tier in `R0`).

---

## 4. Flexible Runtime Ownership & Configurable Knobs (`DEC-020`, `FR-AIP-08`)

Runtime Manager exposes both **Automatic (*Recommended*)** and **Manual Override** controls across four ownership modes:
1. **`managed_local`**: JARVIS starts, monitors, idles/unloads, and terminates the worker (`ProcessSupervisorPort`).
2. **`external_local`**: Connects to an existing user-managed `Ollama` or `llama.cpp` server; JARVIS probes capabilities and respects capacity, **never stopping or reconfiguring the user's process on exit**.
3. **`authorized_lan` (`R2`)**: Connects to an explicitly enrolled private-network server with TLS verification and per-scope consent.
4. **`custom_compatible`**: Connects to any additional local/private provider passing the adapter conformance probe.

**Configurable Runtime Parameters (where supported by backend)**: Inference backend (`Auto`, `CPU`, `CUDA`, `Vulkan`), GPU device selector, GPU layer offload count, CPU thread cap, context window limit, lifecycle policy (`always_loaded`, `on_demand`, `idle_unload` + timeout), OS process priority (`low`, `normal`, `high`), CPU/RAM/VRAM ceilings, OS startup & background mode, battery-saver downgrade policy, and fullscreen-gaming pause/throttle policy.
