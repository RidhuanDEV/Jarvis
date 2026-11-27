# J.A.R.V.I.S. — SDLC `v0.2.2` Change Proposal (Delta Over Frozen `v0.2.1` Baseline)

**Document ID:** `G0-SDLC-DELTA-001`  
**Base Frozen Baseline:** `JARVIS-SDLC-v0.2.1/` & `planning/DECISION-REGISTER.md` (`DEC-001`–`DEC-030`) — **kept untouched for audit provenance**  
**Proposed Target Revision:** `v0.2.2` Remediation Baseline → Foundation for `JARVIS 2.0` Roadmap  
**Status:** **PROPOSAL PENDING OWNER APPROVAL AT GATE G0**

---

## 1. Purpose & Governance Rule

Per `JRV-IR-001` §2.4 & §16, this document proposes targeted amendments to existing ADRs, decisions (`DEC-001`–`DEC-030`), and requirements (`FR`/`NFR`) rather than duplicating decisions or rewriting the frozen `v0.2.1` SDLC corpus. Substantive product policy changes below require explicit owner approval before `G1` implementation modifies authorization, storage, or transport behavior.

---

## 2. Proposed Decision Register Revisions (`DEC-001`–`DEC-030` Amendments + New Decisions)

| Decision ID | Type | Frozen `v0.2.1` Baseline | Proposed `v0.2.2` Amendment | Triggering Review Findings |
| :---: | :---: | --- | --- | --- |
| **`DEC-012` (Amend)** | Substantive Policy | Empty deny-by-default grants across all tools (including `R0`/`os.app.launch`), causing repetitive rejection on ordinary safe actions while ignoring `grant.scope` | **3-Tier Owner Policy via Single Authoritative Gateway (`AuthorizedActionGateway`):**<br>• **T1 (Auto-Allow within Initial Scope Consent):** discover/launch ordinary trusted non-elevated apps, search/open safe docs in authorized scopes, read permitted files, system resource status, volume/media, time/reminders.<br>• **T2 (Explicit GUI Approval):** exact diff/preview + single-use nonce + unlocked OS for file edit/create, persistent settings, external transfer, first-use screen/camera, software install.<br>• **T3 (Immutable Hard Prohibited):** user file/folder/DB deletion, Recycle Bin move, drive format, destructive overwrite/truncation, arbitrary shell, UAC elevation, unrestricted GUI robot — enforced in trusted Python/Rust code, never overridable by LLM/voice/approval. | `IR-01`, `IR-02`, `IR-03`, `IR-07`, `IR-09`, Review §5.1–5.2 |
| **`DEC-019` (Amend)** | Substantive Policy | 11 storage roots with `cleanup_cache_lru` accepting arbitrary cache folder and `migrate_location` copying open WAL | **Ownership-Bound Cache & Safe No-Delete Migration:** Cache cleanup restricted strictly to JARVIS-owned artifact records inside an immutable sentinel-verified root (zero reparse traversal, zero arbitrary user folder adoption). Migration uses online SQLite backup / quiesced copy + SHA-256 verification + atomic control-plane pointer switch; **never auto-deletes source files** under no-delete policy (user cleans old copy manually). | `IR-01`, `IR-02`, `DEF-14`, Review §5.3, §12.3 |
| **`DEC-007` (Amend)** | Technical Hardening | Dual SQLite (`jarvis_core.db` + `jarvis_knowledge.db`), `AES-256-GCM` sensitive fields, portable `Argon2id` backup | **Portable Recovery Key Wrapping & Integrity Bounds:** Wrap per-machine memory DEK inside the passphrase-protected recovery envelope (bounded KDF params to stop OOM DoS); fail closed on missing/invalid key; verify real cross-machine restore with `is_encrypted=1` fixtures; add SQLCipher evaluation spike before full DB encryption migration. | `IR-06`, `DEF-24`, Review §5.3, §12.3 |
| **`DEC-008` (Amend)** | Transport Interim ADR | Windows Named Pipe (`DACL` current-SID) target | **Formalize Authenticated Loopback Interim + Named Pipe Target:** Explicitly permit hardened loopback (`127.0.0.1` only, per-start 256-bit secret, IPv6/Host check fixed, chunked body cap, typed Rust IPC IDs, authenticated SSE, authoritative Win32 OS-lock guard) as documented G1–G2 interim while scheduling Windows Named Pipe migration before public release. | `IR-07`, `IR-08`, `DEF-22`, Review §5.3 |
| **`DEC-013` & `DEC-028` (Amend)** | Voice Architecture | Separate `VoicePipelineService` + `LiveVoiceEngine` (`language="id"`, sync capture, `OWW_WAKE_THRESHOLD=0.45`) | **Unified Asynchronous Voice/Text Runtime:** Single capture->DSP->VAD->STT->Normalizer->Shared Turn Coordinator->TTS->Playback pipeline; count real voiced frames only; non-blocking capture queue; configurable bilingual ID+EN decoding + confidence gating + Voice Lab diagnostics; no synthetic-only WER certification. | `IR-10`, `DEF-17`, `DEF-37`, Review §8 |
| **`DEC-021` (Amend)** | Supply Chain & Provenance | Auto-discover `llama-server.exe`, `.gguf`, `.onnx` from configured folders | **Strict Binary & Model Provenance:** Reject auto-execution of unverified binaries/models from arbitrary shared folders; require independently trusted release manifest + SHA-256 verification (and signature where available) before spawning runtimes or loading weights. | `IR-05`, Review §5.3, §12.3 |
| **`DEC-024` (Amend)** | Extensibility Strategy | Custom `extension_package` SQLite SDK | **Adopt Standard MCP as Opt-In Sandboxed Extensibility (Phase G6):** Keep all core desktop/app/file/voice/scheduler tools native & fast; retire dead custom plugin runner in favor of read-only-first, hash-pinned, policy-mediated MCP Host/Client only after G1–G4 gates pass. | `IR-20`, Review §11 |
| **`DEC-031` (New Proposal)** | Evidence & Release Governance | Manual status claims (`VERIFIED_LOCAL_TIER_A`) | **Evidence-Derived Verification Taxonomy:** Replace manual signoff with strict states (`IMPLEMENTED_SOURCE`, `VERIFIED_UNIT`, `VERIFIED_INTEGRATION`, `VERIFIED_INSTALLED_E2E`, `VERIFIED_HARDWARE_CLASS`, `MOCK`, `PARTIAL`, `BLOCKED`, `NOT_IMPLEMENTED`). Production composition root (`app.py`) MUST fail closed or honestly mark capabilities `unavailable`—**mock adapters prohibited in production**. | Review §2.4, §4 |
| **`DEC-032` (New Proposal)** | File & App Intelligence Separation | 4-format RAG only + 3 hardcoded System32 apps | **4-Layer Filesystem Intelligence + Native Windows App Catalog:** Separate Layer 1 fast metadata index (opt-in authorized scopes, excluded secret dirs) from Layer 2 FTS5 full-text, Layer 3 optional local semantic embeddings, and Layer 4 personal memory/working set; build non-elevated Windows App Catalog (Start Menu validated `.lnk`, `AppsFolder` AUMID, `App Paths`, user-pinned portable apps). | `IR-09`, `IR-15`, Review §6, §7 |

