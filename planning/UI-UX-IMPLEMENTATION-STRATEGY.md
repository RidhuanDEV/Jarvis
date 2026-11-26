# ADAPTIVE CINEMATIC UI/UX & PERSONALIZATION STRATEGY — J.A.R.V.I.S.

**Document ID:** `PLAN-07`  
**Version:** 0.2.1 (Revised for Adaptive Rendering, 10-Step Onboarding & Dynamic Personalization)  
**Baseline Evaluated:** `JARVIS-SDLC-v0.2.1/01-PRD.md`, `02-SRS.md`, `10-UX-DESIGN.md`  
**Date:** 26 November 2026  
**Status:** Design System, Onboarding & Adaptive Rendering Blueprint (`DEC-010`, `DEC-015`, `DEC-018`)

---

## 1. Experience Vision: "Orbital Precision OS" + Effortless Portability

JARVIS delivers an original, tactile sci-fi industrial Personal Intelligence Operating System that feels effortless for everyday users (**1-Click Recommended Setup**) while giving power users complete control over visuals, storage, runtimes, and persona:
1. **Original Visual Identity & Anti-Slop Discipline**: Centered around one state-driven **Interactive Intelligence Core**, precision SVG reticle geometry, and truthful live telemetry — free of copied movie assets, generic 4-card AI dashboard templates, fake terminal costumes, invented numbers, excessive glassmorphism (`≤ 2` surfaces), or meaningless pulsing status dots.
2. **Truthful State & Hardware Privacy Indicators**: All 12 engine states (`Startup`, `Idle`, `Listening`, `Transcribing`, `Thinking/Loading`, `Executing`, `Approval`, `Speaking`, `Success`, `Error/Degraded`, `Muted/Locked`, `Offline`) are driven by monotonic `(request_id, seq)` backend events. Explicit text+icon badges always display real Microphone, Camera, Network (`Offline` vs `Online`), and Runtime Location (`Direct` / `Local` / `LAN`) states.

---

## 2. Guided 10-Step First-Run Onboarding (`DEC-018`, `FR-ADM-07`)

Designed so any user on any PC can install the lightweight base installer and get running without touching configuration files or source code:

| Step | Screen Focus | *Recommended Setup* Default | User Override Capabilities |
| :---: | :--- | :--- | :--- |
| **1** | **System Capability Discovery** | Displays detected CPU, RAM, GPU/VRAM, disks, audio, display `Hz`, and battery state with **1-Click Recommended Setup** CTA | Inspect detailed hardware snapshot & support tier badges (`Supported`/`Experimental`/`Unverified`) |
| **2** | **Storage Location Selection** | OS-standard user app directory (`%LOCALAPPDATA%\Jarvis`) validated for free space & local FS | Redirect any of the 11 paths (e.g., place `models` or `backups` on secondary SSD or point to an existing shared model folder) |
| **3** | **AI Runtime Selection** | Selects existing local runtime if healthy, or offers managed local runtime / *Direct Mode* | Choose `managed_local`, `external_local` (`Ollama`/`llama-server`), `authorized_lan` (`R2`), or *Skip AI Runtime (Direct Mode Only)* |
| **4** | **AI Model Selection** | Recommends best-fit model tier for detected RAM/VRAM (showing exact GB size, disk needed, RAM/VRAM est., and license) | Import existing local `.gguf`/`.onnx` files, pick alternative model size, or defer download entirely |
| **5** | **Resource Budget** | Safe proportional RAM/VRAM/CPU ceilings + `120s` idle unload + battery/gaming conservation | Tune GPU offload layers, CPU threads, context window, keep-warm policy, and gaming pause rules |
| **6** | **Audio & Voice Setup** | Selects active OS default mic/output and verifies actually installed local/OS voices | Pick specific input/output devices, test mic level & echo guard, choose wake word vs PTT, test voice speed/pitch |
| **7** | **Language & Persona** | Bahasa Indonesia primary + auto-detected OS IANA timezone + concise professional persona + `22:00–07:00` quiet hours | Configure primary language, multilingual code-switching, timezone override, persona tone, verbosity, and quiet hours |
| **8** | **Visual Quality & FPS** | Recommends `Cinematic` / `Balanced` / `Lite` (or `Reduced Motion` if OS accessibility flag is on) + `Auto` FPS | Choose tier manually and set FPS limit (`Auto`, `30`, `60`, `120`, `Native`) |
| **9** | **Permissions (`Deny-by-Default`)** | All network, folder, screen, and app grants start **disabled** | Opt-in to specific desktop apps (`Win32`/`AUMID`) and approved document folders |
| **10** | **Validation & Readiness** | Runs offline smoke check (`IPC`, `core.db`, audio/text readiness) and launches Command Center | Export clean configuration profile JSON (sans secrets) |

