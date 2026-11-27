# 17 — Dependency, License, and Open-Source Readiness Review

This review audits actual locked versions across `core/uv.lock`, `apps/desktop/package-lock.json`, and `apps/desktop/src-tauri/Cargo.lock`, evaluates copyleft redistribution obligations objectively (without reflexively banning GPL/AGPL), inspects `scripts/generate_release_sbom.py` and `core/jarvis/application/license_service.py`, and identifies unused/bloated packages.

---

## 1. Actual Locked Technology Stack (`825` Components in SBOM)

| Layer | Runtime / Toolchain | Lockfile Count | Key Locked Dependencies |
| --- | --- | :---: | --- |
| **Python Core (`core/pyproject.toml`, `uv.lock`)** | CPython `3.11.9` (`uv`) | **104** third-party pkgs (`579.63 MiB` installed in `.venv` with all extras) | Base (50 transitive): `fastapi==0.165.0`, `uvicorn==0.54.0`, `pydantic==2.14.4`, `cryptography==50.0.2`, `argon2-cffi==25.1.0`, `httpx==0.28.1`, `sqlite-vec==0.1.9`, `keyring==25.7.0`, `structlog==26.1.0`, `psutil==7.2.2`, `pypdfium2==5.15.2`, `pypdf==7.1.1`, `python-docx==1.2.0`, `jsonschema==4.26.0`. Extras: `[voice]` (`faster-whisper==1.2.1`, `openwakeword==0.6.0`, `onnxruntime==1.32.0`, `numpy==2.2.6`, `sounddevice==0.5.6`), `[tts-piper]` (`piper-tts==1.8.0`), `[nvidia]` (`nvidia-ml-py==13.615.71`), `[dev]` (`pytest`, `mypy`, `ruff`, `hypothesis`, `import-linter`). |
| **Desktop UI (`apps/desktop/package-lock.json`)** | Node `v24.22.1`, npm | **228** pkgs (**14** runtime, 112 dev, 102 optional) | Runtime: `react==19.3.1`, `react-dom==19.3.1`, `@tauri-apps/api==2.12.5`, `zod==4.6.7`, `zustand==5.1.0`, `motion==14.14.0`, `lucide-react==1.81.0`. Dev: `typescript==~7.0.2`, `vite==8.4.0`, `vitest==5.1.2`, `tailwindcss==4.3.5`, `oxlint==1.94.0`. |
| **Rust Broker (`apps/desktop/src-tauri/Cargo.lock`)** | `rustc 1.99.0` (`edition 2021`) | **476** crates | `tauri==2.12.7`, `wry==0.57.4`, `tao==0.37.3`, `webview2-com==0.39.1`, `tray-icon==0.25.1`, `tokio==1.54.1`, `reqwest==0.12.28` (+ `0.13.5`), `rustls==0.23.46`, `ring==0.17.14`, `serde==1.0.229`, `windows-sys==0.59.0`. |
| **External AI & Voice Assets (On Local Disk, Not in Repo)** | Managed / Optional | — | `llama-server.exe` (`llama.cpp` `b12774`, **MIT**), `Qwen3-4B/1.7B-Q4_K_M.gguf` (**Apache-2.0**), `faster-whisper-small` weights (**MIT**), `silero_vad.onnx` (**MIT**), `openWakeWord hey_jarvis_v0.1.onnx` (**Apache-2.0** code; verify wake training/model card **`CC-BY-NC-SA 4.0`** noted in `R0-FEASIBILITY-REPORT.md`!), `vits-piper-id_ID-news_tts-medium` (**upstream `MODEL_CARD`: `License: See URL` / Kaggle corpus — non-standard, requires legal check before redistribution**). |

---

## 2. Critical Licensing & Redistribution Audit

1. **[CRITICAL] Undisclosed Strong Copyleft (`GPL-3.0-or-later`) Hidden Inside `[voice]` Extra (`faster-whisper` → `av==18.1.1`):**
   - `core/pyproject.toml:34-40` isolates GPL into `[tts-piper]` while presenting `[voice]` as permissive, and `license_service.py:153-161` declares `faster-whisper` solely as `MIT`.
   - **Verified Binary Evidence:** `faster-whisper==1.2.1` depends on `av==18.1.1`, whose `av.libs/` (**`73.50 MiB`**) bundles **`libx264-165` (2.16 MiB)**, **`libx265-02` (21.43 MiB)**, and **`avcodec-62` (18.66 MiB)** compiled with `--enable-version3 --enable-libx265 --enable-libx264` (**GPL-3.0-or-later**).
   - **Compliance Impact:** Fine for private personal use, **but redistributing a bundled `[voice]` environment requires full GPLv3 source compliance (or shipping a GPLv3-compatible license) OR replacing PyAV audio decoding** (note: JARVIS already passes in-RAM NumPy float32 arrays to Whisper and does not need FFmpeg video codecs!).
2. **[HIGH] `[tts-piper]` (`piper-tts==1.8.0`, `43.95 MiB`, `GPL-3.0-or-later` + bundled `espeak-ng`) & Voice Model Card Ambiguity:**
   - Properly isolated in `[tts-piper]` and documented in `license_service.py:93-101`. If redistributed in binary bundles, requires GPLv3 text + corresponding source offer. Additionally, `id_ID-news_tts-medium` upstream `MODEL_CARD` cites `License: See URL` (Kaggle news corpus) — **must NOT be bundled into public releases without explicit upstream copyright clearance**; users must download directly with disclosure (`DEC-028`).
