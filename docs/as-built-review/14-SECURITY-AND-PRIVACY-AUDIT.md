# 14 — Security, Privacy, and Reliability Audit

This document presents a severity-ranked security and privacy audit of the actual implementation, verifying whether authorization is enforced in trusted code versus LLM prompts and identifying concrete bypasses, insecure defaults, and data-protection defects.

---

## 1. Fundamental Security Verdict: Trusted Code vs LLM Prompts

- **Core Positive:** On the primary `POST /v1/requests` path, authorization **IS enforced in trusted Python application logic (`PolicyEngine` at `core/jarvis/domain/policy.py:164-331` and `ApprovalService` at `core/jarvis/application/approval_service.py:49-354`)**, NOT merely instructed via LLM prompts. R3 bans (`os.shell.exec`, `fs.delete_permanent`, `payment.transfer`, `email.send`, `iot.lock`) and single-use R2 approval tokens are enforced deterministically in Python.
- **Core Negative:** Multiple sibling HTTP endpoints, file/storage services, network fetchers, local runtime loaders, and Rust IPC proxies **bypass `PolicyEngine`, `ApprovalService`, integrity verification, or anti-SSRF guarantees**—creating **8 CRITICAL** and **16 HIGH** concrete security/privacy exposures.

---

## 2. Severity-Ranked Security & Privacy Findings Ledger

### CRITICAL Findings (`SEC-C01` – `SEC-C07`)

| ID | Area | Exact Source Evidence | Confirmed Vulnerability & Concrete Exploitation / Failure Path |
| --- | --- | --- | --- |
| **SEC-C01** | Policy / Approval Bypass | `core/jarvis/transport/app.py:1099-1116, 1771-1833, 1992-2051`; `workflow_service.py:291` | `POST /v1/storage/migrate` (R2), `/v1/screen/analyze`, `/v1/web/{query,fetch}`, and `/v1/knowledge/query` completely bypass `PolicyEngine`/`ApprovalService`. `POST /v1/workflows/{id}/execute` accepts a caller-echoed `bound_hash` copied directly from `GET /dry-run` without ever consuming an `ApprovalService` nonce. |
| **SEC-C02** | Permanent User-File Deletion Bypass | `storage_service.py:158-218, 346-378`; `app.py:1087-1097, 1118-1134` | 2-step destructive chain with **zero R2 approval**: (1) `PUT /v1/storage/locations/cache` accepts ANY writable folder (e.g., `Documents`/`Desktop`) with no overlap/emptiness check; (2) `POST /v1/storage/cleanup` (`max_bytes=0`) permanently `unlink()`s every file inside (`rglob("*")` also ignores junctions/reparse points). |
| **SEC-C03** | TOCTOU DNS Rebinding SSRF | `core/jarvis/infrastructure/web_fetch.py:149-182` | `pinned_ip = self.validate_and_resolve_url(...)` (`L150`) is **never passed to `httpx`**; `client.get(current_url)` (`L160`) triggers a second unpinned DNS resolution vulnerable to TTL=0 rebinding onto `127.0.0.1` or `169.254.169.254`. Plus `response.content` (`L177`) reads unbounded bytes into RAM before checking 2 MiB limit. |
| **SEC-C04** | Unverified Binary & Model Execution | `local_runtime_manager.py:53-120, 154-196`; `live_voice_engine.py:168-212, 425-480` | `LocalLlmRuntimeManager` executes `llama-server.exe` and loads `.gguf` (including from user-configured `shared_model_directories`) with **zero SHA-256 verification**, zero Authenticode check, and zero `model_manifest` check. `LiveVoiceEngine` similarly loads ONNX/Whisper binaries without SHA-256 checks. |
| **SEC-C05** | Cross-Machine Backup Data Loss (DEK Omission) | `backup_service.py:76-99, 165-226`; `vault.py:32-40` | Portable backup archives omit/fail to re-wrap `jarvis.memory.master_dek.v1` from Windows Credential Manager. Restoring onto another host permanently bricks 100% of `sensitive` memories (`CryptoIntegrityError`) and crashes `list_memories()`. |
| **SEC-C06** | Remote Gateway Crypto / TLS / Replay | `remote_gateway_service.py:87-88, 151-156, 236, 302-329`; `remote_gateway_app.py` | Unwired dead server; **zero TLS/mTLS enforcement** (only stores fingerprint string); bare unsalted SHA-256 on **6-digit numeric pairing code** (`0` Argon2id, `0` attempt limit); TOCTOU race in `approve_pairing_locally` (`core_read` then `UPDATE` without `AND state='pending'`); zero Host/Origin/size middleware. |
| **SEC-C07** | Extension SDK Sandbox Absence | `ecosystem_service.py:228-381` | Zero subprocess/WASM sandbox or artifact file hashing (`install_extension` compares two caller-provided strings!); `authorize_extension_capability` and `verify_lan_dispatch` are dead code. |

