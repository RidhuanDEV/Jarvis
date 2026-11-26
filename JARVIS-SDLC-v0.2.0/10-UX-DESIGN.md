# UX/UI Specification & Interaction Design

**Project:** J.A.R.V.I.S. Local Personal Intelligence System  
**Version:** 0.2.0 | **Status:** Proposed baseline, belum diimplementasikan  
**Tanggal:** 25 November 2026 | **Pemilik persetujuan:** Product Owner

## 1. Product experience
Desktop tray-first, optional compact overlay and full dashboard. Voice natural and concise; show transcript and action cards. Avoid fake sci-fi telemetry; visual state reflects actual system state. Primary language Indonesian, English selectable. No claim of sentience. WCAG-inspired accessibility: keyboard, visible focus, labels, contrast, no color-only state; validate screen reader and reduced motion.

## 2. Information architecture
| Screen | Contents / actions |
|---|---|
| First-run setup | hardware check, models, language, audio test, consent, optional wake, permitted apps; network off |
| Tray | mute, PTT, open dashboard, pause automation, offline toggle, stop current action, quit |
| Voice overlay | waveform/indicator, partial transcript, final response, cancel, text alternative |
| Dashboard | current state, upcoming reminders, recent verified activities, quick commands, resource status |
| Chat | text/voice history for session, source cards, actions, clarify/approve cards |
| Memory | searchable facts, source/time, edit/delete, pending proposals, retention settings |
| Knowledge | approved roots, indexing queue/errors, document preview/locator, revoke |
| Personal | tasks, calendar, expense totals by currency, habit logs |
| Automation | rule builder, trigger, conditions, typed steps, preview, runs, stop |
| Integrations | OS apps/folders, web network, read-only calendar/email, IoT and paired devices by phase |
| Settings & security | permissions, voice/model profiles, quiet hours, backups, audit, privacy, health |

## 3. Interaction flow
Onboarding: welcome → explain local data and mic → check actual hardware → install/verify models with consent → test mic/TTS → choose PTT/wake → grant only selected app actions → offline smoke command → dashboard. Skip model download leaves direct mode; no forcing network permissions. On wake: sound/visual indicator → listen → transcribe → clarify or plan → approval if required → progress → verified outcome → idle. If user interrupts, cancel audio and prior unstarted steps; confirm already-applied effects. Overlay always has stop button and text fallback.

Approval card: action and target, exact argument before/after, risk label, consequences, expiry countdown, Approve once / Reject. No approve by voice. Escape closes/rejects; focus returns to triggering action; no auto approval. If target changed, show fresh preview. For multi-step mixed action show plan preview and report each result. A red denied action must include reason and safe alternative, not just error code.

## 4. State and feedback design
| State | UI copy/behavior |
|---|---|
| Muted | "Mikrofon nonaktif"; no listening indicator |
| Wake enabled | "Menunggu panggilan"; persistent tray state |
| Listening | live indicator + stop, partial transcript if available |
| Thinking/loading | "Memuat model lokal" or "Memproses" based on real state, no fake percentage |
| Approval | explicit dialog, target and expiry, no hidden effects |
| Degraded | "Model lokal tidak tersedia; perintah dasar masih dapat digunakan" |
| Offline | "Mode offline; pencarian internet dinonaktifkan" |
| Partial/unknown | distinguish completed steps and unverified outcome; offer safe readback |
| Host unavailable | mobile shows last successful contact and no execution confirmation |

## 5. UX acceptance
Keyboard-only setup, chat, stop, approval, permissions and memory delete; screen reader announcement for listening/approval/result; visual indicators for mic/camera; reduced motion; responsive mobile at 360 px minimum candidate; confirmation before destructive settings changes. User can find offline toggle and mute within two interactions from tray. Test Indonesian number/date pronunciation and mixed-language commands with target users. Prototype UI before implementation, no pixel mockups supplied here.

## 6. Art direction and visual system
**Creative direction:** original cinematic command interface, precise, quiet when idle, alive during interaction. One dominant intelligence core instead of a wall of interchangeable cards. Use negative space, thin grid/arc geometry, compact secondary panels and meaningful telemetry. No copied movie HUD, likeness, sound, branding or voice; create original assets.

