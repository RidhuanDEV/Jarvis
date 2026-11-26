# Changelog

All notable changes to **J.A.R.V.I.S. Personal Intelligence OS** are documented in this file.
Format follows [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning 2.0.0](https://semver.org/).

## [0.2.1] — 2026-11-26

### Added
- **SDLC v0.2.1 Architecture Baseline (`DEC-001..030`)**: Hardware-adaptive, private-first, open-source-ready Personal Intelligence OS specification with `98` traceable requirements (`82 FR`, `16 NFR`) and deterministic `build_sdlc_complete.py` verification.
- **Phase 2 Foundation (`R1` Core Infrastructure)**:
  - Dual SQLite WAL architecture (`jarvis_core.db` ACID + `jarvis_knowledge.db` rebuildable index) with SHA-256 checksummed migrations and `deletion_ledger` tombstone replay.
  - Deterministic `R0`–`R3` Policy Engine, single-use local `R2` approval binding (`nonce_hash`, `bound_hash`, `60s` TTL), and 9 OS portability ports (`NFR-16` verified via `import-linter`).
  - Dynamic Hardware Capability Discovery, Configuration Recommendation Engine, 11-Root Storage Manager with atomic cross-drive staging migration & rollback, AES-256-GCM + Argon2id portable encrypted backups, and 11-category License Inventory with CycloneDX 1.5 SBOM/`NOTICE`.
  - Tauri 2 Rust Native Broker (256-bit Rust-only IPC token, Win32 Job Object `KILL_ON_JOB_CLOSE` protecting `external_local`, System Tray) and React 19 + Tailwind v4 Orbital Precision UI with VSync-harmonic `AdaptiveVisualEngine` and native `<dialog>` R2 modal.
- **Phase 3 (`R1` Core Intelligence)**:
  - Pluggable AI Provider Registry (`llama.cpp` & `Ollama` reference adapters, 4 runtime ownership modes, 6 AI profiles, atomic switch & rollback, Dynamic Resource Governor).
  - Dynamic Audio & Voice Pipeline (2s RAM-only ring buffer, endpoint-aware echo guard, hotplug recovery, local OneCore TTS probe).
  - Deterministic-First ID/EN Router (`0` LLM calls in Direct Mode), AES-256-GCM Encrypted Memory Vault, IANA/UTC Reminders with Quiet Hours & Suspend reconciliation, allowlisted non-shell OS tools, and 10-step Guided Onboarding Wizard (`0 GB` forced downloads).
- **Phase 4 (`R2` Productivity & Portability Expansion)**:
  - Isolated no-network document parsers (`.txt`/`.md`/`.pdf` via `pypdfium2`/`pypdf`, `.docx` with ZIP-bomb & macro blocking), Hybrid RAG (FTS5 + atomic blue/green vector generations + RRF + pre-top-K ACL + `tools_disabled=True` + citation verification).
  - Anti-SSRF Pluggable Web Search & Read-Only Fetch Client (DNS IPv4/IPv6/CGNAT/obfuscated IP blocking, manual per-hop redirect validation, stale cache labels).
  - Opt-in Screen Understanding with pre-context secret redaction & mandatory RAM wipe, Personal Life Management (Tasks, IANA Calendar, Integer Minor-Unit Multi-Currency Expenses, Descriptive Habits), Declarative Typed Workflows (`1..5` steps, `dry_run_preview`, `UNKNOWN` reconciliation), Opt-in Private LAN TLS Providers, and Trusted Extension SDK v1.0.
- **Phase 5 (`R3` Ecosystem & Production Hardening)**:
  - On-Demand Camera Understanding (per-session local consent, indicator events, RAM zero-wipe, instant OS-lock revocation).
  - Home Assistant Allowlist Integration with hard `R3` safety-critical bans (`lock`, `alarm_control_panel`, `heater`, `valve`, `garage`, `medical`), explicit target states only, and verified readback.
  - Structurally isolated Private Scoped Remote Mobile Gateway (disabled by default, private/VPN bind check, TLS pin, local pairing challenge, sliding-window rate limit, narrow scope ceiling, instant revocation, honest `host_unreachable`).
  - Local Adaptive Preference Proposals (safe UX keys only, zero silent mutation, hard block on security escalation).
  - 98-Case Executable RTM Traceability Manifest, Threat Model (`T01`–`T18`) & Supply-Chain Reachability Triage (`PRODUCTION-HARDENING-AND-RTM-REPORT.md`).
- **CI/CD & Release Compliance**:
  - 40-char SHA-pinned GitHub Actions Tier-A CI (`.github/workflows/ci-tier-a.yml`) & Windows minimal base installer release workflow (`.github/workflows/release-windows.yml`) with SLSA v1.2 provenance attestation.
  - Deterministic lockfile-reconciled SBOM, `THIRD-PARTY-NOTICES.txt`, and `SHA256SUMS.txt` generator (`scripts/generate_release_sbom.py`).
