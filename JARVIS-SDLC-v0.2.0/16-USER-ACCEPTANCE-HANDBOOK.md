# User Acceptance Test, User Guide & Handover

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Pre-acceptance requirements
Approved build and hash, actual reference hardware recorded, model manifests/licenses approved, RTM and QA evidence available, encrypted backup configured if enabled, test profile with synthetic data, no critical defects. User grants test-specific permissions. Do not test destructive or real IoT high-risk actions. UAT status starts Not Run.

| UAT | Phase | User scenario | Expected acceptance |
|---|---|---|---|
| U01 | R1 | install, offline, type "buka aplikasi" (allowlisted) | opens and reports verified status |
| U02 | R1 | PTT and wake command set volume 30 | transcript + actual volume, no paid API |
| U03 | R1 | mute and interrupt spoken response | capture/playback stops, text works |
| U04 | R1 | remember preference, ask, edit, delete, ask again | updated data only, deletion effective |
| U05 | R1 | create reminder, restart, snooze, cancel | state survives, no phantom success |
| U06 | R1 | attempt ambiguous or unapproved file action | clarify/deny, R2 trusted preview for rename |
| U07 | R1 | lock workstation during approval; unlock | old approval invalid, capture off |
| U08 | R1 | stop LLM worker, use basic command | degraded direct mode, no cloud |
| U09 | R1 | backup and restore to isolated profile | valid records, ledger applied, no silent loss |
| U10 | R2 | index approved file and ask summary | accurate citation and locator; revoke removes retrieval |
| U11 | R2 | ask internet question in offline and enabled mode | explicit offline vs cited online, no private leakage |
| U12 | R2 | select window, explain content, stop | scope visible, no persistent screenshot |
| U13 | R2 | create task and expense, inspect totals | correct local records and separated currencies |
| U14 | R2 | create workflow, dry-run, approve, cancel | expected steps, verified/partial states |
| U15 | R3 | camera on demand and stop | clear indicator, no capture after stop |
| U16 | R3 | control allowlisted light, test unavailable device | actual state or unknown, no dangerous actions |
| U17 | R3 | pair mobile, create reminder, revoke device | scoped success then denied; offline shown |
| U18 | R3 | reject adaptive preference proposal | no permanent change or policy escalation |

For each case record tester, environment, build, steps, actual, evidence, pass/fail, defect and approval. No tests run yet. Owner sign-off: release tag ___; UAT date ___; accepted scope ___; exceptions ___; approval ___; QA reviewer ___; rollback owner ___.

## 2. User guide (planned behavior)
Start JARVIS from desktop/tray. First-run check hardware and approved local models; select language and mic. Enable wake only if desired, otherwise use PTT or type. Example commands: "Jarvis, buka Spotify", "atur volume ke 30 persen", "ingatkan saya besok jam 8", "ingat bahwa saya suka kopi", "apa yang kamu ingat?". App names must be granted. Review transcript if action ambiguous. For sensitive effects review exact preview and approve once via trusted UI. Stop immediately via tray; mute disables capture; offline toggle disables external requests. Use Memory to review/delete facts, Knowledge to grant/revoke folders, Personal to manage local records, Integrations to opt in and revoke. Optional network/IoT/remote features appear only at applicable release.

## 3. Troubleshooting and limitations
No wake: verify mic permission, mute state, language/phrase and noise; use PTT. Model slow: switch approved smaller profile or direct mode; check resource dashboard. If app action unsupported, perform manually. If reminder missed while host off, inspect missed history. Offline cannot fetch current web data; cached data labeled stale. Remote cannot work while host asleep/off. JARVIS does not authenticate identity by voice, does not code, pay, send email, control safety-critical devices, or run arbitrary commands. Raw media not stored by default; OS swap or old backups may retain residual data. Do not treat assistant as emergency/medical/safety system.

## 4. Handover package checklist
Signed installer and SHA-256, source repository/tag, README and all SDLC docs, actual OpenAPI/IPC and migration artifacts after implementation, config template without secrets, model manifest and licenses, SBOM/NOTICE, QA/AI benchmark reports and RTM actual status, UAT record, deployment/rollback/runbook, backup key recovery instructions (not the secret itself), known issues/risks and maintenance owner. Document package alone is not a completed software handover or BAST. No application implementation or validation is included in this deliverable.

## UAT extension v0.2.0
Owner verifies model profile selection, actual provider/location shown, switch/rollback, direct mode, offline baseline, explicit benchmark consent and LAN consent/revoke if R2. Test animated voice core and verified action state, rapid interruption, keyboard focus, Reduced Motion, Lite and renderer pressure fallback. Owner approves original visual direction from R0 prototype before implementation; no pixel mockup or benchmark evidence included here. Acceptance requires applicable TC-FR-AIP, TC-FR-UX, TC-NFR-13/14 in 17.
