# 12 — Hardware Adaptability and Resource Management Audit

This document evaluates whether J.A.R.V.I.S. is genuinely portable and hardware-adaptive across Windows workstations (`core/jarvis/platform/windows/hardware.py`, `core/jarvis/domain/recommendations.py`, `core/jarvis/domain/ai_models.py`, `core/jarvis/infrastructure/providers/local_runtime_manager.py`, `apps/desktop/src/lib/visualEngine.ts`, `scripts/install_local_windows.ps1`).

---

## 1. Hardware Discovery & Resource Governance Matrix

| Capability | Implementation & Source Evidence | Status | Observed Defects & Gaps |
| --- | --- | :---: | --- |
| **CPU Discovery** | `hardware.py:202-203, 226-231` (`psutil.cpu_count`, `platform.processor()`) | **`PARTIAL`** | `platform.processor()` returns cryptic Windows family/stepping string instead of CPU brand; `isa_flags=()` hardcoded empty (`L230`) — never detects AVX2/AVX-512. |
| **GPU & VRAM Discovery** | `hardware.py:77-110, 157-175, 205-212` (`pynvml` for NVIDIA; GDI `EnumDisplayDevicesW` fallback) | **`BROKEN` (AMD/Intel/No-NVML)** | (1) `if vendor != "nvidia":` (`L161`) skips NVIDIA in GDI fallback — if `nvidia-ml-py` is missing, NVIDIA GPU disappears completely; (2) **ALL AMD & Intel GPUs hardcode `vram_total_mib=0, vram_free_mib=0, driver_version=""`** (`L167-169`), breaking GPU profile recommendations (`recommendations.py:153`); (3) misclassifies AMD iGPUs as discrete + assumes `supports_rocm=True` for all AMD (`L170-173`); (4) headless GPUs missed. |
| **RAM Monitoring** | `hardware.py:204` (`psutil.virtual_memory()`) | **`IMPLEMENTED`** | Boot/on-demand snapshot only; **zero continuous runtime RAM pressure monitoring**. |
| **VRAM Monitoring** | `hardware.py:86-98` (`nvmlDeviceGetMemoryInfo`) | **`PARTIAL`** | Snapshot only during `/v1/system/capabilities` or boot; **zero continuous runtime VRAM monitoring or OOM guard**. |
| **Storage Discovery** | `windows/filesystem.py:169-191` (`GetLogicalDrives`, `GetDriveTypeW`, `shutil.disk_usage`) | **`VERIFIED`** | Properly classifies fixed/removable/network drives and rejects UNC/SMB for SQLite WAL. |
| **Audio Device Discovery** | `windows/audio.py:54-93` (legacy WinMM) vs `hardware.py:215-216` | **`BROKEN`** | `hardware.py:216` hardcodes **`audio_endpoints=()`** (placeholder comment); WinMM truncates names at 32 wchars, assumes `idx==0` default, no hotplug, and uses incompatible IDs vs `sounddevice` PortAudio. |
| **Display Discovery** | `hardware.py:126-156` (`EnumDisplaySettingsW`) | **`PARTIAL`** | Reads resolution & Hz accurately (`200 Hz` detected in R0), but hardcodes `scale_percent=100` (`L153`, never queries per-monitor DPI). |
| **Recommendation Engine** | `domain/recommendations.py:1-265` (`recommend_configuration()`) | **`IMPLEMENTED`** | Clean deterministic classification (`Supported`/`Experimental`/`Unverified`/`Unsupported`), **but undermined by `vram=0` for AMD/Intel** and **never applied persistently** by `OnboardingWizard` or `LocalLlmRuntimeManager`. |
| **AI Performance Profiles** | `ai_registry_service.py:67-126` (`direct` + 6 profiles) | **`BROKEN`** | Only `direct` and `balanced` rev 2 work at boot; switching profiles defaults to rev 1 (`role_bindings={}`), disconnecting LLM; `Eco`/`Performance`/`Quality`/`Adaptive`/`Custom` have zero model/knob wiring. |
| **Visual Quality Profiles** | `apps/desktop/src/lib/visualEngine.ts:1-153` | **`PARTIAL`** | 4 tiers + 5 FPS targets + VSync-harmonic pacing work, **but** settings are Zustand-only (lost on restart), `dprCap` is dead (`OrbitalCore.tsx` never uses it), and `onBattery` is never passed from `App.tsx`. |
| **CPU-Only Operation** | `local_runtime_manager.py:67-72, 191` | **`BROKEN`** | `discover_llama_server_binary` appends `llama-vulkan`/`llama-cuda` BEFORE `llama-cpu` even when `has_cuda=False, has_vulkan=False` — causing CPU-only machines to launch GPU binaries with `-ngl 99`! |
| **Power / Battery Policies** | `hardware.py:182-191` | **`PARTIAL` / UNWIRED** | Reads `psutil.sensors_battery()` (`<=20%` heuristic, not OS Energy Saver); `App.tsx` never passes `onBattery` to `OrbitalCore`; `LocalLlmRuntimeManager` ignores battery state. |
| **Gaming / Heavy-Workload Policies** | `domain/ai_models.py:218`, `domain/models.py:324` | **`NOT IMPLEMENTED`** | `gaming_throttle: bool = True` config flag and `DynamicResourceGovernor(..., gaming_active=False)` are **100% dead code** — zero fullscreen/DirectX/GPU-utilization gaming detector exists. |

