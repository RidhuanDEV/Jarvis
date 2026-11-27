# 08 — Proactive Intelligence & Autonomy Audit

This document audits whether J.A.R.V.I.S. can monitor events, fire due reminders, run scheduled workflows, recognize user habits, or deliver unsolicited proactive intelligence without an immediate user request (`core/jarvis/transport/app.py`, `core/jarvis/application/reminder_service.py`, `core/jarvis/application/workflow_service.py`, `core/jarvis/application/preference_proposal_service.py`, `core/jarvis/application/personal_life_service.py`).

---

## 1. Executive Finding: Proactive Autonomy Is `NOT IMPLEMENTED` at Runtime

**VERDICT: J.A.R.V.I.S. CANNOT initiate any action, notification, reminder, or background workflow without an explicit user/HTTP trigger.**

Exhaustive grep of every `asyncio.create_task`, `threading.Thread`, and timer loop across `core/jarvis/` proves:
- `core/jarvis/transport/app.py:808-830` (`lifespan`) spawns **ONLY ONE** background coroutine: a one-shot startup call `asyncio.create_task(local_llm_manager.start_if_available())`.
- The only `threading.Thread` instances in the entire backend belong to `LiveVoiceEngine` (`_capture_loop` and TTS playback).
- **There is ZERO scheduler loop, ZERO cron engine, ZERO event-monitor daemon, and ZERO OS toast notification adapter in production.**

---

## 2. Component-by-Component Forensic Audit

| Proactive Capability | Status | Exact Source Evidence & Runtime Behavior |
| --- | :---: | --- |
| **Background Scheduler Loop** | **`NOT IMPLEMENTED`** | `ReminderSchedulerService.process_due_reminders()` (`reminder_service.py:182-281`) is **only** called if an external client sends `POST /v1/reminders/process-due` (`app.py:1680-1691`). Neither Rust (`apps/desktop/src-tauri/`) nor React (`apps/desktop/src/`) ever calls this endpoint. |
| **OS Notifications (`NotificationPort`)** | **`MOCK`** | `app.py:621` wires `resolved_notify = notification_port or FakeNotificationAdapter()`. Even if `/v1/reminders/process-due` is invoked manually, notifications append to an in-memory Python list (`portable_mock.py:246-252`) — **zero Windows Toast notifications appear**. |
| **Reminder Quiet Hours, Snooze & Missed Reporting** | **`IMPLEMENTED` (Pull-Only)** | `reminder_service.py:182-356` implements IANA timezone quiet-hours deferral (`22:00–07:00` default), snooze, dismiss, and `missed` status (>15 min past due). **Defects:** (1) `recurrence_json` is always `NULL` (`L130` — recurring reminders unimplemented); (2) `job.lease_until` and `job.attempt` are never updated (no crash-safe lease recovery); (3) never triggered automatically. |
| **Proactive Rate Limiting & Throttling (`BR-11`)** | **`NOT IMPLEMENTED` (DEAD CODE)** | `ProactiveRateLimiter` (`reminder_service.py:62-85`, `debounce=60s`, `<=1/hr`, `<=3/day`) is instantiated as `self.proactive_limiter` (`L103`) and **NEVER called anywhere in production code** (unit-tested in isolation only). |
| **Event Monitoring & Trigger Conditions** | **`NOT IMPLEMENTED`** | Zero OS event hooks (no idle/lock/resume `WM_POWERBROADCAST`, no file watchers, no calendar alert polling, no battery/gaming watchers, no HA state webhook listener). |
| **Scheduled / Event Workflows** | **`NOT IMPLEMENTED` / `MOCK`** | `WorkflowEngineService.create_workflow()` (`workflow_service.py:168`) hardcodes `next_due_at = NULL`. `trigger.kind="schedule"|"event"` and `trigger.expression` are stored as inert strings and never evaluated. `execute_workflow()` (`L351-359`) is a no-op stub. |
| **User Habit Recognition** | **`IMPLEMENTED` (Manual CRUD Only)** | `PersonalLifeService.log_habit()` & `summarize_habit()` (`personal_life_service.py:290-356`) store manually logged habit numbers and compute count/sum/average with a descriptive disclaimer (`BR-18`). Zero automatic habit detection, pattern mining, or UI panel exists. |
| **Proactive Recommendations & Adaptive Proposals** | **`MOCK` / Manual API Only** | `PreferenceProposalService` (`preference_proposal_service.py:43-250`) only accepts manually posted proposals via `POST /v1/preferences/proposals` (`app.py:2271-2286`). Zero correction detector or behavioral observer creates proposals automatically. The UI (`jarvisStore.ts:177-186`) displays a **hardcoded fake proposal** (`prop-verbosity-brief`). |
| **Task Prioritization & Retry/Recovery** | **`NOT IMPLEMENTED`** | `task` table (`0001_initial_core.sql:220-227`) has no `priority` column; `job` retry/backoff (`BR-08`) is unimplemented (`job.attempt` stays `0`); no bounded 20-item mutating workflow queue (`BR-07`) exists. |

---

## 3. Rule-Based Automation vs AI-Driven Autonomous Planning

- **Rule-based automation:** Exists only as passive SQLite schemas and manually invoked REST endpoints (`process_due_reminders`, `dry_run_workflow`). No background evaluator runs the rules.
- **AI-driven autonomous planning:** **Completely absent (0%).** There is no autonomous goal loop, no proactive context synthesis, and no background LLM invocation.
- **Resource Impact Note:** Because zero continuous monitoring loops run (aside from user-armed `LiveVoiceEngine` openWakeWord/VAD), background proactive monitoring consumes `0%` LLM inference—**not by intelligent gating, but because proactive monitoring does not exist**.