---

## 3. Adaptive Visual Rendering Engine (`DEC-010`, `FR-UX-03`, `FR-UX-04`)

Instead of hardcoding `Intel UHD` or locking animations permanently to `60 FPS`, JARVIS implements a hardware-aware **Adaptive Visual Rendering Engine**:

| Dimension | Architectural Implementation |
| :--- | :--- |
| **Visual Quality Profiles** | 1. **`Cinematic`**: Full layered orbital geometry, subtle depth/particles, coordinated layout choreography.<br>2. **`Balanced`** *(default)*: Crisp SVG core, smooth state & spring transitions, low GPU footprint.<br>3. **`Lite`**: Static precision geometry + low-frequency state updates, zero blur/particles.<br>4. **`Reduced Motion`**: Honors OS `prefers-reduced-motion` or manual toggle unconditionally (`BR-UX-02`); replaces continuous motion with calm `120ms` opacity transitions and full functional parity. |
| **Configurable Frame-Rate Targets** | User-selectable **`Auto`**, **`30`**, **`60`**, **`120`**, or **`Native`** FPS ceiling. In `Auto` mode, the scheduler adapts to detected display refresh rate (`60 Hz`, `120 Hz`, `144 Hz`, `200 Hz+`), AC vs. battery power, and active AI inference load — scaling smoothly on capable desktop GPUs when headroom exists and throttling cleanly during heavy inference or battery use. |
| **WebView2 Hardware Acceleration & Telemetry** | Keeps WebView2 hardware acceleration **enabled by default** per Microsoft best practices (`REF-23`). Rather than assuming iGPU vs. dGPU placement, JARVIS exposes GPU rendering preference options where supported by OS/WebView flags and measures actual frame intervals (`p50`/`p95`, long frames) + GPU memory telemetry (`NFR-13`). |
| **Rendering Technology Roadmap** | **Initial Foundation (`R1`)**: Vector SVG + `Motion` (`useMotionValue` zero-React-rerender transforms) + DPR-capped Canvas 2D for `≤ 30 Hz` interpolated audio envelopes. **Future Openness**: WebGL / Three.js remains an open, benchmark-gated option for `Cinematic / Advanced` scenes on high-headroom GPUs whenever empirical R0/R2 traces demonstrate clear visual value within resource budgets. |
| **Contextual Suspension** | Continuous `requestAnimationFrame` loops pause immediately when the window is hidden/minimized to tray or the workstation is locked (`0` background animation loop cost), and step down with `~15s` hysteresis during sustained CPU/GPU pressure or fullscreen gaming. |

---

## 4. Semantic Tokens, Core Surfaces & Accessibility (`WCAG 2.2 AA`)

- **Verified Contrast Tokens**: Deep slate/obsidian surfaces (`#080D17`, `#101927`) paired with high-legibility text (`#E6F1FF` `14.2:1+`, `#A9B9CC` `8.1:1+`), focal cyan (`#57DFFF` `10.9:1`), approval amber (`#FFBE69` `10.1:1`), and error crimson (`#FF737C` `6.4:1`). Tabular numerals (`tabular-nums`) prevent layout shift on live timers and metrics.
- **Interactive Craft & Native `<dialog>` Approval**: Every interactive element provides all 5 states (`default`, `hover`, `active`, `:focus-visible` `≥ 3:1` outline, `disabled`) with explicit `cursor: pointer` / `cursor: not-allowed`. `R2` approvals render exclusively in a native modal `<dialog>` with initial focus on the safe *Reject/Inspect* control, `60s` countdown, and voice-approval hard-disabled.
- **Dedicated Management Views**:
  - **Dynamic Storage Manager**: Visualizes drive free space across volumes, edits all 11 paths, sets cache quotas (`10/25/50 GB/Custom/Unlimited`), links shared model folders, and runs staged cross-drive migrations (`R2`).
  - **Runtime & Model Manager**: Manages the 4 runtime ownership modes, backend/GPU/thread/context/battery/gaming knobs, SHA-256 & license badges, atomic profile switching, and consent-gated benchmarks.
  - **Dynamic Personalization**: Live switching of primary language, multilingual mode, IANA timezone, voice engine/speed/pitch, wake phrase, persona style, verbosity, and quiet hours (`DEC-015`).
