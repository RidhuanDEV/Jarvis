# 07 — Tool Execution and Automation Audit

This document audits the tool registry, schemas, parameter validation, OS/desktop/file/browser/IoT execution adapters, human approval binding, outcome verification, audit logging, and declarative workflow automation (`core/jarvis/transport/app.py`, `core/jarvis/domain/policy.py`, `core/jarvis/application/turn_orchestrator.py`, `core/jarvis/application/approval_service.py`, `core/jarvis/application/workflow_service.py`, `core/jarvis/platform/windows/*`).

---

## 1. Tool Registry, Discovery & Schema Validation

- **Tool Registry (`core/jarvis/transport/app.py:120-255`, `default_tool_registry()`):** Static hardcoded dictionary of **13 `ToolSpec` entries** keyed by `(tool_id, version=1)`. Zero dynamic tool discovery or plugin tool registration exists.
- **Proposal Schema (`core/jarvis/domain/models.py:382-390`, `contracts/tool-proposal.schema.v1.json`):** `ToolProposal` enforces `steps` length `1..5`, `extra="forbid"`, `tool_id` regex `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*){1,3}$`, `version` `1..99`. **Drift:** Pydantic omits `maxProperties: 24` on `args`, and there is **zero per-tool JSON Schema validation** of `args` before `_execute_verified_step()` indexes dictionary keys directly (`turn_orchestrator.py:515, 532, 556, 570, 598, 663` -> unhandled `KeyError`/`ValueError` = HTTP 500).

### Complete 13-Tool Execution & Verification Audit Matrix

| # | `tool_id` (v1) | Risk | Capability | Channels | Declared Verification | Actual Runtime Implementation & Verdict | Status |
| :---: | --- | :---: | --- | --- | --- | --- | :---: |
| 1 | `system.time.get` | R0 | `system.time` | local, remote | `return_clock` | Reads `ClockPort.now_utc()`, converts to explicit IANA or OS local TZ (`turn_orchestrator.py:495-512`). | **`VERIFIED`** |
| 2 | `os.volume.set` | R1 | `os.volume` | local | `readback_volume` | Calls legacy `winmm.waveOutSetVolume(0, ...)` (`desktop_automation.py:61-73`) — **does NOT control Windows WASAPI master system volume**, and silently falls back to `_software_volume_fallback` on error, faking `verified=True`. | **`BROKEN`** |
| 3 | `os.app.launch` | R1 | `os.app.launch` | local | `process_started` | **`app.py:620` hardcodes `allow_live_launch=False`!** `desktop_automation.py:38-39` returns `True` without calling `subprocess.Popen`, reporting `verified=True` for a **no-op**. Allowlist hardcoded to 3 System32 binaries (`calc.exe`, `notepad.exe`, `mspaint.exe`); zero `AUMID`/MSIX (`FR-OS-06`). | **`MOCK` / `BROKEN`** |
| 4 | `memory.create` | R1 | `memory.write` | local | `sqlite_commit` | Persists row to `jarvis_core.db` (`memory_service.py:65-122`); verified commit. Never retrieved by LLM. | **`VERIFIED`** |
| 5 | `reminder.create` | R1 | `reminder.write` | local, remote | `sqlite_commit` | Persists `reminder` + `job` rows (`reminder_service.py:105-160`). No background scheduler ever fires it. | **`PARTIAL`** |
| 6 | `life.task.create` | R1 | `life.task` | local, remote | `sqlite_commit` | Persists `task` row (`personal_life_service.py:89-111`). | **`VERIFIED`** |
| 7 | `life.task.list` | R0 | `life.task` | local, remote | `sqlite_read` | Reads open/in-progress tasks (`turn_orchestrator.py:618-646`). | **`VERIFIED`** |
| 8 | `knowledge.query` | R0 | `knowledge.read` | local, remote | `citation_readback` | Calls `KnowledgeRagService.answer_from_knowledge` (`turn_orchestrator.py:648-683`), BM25-only (`embedding_provider=None`), `tools_disabled=True`. | **`PARTIAL`** |
| 9 | `screen.analyze` | R1 | `screen.read` | local | `redacted_uia_read` | Reads foreground window title + process name ONLY (`screen_capture.py:26-55`), redacts secrets on `extracted_text` (not `window_title`), zero UIA tree/OCR, hardcodes `has_focused_password_field=False`. | **`PARTIAL`** |
| 10 | `storage.location.migrate` | R2 | `storage.migrate` | local | `sha256_integrity` | **No executor branch** in `_execute_verified_step()` (returns `UNSUPPORTED`). Direct route `POST /v1/storage/migrate` bypasses Policy/Approval! | **`BROKEN`** |
| 11 | `fs.file.move` | R2 | `fs.move` | local | `handle_readback` | Pauses at `202 AWAITING_APPROVAL`, **but `execute_approved_file_move()` (`turn_orchestrator.py:733-813`) has ZERO callers in `app.py`!** Approving in GUI never moves any file. Also uses path `.rename()` (no Win32 handle pinning) and fails to bind `approval_id` to `bound_hash` (replayable). | **`BROKEN`** |
| 12 | `web.search.query` | R0 | `web.search` | local | `http_response` | **No executor branch** in `_execute_verified_step()` (`UNSUPPORTED`), absent from LLM prompt, `search_provider=None` in `WebIntelligenceService`. | **`NOT IMPLEMENTED`** |
| 13 | `os.shell.exec` | R3 | `shell.exec` | local | `never` | Hard-banned by `PolicyEngine` (`403 DENIED`, `policy.py:24, 179-188`). | **`VERIFIED`** |

