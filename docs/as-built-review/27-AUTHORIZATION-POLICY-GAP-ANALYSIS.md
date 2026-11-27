# 27 — Authorization Policy Gap Analysis & Bypass Audit

> **Document Scope:** Independent security and product-governance evaluation of J.A.R.V.I.S.'s implemented authorization model against the owner's **Revised 3-Tier Authorization Policy** (Addendum §B), including a forensic audit of **all 7 confirmed authorization bypass paths** across native tools, HTTP endpoints, storage/backup lifecycle, workflows, voice/GUI approval boundaries, and future MCP / browser / GUI automation vectors.

---

## 1. Revised 3-Tier Policy vs. Actual As-Built Implementation

| Policy Tier (Owner Direction — Addendum §B) | Required Capability Set | Current Implementation (`policy.py`, `app.py`, `approval_service.py`) | Compliance Status | Key Gap Summary |
| --- | --- | --- | :---: | --- |
| **Tier 1: Auto-Allowed Within Authorized Scopes** *(No repetitive confirmations)* | Discover installed apps; open ordinary trusted non-elevated apps; search authorized files/dirs; open ordinary trusted docs; read/analyze authorized files; inspect system resources; ordinary non-destructive desktop ops; audio volume & media control | `policy.py:274-282` requires an explicit active DB `permission_grant` row for **every** tool—even `R0` read-only tools! `_has_active_grant` (`L315-331`) **completely ignores `grant.scope`**. `os.app.launch` is `R1` (not auto-granted during 1-Click Onboarding), restricted to 3 System32 binaries, and disabled (`allow_live_launch=False`). Volume/media, file search, doc open, and app discovery tools do not exist or lack Policy tiers. | `BROKEN` | Over-blocks ordinary safe actions (causing ORI-03) while simultaneously failing to enforce scope boundaries once any grant exists! |
| **Tier 2: Explicit GUI Approval Required** *(Target, proposed changes, impact, preview/diff; action+target scoped; auto-expiring; reject/cancel; voice-only forbidden)* | Modify existing files; create new files; rename/move files; change persistent system/app config; install software; send info to external recipients; other consequential state changes | Only `fs.file.move` and `storage.location.migrate` are registered as `R2`. `execute_approved_file_move()` (`turn_orchestrator.py:733-813`) has **0 callers** in `app.py` and never checks `bound_hash`/replay. `target_snapshot_hash` is never supplied (`turn_orchestrator.py:399-407`, `commands.rs:152-158`). `POST /v1/storage/migrate`, `/v1/grants`, `/v1/roots`, `/v1/backups/create`, and `/v1/iot/ha/actuate` bypass `ApprovalService` entirely. `approval_service.py:181-185` checks `TRUSTED_UI` + `LOCAL` via self-reported JSON fields while `app.py:1300` hardcodes `is_os_locked=False`. | `BROKEN` | GUI approval is simultaneously non-functional for intended actions (`fs.file.move` orphaned) and bypassed by direct REST & workflow routes. |
| **Tier 3: Strictly Prohibited** *(Enforced in trusted app logic, NOT LLM prompts; distinguishes safe internal cache cleanup from user-data destruction)* | Delete user files/dirs; delete user databases; move user files to Recycle Bin; format drives; destructive system ops; bypass security policies; arbitrary shell commands; indirect user-data destruction via overwrite/truncation/scripts/automation/3rd-party tools | **No unified Tier-3 denylist or immutable hard-ban guard exists.** Two-step permanent user-file deletion is actively exploitable via `PUT /v1/storage/locations/cache` + `POST /v1/storage/cleanup (max_bytes=0)`. `POST /v1/backups/create` accepts arbitrary unconfined `archive_path` enabling destructive file overwrite. `restore_into_directory` overwrites live data without R2 approval or pre-restore snapshot. | `BROKEN` | Critical security violation: indirect user-file deletion and arbitrary file overwrite are possible today via trusted backend endpoints. |

---

## 2. Detailed Forensic Audit of All 7 Confirmed Authorization Bypass Paths