| Token | Proposed value / rule |
|---|---|
| Background | #080D17 / #101927, layered solid surfaces; glass only where legible |
| Primary / accent | #57DFFF cyan, secondary #7995B8; amber #FFBE69 for approval, red #FF737C for actual errors |
| Text | #E6F1FF main, #A9B9CC secondary, minimum WCAG AA contrast for text and controls; test composited backgrounds |
| Typography | System sans for UI, optional licensed geometric display face for headings, tabular mono for numeric data; no sci-fi font for paragraphs |
| Spacing | 4 px base; 8/12/16/24/32 spacing; 6–14 px panel corners; alignment over decorative borders |
| Effects | Thin halos, low-opacity gradients, sparse grid; avoid blur on large animated surfaces, no full-screen shader by default |
| Sound | Optional original earcons for wake/result/error; mute and quiet hours honored; no imitation of film actor |

### Command Center layout blueprint
```text
┌──────────────────────────────────────────────────────────────────┐
│ JARVIS / LOCAL   Mic state   Active model / runtime   System health │
├───────────────┬──────────────────────────────────┬───────────────┤
│ Navigation    │ Context label / current task     │ Next reminders│
│ Home          │                                  │ Real CPU/GPU  │
│ Conversation  │     Animated intelligence core   │ Active tools  │
│ Knowledge     │       + live state / waveform    │ Network status│
│ Automation    │                                  │               │
│ Personal      │ Transcript / response / citations│ Recent activity│
│ Models        │ Clarify / action / approval card │               │
│ Settings      │ Text input   PTT   Stop          │               │
└───────────────┴──────────────────────────────────┴───────────────┘
```
At smaller widths, side rail collapses and right region becomes drawer; keyboard focus order remains logical. Test 1024×768, 1366×768, 1920×1080, 125/150/200% DPI, multiple monitors. Compact HUD shows core, mic state, transcript, stop; movable, clamped to working area, click-through never applied to controls, always-on-top opt-in. Fullscreen optional with Esc exit; no forced fullscreen. Tray and text mode remain available independently of renderer. Mobile R3 uses static/light core and responsive safe controls, not desktop HUD squeezed into phone.

## 7. Motion choreography and state machine
Motion is state-driven; backend sequence numbers/request IDs resolve out-of-order updates; stale events cannot revive a canceled turn. Mic, camera, offline and model location are independent status badges, not inferred from ring color. State precedence: locked/muted privacy indicators override input visualization; awaiting approval overlays actual current request; error and partial/unknown remain visible until acknowledged. Parallel background jobs have own status and cannot hijack foreground animation.

| Engine state | Visual/audio treatment | Transition / exit |
|---|---|---|
| Startup | Original arc assembly + readiness text, optional skip | ≤600ms decorative portion, no delay to available controls; readiness based on health |
| Idle | Slow low-amplitude orbit/breath, 6–10s cycle optional | Static after idle timeout or in Lite; never implies recording |
| Listening | Cyan inner ring opens, waveform follows normalized mic RMS | 100–180ms enter; close when capture stops; no raw frames persisted |
| Transcribing | Short directional sweep, partial transcript | Stop listening waveform; streaming text without layout jumping |
| Thinking / loading | Segmented orbit, distinct truthful status text | 180–240ms transition; indeterminate unless genuine progress available |
| Executing | Action steps animate into list, actual started/done/failed icons | No premature success; cancel remains available |
| Approval | Amber stationary/slow halo, clear trusted dialog | Focus trapped; no auto approval; no motion obscuring details |
| Speaking | Core expands to actual TTS playback envelope | Smooth attack/release, stop within cancel budget; no fake audio amplitude |
| Success | Single restrained outward pulse and verified result | 220–350ms then idle; avoid repeated reward effects |
| Error / degraded | Ring settles, short non-flashing amber/red cue and text | Retry/direct-mode options; not every error requires red |
| Muted/locked/offline | Explicit persistent label; static core when appropriate | No mic animation on muted/locked; offline may coexist with speaking |

