# 31 — AI Training & Personalization Readiness Assessment

> **Document Scope:** Objective evaluation of all **13 Addendum §F AI improvement and personalization mechanisms**, strict architectural distinction between **runtime personalization** (non-parametric) and **model-weight training** (parametric SFT/LoRA/QLoRA), baseline verification of what exists in J.A.R.V.I.S. (`v0.2.1`) today, and an opt-in, privacy-preserving local feedback collection architecture that preserves J.A.R.V.I.S.'s **zero-mandatory-cloud** and **hardware-adaptive** invariants.
>
> **Execution Restriction:** Per Addendum §F, **zero model training, model downloads, or intensive benchmarks were executed** during this read-only audit.

---

## 1. Baseline Reality Check: What Exists in `v0.2.1` Today

| Subsystem | Source Evidence | Actual As-Built State | Status |
| --- | --- | --- | :---: |
| **Model Training / LoRA Stack** | `core/pyproject.toml`, `core/jarvis/infrastructure/providers/llama_cpp_adapter.py` | Zero training libraries (`peft`, `trl`, `bitsandbytes`, `datasets`, `accelerate`, `torch` training loops absent); `llama_cpp_adapter.py` never passes `--lora` / `--lora-scaled` flags. | `NOT IMPLEMENTED` |
| **Feedback Collection & Dataset Pipeline** | `core/migrations/core/0001_initial_core.sql` | Zero `feedback_event`, `correction_log`, `eval_run`, or `pronunciation_lexicon` tables; `message` and `model_benchmark` tables exist in DDL but are **unused (`0` runtime writes)**. | `NOT IMPLEMENTED` |
| **Runtime Personalization (Memory & Preferences)** | `core/jarvis/application/memory_service.py`, `preference_proposal_service.py`, `domain/models.py` (`PersonaConfig`), `turn_orchestrator.py` | `MemoryVaultService`, `PreferenceProposalService`, and `PersonaConfig` persist to SQLite via CRUD APIs, **but have `0` invocations inside `TurnOrchestrator` or `Router`**—the LLM never sees stored user facts, preferences, or persona tone! | `BROKEN` / `PARTIAL` |
| **Pronunciation & Alias Learning** | `core/jarvis/domain/router.py:80-87`, `live_voice_engine.py:75-84` | Only 6 static app aliases (`calculator`/`notepad`/`paint`) and a static `_BILINGUAL_INITIAL_PROMPT`; zero user alias learning or TTS pronunciation dictionary. | `NOT IMPLEMENTED` |

---

## 2. Critical Distinction: Runtime Personalization vs. Model-Weight Training

| Dimension | Runtime Personalization (Non-Parametric) | Model-Weight Training (Parametric: SFT / LoRA / QLoRA) |
| --- | --- | --- |
| **Mechanisms** | Memory Vault prompt injection, user preference rules, file/folder/app alias tables, dynamic STT `hotwords`, TTS pronunciation lexicon, hybrid RAG (`FTS5 + sqlite-vec`), structured grammar/tool schemas, few-shot retrieval | Updating neural weights of Whisper (STT), Qwen3 (LLM), Piper/VITS (TTS), or openWakeWord via gradient descent on curated datasets |
| **Update Latency** | **Instant (`< 50 ms`)** — user says *"panggil Visual Studio Code sebagai koding"* and it works immediately on the very next turn | Slow (`minutes–hours` on GPU; impractical on CPU-only laptops) + requires holdout regression validation before promotion |
| **Forgetting / Deletion (UU PDP / `BR-17`)** | **Exact deterministic erasure** (`DELETE` row + tombstone -> 100% forgotten immediately) | **Hard/impossible to unlearn** individual facts without full retraining from scratch |
| **Hardware Compatibility** | Runs cleanly on **every tier** (CPU-only 8 GB laptops through 24 GB VRAM workstations) | Requires >= 8–16 GB CUDA VRAM even for QLoRA on 4B LLMs; infeasible on CPU-only user machines |
| **Catastrophic Forgetting Risk** | Zero risk of corrupting base model reasoning or multilingual fluency | High risk of degrading general reasoning, JSON formatting, or safety refusal if dataset is small/noisy (`< 500` clean examples) |
| **Best Used For** | User facts, aliases, app/file names, preferred response style/language, pronunciation fixes, local document knowledge | **Only** narrow, recurring systematic failure modes proven on held-out eval sets after runtime fixes saturate (e.g., custom wake-word, lightweight intent classifier, or Indonesian function-calling LoRA) |