3. **[HIGH] `openWakeWord` Model Card (`CC-BY-NC-SA 4.0`) Commercial Restriction:**
   - While `openwakeword` Python code (`0.6.0`) is `Apache-2.0`, `R0-FEASIBILITY-REPORT.md` notes `hey_jarvis_v0.1.onnx` carries `CC-BY-NC-SA 4.0` (Non-Commercial + ShareAlike) — incompatible with commercial redistribution if bundled; must remain user-consented optional download with explicit notice (not labeled solely `Apache-2.0` as `license_service.py:163` currently does!).
4. **[HIGH] Missing Open-Source Publication Files & Package Metadata:**
   - Repository root lacks `LICENSE`, `NOTICE`, `THIRD-PARTY-NOTICES.txt`, `SECURITY.md`, and `CONTRIBUTING.md`.
   - `core/pyproject.toml`, `apps/desktop/package.json`, and `apps/desktop/src-tauri/Cargo.toml` all omit the `license` metadata field.
5. **[MEDIUM] Undisclosed Weak Copyleft (`MPL-2.0`) & False OS Voice License Label:**
   - `certifi==2026.11.20` (`MPL-2.0`, base runtime), `tqdm==4.70.1` (`MPL-2.0 AND MIT`, `[voice]`), `hypothesis`/`pathspec` (`MPL-2.0`, `[dev]`), and `lightningcss` (`MPL-2.0`, npm dev) are absent from `license_service.py`.
   - `platform/windows/audio.py:140` **falsely labels proprietary Microsoft Windows OneCore voices as `license_spdx="BSD-3-Clause"`**!
   - All **14 npm runtime packages** are cleanly permissive (`MIT`, `Apache-2.0 OR MIT`, `ISC`, `0BSD`).
   - Dependabot Alert #1 (`glib 0.18.5` via Tauri Linux GTK3): verified `0` Windows reachability, documented with 90-day waiver expiring `2027-02-24` in `planning/PRODUCTION-HARDENING-AND-RTM-REPORT.md`.

---

## 3. SBOM Generator Audit (`scripts/generate_release_sbom.py` & `license_service.py`)

- **[HIGH] Zero Transitive Licenses in CycloneDX SBOM (`generate_release_sbom.py:148-181`):** All 104 PyPI, 228 npm, and 476 Cargo entries emit ONLY `type`, `name`, `version`, `purl`, and `scope` — **zero `"licenses"` metadata**!
- **[HIGH] Incomplete `THIRD-PARTY-NOTICES.txt` (`L195-196`):** Only prints the 17 hardcoded entries from `baseline_license_artifacts()` (`license_service.py:19-193`), omitting all 808 locked dependencies.
- **[MEDIUM] Wrong CycloneDX Scopes (`L156, L177`):** Marks EVERY `uv.lock` package (including `pytest`, `mypy`, optional GPL `piper-tts`, and Linux-only `tflite-runtime`) and EVERY Cargo crate as `"scope": "required"`.
- **[LOW] Version Drift & 6/11 Categories Seeded (`license_service.py`):** Hardcoded baseline strings drift from lockfiles (`lucide` `"0.460+"` vs `1.81.0`, `tauri` `"2.x"` vs `2.12.7`, etc.), and 5 of 11 `LicenseArtifactCategory` values (`model_weights`, `training_dataset`, `wake_model`, `audio_sfx`, `ui_asset`) have 0 baseline entries.

---

## 4. Unused, Redundant & Heavy Dependencies (`579.63 MiB` `.venv`)

| Package | Size / Location | Why Redundant or Bloated |
| --- | --- | --- |
| `scipy==1.17.1` + `scikit-learn==1.9.1` + `joblib` | **`144.65 MiB`** (`[voice]` via `openwakeword`) | Dragged in by `openwakeword` training/utility extras even though JARVIS runs pure ONNX inference (`melspectrogram.onnx` → `embedding_model.onnx` → `hey_jarvis_v0.1.onnx`). Direct 3-session `onnxruntime` inference eliminates ~150 MiB! |
| `av==18.1.1` + `av.libs/` | **`77.08 MiB`** (`[voice]` via `faster-whisper`) | Pulls full GPL-3.0 FFmpeg (`libx264`/`libx265`) despite JARVIS feeding in-RAM NumPy float32 PCM directly to `faster-whisper`. |
| `tflite-runtime==2.14.0` | `uv.lock` (Linux marker) | Locked via `openwakeword` despite `inference_framework="onnx"`. |
| `httpx2==2.16.2` + `httpcore2==2.16.2` | `[voice]` via `huggingface-hub` | Duplicate HTTP client stack alongside `httpx==0.28.1` + `httpcore==1.0.9`. |
| `pypdfium2` + `pypdf` | `11.53 MiB` (Base) | Dual PDF parsers kept for fallback; acceptable trade-off, note both are mandatory base deps. |
| Duplicate Cargo Major Versions | `Cargo.lock` | Compiles dual majors of `reqwest` (`0.12`/`0.13`), `rand` (`0.8`/`0.10`), `thiserror` (`1`/`2`), and 4 versions of `windows-sys` (`0.45`/`0.52`/`0.59`/`0.61`). |