### Bypass BP-01: Two-Step Permanent User-File Deletion via Cache Repointing + Cleanup (`CRITICAL`)
- **Source Evidence:**
  - `core/jarvis/application/storage_service.py:158-218` (`set_location` via `PUT /v1/storage/locations/cache` at `app.py:1656-1671`): accepts **any** existing writable directory path as the `cache` storage root without verifying it is an isolated JARVIS-owned cache folder or outside user document/project directories, and without requiring R2 GUI approval.
  - `core/jarvis/application/storage_service.py:346-378` (`cleanup_cache` via `POST /v1/storage/cleanup` at `app.py:1689-1699`): iterates recursively over the configured `cache` root and calls `path.unlink()` on files until total size `<= max_bytes` (accepting `max_bytes=0`), without rejecting NTFS junctions/symlinks or requiring a JARVIS cache sentinel marker.
- **Current Behavior:** Calling `PUT /v1/storage/locations/cache` targeting a user folder (e.g., `%USERPROFILE%\Documents\Work`) followed by `POST /v1/storage/cleanup {"max_bytes": 0}` **permanently deletes every user file inside that directory**, completely bypassing Recycle Bin and violating Tier 3.
- **Expected Behavior:** Safe internal cache maintenance MUST be strictly confined to an application-owned cache directory containing a cryptographic/signed sentinel (`.jarvis-cache-owned`), never allow repointing onto non-empty user directories or system roots, reject reparse points/junctions (`os.path.islink` / `FILE_ATTRIBUTE_REPARSE_POINT`), and require Tier-2 GUI approval for any storage-root reconfiguration.
- **Probable Root Cause:** Confirmed missing ownership boundary and conflation of internal cache lifecycle with arbitrary user-supplied filesystem paths.
- **Verification Status:** `BROKEN` (Confirmed directly in `storage_service.py:158-218, 346-378`).
- **Proposed Improvements:** Confine cache cleanup strictly to JARVIS-created subdirectories verified by ownership sentinel + `O_NOFOLLOW`/reparse-point rejection; prohibit `set_location` from adopting non-empty user folders; require R2 GUI approval for location changes.
- **Security Implications:** Direct violation of Owner Tier-3 absolute ban on user file deletion; any compromised local client or future tool invoking storage endpoints can wipe arbitrary user folders.
- **Acceptance Criteria:** Automated negative security tests prove `PUT /v1/storage/locations/cache` rejects any non-empty user directory or symlink, and `cleanup_cache` refuses to delete any directory lacking a verified JARVIS cache sentinel (`0%` user-file deletion under adversarial tests).

---

### Bypass BP-02: Arbitrary File Overwrite & Unapproved Restore via Backup Endpoints (`CRITICAL`)
- **Source Evidence:**
  - `core/jarvis/application/backup_service.py:101` (`create_backup` via `POST /v1/backups/create`): accepts a caller-supplied `archive_path` with **zero path containment** and writes/overwrites the destination file directly (can destroy any existing user file by truncating/overwriting it with backup bytes).
  - `core/jarvis/application/backup_service.py:165-226` (`restore_into_directory`): executes filesystem restoration **without** checking an R2 approval token, **without** closing active SQLite connections or clearing `-wal`/`-shm` sidecars, **without** taking a pre-restore safety snapshot, and **without** replaying deletion tombstones (`BR-17`).
- **Current Behavior:** Backup creation can overwrite arbitrary user files anywhere on disk; restore can corrupt or overwrite live databases and resurrect erased memory records without GUI approval.
- **Expected Behavior:** Backup archives may only be written to verified, isolated backup roots using `O_CREAT | O_EXCL` (create-new-only, never overwrite existing non-backup files); restore requires Tier-2 GUI approval with impact preview, clean DB quiescing (`-wal`/`-shm` teardown), pre-restore snapshot, and mandatory tombstone replay.
- **Probable Root Cause:** Confirmed missing path confinement (`archive_path`), missing `O_EXCL` create semantics, and absent Policy/Approval gate on backup/restore operations.
- **Verification Status:** `BROKEN` (Verified in `backup_service.py:101, 165-226`).
- **Proposed Improvements:** Constrain backup writes to managed backup directory with unique timestamped filenames (`x` mode, never overwrite); route restore through `ApprovalService` (Tier 2) with full quiesce + snapshot + tombstone replay.
- **Security Implications:** Direct indirect user-data destruction vector (Tier-3 violation via overwrite/truncation) plus privacy regression (erased data resurrection).
- **Acceptance Criteria:** Attempting `POST /v1/backups/create` targeting an existing user document fails with `403/400` leaving target bytes and mtime untouched; restore without valid R2 GUI approval returns `403`.

---

