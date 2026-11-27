# 11 — API, IPC, and Event Contracts Audit

This document audits the HTTP API surface (`core/jarvis/transport/app.py`, `remote_gateway_app.py`), the Rust Tauri IPC layer (`apps/desktop/src-tauri/src/commands.rs`, `lib.rs`, `ipc_transport.rs`), the SSE event bus (`core/jarvis/infrastructure/event_bus.py`), and all 4 JSON Schema contracts (`contracts/*.json`).

---

## 1. Local IPC & Transport Reality (`DEC-008` Deviation)

- **Configured Transport:** `http://127.0.0.1:<ephemeral_port>` with 64-hex-char (`256-bit`) `Authorization: Bearer <token>` piped via stdin (`core_launcher.rs:205-229`, `transport/__main__.py:14-20`).
- **Windows Named Pipe (`DEC-008`):** **NOT IMPLEMENTED.** `IpcTransportKind::WindowsNamedPipe` (`ipc_transport.rs:9`) and `windows_named_pipe_path()` (`L62-65`) are dead code; `app.py:756` labels `transport_kind="win_named_pipe_or_loopback"`, yet no Named Pipe listener exists anywhere.
- **OpenAPI Spec (`08-INTERFACE-CONTRACTS.md` §5):** **NOT IMPLEMENTED.** Zero OpenAPI files exist in `contracts/`; FastAPI explicitly disables schema export (`openapi_url=None`, `app.py:837`, `remote_gateway_app.py:82`).

### Critical Transport & Proxy Bugs
1. **Rust 10s Global HTTP Timeout (`apps/desktop/src-tauri/src/lib.rs:45-49`):** `reqwest::Client::builder().timeout(Duration::from_secs(10))` applies to ALL 41 commands including `submit_turn` (where Core allows `60s`).
2. **Rust Path Traversal in 7 Commands (`commands.rs:133, 151, 282, 321, 382, 398, 454`):** Direct `format!("/v1/.../{id}")` interpolation with zero percent-encoding or `../` rejection.
3. **IPv6 `[::1]` Broken + Empty Host Bypass + Chunked Cap Bypass (`app.py:854-890`):** `"[::1]:47123".split(":", 1)[0]` produces `"["` → `403`; empty `Host` bypasses check; `"testserver"` stays allowed in production; chunked transfer encoding bypasses 256 KiB payload cap; Pydantic `422` validation errors are NOT converted to `ErrorEnvelope` (`app.py:2401-2408` handles `HTTPException` only).
4. **Silent Stdin Token Fallback (`transport/__main__.py:14-20`):** If `JARVIS_TOKEN_FROM_STDIN=1` but stdin is empty/EOF, silently falls back to a newly generated random token instead of failing closed.

---

## 2. Backend Route Surface vs Tauri IPC vs Frontend Usage

| Surface | Total Endpoints / Commands | Wired to Frontend UI | Unused / Dead |
| --- | :---: | :---: | :---: |
| **Local Core FastAPI (`app.py`)** | **96 route paths** (95 handlers) | **19** reachable via UI | **56** have no Tauri command; **22** Tauri commands never invoked by UI |
| **Remote Gateway (`remote_gateway_app.py`)** | **5 routes** (`/remote/v1/*`) | **0** | **5** — server is **never started** outside `TestClient` |
| **Rust Tauri IPC (`commands.rs`)** | **41 commands** | **19** invoked in `brokerClient.ts` | **22** dead commands (`get_config`, `set_storage_location`, `lock_session`, `list_memories`, `list_reminders`, `list_profiles`, `activate_profile`, `rollback_profile`, `list_knowledge_roots`, `add_knowledge_root`, `revoke_knowledge_root`, `query_knowledge`, `list_tasks`, `get_expense_summary`, `list_workflows`, `list_extensions`, `list_ha_entities`, `list_remote_devices`, `list_preference_proposals`, `get_audio_state`, `set_audio_mode`, `emergency_stop_managed_workers`) |