---

## 3. Specific Owner Policy Clarifications Needed Before G1 Code Edits (From Review §5.1 & §15)

The following **4 product-policy edges** directly affect G1/G2 code implementation and are surfaced explicitly for owner confirmation at Gate G0:

1. **File Move / Rename (`FR-OS-04` vs Strict Tier-3 No-Delete):**
   - *Context:* Moving a file removes its original pathname and can resemble deletion or cause collisions if unchecked.
   - *Options:* **(A — Recommended)** Disable `fs.file.move` during G1 safety lockdown, and re-enable in G4 strictly as **Tier-2 Explicit GUI Approval + No-Overwrite + Same-Scope Check**; or **(B)** Permanently disable file move/rename under strictest no-removal interpretation (file create/diff-edit only).
2. **Owner-Controlled Privacy UI Exception for Erasing JARVIS's Own Saved Memories / Rebuildable Indexes (`FR-MEM-02` / `FR-MEM-05`):**
   - *Context:* Tier-3 prohibits any assistant/tool-triggered deletion of user files or databases. However, managing privacy requires a separate owner-clicked GUI action to erase JARVIS's own stored memory rows or rebuild local indexes.
   - *Options:* **(A — Recommended)** Allow strictly via direct owner GUI interaction in Settings/Memory Inspector (never callable by LLM/voice/MCP tools, with audit log + tombstone); or **(B)** Keep disabled until further review.
3. **First-Run File Metadata Scan Scope Default (`DEC-032`):**
   - *Options:* **(A — Recommended)** Guided GUI selection of standard user folders (`Documents`, `Desktop`, `Downloads`, selected project folders) by default + opt-in per-drive broad metadata scan (always excluding OS/credential/secret dirs); or **(B)** Restrict strictly to manually added individual folders only.
4. **Git Isolation Strategy for G1–G5 Execution (`Review §13 & §15`):**
   - *Context:* Current working tree has `19` modified tracked files + `5` untracked code files (`dirty diff` `169,231` bytes) on `main`.
   - *Options:* **(A — Recommended)** Create a local branch `remediation/v0.2.2-g1` from current state (without committing or pushing yet—preserving `main` cleanly while isolating G1–G5 patches locally), OR **(B)** Patch directly in current working tree on `main` (zero Git branch/commit mutations until owner explicitly approves a commit).

---

## 4. Requirements Impact Summary (`FR` / `NFR` Targets for `v0.2.2`)

- **Tightened / Hardened in G1:** `FR-ADM-01`, `FR-ADM-02`, `FR-ADM-03`, `FR-ADM-04`, `FR-ADM-05`, `FR-ADM-08`, `FR-AUT-02`, `FR-WEB-02`, `FR-SYS-03`, `FR-SYS-04`, `FR-SCR-01`, `NFR-04`, `NFR-05`, `NFR-10`.
- **Reconstructed in G2–G3:** `FR-OS-01`, `FR-OS-02`, `FR-OS-03`, `FR-OS-05`, `FR-OS-06`, `FR-VOI-01`..`06`, `FR-COR-01`, `FR-COR-04`, `FR-COR-05`, `FR-ADM-07`, `FR-UX-01`.
- **Completed in G4–G5:** `FR-COR-03`, `FR-COR-07`, `FR-MEM-01`..`05`, `FR-SCH-01`..`05`, `FR-KNO-01`..`05`, `FR-AUT-01`, `FR-AUT-03`, `FR-SCR-02`, `FR-SCR-04`, `FR-AIP-01`..`08`, `FR-UX-02`..`04`, `FR-SYS-01`, `FR-SYS-02`, `FR-SYS-05`, `NFR-01`, `NFR-02`, `NFR-06`, `NFR-13`.
- **Explicitly Deferred Beyond Core Remediation (G6–G7):** `FR-SYS-06` (MCP read-only pilot in G6), `FR-WEB-01`, `FR-LIF-04`, `FR-IOT-01`..`04`, `FR-REM-01`..`04`, optional model adaptation/LoRA (`NFR-07` human baseline first).
