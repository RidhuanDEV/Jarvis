# B25 — Evidence-Gated Model Adaptation & Fine-Tuning Decision Record

**Decision Date:** `2026-11-27`  
**Source Authority:** `docs/JARVIS-INDEPENDENT-REVIEW-AND-ENHANCEMENT-PLAN.md` (`JRV-IR-001`, §14.1–14.2)  
**Primary Evidence:** `planning/remediation-v0.2.2/G6-EVAL-SCORECARD.json` (`pilot-bilingual-v1.0`, `held_out_test`, SHA-256 `e31a25aebaa68bca0545a3b98876f9ca3bb73d78f9c684712358c9e390a98f43`)

---

## 1. Executive Decision: **NO FINE-TUNING / NO WEIGHT TRAINING AT GATE G6**

Per `JRV-IR-001` §14.1–14.2, model fine-tuning (LoRA / STT adapter / custom wake-word weight training) is **NOT justified** at Stage G6:

1. **Zero residual deterministic text-routing or entity errors on the sealed pilot `held_out_test` split:**
   - Intent exact accuracy: **`23/23` (`100.0%`, 95% Wilson CI `[0.857, 1.000]`)**, Macro-F1 = **`1.000`**
   - Entity Top-1 app resolution: **`4/4` (`100.0%`, 95% Wilson CI `[0.510, 1.000]`)**
   - Negation & meta-question safety: **`4/4` (`100.0%`, 95% Wilson CI `[0.510, 1.000]`)**
   - Tier-3 prohibited denial: **`5/5` (`100.0%`, 95% Wilson CI `[0.566, 1.000]`)**
   - Unauthorized execution rate: **`0/9` (`0.0%`, 95% Wilson CI `[0.000, 0.299]`)**
   - Routing latency: **`p50 = 0.0159 ms`**, **`p95 = 0.1514 ms`**
   - Even the single colloquial Indonesian miss surfaced during the first eval run (`"Hey Jarvis, pukul berapa sekarang ya?"`) was resolved cleanly by a 1-token grammar update (`_TIME_RE`) with precision/recall probes passing (`recall_ok=True, precision_ok=True`) — zero model weight modification required.
2. **Non-parametric learning already solves owner personalization immediately:**
   - Instant alias learning (`"<alias> maksud saya <target>"`, `B13`), persistent `MemoryVault`, and TTS pronunciation dictionaries (`B12`) adapt immediately without GPU training cost, catastrophic forgetting, or safety regressions.
3. **Human acoustic WER baseline is NOT YET collected (`Not measured`):**
   - Training an STT adapter or custom wake-word model without an owner-consented, multi-condition real human audio corpus violates §14.1 ("No synthetic-only evidence for human WER").

---

## 2. Explicit Quantitative Triggers Required Before Future Training Approval

Any future model training proposal requires separate explicit owner authorization **AND** reproducible evidence on an expanded `held_out_test` corpus (`>= 100` real consented utterances across quiet/noise/headset/speaker conditions):

| Failure Mode | Non-Training First Fix | Quantitative Condition to Propose Training |
| :--- | :--- | :--- |
| Indonesian / code-switch STT errors | Pretrained Whisper model swap (`small`/`medium`), gain/VAD tuning, hotword glossary (`B11`) | Real human audio WER `> 12%` or entity error `> 8%` persisting after audio/hotword tuning |
| Multi-step tool schema drift on local 4B LLM | Strict Pydantic repair loop (`B14`), GBNF grammar decoding, few-shot examples | Held-out malformed tool-proposal rate `> 5%` on verified local GGUF runtime after repair loop |
| Wake-word false alarms / misses | Silero VAD + openWakeWord threshold calibration (`B11`) | Real-room `FAR > 1/24h` or `FRR > 10%` after threshold calibration |
| Memory / preference recall gaps | Retrieval & `ContextAssembler` tuning (`B13`) | **Never train weights** for personal facts; fix retrieval/index architecture |