---

## 2. Complete Inventory of Hardcoded Assumptions (`NFR-16` Audit)

**Positive (`VERIFIED`):** Static contract test `test_t18_zero_hardcoded_developer_paths_or_hardware_in_product_code` passes — **zero developer usernames, personal drive letters, or developer GPU model names exist in `contracts/`, `core/jarvis/`, or `apps/desktop/src/`**.

**Remaining Operational & Architectural Hardcodes Found:**

| Category | Exact Hardcoded Value & Source Location | Impact on Portability |
| --- | --- | --- |
| **Windows-Only Core Instantiation** | `core/jarvis/transport/app.py:615-621` unconditionally instantiates `Windows*Adapter`; `tauri.conf.json:34` targets only `nsis`; `single_instance.rs:64` no-op off Windows | Cannot run on Linux/macOS without factory dispatch on `sys.platform`. |
| **Developer Sandbox Leftover in Script** | `scripts/install_local_windows.ps1:58, 68` probes `%LOCALAPPDATA%\Jarvis-R0-Sandbox\{runtimes,models}`; `L27` overrides `CARGO_TARGET_DIR` to `%LOCALAPPDATA%\Jarvis-Build-Cache\cargo-target` | Dev-only install helper; does not ship a portable end-user installer. |
| **System32 3-App Allowlist** | `desktop_automation.py:13-17, 34` (`calc.exe`, `notepad.exe`, `mspaint.exe`, fallback `"C:\\Windows"`) | Rejects every ordinary user-installed app. |
| **Model Name Ranking** | `local_runtime_manager.py:111-116` (`"4b" in low and "qwen" in low`, `"1.7b"`, `"3b"`) | Forces 4B Qwen over larger models on high-VRAM GPUs. |
| **Language & Locale** | `live_voice_engine.py:845` (`language="id"`), `index.html:2` (`lang="id"`), Indonesian-only UI copy & wake/sleep prompts, `windows/audio.py:128-130` (only LCID `421`/`409`) | Breaks non-Indonesian users & English/ID code-switching. |
| **Timezones** | `jarvisStore.ts:189` (`'UTC'`), `OnboardingWizard.tsx:41-49` (hardcoded 7-city dropdown omitting `Asia/Jakarta` unless auto-detected) | Confusing manual selector; choices not persisted to backend. |
| **Inference & Timing Constants** | `local_runtime_manager.py:188-193` (`-c 4096 -ngl 99 -ctk q8_0`), `lib.rs:46` (`10s` HTTP timeout), `brokerClient.ts:119` (`5s` boot wait), `App.tsx:171` (`350 ms` poll), `live_voice_engine.py:297-307` (`16000 Hz`, `0.45` OWW, `0.42` VAD, `30s` session) | Ignores user `AiConfig` & `AudioConfig` knobs; 10s Rust timeout breaks slow machines. |
| **GPU/Audio Vendor Heuristics** | `hardware.py:167-173` (`vram=0` AMD/Intel, `scale_percent=100`), `windows/audio.py:14-26` (brand substrings `airpods`/`buds`/`realtek`/`hdmi`) | Wrong GPU/headphone classification on diverse workstations. |

---

## 3. Clean-Workstation Installability Verdict

**Can another person install J.A.R.V.I.S. on a different Windows workstation from the released NSIS installer without modifying source code or cloning the repo?**

**NO — `BROKEN` (`F-01`).**
- `JARVIS_0.2.1_x64-setup.exe` (`3.01 MiB`) contains only `jarvis-desktop.exe` and static Vite HTML/JS/CSS (`tauri.conf.json:32-45`). It bundles **no Python interpreter, no `core/jarvis/`, no `.venv`, no `migrations/`, and no `contracts/`**.
- Even if a developer clones the repo and runs `scripts/install_local_windows.ps1`, they must manually install `uv`, sync `--extra voice --extra tts-piper --extra nvidia`, and manually download `llama-server.exe`, GGUF weights, `faster-whisper-small`, `silero_vad.onnx`, `openwakeword` ONNX files, and Piper voice ONNX+JSON into `%LOCALAPPDATA%\JarvisOS\Jarvis\{runtimes,models}\` because **zero in-app runtime/model downloader exists**.
