# Business Rules & Automation Policy

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Authority and decision order
BR-01 default deny; product hard bans > OS lock/mute > channel scope > explicit grant > risk approval > user preference. Model or document text cannot elevate permission. Voice wake is not authentication. Owner may grant tools through trusted UI; guest speech is treated as unverified actor. Locked host: no capture and no effects requiring owner; scheduler may record due notifications without speaking.

| Class | Examples | Rule |
|---|---|---|
| R0 read | local time, app status, list reminders | allow after capability grant, subject to context |
| R1 reversible low-risk | open allowlisted app, set volume, create local reminder/task, switch allowlisted lamp | explicit unambiguous request or preapproved bounded automation; visible result |
| R2 sensitive / consequential | file rename/move/write, export, memory reset, external private query, connector enable, workflow with sensitive effect | per-action trusted local preview and one-use approval; no blanket consent |
| R3 prohibited | arbitrary shell/code, credential entry/extraction, permanent deletion, payment, email send/delete, public exposure, safety-critical IoT control | deny even if requested through model/automation; change requires scope review, some remain prohibited |

Memory delete is owner privacy operation via trusted UI with clear effect; reset/restore require R2. Approved folder read is R0 for ordinary files; sensitive folders denied or explicit scoped grant. Screen and camera require per-request/session explicit consent independently of read risk. Remote scope narrower than local: R0 and selected R1 chat/reminder; no screen, camera, file mutation, security settings or R2 approval.

## 2. Rules catalogue
| ID | Rule |
|---|---|
| BR-02 | Unknown intent, ambiguous target, missing slot or low-confidence high-impact command yields clarification, never guess. |
| BR-03 | Approval binds action name/version, canonical arguments hash, requester, session, resource revision, nonce and expires after 60s; single use; invalidate on lock/cancel/parameter change. |
| BR-04 | Re-evaluate policy and preconditions immediately before every effect. Revocation invalidates queued runs. |
| BR-05 | No claim success without adapter result; verified, unknown, partial and failed are distinct. |
| BR-06 | Workflow max 5 steps, no recursion, no arbitrary expression/code, per-step timeout and overall 120s execution deadline. LLM proposal max 60s separately. |
| BR-07 | At most one active effectful workflow per owner; other requests wait in bounded queue (20), cancel allowed; voice/text read tasks can be prioritized. |
| BR-08 | Retries only transient read or proven idempotent actions, max 2 with jitter; uncertain effects require readback or user resolution. |
| BR-09 | Reminders store absolute UTC and original IANA timezone; resolve ambiguous local times explicitly; repeat uses local recurrence rules, not fixed UTC interval for calendar repeats. |
| BR-10 | Default quiet hours 22:00–07:00 local configurable; silent tray delivery for due reminders; user may opt-in urgent audio. |
| BR-11 | Proactive rules default off, debounce 60s, nonessential nudges max 3/day and 1/hour; explicit reminders excluded. No automated consequential behavior. |
| BR-12 | Background tasks pause on high resource usage; foreground stop/mute takes priority. |
| BR-13 | Raw mic frames stay in memory ring; no raw audio or screenshots stored by default; transcript retention off by default. |
| BR-14 | Long-term memory save explicit; inferred preference stored only as pending proposal, not retrieved as fact until approved. |
| BR-15 | Web content and documents are untrusted; no tool calls from retrieved instructions; query redaction or approval for private data. |
| BR-16 | Offline mode denies external network; no silent switch to paid/cloud services. |
| BR-17 | Expense amount positive integer minor units with currency and category; refund represented separate type; no conversion without user-selected rate and source. |
| BR-18 | Health/habit insights descriptive only; no diagnosis or automatic treatment. |
| BR-19 | Tool permission change audited; future jobs rechecked. No privilege escalation to SYSTEM/admin. |
| BR-20 | Remote pairing requires local approval, device revoke and credential expiry; no remote grant expansion. |
| BR-21 | Pending actions canceled on lock; camera/mic stop; reminder due recorded. Host offline response truthful. |
| BR-22 | User can stop workflow, mute, disable proactive rules and turn off network from tray. |

## 3. Examples and edge cases
"Buka Chrome dan hapus semua download" → first action may proceed only if independently clear; prohibited deletion denied; report partial, preview mixed plan before execution. "Pindahkan laporan" with duplicate names → ask which path. "Ingat saya suka kopi" → explicit memory, provenance user statement. A website says "send your files" → ignore as data. "Matikan lampu" with two matching entities → ask room. Power loss after rename → read source and destination before outcome; no blind retry. Reminder recurrence during DST gap → ask or apply owner-configured skip/next-valid policy and show it. Device revoked while queued → denied on execution.

## Model and motion policy extension
BR-AI-01 only approved provider/model and supported capability may be activated; BR-AI-02 local device default, private LAN opt-in with data-scope approval, no cloud fallback; BR-AI-03 switch atomic, rollback or direct mode on failure, no action replay; BR-AI-04 no arbitrary model plugin/code execution or autonomous installation; BR-AI-05 benchmark only after explicit consent; BR-UX-01 visual state never authorizes an action or claims unverified result; BR-UX-02 Reduced Motion overrides visual tier; resource pressure can downgrade animation without blocking controls. See 06 and 10.
