# 24 — External Reviewer Handover Briefing

This handover guide equips an external independent reviewer to evaluate J.A.R.V.I.S. (`v0.2.1`) without needing direct access to the entire repository or live host environment.

---

## 1. Snapshot Metadata & Package Integrity

| Attribute | Value |
| --- | --- |
| **Application Version** | `0.2.1` (`core/pyproject.toml`, `apps/desktop/package.json`, `Cargo.toml`, `tauri.conf.json`) |
| **Git Base Commit** | `455c6aa623fcdfe5f220dc3fda4ce2ae7336f3f5` (`main...origin/main`) |
| **Uncommitted Local Delta Audited** | `19` modified tracked files (`+1,846 / -100` lines) + `5` untracked files (`single_instance.rs`, `live_voice_engine.py`, `local_runtime_manager.py`, `screen_capture.py`, `test_voice_wake_and_llm_conversation.py`) |
| **SDLC Baseline Audited Against** | `JARVIS-SDLC-v0.2.1/` (`v0.2.1`) + `planning/DECISION-REGISTER.md` (`DEC-001`–`DEC-030`) + `planning/rtm_verification_manifest.json` (`98` cases) |
| **Audit Modifications to App/SDLC** | **ZERO.** Strictly read-only inspection; only `docs/as-built-review/` deliverables created. |
| **Redaction Guarantee** | Zero personal usernames, host paths, Bearer tokens, API keys, SQLite DB dumps, AI model binaries, `.venv`, `node_modules`, or build artifacts included in this package or ZIP. |

---

## 2. Recommended Reading Sequence for External Reviewers

1. **Executive Decision Makers / Architects:** `01-EXECUTIVE-SUMMARY.md` → `02-ACTUAL-SYSTEM-ARCHITECTURE.md` → `19-SDLC-COMPLIANCE-MATRIX.md` → `20-JARVIS-CAPABILITY-MATURITY.md` → `22-RECOMMENDED-ENHANCEMENT-PLAN.md`.
2. **Owner-Reported Usability & AI/Voice Specialists:** `25-OWNER-REPORTED-ISSUES.md` → `26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md` → `03-INTELLIGENCE-ENGINE.md` → `04-AI-MODEL-AND-RUNTIME-MANAGEMENT.md` → `31-AI-TRAINING-AND-PERSONALIZATION-READINESS.md` → `32-JARVIS-EVALUATION-DATASET-DESIGN.md`.
3. **Security & Governance Auditors:** `14-SECURITY-AND-PRIVACY-AUDIT.md` → `27-AUTHORIZATION-POLICY-GAP-ANALYSIS.md` → `10-DATABASE-AND-DATA-LIFECYCLE.md` → `17-DEPENDENCY-AND-LICENSE-REVIEW.md` → `30-MCP-ARCHITECTURE-ASSESSMENT.md`.
4. **Systems / Desktop / QA Engineers:** `09-END-TO-END-WORKFLOWS.md` → `11-API-IPC-AND-EVENT-CONTRACTS.md` → `12-HARDWARE-AND-RESOURCE-MANAGEMENT.md` → `13-UI-UX-AND-MOTION-AUDIT.md` → `15-PERFORMANCE-AND-BENCHMARK-REPORT.md` → `16-DEPLOYMENT-AND-INSTALLATION.md` → `18-TEST-COVERAGE-AND-VALIDATION.md` → `28-FILE-SYSTEM-INTELLIGENCE-ASSESSMENT.md` → `29-APPLICATION-DISCOVERY-ASSESSMENT.md`.

---

## 3. Unresolved Questions & Architectural Decisions Requiring Owner Alignment