### Bypass BP-03: Workflow Runner `bound_hash` Self-Echo Approval Bypass (`HIGH`)
- **Source Evidence:** `core/jarvis/application/workflow_service.py:291`, `351-359`.
- **Current Behavior:** `POST /v1/workflows/{id}/dry-run` computes and returns `bound_hash` in its JSON response. `POST /v1/workflows/{id}/execute` accepts `bound_hash` directly in the request body and validates only that it matches the recomputed hash—**never requiring or consuming a single-use `ApprovalService` GUI nonce**. Currently this bypass does not execute destructive OS changes solely because `L351-359` mocks step execution; the instant real executors are wired, any caller can self-authorize arbitrary multi-step mutations by echoing `/dry-run`'s output.
- **Expected Behavior:** Multi-step workflow execution containing any Tier-2 action MUST bind its `plan_hash` to a single-use, expiring `ApprovalService` GUI token (`TRUSTED_UI` + `LOCAL`), displaying every step's target and diff preview, and refuse any workflow containing a Tier-3 prohibited action at dry-run time.
- **Probable Root Cause:** Confirmed confusion between an integrity hash (`bound_hash`) and an authenticated human-approval credential (`approval_id` + single-use `nonce`).
- **Verification Status:** `BROKEN` (security design flaw confirmed in `workflow_service.py:291`; live impact currently masked by mock loop at `L351-359`).
- **Proposed Improvements:** Require valid, unconsumed `ApprovalService` verification token referencing `plan_hash` before workflow execution; enforce per-step Policy Engine re-check at runtime (defense-in-depth).
- **Security Implications:** Complete circumvention of Tier-2 human-in-the-loop approval once real workflow step execution is enabled.
- **Acceptance Criteria:** Calling `/execute` with a valid `bound_hash` but missing/expired/replayed GUI approval nonce deterministically returns `403 APPROVAL_REQUIRED`.

---

### Bypass BP-04: Unchecked Replay & Orphaned Executor on `fs.file.move` + Ignored `grant.scope` (`HIGH`)
- **Source Evidence:**
  - `core/jarvis/domain/policy.py:315-331` (`_has_active_grant`): queries active `permission_grant` rows by `capability` only, **completely ignoring `grant.scope`** (a grant scoped to `D:\Notes` authorizes access across the entire filesystem).
  - `core/jarvis/application/turn_orchestrator.py:399-407` & `apps/desktop/src-tauri/src/commands.rs:152-158`: `target_snapshot_hash` is never computed or passed during R2 approval creation/confirmation (TOCTOU vulnerability if file changes between preview and execution).
  - `core/jarvis/application/turn_orchestrator.py:733-813` (`execute_approved_file_move`): has **zero callers** in `app.py`, never verifies `bound_hash` match against requested src/dst, never prevents approval replay, and uses non-atomic `Path.rename()` (which on Windows/POSIX fails across volumes or risks target collision if unchecked).
  - `core/jarvis/application/storage_service.py:308`: `POST /v1/storage/migrate` executes file relocation directly without Policy/Approval gating.
- **Current Behavior:** Scope constraints on grants are illusory; R2 file moves cannot execute from the UI today, yet the latent executor lacks TOCTOU hash verification and replay protection.
- **Expected Behavior:** `_has_active_grant` enforces canonical path-prefix containment (resolving symlinks/junctions via `realpath`) against `grant.scope`; Tier-2 approvals bind `(action, canonical_src, canonical_dst, target_snapshot_hash, expires_at)` to a single-use cryptographic nonce consumed atomically inside a DB transaction; destination existence check forbids overwriting existing user files.
- **Probable Root Cause:** Confirmed incomplete authorization enforcement in `policy.py` and unwired/incomplete R2 transaction lifecycle in `turn_orchestrator.py`.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Implement canonical scope matching in `policy.py`; wire `execute_approved_file_move` via atomic approval-consumption endpoint; reject any move/rename whose destination already exists (preventing indirect overwrite deletion); gate `/v1/storage/migrate` behind `ApprovalService`.
- **Security Implications:** Overly broad scope grants + destination overwrite during move/rename would violate both Tier-2 scoping and Tier-3 non-destruction rules.
- **Acceptance Criteria:** Grant scoped to `<SCOPE_A>` deterministically returns `403` for paths in `<SCOPE_B>` or symlinks escaping `<SCOPE_A>`; replaying a used approval nonce returns `409/403`; moving onto an existing target file is blocked (`0%` silent overwrite).

