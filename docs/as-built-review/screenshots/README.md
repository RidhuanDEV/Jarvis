# Runtime Screenshots & Visual Evidence

> **Capture Boundary Notice (Strict Read-Only Audit Policy):**
> Per Section 15 & Section 16 of the audit specification, this folder contains **strictly authentic runtime screenshots** of the actual implemented J.A.R.V.I.S. (`v0.2.1`) application. **Zero design mockups, concept styleframes, or synthetic wireframes are included.**

---

## Included Authentic Runtime Evidence

| File | Capture Source | What It Proves | Referenced By |
| --- | --- | --- | --- |
| [actual-voice-command-center-defect-01.png](./actual-voice-command-center-defect-01.png) | Owner-captured live Windows desktop screenshot during actual voice operation prior to audit | Confirms live runtime stack (`STT: faster-whisper-small`, `TTS: Piper ID Lokal`, `Brain: Qwen3-4B-Q4_K_M (cuda)`), demonstrates confirmed voice/STT/LLM defect (`Anda: "Hey Jarvis, sekarangnya berapa?"` -> nonsensical English echo `"What is the current time?"` instead of reporting local time), and exposes SSE synchronization disconnect (`Event Cursor: seq #0` remained zero after a completed voice turn). | `01-EXECUTIVE-SUMMARY.md`, `05-VOICE-AND-AUDIO-PIPELINE.md`, `13-UI-UX-AND-MOTION-AUDIT.md`, `25-OWNER-REPORTED-ISSUES.md`, `26-VOICE-PIPELINE-ROOT-CAUSE-ANALYSIS.md` |

## Additional Visual Captures Pending Authorized Runtime Session

Because this audit was conducted in **strict read-only mode** (without launching the desktop application, mutating local runtime state, or executing live browser/desktop automation), screenshots of the remaining 11 desktop tabs (`Memory`, `Knowledge`, `Tasks`, `Approvals`, `Workflows`, `Settings`, `Security/Privacy`, `Hardware`, `Storage`, `Extensions`, `Diagnostics`) were **not** synthetically fabricated.

An external reviewer with authorized local runtime access can capture live state across all 12 tabs following the non-destructive verification protocol in [../24-EXTERNAL-REVIEW-HANDOVER.md](../24-EXTERNAL-REVIEW-HANDOVER.md).