### HIGH Findings (`SEC-H01` – `SEC-H12`)

| ID | Area | Exact Source Evidence | Confirmed Vulnerability / Gap |
| --- | --- | --- | --- |
| **SEC-H01** | Silent `screen.read` Auto-Grant & Duplicate Grants | `apps/desktop/src/lib/brokerClient.ts:268-284`; `commands.rs:195-210`; `app.py:1162` | Arming the mic silently grants `screen.read` (violating `DEC-012`/`FR-SCR-01`) AND creates 4 new duplicate UUID rows in `grant` on every toggle—breaking single-row `DELETE /v1/grants/{id}` revocation. |
| **SEC-H02** | Rust IPC Path Traversal | `apps/desktop/src-tauri/src/commands.rs:133,151,282,321,382,398,454` | Raw `format!("/v1/.../{id}")` interpolation with zero percent-encoding or `../` rejection allows a compromised WebView to pivot to arbitrary Core API paths with the Rust Bearer token. |
| **SEC-H03** | Host/IPv6 Bug & Chunked Cap Bypass | `core/jarvis/transport/app.py:117, 854-890` | Empty `Host` bypasses validation; IPv6 `[::1]:port` breaks (`split(":",1)[0]` -> `"["`); `Transfer-Encoding: chunked` bypasses 256 KiB payload limit; `"testserver"` allowed in prod. |
| **SEC-H04** | Client-Trusted Security Flags & No OS Lock Hook | `app.py:329-362, 1295-1332`; `lib.rs` | `/v1/session/lock` never persists server-side lock state on `CoreContainer`/`PolicyEngine`; endpoints trust client-supplied `is_os_locked=False`, `explicit_user_request`, `private_query_approved`, `modality`; Rust has zero `WM_WTSSESSION_CHANGE` OS lock listener. |
| **SEC-H05** | Second-Order Prompt Injection & Tag Breakout | `domain/knowledge.py:192-202`; `turn_orchestrator.py:276-281, 473`; `policy.py:210` | Unescaped `</untrusted_document_data>` breakout; RAG & screen summaries saved verbatim into `_session_history` as `assistant` turns fed to tool-calling LLM next turn; `SessionContext.untrusted_origin` is dead (never set `True`). |
| **SEC-H06** | `execute_approved_file_move` Replay & TOCTOU | `turn_orchestrator.py:399-407, 733-791`; `commands.rs:152-158`; `windows/filesystem.py:156` | Never checks `bound_hash`/`tool_id`/`source_root` or marks approval executed (infinitely replayable); `target_snapshot_hash` never populated in live flows; `.rename()` lacks Win32 handle pinning. |
| **SEC-H07** | Arbitrary File Overwrite on Backup Create | `app.py:2332-2337`; `backup_service.py:101-104` | `body.archive_path` unconfined to `backups` root (`staging.replace(dest)` overwrites arbitrary writable files). |
| **SEC-H08** | Plaintext SQLite Databases at Rest | `core/jarvis/infrastructure/dual_db.py:67` | Zero SQLCipher/full-DB encryption; all `normal` memories, tasks, expenses, audit logs, and 100% of indexed personal document text (`jarvis_knowledge.db`) sit unencrypted on disk. |
| **SEC-H09** | Unbounded Argon2id KDF Header DoS | `core/jarvis/infrastructure/crypto.py:129-139` | Untrusted `t`/`m`/`p` from unauthenticated backup JSON header passed straight into Argon2id without min/max bounds. |
| **SEC-H10** | Log Redaction Ordering & Key Regex Gaps | `core/jarvis/infrastructure/logging_setup.py:13-30, 61-70` | `format_exc_info` runs **after** `_redact_and_sanitize_processor` (leaking secrets in tracebacks); `^...$` anchor on `SENSITIVE_KEY_RE` misses `recovery_passphrase`, `bearer_token`, `pairing_code`, `provider_api_key`; `sanitize_log_string` misses `sk-`, `ghp_`, `AKIA`, PEM, NIK. |
| **SEC-H11** | Screen Privacy Bypass (`screen_capture.py`) | `platform/windows/screen_capture.py:40-55`; `screen_service.py:118,143`; `security_guards.py:43-60` | `has_focused_password_field=False` hardcoded; no Win32 `TokenElevation` check; elevated apps hit `AccessDenied` → `"pid:N"` bypassing blocklists; `window_title` unredacted; `^`-anchored env secret regex bypassed by JSON/inline secrets. |
| **SEC-H12** | `grant.scope` Unenforced | `core/jarvis/domain/policy.py:315-331` | `_has_active_grant()` ignores `grant.scope` completely—all grants act as unscoped wildcard grants for their capability. |