Motion tokens: micro interaction 100–160ms; enter/exit 160–240ms; page/shared layout 220–350ms; cinematic transitions 350–600ms only on non-blocking opt-in scenes. Use spring for core response with bounded overshoot, ease-out enter/ease-in exit; no animation delaying input, approval or stop. Interruptible, retargetable transitions, no queued animations across turns. Prefer transform/opacity, CSS/SVG, Motion for React for layout/choreography; Canvas 2D optional for particles with capped DPR and update rate. WebGL/Three.js optional later after measured benefit; no mandatory 3D render loop. Dynamic values via motion values/requestAnimationFrame, not React rerender at audio sample rate. Audio visualization uses ephemeral envelope sampled at 20–30 Hz and interpolation; smooth attack 50ms/release 150ms candidates. Never pass raw PCM through UI telemetry solely for animation.

## 8. Adaptive rendering and performance budget
| Visual quality | Rendering policy |
|---|---|
| Cinematic | Full core geometry, subtle parallax/particles, shared transitions; optional fullscreen; requires admission by resource governor |
| Balanced default | SVG core, controlled glow, limited particles, motion transitions; 60Hz target |
| Lite | Static geometry + low-frequency indicators, no blur/particles/parallax; 30Hz maximum visual updates |
| Reduced Motion | OS preference or manual; static status + short opacity transitions when safe; overrides all tiers |

Auto downgrade with explicit visible reason when GPU/CPU pressure, hidden/minimized UI, battery saver or measured frame misses; re-upgrade only after stable headroom (candidate 15s hysteresis), no profile flapping. Pause continuous render loops when hidden; only state events continue. Manual Cinematic preference is a ceiling, not permission to starve AI. No telemetry upload. Test with LLM warm/active, STT, TTS, indexing and simulated desktop workload. Reference 60Hz Balanced p95 frame interval ≤20ms and input-to-visible feedback ≤100ms; log dropped/long frames, CPU/GPU and memory. R0 determine incremental UI budget (candidate ≤300MB RAM and ≤250MiB GPU when foreground, within combined NFR-02 envelope); no guarantee before measurement. Use WebView2 performance traces, not FPS counter alone. R0 compare SVG/Canvas prototype; test Lite retains input target when loaded. Frame budget failures block promotion of tier, not core offline operation.

## 9. Model Manager and AI Settings UX
Tabs: Overview, installed models, providers, profiles, benchmark/history, advanced. Show model role, family/version, quantization, capabilities (chat, schema/tool, embeddings, STT/TTS/vision), backend, local/LAN trust badge, file/hash/license status, measured VRAM/RAM, estimated vs measured clearly labeled, context and last health. Import flow: choose file/provider → inspect manifest and license → explain size/location → explicit install/import consent → checksum/health → test → activate or keep installed. No download on open. LAN enrollment includes host identity, TLS trust, scope and warning that selected data leaves workstation; no public endpoint. Secret input write-only and stored via OS vault. Active request: switch after drain or explicit cancel; display old model until committed, rollback with reason if failed. Profile selection preview: effect on quality, latency, resources; custom fields validate bounds; unsupported fields disabled, never silently ignored. Benchmark is explicit, cancelable, labeled load test; no run without consent. Embedding switch indicates reindex state and lexical fallback. Return to known healthy profile and direct-mode always reachable.

## 10. Design handoff and interaction quality gates
R0: original low-fi layout, visual styleframes, clickable prototype for idle→listen→think→speak and approval/cancel; actual local renderer spike under inference; owner approves direction before asset expansion. R1: reusable token library, core component, overlay/tray, keyboard and focus, motion state controller, mock-event story fixtures, settings/model manager and responsive shell. R2/R3: extend same tokens/state semantics to documents, vision, IoT and mobile. Use Storybook or equivalent isolated component catalog (candidate), visual regression on fixed snapshots with animations frozen; motion tested separately via event timelines/video traces. QA covers 12 states, 20 rapid transitions, interruption, lost worker, offline, muted, DPI, resize, idle/minimized, accessibility, and concurrent inference. No high-frequency flashing, no motion-only information. All motion and 3D assets original/licensed; asset inventory includes source and license. No actual prototype or implemented interface is delivered by this document.