---

## 3. Comprehensive Evaluation of All 13 Addendum §F Mechanisms

| # | Mechanism (Addendum §F) | Category | Verdict / Priority | Evidence-Based Engineering Rationale |
| :---: | --- | :---: | :---: | --- |
| 1 | **Better Pretrained Models** | Model Selection (No Training) | **HIGH — Phase 1/2 (Hardware-Adaptive)** | Owner's machine already runs CUDA (`Qwen3-4B-Q4_K_M (cuda)`), yet STT runs CPU `faster-whisper-small` (`language="id"`) and TTS uses monolingual `id_ID-news_tts-medium`. Upgrading CUDA tier to `faster-whisper-large-v3-turbo` (int8_float16, ~1.6 GB VRAM) + `Qwen3-4B/8B` (depending on VRAM tier) + bilingual Piper (`id_ID` + `en_US`) / Kokoro immediately removes major accuracy & naturalness ceilings with zero training cost. Keep `small` + `1.7B/4B` fallback for CPU-only hardware. |
| 2 | **Improved Inference Configuration** | Runtime Config | **CRITICAL — Phase 1 (Immediate)** | Directly fixes confirmed bugs in `live_voice_engine.py`: stop forcing `language="id"`, enable VAD voiced-frame gating + Whisper `no_speech_prob`/`avg_logprob`/`compression_ratio` filters, pass dynamic `hotwords`, disable thinking-token bloat on simple tool turns, tune temperature (`0.0–0.2` for tool calls, `0.6` for chat), wire `speech_rate` to Piper. |
| 3 | **Prompt & Context Optimization** | Runtime Personalization | **CRITICAL — Phase 1 (Immediate)** | Fix `router.py:386-410`: inject live local time/date/timezone, user language preference, concise spoken-style instructions (preventing raw Markdown/non-Latin script dumps to TTS), structured tool definitions with GBNF grammar enforcement, and bounded Memory Vault summary. Eliminates `"sekarangnya berapa?" -> "What is the current time?"` class failures immediately. |
| 4 | **Improved Deterministic Routing** | Runtime Logic | **CRITICAL — Phase 1 (Immediate)** | Fix `normalize_utterance()` trailing-punctuation bug (`router.py:99-101`), add polite-prefix normalization, replace 6-key static dict with live `InstalledAppCatalog` + `EntityWorkingSet` + fuzzy scorer. Deterministic fast-path handles high-frequency commands (time, volume, media, app launch, file open) in `< 50ms` with 0 LLM hallucination risk. |
| 5 | **Intent Classifier Training** | Lightweight Parametric (Optional) | **DEFER — Phase 3 (Only if needed)** | With deterministic fast-path + grammar-constrained `Qwen3-4B/8B` tool calling, a separate trained classifier is **unnecessary initially**. Consider a tiny local ONNX multilingual SetFit/MiniLM router (`< 40 MB`, `< 10ms` CPU) ONLY if Phase 2 benchmarks show CPU-only laptops suffer >2s routing latency on ambiguous commands. |
| 6 | **STT Adaptation (Fine-Tuning Whisper)** | Parametric Training | **NOT RECOMMENDED NOW — Phase 4 Only** | Do NOT fine-tune Whisper before fixing DSP/AEC, VAD 33-frame bug, `language="id"` lock, dynamic `hotwords`, and testing `large-v3-turbo`. Revisit LoRA Whisper adaptation ONLY if held-out Indonesian/accent WER remains `> 12%` after Phase 1–2 fixes and `>= 5 hours` of verified opt-in owner audio exist. |
| 7 | **LLM Supervised Fine-Tuning (Full SFT)** | Parametric Training | **REJECT for Desktop Target** | Full SFT of a 4B–8B model is completely misaligned with local consumer desktop hardware, breaks base model upgrades (`Qwen3` -> `Qwen3.5/4`), and creates catastrophic forgetting. Never pursue full SFT on-device. |
| 8 | **LoRA / QLoRA (LLM Adapters)** | Parametric Training | **DEFER — Phase 4 (Conditional)** | `llama.cpp` supports runtime `--lora` hot-swapping cleanly (`0` base-weight mutation, easy rollback). However, **prerequisite evidence is absent today**. Only train a small offline/maintainer LoRA (e.g., Indonesian+English bilingual tool-calling & concise spoken style, `r=16`, `>= 1,500` curated train pairs) if grammar-constrained base `Qwen3` scores `< 92%` tool-call accuracy on the held-out test set ([32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)). |
| 9 | **TTS Adaptation** | Parametric Training | **DEFER — Phase 4 (Low Priority)** | Current TTS robotic/garbled quality stems primarily from missing text normalization (acronyms, Markdown, English words fed to `espeak id`) and single monolingual voice. Fix normalizer + pronunciation lexicon + bilingual voice switching first; custom Piper voice fine-tuning is purely cosmetic and requires hours of clean studio audio. |
| 10 | **Wake-Word Customization** | Small Parametric Model | **MEDIUM — Phase 2/3 (Targeted)** | `openWakeWord` (`hey_jarvis_v0.1.onnx`) uses tiny `< 1 MB` verifier/classifier heads. Supports both: (a) **personalized speaker/threshold calibration** (runtime, zero full training), and (b) **openWakeWord synthetic-data custom verifier training** for Indonesian-accented `"Hey Jarvis"` / `"Jarvis"` to cut FAR/FRR without touching the LLM/STT stack. |
| 11 | **Pronunciation Dictionaries** | Runtime Personalization | **HIGH — Phase 1/2 (Immediate Win)** | Local SQLite `pronunciation_lexicon` mapping technical/English/Indonesian terms (`"VS Code"` -> `"vi es koud"`, `"Chrome"` -> `"krom"`, `"PDF"` -> `"pe de ef"`, `"CPU"` -> `"si pi yu"`, custom names) applied before Piper phonemization. Instant, deterministic, zero GPU required, editable in UI. |
| 12 | **Personal Memory Improvements** | Runtime Personalization | **HIGH — Phase 1/2 (Immediate Win)** | Wire existing `MemoryVaultService`, `PreferenceProposalService`, and `PersonaConfig` into `TurnOrchestrator` prompt assembly with token budget (`<= 400 tokens`), relevance ranking, recency decay, provenance attribution, and strict privacy scoping (never inject sensitive/tainted items blindly). |
| 13 | **User Feedback & Alias Learning** | Runtime Personalization + Opt-In Data | **HIGH — Phase 2** | Capture lightweight local corrections (*"maksud saya Chrome, bukan Chromium"*, *"kalau saya bilang koding itu VS Code"*, thumbs-down on bad response) -> immediately update `app_alias`, `file_alias`, `pronunciation_lexicon`, or preference proposals (instant win), while optionally storing reviewed anonymized pairs for future benchmark evaluation. |

