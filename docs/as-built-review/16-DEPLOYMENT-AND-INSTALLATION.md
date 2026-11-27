# 16 — Deployment, Packaging, and Installation Audit

This document audits installation, packaging, build reproducibility, CI/CD workflows, signing, and update mechanisms (`apps/desktop/src-tauri/tauri.conf.json`, `apps/desktop/src-tauri/src/core_launcher.rs`, `scripts/install_local_windows.ps1`, `.github/workflows/{ci-tier-a.yml,release-windows.yml}`, `core/pyproject.toml`).

---

## 1. Showstopper Clean-Machine Portability Failure (`F-01` — `BROKEN`)

**Forensic Question:** *Can a user on a clean Windows 11 workstation download `JARVIS_0.2.1_x64-setup.exe` produced by `.github/workflows/release-windows.yml` and run J.A.R.V.I.S. without cloning the Git repository or installing Python/uv manually?*

**Answer: NO — 100% BROKEN.**

| Packaging Layer | Actual Configuration | Source Evidence | Failure Mode on Clean Machine |
| --- | --- | --- | --- |
| **Tauri NSIS Bundle** | `"targets": ["nsis"]`, `"installMode": "currentUser"`, **NO `"resources"`**, **NO `"externalBin"`** | `apps/desktop/src-tauri/tauri.conf.json:32-45` | Installer (`3.01 MiB`) ships ONLY `jarvis-desktop.exe` + Vite static HTML/JS/CSS. Zero Python runtime, zero `core/jarvis/`, zero `.venv`, zero `migrations/`, zero `contracts/`. |
| **Rust Core Discovery** | Checks env `JARVIS_CORE_PYTHON`/`DIR` → ancestor `core/.venv` → `%LOCALAPPDATA%\JarvisOS\Jarvis\runtime-pointer.json` | `apps/desktop/src-tauri/src/core_launcher.rs:130-192` | On a clean machine none of those exist → returns error `"Portable Python Core runtime not found..."` → UI silently degrades to fake `preview_fixture` data after 5s! |
| **Local Install Script** | Requires pre-existing `core/.venv\Scripts\python.exe` inside repo; probes `%LOCALAPPDATA%\Jarvis-R0-Sandbox\{runtimes,models}`; writes `runtime-pointer.json` pointing back to repo `.venv` | `scripts/install_local_windows.ps1:22-24, 58, 68, 70-86` | Developer convenience script only; ties installed exe to local git clone & developer sandbox folder. |
| **Python Wheel Build** | `packages = ["jarvis"]` only; `config_service.py:31` reads `parents[3]/contracts`, `dual_db.py:21` reads `parents[2]/migrations` | `core/pyproject.toml:55-56`, `config_service.py:31`, `dual_db.py:21` | Installing `jarvis-core` as a built wheel outside git checkout crashes immediately with `FileNotFoundError`. |

---

## 2. CI/CD Workflows & Build Reproducibility Audit

### 2.1 `.github/workflows/ci-tier-a.yml` (`119` lines) — **4 Jobs**
- **Verified Strengths (`VERIFIED`):**
  - Top-level `permissions: {}` (least privilege), `persist-credentials: false` on every checkout.
  - All 6 GitHub Actions pinned to **40-char commit SHAs** (verified by `tests/contract/test_ci_and_release_sbom.py`).
  - `npm ci --ignore-scripts` blocks lifecycle script supply-chain attacks.
  - Runs `mypy --strict`, `ruff`, `lint-imports`, `pytest` (`--extra dev`), `tsc --noEmit`, `oxlint`, `vitest`, `cargo test --locked`, `build_sdlc_complete.py --check`, and `generate_release_sbom.py --verify-ci-pinning`.
- **Confirmed Gaps:**
  1. **Floating Toolchains:** `dtolnay/rust-toolchain` installs floating `# stable` (no `rust-toolchain.toml` committed); `setup-node` pins major `"24"` (not exact `24.22.1`); `runs-on: windows-latest` is floating.
  2. **Optional Extras Untested in CI:** `ci-tier-a.yml` runs `uv sync --frozen --extra dev` only — **`[voice]`, `[tts-piper]`, and `[nvidia]` are NEVER resolved or tested in CI**.
  3. **Missing Security & Build Gates:** No `pip-audit`, no `cargo-audit`/`cargo-deny`, no `cargo clippy`, no `npx tauri build` PR smoke test, and no Playwright/clean-machine installer smoke test.
  4. **Uncommitted Working-Tree Drift:** Local workspace has `19` modified tracked files and `5` untracked files (`git status`) not yet committed or verified on GitHub Actions CI.

### 2.2 `.github/workflows/release-windows.yml` (`87` lines)
- **Verified Strengths:** 40-char SHA-pinned actions, `actions/attest-build-provenance` (SLSA v1.2) on release artifacts, runs `generate_release_sbom.py`, uploads NSIS + SBOM + `THIRD-PARTY-NOTICES.txt` + `SHA256SUMS.txt`.
- **Confirmed Defects:**
  1. **Never Publishes a GitHub Release (`release-windows.yml:7-12, 88-101`):** Declares `inputs.dry_run` (`"Build artifacts without publishing a GitHub Release"`), yet the input is **unused** and no `gh release create` / release publication step exists — only `actions/upload-artifact` (90-day retention).
  2. **Zero Code Signing:** Neither `jarvis-desktop.exe` nor `JARVIS_0.2.1_x64-setup.exe` is Authenticode-signed (triggers Windows SmartScreen unknown-publisher block).
  3. **Zero Auto-Updater:** `tauri-plugin-updater` is completely absent from `Cargo.toml`, `package.json`, and `tauri.conf.json` (`FR-SYS-06` integrity-verified updates are **`NOT IMPLEMENTED`**).
  4. **Target-Dir Divergence:** `install_local_windows.ps1:27` redirects `CARGO_TARGET_DIR` to `%LOCALAPPDATA%\Jarvis-Build-Cache\cargo-target`, whereas `release-windows.yml:79-80` hardcodes `apps/desktop/src-tauri/target/release/bundle/nsis/`.

---

## 3. Packaging Strategy Recommendations (Summary)

To ship a genuinely portable Windows Minimal Base Installer (`DEC-018`):
1. Bundle `contracts/` and `migrations/` inside `core/jarvis/` package data (`importlib.resources`).
2. Embed a relocatable `python-build-standalone` (`CPython 3.11.9`) + base `jarvis-core` site-packages inside Tauri `"resources"` (keeping optional `[voice]` / `[tts-piper]` / `llama-server` / GGUF assets downloadable on explicit user consent with SHA-256 verification).
3. Add a clean-VM Windows NSIS install-and-launch smoke job in `release-windows.yml`.
