# Deployment, CI/CD, Maintenance & Runbook

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Environments and packaging
Windows x64 per-user install (proposed), no required Docker/Kubernetes/cloud service. Dev uses official scaffolds, pinned lockfiles, reproducible Python/Rust/Node dependencies. Release packages native shell, core runtime and signed binaries; models separate manifest-driven download or offline bundle when redistribution license allows. Install path read-only app binaries; per-user data path separate from install, model cache and backup directory separate. No default auto-start; opt-in at login, no system service.

## 2. Pipeline
PR → formatting/lint/typecheck → unit/contract → dependency/license/SBOM and secret scan → build → migration tests → signed artifact → sandbox smoke → owner-approved hardware validation → UAT → signed release. CI must not invoke actual device/OS mutations outside fixtures or upload private data. Branch main protected; feature branches PR, tagged SemVer, release notes include schema/model compatibility, known limitations and rollback. Pin toolchain versions and hashes, verify upstream and signing. Secrets via CI vault only. No auto-install from internet without user confirmation. Hardware tests run locally with explicit permission; evidence redacted.

## 3. Installation and upgrade sequence
1. Verify actual OS, CPU, RAM, GPU/driver, disk free, mic/speaker. Estimate model sizes via manifest; require model + temp + backup headroom (initial 15 GB free candidate, validate). 2. Verify installer signature/hash; install app, initialize DB ACL and schema. 3. Download approved models with checksums or import verified offline files; if unavailable start direct/text mode. 4. Run onboarding audio test and permissions; network off by default. 5. Run offline smoke, verify no listener outside loopback. 6. Enable optional start-on-login and encrypted backups with user key. Upgrade: stop requests and capture, backup, verify package, migrate staging copy, smoke, switch, record version. On failure restore previous app and compatible DB snapshot, replay deletion ledger, test before resuming. Do not overwrite user data on uninstall; offer keep/delete with explicit confirmation.

## 4. Observability
Local rotating structured logs with correlation_id, component, event, duration, state, error code; no raw prompts/audio/secrets. Default 30 days with max 100 MiB candidate; prune oldest noncritical, surface inability to audit. Metrics: request latency, route usage, worker uptime, model load/OOM, GPU/RAM, due job lag, queue depth, denied effects, backup age, index errors. Dashboard health states READY, DEGRADED, OFFLINE, PAUSED, FAILED; component readiness not aggregate false success. No telemetry upload by default. Export support bundle via R2 preview/redaction.

## 5. Incident runbook
| Symptom | Diagnosis | Recovery | Verification |
|---|---|---|---|
| Wake false triggers | mic noise/TTS feedback, sensitivity | mute, PTT, adjust threshold after test | negative audio fixture |
| LLM slow/OOM | GPU free memory, context, worker logs | unload, smaller model/CPU, direct fallback | direct command + benchmark |
| Missed reminder | host sleep, DB/lease/timezone | resume, reconcile due jobs, notify missed | test reminder after restart |
| DB corruption | integrity_check and disk status | stop writes, preserve corrupt copy, restore encrypted snapshot | integrity + RTM smoke |
| Unknown file action | crash/timeout after call | read source/destination, show unknown if inconclusive | no duplicate mutation |
| Network unavailable | check opt-in and connectivity | offline core, no cloud fallback | local-only tests |
| Suspicious tool attempt | audit correlation and grant | stop, revoke, disable network, preserve redacted evidence | denial and scope tests |
| Lost paired phone | device registry | revoke token, rotate affected creds, review access | revoked device rejected |
| Disk full | data/model/log storage | pause writes/index, prune approved caches; never silently delete user records | free space and backup check |

## 6. Backup, recovery and maintenance
Opt-in encrypted daily backups while host active; retain 7 daily/4 weekly, check age and manifest. Monthly restore drill (after approval) to isolated profile, target RPO ≤24h while scheduled backups can run, RTO ≤30min for 1 GB fixture. Verify deletion ledger and prevent resurrection. Weekly review model/dependency/security advisories as manual operator task; patch via signed release. Monthly review grants, audit, quiet rules and model disk usage. No automatic external update/analytics. User owns backup key and recovery path; keep offline recovery instructions. Host failure means voice/remote/scheduler unavailable until recovery.

## 7. Release checklist
Signing verified, SBOM/NOTICE/model cards packaged, migration and restore tested, offline smoke and security pass, hardware metrics recorded, UAT signed, user guide and known issues present, rollback tested, optional connectors default off. Support/handover package includes installer checksums, source tag, configs sans secrets, test evidence, licenses, recovery procedure and unresolved risk list. Nothing installed or deployed as part of this document.

## Provider and renderer operations v0.2.0
Installer ships only approved adapters and manifests; model files optional, explicit download/import and checksum verification. Provide offline bundle where licenses permit. External runtime lifecycle is user-owned unless explicitly enrolled as managed. Roll back active config and app migration independently; preserve memory and pending reminders. Local health diagnostics show model/profile revision, provider trust zone, renderer tier and resource pressure with redacted metrics. Runbook: model load failure → rollback/direct mode; animation jank → Lite/reduced motion → inspect trace and GPU budget; do not disable safety controls to regain speed. Verify WebView2 and local provider versions at R0; no automatic internet inference or update fallback.
