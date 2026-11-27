# Security Policy — J.A.R.V.I.S. Personal Intelligence OS

## Local-First Security Architecture & Trust Boundaries

J.A.R.V.I.S. enforces defense-in-depth through trusted application code — never relying on LLM prompt instructions alone:

1. **Tier 1 (Ordinary Read-Only & Non-Destructive Local Actions):**
   - Searching authorized opt-in directories, opening ordinary non-executable documents, launching trusted non-elevated installed applications, adjusting audio volume, and reading system time.
2. **Tier 2 (Consequential State Changes — Mandatory Single-Use Local GUI Approval):**
   - Editing or moving files within an authorized root, migrating storage roots, or running R2 workflow steps require an explicit local GUI confirmation dialog (`modality="trusted_ui"`, `channel="local"`) bound cryptographically via a single-use 256-bit nonce, canonical parameter hash, and TOCTOU target snapshot hash (`409 TARGET_CHANGED` on external modification).
   - Voice confirmation alone and remote sessions are strictly prohibited from approving Tier-2 actions.
3. **Tier 3 (Permanently Prohibited Actions):**
   - Deleting user files or directories, moving user files to the Recycle Bin, formatting drives, executing arbitrary shells/LOLBins (`cmd.exe`, `powershell.exe`, `mshta.exe`, etc.), UAC elevation, bypassing policy gates, or indirect data destruction via truncation/overwrite.
4. **Prompt-Injection Isolation (`BR-15`):**
   - Document RAG synthesis runs with `tools=[]` and delimiter escaping (`[ESCAPED_TAG]`).
   - Sessions exposed to untrusted external/document/screen content inherit `untrusted_origin=True`, blocking LLM-proposed state mutations.
5. **Local IPC & Secrets Hygiene:**
   - Loopback-only authenticated transport with per-run 256-bit CSPRNG Bearer token delivered via stdin pipe, strict `Host` & zero-CORS `Origin` validation, 256 KiB payload caps, OS Credential Vault / DPAPI key storage, AES-256-GCM sensitive memory encryption, and Argon2id encrypted portable backups.

## Reporting a Vulnerability

Please report suspected security defects privately to the repository maintainer with:
- Affected component/file path and version (`v0.2.2+`).
- Minimal reproduction steps inside an isolated temporary directory.
- Observed vs expected policy/security behavior.

Never test security findings against live personal documents or production credential stores.