### MEDIUM / LOW Findings (`SEC-M01` – `SEC-M06`)
- **`SEC-M01` (`llama_cpp_adapter.py:23-60`):** Managed `llama-server` binds `127.0.0.1:<port>` without `--api-key`, allowing any local process to query the loaded model.
- **`SEC-M02` (`app.py:1472`):** `POST /v1/models?verify_local_file=false` allows skipping SHA-256 verification.
- **`SEC-M03` (`remote_gateway_service.py:465, 476-501`):** OS lock still permits remote `GET` reminder disclosure; invalid tokens bypass rate limiter.
- **`SEC-M04` (`app.py:1160`):** `PUT /v1/grants` permits inserting `PROHIBITED_CAPABILITIES` rows (blocked later at policy eval).
- **`SEC-M05` (`settings.py:34`, `ipc_transport.rs:49`):** Minimum token length check `< 32` chars (`128-bit` hex) contradicts `"256-bit"` validation message (generators do produce 64 hex chars = 256-bit).
- **`SEC-M06` (`windows/vault.py:1, 32-40`):** Missing promised DPAPI fallback; silently overwrites DEK if decoded length != 32; no check rejecting insecure keyring backends.

---

## 3. Reliability & Crash-Recovery Audit Summary

- **Strong (`VERIFIED`):** Win32 Job Object (`KILL_ON_JOB_CLOSE`) cleanly releases Python Core and `llama-server.exe` on exit while sparing `external_local` processes; single-instance mutex eliminates WebView2 `0x800700AA` lock crashes; SQLite WAL + `foreign_keys=ON` + `deletion_ledger` startup orphan GC work cleanly.
- **Weak / Broken:** Zero Python Core crash-restart loop in Rust (`lib.rs`); zero `llama-server` crash watchdog (`local_runtime_manager.py`); Python Core `stdout`/`stderr` discarded to `Stdio::null()` (`process_supervisor.rs:212-213`); Tray `stop_all` murders Python Core and destroys the Job Object (`lib.rs:95-98`); Rust `10s` HTTP timeout aborts `60s` LLM turns (`lib.rs:46`); non-atomic `executescript()` migrations (`migrations.py:102`); live-WAL `shutil.copy2` DB migration (`storage_service.py:295`).