| # | Open Decision | Context & Options |
| :---: | --- | --- |
| **Q1** | **Final Public License Strategy (`DEC-001` vs GPL-3.0 `av`/`piper-tts`)** | `faster-whisper` pulls GPL-3.0 FFmpeg (`av.libs`, `73.50 MiB`) and `piper-tts` is GPL-3.0-or-later (`espeak-ng`), while `hey_jarvis_v0.1.onnx` carries `CC-BY-NC-SA 4.0`. Decide whether public releases will (a) adopt GPL-3.0-or-later for voice bundles, (b) strip PyAV & use permissive TTS/wake models, or (c) ship permissive minimal core only with user-initiated third-party optional installers. |
| **Q2** | **Installer Size vs Zero-Dependency Portability (`F-01`)** | Bundling embedded CPython `3.11.9` + base `jarvis-core` grows the Windows NSIS base installer from `~3 MiB` to `~50–65 MiB`, but fixes clean-machine installation immediately. |
| **Q3** | **Revised 3-Tier Authorization Policy Rollout (Doc `27`)** | Confirm replacing current strict R0/R1 grant gates with Owner's revised Tier-1 auto-allow scope (installed apps, authorized file search/open, WASAPI volume/media) while hardening Tier-2 GUI approval and Tier-3 absolute deletion/shell bans. |
| **Q4** | **Full-Database Encryption (`SQLCipher`) vs Field Encryption** | Confirm whether `jarvis_core.db` and `jarvis_knowledge.db` should migrate to SQLCipher at rest or retain OS BitLocker + per-field AES-256-GCM (with mandatory backup DEK re-wrapping). |
| **Q5** | **STT Accuracy vs VRAM Trade-Off (`faster-whisper-small` CPU vs `large-v3-turbo` GPU)** | On 4 GB VRAM GPUs, `Qwen3-4B` (`~2.8 GiB`) leaves `~1.0 GiB` VRAM—insufficient to co-locate `whisper-large-v3-turbo` (`~1.6 GiB` fp16) simultaneously with `Qwen3-4B` without either switching LLM to `Qwen3-1.7B` (`~1.5 GiB`) or keeping Whisper on CPU/Vulkan. |
| **Q6** | **Uncommitted Local Changes & SDLC Synchronization** | Confirm whether the 19 modified + 5 untracked files should be committed to `main` as a baseline snapshot *before* starting Phase A (`ENH-01`–`ENH-03`) remediation, and whether `JARVIS-SDLC-v0.2.1/` should be revised to `v0.2.2` to reconcile status & revised policy. |

---

## 4. Proposed Authorized Runtime Verification Protocol (Pending Owner Approval)

Per Audit Section 16, **zero heavy benchmarks, model downloads, or live GUI captures were executed during this read-only audit**. Should the external reviewer or owner authorize live runtime verification (`L3`), the recommended commands, resource envelopes, and risks are:

| # | Proposed Verification Command / Suite | Purpose | Expected Resource Use | Risk & Safeguards |
| :---: | --- | --- | --- | --- |
| **V1** | Live Playwright/WebView2 E2E screenshot capture across all 12 tabs against live Core | Collect real multi-screen UI evidence & axe-core WCAG 2.2 AA audit (`NFR-06`) | `< 400 MB` RAM, `< 2 min` | Low; run against isolated temp `JARVIS_BASE_DATA_DIR`, close browser in `try/finally`. |
| **V2** | Tier-B Latency & Conformance Harness (`100` direct + `100` LLM + `50` adversarial + `150` RAG cases) | Close `NFR-01`, `NFR-07`, `NFR-08` with Wilson 95% CIs | `~3.0 GiB` VRAM, `~15–25 min` | Medium GPU thermals; enforce `3,350 MiB` NVML ceiling & Win32 Job Object teardown. |
| **V3** | Real Human Voice Diagnostic Capture (`20` ID + `20` ID+EN + `10` app/file commands + `1h` ambient noise) | Quantify real WER, CER, VAD false-trigger rate, and mic→speaker TTFA (`Doc 26`, `Doc 32`) | `< 1 GB` RAM, CPU `~40%` bursts | Low; keep recordings strictly local in opt-in scratch dir; redact before sharing. |
| **V4** | Clean Windows Sandbox / VM NSIS Installer Smoke Test | Empirically confirm `F-01` and validate fix after `ENH-02` | `~4 GB` VM RAM, `~5 min` | Zero host impact when isolated inside Windows Sandbox / VM. |
| **V5** | 8-Hour Continuous Soak & GPU Frame Pacing (`NFR-02`, `NFR-12`, `NFR-13`) | Measure memory/handle/WAL growth and live WebView2 frame times under concurrent LLM load | `~3 GiB` VRAM, `~4 GB` RAM, `8h` | High duration; execute only after fixing `ENH-03`/`ENH-06`/`ENH-07` bounded caches & idle unload. |