---

## 4. Detailed Findings & Local Opt-In Feedback Collection Architecture

### Finding AI-01: Disconnected Personalization Stack (Memory Vault, Preferences & Persona Unwired)
- **Source Evidence:** `core/jarvis/application/memory_service.py`, `core/jarvis/application/preference_proposal_service.py`, `core/jarvis/domain/models.py` (`PersonaConfig`), `core/jarvis/application/turn_orchestrator.py:219-410`.
- **Current Behavior:** Users can store memories, approve preference proposals, and configure persona verbosity/language via REST/UI, but `TurnOrchestrator` never queries or injects any of them into LLM system prompts.
- **Expected Behavior:** Every non-trivial LLM turn constructs a bounded, priority-ranked `PersonalContextBlock` (`PersonaConfig` -> active `Preferences` -> top-K relevant `MemoryVault` facts -> active `EntityWorkingSet` -> current local clock/timezone), keeping total personalization overhead `<= 450 tokens`.
- **Probable Root Cause:** Confirmed missing dependency wiring between `MemoryVaultService`/`PreferenceProposalService` and `TurnOrchestrator`.
- **Verification Status:** `BROKEN` (storage implemented; prompt injection `NOT IMPLEMENTED`).
- **Proposed Improvements:** Inject `ContextAssembler` into `TurnOrchestrator` with explicit token budgeting, citation/source tagging, and UI transparency ("Memories used in this reply").
- **Security Implications:** Memory items extracted from untrusted files/web pages MUST NEVER auto-promote into trusted system instructions (memory poisoning vector); only explicit user-confirmed memories (`BR-10`) enter system-level preferences.
- **Acceptance Criteria:** Setting persona to *"concise Bahasa Indonesia"* and saving fact *"proyek utama saya adalah Jarvis"* persists across Core restarts and observably shapes replies in `>= 95%` of test prompts.

