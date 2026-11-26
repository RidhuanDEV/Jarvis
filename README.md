# J.A.R.V.I.S. — Local-First Hardware-Adaptive Personal Intelligence OS

**Private-first, open-source-ready, hardware-adaptive Personal AI Operating System** (`v0.2.1`).

> **Governing Principle:** *"Convention over configuration, with full configuration overrides."*
> Everyday users finish setup in 1 click via **Recommended Setup** (`0 GB` forced model downloads, instant offline **Direct Mode**). Power users override AI runtimes, models, hardware backends, all 11 storage locations, voice engines, language/IANA timezone/persona/quiet hours, and adaptive frame-rate visuals without editing source code.

---

## Core Architecture & Guarantees

- **Zero Mandatory Paid Cloud APIs:** Full offline Direct Mode works immediately with `0` downloaded LLMs; local models (`llama.cpp`, `Ollama`, or compatible adapters) and private LAN TLS endpoints are strictly opt-in with zero silent cross-zone fallback.
- **Deterministic-First & Policy-Bounded (`R0`–`R3`):**
  - Simple commands (time, allowlisted non-shell app launch, volume readback, memories, reminders) execute deterministically with **0 LLM calls**.
  - Sensitive actions (`R2`) require a single-use local native `<dialog>` approval bound to canonical argument hash, target snapshot, active unlocked session, and `60s` expiry.
  - Hard Product Bans (`R3`) permanently block arbitrary shell execution, coding/deploy agents, permanent file deletion, covert capture, automated payments, medical diagnosis, and safety-critical IoT actuation (`lock`, `alarm`, `heater`, `valve`, `garage`).
- **Dual SQLite WAL Persistence & Portable Recovery:** Authoritative `jarvis_core.db` (`AES-256-GCM` field encryption, SHA-256 checksummed migrations, `deletion_ledger` tombstone replay) separated from rebuildable `jarvis_knowledge.db` (FTS5 + optional vector generations). Portable encrypted backups use `Argon2id + AES-256-GCM`.
- **11-Root Dynamic Storage Manager:** Defaults to OS-standard user directories (`platformdirs`) with zero hardcoded drives or usernames, WAL filesystem guards (rejects SMB/UNC for active DBs), shared model directory support, and transactional cross-drive staging migration with rollback.
- **Hardware-Adaptive Rendering:** Supports CPU-only, NVIDIA, AMD, Intel, or Apple hardware tiers and configurable FPS targets (`Auto / 30 / 60 / 120 / Native`) synchronized to monitor refresh rate with `Reduced Motion` and background pause support.

---

## Repository Structure

| Path | Purpose |
|---|---|
| `core/` | Python `3.11.9` (`uv`) local Core engine (`domain/`, `application/`, `infrastructure/`, `platform/`, `transport/`, checksummed SQL `migrations/`) |
| `apps/desktop/` | Tauri 2 Rust Native Broker (`src-tauri/`) + React 19 / TypeScript strict / Tailwind v4 Orbital Precision UI (`src/`) |
| `contracts/` | Draft 2020-12 JSON Schemas (`config`, `tool-proposal`, `events`, `license-artifact`) |
| `tests/` | Automated Contract, Unit, Integration, Security, and 98-Case RTM Verification suites |
| `scripts/` | SDLC aggregator (`build_sdlc_complete.py`) and release CycloneDX 1.5 SBOM / Notices / CI pinning verifier (`generate_release_sbom.py`) |
| `JARVIS-SDLC-v0.2.1/` | Approved normative SDLC baseline (`82 FR + 16 NFR = 98` requirements, `ADR-001..025`, `B01..34`) |
| `planning/` | Empirical `R0` report, `DEC-001..030`, 98-case `rtm_verification_manifest.json`, and `PRODUCTION-HARDENING-AND-RTM-REPORT.md` |
| `.github/workflows/` | 40-char SHA-pinned Tier-A CI (`ci-tier-a.yml`) and Windows minimal release pipeline (`release-windows.yml`) |

---

## Portable Development & Installation Quickstart

### Prerequisites (Standard Per-User Tools — Zero Admin Required)
- **Python `3.11.9`** managed cleanly via **[uv](https://docs.astral.sh/uv/)**
- **Node.js `24+`** & **`npm`** (lockfile-pinned)
- **Rust stable toolchain (`cargo` / `rustc`)** for the Tauri 2 native broker (Windows x64 requires WebView2 Runtime, pre-installed on Windows 11)

### 1. Install Dependencies (Frozen Lockfiles)
```powershell
# Python Core (isolated virtualenv via uv.lock)
cd core
uv sync --frozen --extra dev
cd ..

# Desktop UI (strict package-lock.json)
cd apps/desktop
npm ci --ignore-scripts
cd ../..
```

### 2. Run Full Tier-A Verification Locally
```powershell
# Backend lint, strict typing, NFR-16 portability contracts, and full 114-test suite
cd core
uv run ruff check jarvis ../tests
uv run mypy jarvis
uv run lint-imports
uv run pytest -v
cd ..

# Frontend strict TypeScript, Oxlint, Vitest, and production bundle
cd apps/desktop
npx tsc --noEmit
npx oxlint src
npx vitest run
npm run build
cd ..

# Rust Tauri Broker unit tests
cd apps/desktop/src-tauri
cargo test --locked
cd ../../..

# SDLC sync + CycloneDX 1.5 SBOM, THIRD-PARTY-NOTICES, checksums & CI pinning check
uv run --project core python scripts/build_sdlc_complete.py --check
uv run --project core python scripts/generate_release_sbom.py --output-dir release-compliance --verify-ci-pinning
```

### 3. Run Locally (Development Preview)
Optional environment overrides can be copied from `.env.example` into a gitignored `.env.local` (never commit real secrets or personal paths). All runtime data defaults cleanly to your OS user-data directory (`%LOCALAPPDATA%\JarvisOS\Jarvis` on Windows) and can be moved to any local drive from **Storage (11 Roots)** inside the app.

```powershell
# Start Desktop UI dev server
cd apps/desktop
npm run dev
```

---

## Operational Rollback & Security Governance

- **Three Independent Rollback Layers (`13-DEPLOYMENT-OPERATIONS.md §3`):**
  1. *Configuration / Profile Rollback:* `POST /v1/config/rollback` or `POST /v1/profiles/rollback` restores the prior healthy revision in seconds.
  2. *Runtime / Model Rollback:* Atomic profile switch automatically drains/cancels active turns and rolls back to the last healthy profile or offline **Direct Mode** on load failure.
  3. *Application & Schema Rollback:* Pre-migration online SQLite snapshots + encrypted `Argon2id + AES-256-GCM` restore with mandatory `deletion_ledger` tombstone replay.
- **Verification & Readiness Honesty:** See [`planning/PRODUCTION-HARDENING-AND-RTM-REPORT.md`](planning/PRODUCTION-HARDENING-AND-RTM-REPORT.md) for the exact `98`-case RTM matrix (`93` verified Tier-A locally, `5` physical hardware/soak Tier-B gates transparently tracked as `NOT_MEASURED` pending dedicated `L3` hardware benchmark execution), Threat Model `T01`–`T18`, and Supply-Chain Reachability Triage.