### Key Unmapped Backend Capabilities (56 Routes Missing From `commands.rs`)
- **SSE Events:** `GET /v1/events` (`app.py:2368`)
- **Config Lifecycle:** `PUT /v1/config`, `POST /v1/config/{rollback,import}`, `GET /v1/config/export`
- **Storage Ops:** `GET /v1/storage/volumes`, `POST /v1/storage/{migrate,cleanup}`
- **Grants & Policy:** `GET /v1/grants`, `DELETE /v1/grants/{id}`, `POST /v1/policy/evaluate`
- **Providers & Models:** `GET/POST /v1/providers`, `POST /v1/providers/{id}/probe`, `GET/POST /v1/models`, `POST/DELETE /v1/providers/lan/*`
- **Audio & Memory/Reminders:** `PUT /v1/audio/devices`, `POST /v1/audio/test`, `PATCH /v1/memories/{id}`, `POST /v1/memories/{id}/approve`, `POST /v1/reminders/{process-due,snooze,dismiss}`
- **Knowledge, Web, Screen, Life, Workflows, Extensions, Camera, HA, Remote, Backups:** `POST /v1/roots/{id}/sync`, `/v1/web/{query,fetch}`, `/v1/screen/analyze`, `PATCH /v1/tasks/{id}`, `/v1/calendar`, `/v1/habits`, `/v1/workflows/{create,dry-run,execute}`, `/v1/extensions/{install,toggle}`, `/v1/camera/*`, `/v1/iot/ha/actuate`, `/v1/remote/{config,pairing/*}`, `/v1/licenses/{sbom,notices}`, `/v1/backups/{create,verify}`.

---

## 3. Event-Driven Architecture (`SequencedEventBus` & SSE `/v1/events`)

- **Backend Implementation (`core/jarvis/infrastructure/event_bus.py:1-63`, `app.py:2368-2398`):**
  - Maintains monotonic global `_seq` counter and a bounded `deque(maxlen=256)` replay ring buffer (`event_bus.py:25-33`).
  - `GET /v1/events?after_seq=<n>` replays missed events from the ring buffer, then streams live SSE frames with `15s` keepalive comments (`app.py:2376-2395`).
  - **Thread-safety bug (`event_bus.py:52-54`):** Calls `queue.put_nowait(event)` directly on `asyncio.Queue` without `loop.call_soon_threadsafe()`, unsafe from non-event-loop threads.
- **Frontend & Broker Disconnection (`BROKEN`):**
  - **Zero SSE client exists in Rust (`src-tauri/`) or React (`apps/desktop/src/`).**
  - `jarvisStore.ts:299-349` (`applySequencedEvent`) is dead code in production (called only by `foundation.test.tsx`). Consequently, `Event Cursor` in the desktop UI is permanently frozen at `seq #0`, and voice-triggered R2 approval events never appear in the UI.
  - Even if connected, `approval.required` payload (`approval_service.py:150-158`) **omits `nonce`**, which `ApprovalChallengeSchema` (`apps/desktop/src/lib/contracts.ts:167`) requires (`min(16)`), so Zod validation would reject it!

---

## 4. Contract Files (`contracts/*.json`) — Runtime Validation vs Drift Audit

| File (`Draft 2020-12`, `v1`) | Validated Against File at Runtime? | Observed Contract Drift / Defects |
| --- | :---: | --- |
| `contracts/config.schema.v1.json` | **YES (Backend)** (`config_service.py:31,104,154`); **NO (Frontend)** | `contracts/` excluded from Python wheel (`pyproject.toml:55`) → `FileNotFoundError` outside git repo. |
| `contracts/tool-proposal.schema.v1.json` | **NO (Tests only)** | Backend Pydantic `ToolStepProposal` (`models.py:382`) omits `maxProperties: 24` on `args`. |
| `contracts/events.schema.v1.json` | **NO (Tests only)** | **ACTIVE RUNTIME VIOLATION:** `camera_service.py:154,203,249` emits `event_type="camera.indicator_changed"`, which is **NOT in the 19-value enum** of `events.schema.v1.json`! Backend `SequencedEvent` leaves `type: str` unconstrained; frontend `SequencedDomainEventSchema` (`contracts.ts:175`) is never called at runtime. |
| `contracts/license-artifact.schema.v1.json` | **NO (Tests only)** | Validated only via Pydantic `LicenseArtifact` (`domain/licensing.py`). |