### Finding AI-02: Proposed Privacy-Preserving Local Opt-In Feedback & Artifact Architecture
- **Source Evidence:** `0001_initial_core.sql` (zero feedback/lexicon/alias/adapter-version tables; `message` and `model_benchmark` tables unused).
- **Current Behavior:** Zero structured telemetry or owner feedback capture exists to diagnose real-world errors, learn user aliases, or build an opt-in evaluation/training corpus.
- **Expected Behavior:** A strictly **opt-in, 100% local, data-minimized feedback pipeline** with four safeguards:
  1. **Default-OFF Consent & Granular Toggles:** Explicit Settings switches separating: (a) *Instant Alias & Pronunciation Learning* (stores only key-value mappings like `"koding" -> "VS Code"`), (b) *Text Correction Logging* (stores redacted utterance + corrected intent/reply), and (c) *Voice Audio Clip Retention* (default OFF; opt-in bounded ring buffer, e.g., max 7 days or 200 clips, auto-purged).
  2. **Automatic PII Scrubbing Before Storage:** Deterministic scrubber redacts emails, phone numbers, Indonesian NIK/NPWP patterns, API keys/tokens, file contents, and absolute usernames before writing any feedback candidate to `feedback_staging`.
  3. **Owner Dataset Review Queue (Human-in-the-Loop):** Nothing enters an evaluation or training export automatically. A local Review UI lets the owner inspect, edit, approve, or permanently delete individual staged records (with real SQLite hard delete + tombstone, honoring `BR-17`).
  4. **Versioned Local Artifacts & Safe Rollback:** Every pronunciation dictionary, alias set, prompt template, or future LoRA adapter carries semantic version metadata (`artifact_id`, `version`, `base_model_sha256`, `dataset_snapshot_sha256`, `eval_report_json`, `status: STAGING | ACTIVE | ROLLED_BACK`). Promoting a new artifact requires passing the held-out evaluation gate ([32-JARVIS-EVALUATION-DATASET-DESIGN.md](./32-JARVIS-EVALUATION-DATASET-DESIGN.md)); one-click rollback restores the previous version cleanly.
- **Probable Root Cause:** Confirmed omission of feedback lifecycle and MLOps/personalization schema in v0.2.1.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement lightweight SQLite tables (`user_alias`, `pronunciation_lexicon`, `feedback_staging`, `eval_artifact_registry`) in Phase 2 while maintaining strict zero-cloud transmission (`0` telemetry leaves localhost).
- **Security Implications:** Unredacted voice clips or screen/file logs stored indefinitely would create a high-value privacy liability on local disk; opt-in gating, PII scrubbing, SQLCipher/DPAPI encryption-at-rest (remediating `DEF-01` plaintext DB), and bounded retention are mandatory.
- **Acceptance Criteria:** With feedback logging OFF (default), `0` utterances or audio clips are persisted to staging; with opt-in ON, PII scrubber removes 100% of synthetic NIK/token/email test strings, owner review can approve/delete items permanently, and zero outbound network requests occur.

---

## 5. Preserving Zero-Mandatory-Cloud & Hardware-Adaptive Invariants

Any AI upgrade MUST scale deterministically across the existing `hardware_tier` profiles detected by `core/jarvis/platform/windows/hardware.py`:

| Hardware Profile | STT Engine | LLM Engine | Embeddings (Layer 3) | TTS Engine | LoRA Support |
| --- | --- | --- | --- | --- | :---: |
| **Tier 1: CPU-Only / Low RAM (`8–12 GB`)** | `faster-whisper-small` (int8, 4T, bilingual + hotwords) | `Qwen3-1.7B` or `Qwen3-4B` (Q4_K_M CPU) | Optional `multilingual-e5-small` ONNX int8 (paused during voice) | Piper `id_ID` + `en_US` + normalizer | Read-only inference only (never train locally) |
| **Tier 2: Mid GPU (`6–8 GB VRAM`, e.g., RTX 3060/4060)** | `faster-whisper-large-v3-turbo` (`int8_float16` CUDA, ~1.6 GB) or `medium` | `Qwen3-4B-Q4_K_M` CUDA (~2.8 GB) | `multilingual-e5-small` ONNX (~0.2 GB) | Piper bilingual / Kokoro-82M | Runtime `--lora` inference supported |
| **Tier 3: High GPU (`>= 12–16 GB VRAM`)** | `faster-whisper-large-v3-turbo` (`float16` CUDA) | `Qwen3-8B-Q4_K_M` / `Qwen3-14B` CUDA | `bge-m3` quantized ONNX | Kokoro / high-quality local neural TTS | Optional owner-approved offline QLoRA evaluation |