---

### Bypass BP-05: Direct REST API Policy Bypass & Missing Untrusted-Origin Tainting (`HIGH`)
- **Source Evidence:**
  - `core/jarvis/transport/app.py`: Over a dozen state-changing or sensitive endpoints bypass `PolicyEngine` / `ApprovalService` completely, including `/v1/storage/migrate`, `/v1/storage/cleanup`, `/v1/storage/locations/*`, `/v1/grants`, `/v1/roots`, `/v1/screen/analyze`, `/v1/web/*`, `/v1/knowledge/query`, `/v1/camera/grant`, `/v1/iot/ha/actuate`, `/v1/backups/create`.
  - `core/jarvis/domain/models.py:412` (`SessionContext.untrusted_origin`): defined in the domain model to enforce `BR-15` (prompt-injection isolation), but **never set to `True` anywhere in the codebase** (dead security control).
  - `core/jarvis/application/turn_orchestrator.py:276-370`: untrusted data (screen OCR, RAG documents, web summaries) injected into conversation context can persist into `_session_history` without taint tags, creating a **second-order prompt injection** path on subsequent turns.
- **Current Behavior:** Only the narrow `TurnOrchestrator` path checks `PolicyEngine`; calling REST endpoints directly (or from an extension/script holding the bearer token) bypasses Policy/Approval entirely. Furthermore, `BR-15` untrusted-origin tainting is non-functional.
- **Expected Behavior:** Every sensitive/state-changing route enforces Policy + Approval inside the authoritative application service layer (not merely inside `TurnOrchestrator`); any turn consuming web, document, OCR, email, or MCP external output marks `SessionContext.untrusted_origin = True` (and taints derived session memory), disallowing automatic elevation or unreviewed state-changing proposals.
- **Probable Root Cause:** Confirmed decentralized enforcement (policy applied only at one orchestrator entry point rather than as mandatory service-layer middleware/guards) and unwired `untrusted_origin` flag.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Centralize authorization enforcement in a mandatory `AuthorizedActionGateway` invoked by **both** `TurnOrchestrator` and direct HTTP routes; enforce `untrusted_origin` taint propagation across `TurnOrchestrator`, RAG, Web, Screen OCR, and future MCP tool outputs.
- **Security Implications:** Any prompt injection embedded in a PDF, webpage, or screenshot—or any local rogue client with the loopback token—can bypass policy controls.
- **Acceptance Criteria:** Every state-changing route requires explicit policy classification and audit trail; tainting a session via untrusted PDF/web content deterministically blocks automatic R1/R2 tool chaining without explicit GUI review.

---

### Bypass BP-06: Voice-vs-GUI Approval Boundary Weaknesses & Lock-Screen Bypass (`HIGH`)
- **Source Evidence:**
  - `core/jarvis/application/approval_service.py:181-185`: checks `modality == "TRUSTED_UI"` and `origin == "LOCAL"` and `not is_os_locked` to enforce that voice alone cannot approve R2 actions.
  - `core/jarvis/transport/app.py:1290-1315`: **reads `modality` and `origin` directly from the client-supplied JSON request body** and **hardcodes `is_os_locked = False` at `L1300`**! No Windows `WM_WTSSESSION_CHANGE` / `OpenInputDesktop` lock-state check exists.
  - `core/jarvis/transport/app.py:748`: voice turns run with a separate `session_id` than the UI, and SSE approval events omit the approval `nonce`, breaking legitimate GUI approval for voice-initiated requests while leaving the REST endpoint spoofable.
- **Current Behavior:** Any HTTP client (or voice/remote bridge) can forge `{"modality": "TRUSTED_UI", "origin": "LOCAL"}` even while the Windows workstation is locked, bypassing the voice-cannot-approve-file-changes invariant. Simultaneously, legitimate voice-triggered R2 proposals cannot cleanly surface their preview + nonce to the Tauri GUI dialog.
- **Expected Behavior:**
  - Only the trusted local Tauri desktop shell (bound via dedicated local IPC channel / per-session GUI signing secret, never self-reported JSON strings from voice/remote origins) may submit `TRUSTED_UI` confirmations.
  - `is_os_locked` MUST be queried live via Windows native session API (`WTSQuerySessionInformation` / `OpenInputDesktop` + `WM_WTSSESSION_CHANGE`), rejecting all approvals while locked.
  - Voice requests proposing a Tier-2 action open the native GUI `<dialog>` showing target, diff/preview, impact, countdown timer, Approve/Reject/Cancel controls, and explicitly inform the user by voice: *"Perubahan file membutuhkan persetujuan di layar."*