---

## 2. Desktop, OS, Browser, File & IoT Integration Reality Check

- **Desktop / Application Control:** Only 3 System32 Win32 binaries in `_ALLOWLISTED_WINDOWS_APPS` (`desktop_automation.py:13-17`), disabled by `allow_live_launch=False` (`app.py:620`). Zero GUI automation, zero window management, zero media playback controls, zero installed-app discovery.
- **File Operations:** Only `fs.file.move` is registered (and orphaned post-approval). `WindowsFilesystemSafetyAdapter` (`platform/windows/filesystem.py:1-191`) blocks UNC/network drives and reparse points in `resolve_within_root`, **but** `snapshot_target()` (`L156-167`) uses `path.stat()` (zero Win32 `CreateFileW` handle pinning -> TOCTOU window). Zero file search, file open (`os.startfile`/`ShellExecuteW`), file copy, or Recycle-Bin trash tools exist.
- **Browser Integration:** **NOT IMPLEMENTED.** Zero browser automation, tab reading, bookmark search, or web search provider (`search_provider=None` in `app.py:660`). Only `POST /v1/web/fetch` (`SafeWebFetchClient`) fetches a single URL (with SSRF DNS-rebinding TOCTOU defect at `web_fetch.py:149-160`).
- **IoT / Home Assistant Integration (`core/jarvis/application/home_assistant_service.py`):** Domain allowlist & R3 safety-critical entity bans (`lock.*`, `alarm_control_panel.*`, `valve.*`, `climate.*`, `cover.*`, `siren.*`, `iot_and_remote.py:17-51`) are implemented and unit-tested, **but `app.py:692` passes `client=None` (`OfflineHomeAssistantClient`)** — zero live Home Assistant REST/WebSocket client exists.

---

## 3. Declarative Workflow Automation (`WorkflowEngineService`)

- **Source:** `core/jarvis/application/workflow_service.py:1-398`, `core/jarvis/transport/app.py:1941-2051`.
- **What actually works:** Persists typed workflows (`1..5` steps, no loops/arbitrary code) into `workflow` table, computes deterministic `bound_hash`, and runs dry-run policy classification (`dry_run_workflow`, `L189-244`).
- **CRITICAL DEFECT #1 — Complete Execution Stub (`workflow_service.py:311-360`):**
  ```python
  results.append(
      WorkflowStepRunResult(
          index=idx,
          tool_id=step.tool_id,
          state=ActionOutcomeState.COMPLETED,
          idempotency_key=idem_key,
          note="Verified step completion.",
      )
  )
  ```
  `WorkflowEngineService` holds **zero reference** to `TurnOrchestratorService` or any tool adapter. It only calls `policy.evaluate_step()` and fabricates `"Verified step completion."` without executing a single real action!
- **CRITICAL DEFECT #2 — R2 Approval Self-Echo Bypass (`workflow_service.py:291`, `app.py:1964-2030`):** Any caller can copy `bound_hash` from `GET /v1/workflows/{id}/dry-run` into `POST /v1/workflows/{id}/execute` without ever creating or consuming a single-use `ApprovalService` challenge!
- **CRITICAL DEFECT #3 — Unwired Scheduling & Test Flags in Prod:** `next_due_at` is always `NULL` (`L168`); `wf.enabled` is never checked (`L287`); `app.py:486-487` exposes `cancel_after_step` and `simulate_unknown_at_step` test hooks on production HTTP routes.

---

## 4. Action Outcome Verification & Audit Logging (`BR-05`, `FR-ADM-04`)

- **Does JARVIS verify that actions actually succeeded before reporting success?**
  - **Partially / Violated in key adapters:**
    - SQLite mutations (`memory.create`, `reminder.create`, `life.task.create`) genuinely verify commit before returning `COMPLETED`.
    - **`os.app.launch` violates `BR-05`:** reports `verified=True` and `"berhasil dijalankan"` even though `allow_live_launch=False` skipped launching the process (`desktop_automation.py:38-39`).
    - **`os.volume.set` violates `BR-05`:** `winmm.waveOutSetVolume` silently falls back to `_software_volume_fallback` and reads back its own memory variable (`desktop_automation.py:59, 73`).
    - **`execute_workflow` violates `BR-05`:** reports `"Verified step completion."` without executing any step.
- **Audit Logging (`audit_event` table):** Security/admin operations (grants, approvals, providers, models, profiles, memories, tasks, screen, camera, HA, remote, workflows, extensions, backups) write redacted rows into `audit_event` with `correlation_id`. However, `TurnOrchestratorService` **never writes `request` or `action_run` rows** for R0/R1/LLM turns (only `ApprovalService.create_challenge` writes them for R2).
