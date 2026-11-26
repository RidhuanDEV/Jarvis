# API, IPC, Events & Tool Contracts

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Transport conventions
Desktop React calls native Tauri IPC allowlisted commands; broker attaches per-run auth token to HTTP localhost core. UI never receives token. Server rejects missing token, invalid Host and unexpected Origin; no wildcard CORS or remote WebView. JSON UTF-8; schema version 1; maximum request 256 KiB (files handled by scoped local references). HTTP 401 unauthenticated, 403 denied, 409 conflict, 422 invalid, 429 capacity, 503 degraded; errors include stable code, safe message, correlation_id, retryable. State transitions asynchronous; HTTP 202 is acceptance, not completion. SSE events authenticated by broker and relayed to UI; reconnect with sequence cursor; expired cursor triggers state resync.

## 2. IPC and internal endpoints
| IPC command | Internal route | Payload / result | Priority |
|---|---|---|---|
| submit_turn | POST /v1/requests | text, channel, client_request_id → request_id/state | P0 |
| get_request | GET /v1/requests/{id} | state + redacted step results | P0 |
| cancel_request | POST /v1/requests/{id}/cancel | accepted + state | P0 |
| approve_action | POST /v1/approvals/{id}/decision | decision, nonce, bound_hash from trusted UI | P0 |
| set_audio_mode | PUT /v1/audio/mode | muted/wake/ptt; state | P0 |
| list_memories | GET /v1/memories | cursor, query, limit → page | P0 |
| mutate_memory | POST/PATCH/DELETE /v1/memories[/{id}] | text, expected_revision or delete | P0 |
| reminders | GET/POST/PATCH/DELETE /v1/reminders[/{id}] | title, local_time, timezone, recurrence, revision | P0 |
| permissions | GET/PUT /v1/grants[/{id}] | scoped capability + revision; trusted UI | P0 |
| health | GET /v1/health | readiness, degraded reasons, worker metrics | P0 |
| event_stream | GET /v1/events | SSE cursor → ordered event stream | P0 |
| knowledge | POST /v1/roots; POST /v1/index/jobs; GET /v1/documents | scoped local roots, index jobs, document status | P1 |
| workflows | GET/POST/PATCH /v1/workflows; POST /v1/workflows/{id}/preview or run | typed steps, condition, trigger, version | P1 |
| personal | /v1/tasks, /v1/calendar, /v1/expenses, /v1/habits | typed CRUD + revision | P1 |
| remote | separate gateway /remote/v1/session, /requests, /reminders, /status | scoped paired-device routes only | P2 |

All mutation requests use idempotency key where applicable; key scope actor + operation, same payload returns same result, different payload gives 409. Optimistic revision for mutable entities. Cursor pagination default 25 max 100. File references are root ID + relative path; broker grants exact target rather than accepting arbitrary raw paths from remote. API paths are design contracts, not implemented endpoints or full OpenAPI spec.

## 3. Tool registry schema and examples
```json
{
  "tool_id": "os.volume.set", "version": 1,
  "risk": "R1", "channels": ["local"],
  "capability": "os.volume", "timeout_ms": 3000,
  "idempotent": true,
  "input_schema": {"type":"object","properties":{"percent":{"type":"integer","minimum":0,"maximum":100}},"required":["percent"],"additionalProperties":false},
  "verification": "readback_volume"
}
```
Tool proposal (LLM untrusted): `{"steps":[{"tool_id":"os.volume.set","version":1,"args":{"percent":30}}]}`. Executor adds actor, session, policy, idempotency key, deadline; model cannot supply approval, credentials or risk class. Validation rejects additional fields and >5 steps.

| Tool ID | Args | Risk | Result verification |
|---|---|---|---|
| os.app.open | app_id | R1 | process/window existence; launched not necessarily ready |
| os.volume.get / set | none / percent | R0/R1 | read current / readback |
| file.search / open | root_id, query or relative_path | R0/R1 | path within root, app opened |
| file.rename | root_id, source, destination, revision | R2 | source absent and expected destination exists |
| memory.save | text, type, sensitivity | R1 explicit | committed record ID |
| reminder.create | title, due_at, timezone, recurrence | R1 | persisted reminder+job |
| knowledge.query | query, root_ids | R0 | scoped citations |
| web.search | query | R0 public / R2 private | approved query and source URLs |
| screen.capture | window_id, consent_ref | consent | selected window only, no persist |
| iot.state / set | entity_id, desired_state | R0/R1 allowed only | fresh HA readback |

Example outcome: `{"status":"unknown","code":"VERIFY_TIMEOUT","verified":false,"message":"Tindakan dikirim; status belum dapat dikonfirmasi.","correlation_id":"example-01"}`. Tool error catalogue: INVALID_ARGS, DENIED, APPROVAL_EXPIRED, TARGET_CHANGED, TARGET_AMBIGUOUS, NOT_FOUND, OFFLINE, WORKER_OOM, TOOL_TIMEOUT, VERIFY_TIMEOUT, QUEUE_FULL, CANCELED, UNSUPPORTED, INTERNAL. Do not leak OS exception secrets.

## 4. Events
Envelope `{"schema_version":1,"event_id":"uuid","seq":42,"type":"action.completed","occurred_at":"2026-11-25T07:00:00Z","correlation_id":"example-01","payload":{"status":"completed"}}`. Event types: voice.state_changed, request.state_changed, approval.required, action.completed, job.due, reminder.delivered, model.health_changed, knowledge.index_progress, permission.revoked. Event log redacted; event subscription cannot cause tools. Persistent delivery for scheduler via DB, UI transient events via SSE; event ordering per request, no global distributed ordering claim.

## 5. Compatibility and contract tests
JSON schemas versioned, unknown enum/fields handled explicitly; additive output fields allowed for clients, input extras rejected. CI verifies schema compatibility, auth/negative cases, timeout and cancellation, idempotency/replay, mock adapter readback. Generate actual OpenAPI from implementation and commit snapshot; native IPC reference separately. API change requires RTM and changelog updates.

## Provider and presentation contracts v0.2.0
Authenticated broker operations (versioned; no direct WebView-to-provider): provider.list/probe/enroll/revoke, model.list/import/verify, profile.get/validate/activate/rollback, benchmark.start/cancel/status, visual.preferences.get/set. Mutations require typed validated payload; model activation accepts expected_revision, profile_id, drain_or_cancel; benchmark.start requires explicit local approval. LAN enrollment binds approved identity, endpoint, data scopes; secrets in vault. Events: provider.health, profile.switch.started/committed/failed, model.load, inference.metrics, resource.pressure, visual.tier.recommended, voice.envelope (ephemeral normalized amplitude only, max 30Hz). All events include sequence, correlation/request ID, timestamp; stale/canceled turn events discarded. State events from core, never trusted client assertions. Keep stream semantics separate from verified action outcome; no raw audio or secret in UI telemetry.