- **Probable Root Cause:** Confirmed trust in self-declared client JSON fields + hardcoded `is_os_locked=False` + missing voice-to-GUI approval handoff channel.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Separate trusted GUI IPC confirmation credentials from general Core API tokens; wire real Windows session-lock detection in Rust Tauri broker and Core; route voice-initiated Tier-2 proposals to the GUI approval queue with full preview & single-use nonce bound to the GUI session.
- **Security Implications:** Voice-replay attacks, nearby speakers, or locked-screen injection could forge `TRUSTED_UI` JSON fields if endpoint authentication is shared.
- **Acceptance Criteria:** Voice utterances (`"ya setuju"`, `"approve"`, `"lanjutkan"`) can NEVER approve a Tier-2 action (`0%` voice-only approval rate); submitting an approval while Windows is locked (`Win+L`) is rejected (`423 LOCKED`); spoofed remote/non-GUI JSON payloads fail cryptographic GUI-channel verification.

---

### Bypass BP-07: Silent `screen.read` Auto-Grant & Duplicate-Row Revocation Failure (`MEDIUM`)
- **Source Evidence:**
  - `apps/desktop/src/lib/brokerClient.ts:273-278`: Desktop startup silently creates a `screen.read` permission grant on behalf of the user without explicit consent.
  - `apps/desktop/src-tauri/src/commands.rs:195-210` & `core/jarvis/transport/app.py:1162`: Every startup inserts a **new duplicate UUID grant row** for the same capability, while UI revocation only revokes a single `grant_id`—leaving older duplicate grant rows active in SQLite!
- **Current Behavior:** Revoking `screen.read` in the Privacy/Security panel appears to succeed in the UI, yet `PolicyEngine._has_active_grant()` still finds an older active duplicate row and continues permitting screen captures.
- **Expected Behavior:** Grants are deduplicated (unique active grant per `(capability, canonical_scope)`), revoking a capability revokes **all** matching active grant rows atomically, and screen reading follows explicit user consent (or clearly surfaced Tier-1 toggle during onboarding with working single-click revoke).
- **Probable Root Cause:** Confirmed non-idempotent grant creation on startup + single-row revocation semantics.
- **Verification Status:** `BROKEN`.
- **Proposed Improvements:** Add SQLite unique partial index on active grants `(capability, scope_canonical) WHERE revoked_at IS NULL`; update revoke endpoint to revoke by `(capability, scope)` or cascade all duplicates; remove silent startup grant mutation.
- **Security Implications:** Broken revocation violates user privacy control and undermines trust in the permission dashboard.
- **Acceptance Criteria:** Launching the desktop app 5 consecutive times creates at most `1` grant row per capability/scope; clicking Revoke immediately flips `PolicyEngine` evaluation to `DENIED` (`0` stale active rows remaining).

---

## 3. Future & Adjacent Surface Bypass Vector Analysis (Native, MCP, Browser & GUI Automation)

Because Addendum §B explicitly requires auditing **all indirect bypass paths** (native tools, MCP tools, browser automation, and GUI automation), the table below documents how Tier-3 prohibitions can be circumvented indirectly unless hardened at the architecture level:

| Attack / Bypass Vector | Indirect Destruction or Escalation Mechanism | Current Code Exposure | Mandatory Trusted-Logic Defense |
| --- | --- | --- | --- |
| **Native File Tools (Write/Move/Edit)** | Overwriting a user file with empty/truncated content (`write("")`), moving onto an existing filename, or following NTFS junction/symlink into `Windows`/`Users` outside authorized scope. | `fs.file.move` lacks destination-exists guard & symlink check; `storage_service.cleanup_cache` unlinks arbitrary dirs; `backup_service.create_backup` overwrites arbitrary paths. | Enforce `realpath` scope containment, block reparse points/junctions, forbid overwriting existing files without explicit Tier-2 diff + atomic backup-before-write (`.jarvis-preedit` shadow copy), ban `unlink`/`rmtree`/`SHFileOperation(FO_DELETE)` on user scopes entirely. |
| **Native App Launcher & Document Opener** | Launching LOLBins/shells (`cmd.exe`, `powershell.exe`, `pwsh.exe`, `wscript.exe`, `mshta.exe`, `regedit.exe`, `rundll32.exe`, `diskpart.exe`, `format.com`, `wsl.exe`) or opening script/shortcut files (`.bat`, `.ps1`, `.vbs`, `.lnk` with hidden args) to run `Remove-Item`/`del`. | Currently masked by 3-app allowlist, but **critical blocker** when enabling dynamic app/file opening. | Hardcoded immutable Tier-3 LOLBin/shell/script-host denylist enforced in Python + Rust; reject `.lnk` targets resolving to denylisted binaries or carrying shell arguments; document-open strictly allowlists non-executable data MIME/extensions (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.png`, `.jpg`, `.mp4`, etc.). |
| **MCP Tools (Future Extensibility)** | A third-party MCP server exposing `delete_file`, `run_shell`, `sql_exec`, or rug-pulling a read-only tool description into a destructive tool after install; indirect prompt injection from tool output steering native tools. | `ecosystem_service.py` is currently a stub (`NOT IMPLEMENTED`); zero MCP runtime exists yet. | Classify every MCP tool statically + by capability schema; hard-block Tier-3 destructive/shell capabilities at MCP Host layer; pin tool manifest SHA-256; default all MCP write/external tools to Tier-2 GUI approval; run stdio MCP servers in isolated Win32 Job Objects with stripped env & OS-restricted paths; taint all MCP outputs (`untrusted_origin=True`). |
| **Browser Automation (Future / Web Tool)** | Navigating to `file://` URLs, downloading & executing `.exe`/`.msi`/`.ps1` installers, clicking "Delete Account / Delete Drive Files" in authenticated web sessions, or exfiltrating local data via URL query parameters. | `web` adapter currently performs HTTP fetch with SSRF TOCTOU risk (DNS rebinding between check and fetch); zero headless browser automation currently wired. | Fix DNS-pinning anti-SSRF on HTTP fetches; if browser automation is ever added, run in isolated profile (zero access to user's logged-in browser cookies), block `file://` and executable downloads, require Tier-2 GUI approval before any form submit / POST / click on destructive web actions. |
| **GUI Automation (`SendInput` / Accessibility)** | Sending `Shift+Delete`, `Ctrl+A -> Backspace -> Ctrl+S`, opening Run dialog (`Win+R`) to type `powershell`, or clicking "Approve" on JARVIS's own R2 approval dialog! | Not yet implemented (`desktop_automation.py` only has stubbed app launch). | **Never** grant generic unrestricted keystroke/mouse injection to the LLM. If limited UI automation is ever added, forbid `Win+R`, `Shift+Delete`, `Alt+F4` on unsaved docs, forbid targeting JARVIS's own HWND (`GetCurrentProcessId` / broker PID exclusion), and require explicit per-action Tier-2 GUI approval. |

---

## 4. Target Authorization Architecture Invariants (Acceptance Gate)

Before any new file, application, workflow, or MCP capabilities ship, the trusted authorization layer (`PolicyEngine` + `ApprovalService` + `AuthorizedActionGateway`) must pass the following non-negotiable invariants:

1. **Single Authoritative Policy Chokepoint:** Zero REST endpoints, voice handlers, workflow steps, or MCP dispatchers may bypass `AuthorizedActionGateway`.
2. **Immutable Tier-3 Hard Ban:** Tier-3 prohibitions (user file/DB deletion, Recycle Bin move, formatting, arbitrary shell/LOLBin execution, indirect overwrite destruction) are enforced in compiled/trusted Python & Rust logic and **cannot be overridden by LLM prompts, user voice commands, config flags, or permission grants**.
3. **Zero-Friction Tier 1 Within Scopes:** Ordinary read-only discovery, authorized search, document read/open (safe extensions), non-elevated trusted app launch, system resource inspection, and volume/media control succeed automatically with canonical scope checks and full audit logging.
4. **Cryptographically Scoped Tier-2 GUI Approvals:** Every consequential state change requires a live, unlocked local GUI confirmation displaying exact target, diff/preview, and impact, bound to `(action, canonical_target, target_snapshot_hash, expires_at)` and consumed atomically on first use.
5. **100% Automated Negative Security Suite:** Dedicated regression suite asserting `0%` unauthorized execution across all 7 documented bypass paths (`BP-01`–`BP-07`) and all LOLBin/symlink/reparse/voice-approval vectors.
