# 15 — AI Performance and Benchmark Report

This report strictly separates **measured empirical data** (from `planning/R0-FEASIBILITY-REPORT.md` and recorded live verification probes in this workspace), **original SDLC targets**, and **unmeasured / estimated metrics**. Zero benchmarks were fabricated or executed during this read-only audit.

---

## 1. Measured Performance vs SDLC Targets

**Sanitized Reference Hardware Class:** Windows 11 Home x64 / 6-core 12-thread x64 mobile CPU (2.70 GHz class) / 39.74 GB system RAM / 4 GB VRAM CUDA discrete GPU (`4,096 MiB` total, `134 MiB` idle baseline) + integrated GPU driving `1920×1080 @ 200 Hz` panel / local SSD.

| Metric | SDLC Target (`NFR-01/02/07/13`) | Recorded Measurement | Source & Sample Size | Classification |
| --- | --- | --- | --- | :---: |
| **Wake-word per-frame inference (`openWakeWord`)** | `<= 0.2` false wake/hr, `<= 10%` FRR | `1.64 ms / 80 ms frame` (RTF `0.020`); silence score `0.0` | `R0-FEASIBILITY-REPORT.md` & live probe (`task-1306`); **0h human negative-audio soak** | **`PARTIAL`** *(inference fast; FAR/FRR **NOT MEASURED**)* |
| **Silero VAD frame probability** | Accurate speech gating | Silence `0.0415` vs speech `0.9997` (`32 ms` frame) | Live probe (`task-1230`, 1 utterance); broken by `min_speech_blocks` inflation bug | **`PARTIAL`** |
| **STT Latency & WER (`faster-whisper-small`, CPU int8, 4T)** | Clean ID WER `<= 20%` (`NFR-07`) | Clean WER `14.18%`, Noisy 15 dB WER `17.38%`, p50 `1,945.2 ms`, p95 `2,116.8 ms`, RTF `0.468`, RAM `+342.8 MiB`, model load `1,056–1,179 ms` | `R0-FEASIBILITY-REPORT.md` (**synthetic Piper audio corpus, exact `N` undisclosed in report, 0 real human speech, 0 CIs**) | **`PARTIAL`** *(synthetic only; human WER **NOT MEASURED**)* |
| **Deterministic Intent Routing** | `>= 95%` accuracy, `p95 <= 4s` (`NFR-01`) | `30/30` in `1.38 µs/turn` (R0); live HTTP `1.1–3.6 ms` (clock/tasks/screen) | `R0-FEASIBILITY-REPORT.md` & `task-1306` (`N=30` vs 100 planned) | **`VERIFIED`** *(limited `N`)* |
| **Local LLM Boot Time (`Qwen3-4B-Q4_K_M` CUDA)** | Warm start fast | Cold `4.17s`; Warm `2.47–2.78s` (`llama-server /health == 200`) | Live probes (`task-1089`, `task-1097`, `task-1306`) | **`VERIFIED`** |
| **LLM TTFT & Token Speed (`Qwen3-4B` CUDA, `--reasoning-budget 0`, Q8 KV)** | Warm simple plan `p95 <= 12s` (`NFR-01`) | TTFT p50 `53.1 ms`, `52.7 tok/s`, plan p50 `987 ms` / p95 `1,856 ms`, VRAM `2,914.5 MiB` (`+2,780.5`), RSS `2,853.2 MiB` | `R0-FEASIBILITY-REPORT.md` (`10`-case multiple, exact `N` undisclosed) | **`VERIFIED`** *(small `N`; full 100-trial Tier-B **NOT MEASURED**)* |
| **LLM `Qwen3-1.7B` CUDA vs CPU-Only** | Respect VRAM/RAM cap (`NFR-02`) | CUDA: `103.5 tok/s`, p95 `857 ms`, VRAM `1,508.5 MiB`. CPU-Only: `15.7 tok/s`, p95 `5,852 ms`, RSS `1,555.1 MiB` | `R0-FEASIBILITY-REPORT.md` | **`VERIFIED`** *(R0 sandbox only)* |
| **LLM SSE Time-to-First-Sentence (TTFS)** | Low-latency voice streaming | 3-sentence ID reply: Sentence 1 at **`1,190 ms`**, Sentence 2 at `1,600.5 ms`, Sentence 3 at `1,805.2 ms` (total `1,825.9 ms`) | Live probe (`task-1306`, `N=1`) | **`PARTIAL`** *(single-sample proof)* |
| **Piper TTS Synthesis (`id_ID-news_tts-medium`, CPU, RAM)** | Low-latency local voice | R0: p50 `167.0 ms`, p95 `199.9 ms`, RTF `0.041`. Cold in-app first synth (load+5.1s audio): `2,200.4 ms` (`RTF 0.43`) | `R0-FEASIBILITY-REPORT.md` & `task-1149` | **`VERIFIED`** |
| **End-to-End Voice Conversational Latency** | `p95 <= 4s` direct / `<= 12s` LLM | **NOT MEASURED** end-to-end with real mic→OWW→Silero (`0.72s` silence)→Whisper (`~1.95s`)→LLM TTFS (`~1.19s`)→Piper (`~0.20s`) = **analytical estimate ~4.1s–5.0s TTFA** | Analytical sum only — **NOT MEASURED** | **`UNVERIFIED`** |
| **Idle Resource Consumption & 8h Soak** | `<= 1 GB` RAM, `<= 3%` CPU (10m); 8h soak `<= 20%` growth (`NFR-02/12`) | **NOT MEASURED** on installed Tauri+Core+LLM tree (note: `Qwen3-4B` never idle-unloads -> permanently holds ~2.8 GiB VRAM + ~2.8 GiB RSS!) | Tier-B deferred | **`UNVERIFIED`** *(likely FAILS `NFR-02` idle RAM without idle-unload!)* |
| **UI Frame Pacing (`Balanced @ 60 FPS`)** | `p95 <= 20 ms` (`NFR-13`) | R0 standalone Edge (no LLM): `200 Hz Native = 5.1 ms p95`, `Auto = 20.1 ms` (tuned to `15.0 ms` in `DEC-030`). **Inside live Tauri + concurrent LLM: NOT MEASURED.** | `R0-FEASIBILITY-REPORT.md` (standalone Chromium only) | **`UNVERIFIED`** |
| **Concurrent VRAM Contention** | Graceful budget fallback (`NFR-02`) | Two simultaneous `Qwen3-4B` instances on 4 GB GPU jumped turn latency from ~`380 ms` to **`5,925.8 ms`** (layer spill to system RAM) | Observed accidentally in `task-1230` | **`VERIFIED` (Degradation)** |

---

## 2. Source-Code Performance Bottlenecks Identified

1. **[CRITICAL] Async Event-Loop Blocking Across ~90 FastAPI Routes (`core/jarvis/transport/app.py`):** Zero `asyncio.to_thread()` usage. Heavy sync operations run directly on Uvicorn's single event loop:
   - `GET /v1/health` & `/v1/ready` (`app.py:959-969`, `dual_db.py:119-125`): executes full **`PRAGMA integrity_check`** on BOTH SQLite DBs on every health poll!
   - `POST /v1/backups/{create,verify}` (`L2332-2366`): blocks on 64 MiB Argon2id + ZIP + `online_backup_sqlite`.
   - `POST /v1/models` (`L1469`): blocks SHA-256 hashing multi-GB `.gguf` files.
   - `POST /v1/roots/{id}/sync` (`L1750`): blocks parsing entire directory trees of PDFs/DOCX.
   - `POST /v1/storage/migrate` (`L1099`): blocks copying & double-hashing directories.
2. **[CRITICAL] Voice Capture Thread Blocked Synchronously During 65s LLM + 60s TTS (`live_voice_engine.py:821, 930, 944`):** `_process_utterance_audio()` runs inline in `_capture_loop`, halting `_audio_queue` drainage (overflows after 8s).
3. **[CRITICAL] Frontend Root Re-Render Storm (`App.tsx:75-137, 161-176`, `OrbitalCore.tsx:101-114`):**
   - `OrbitalCore` calls React `setAngleDeg` inside `requestAnimationFrame` (up to 120–200 React re-renders/s) and updates Zustand `frameTelemetry` every 20 frames.
   - Root `App` subscribes to the **entire** Zustand store without selectors (~6 full-app re-renders/s at 120 FPS) PLUS polls `get_live_voice_status` every `350 ms` (~2.9 full-app re-renders/s even when hidden or on other tabs) = **~9 full-app re-renders/s continuously**.
4. **[HIGH] Permanent Idle VRAM/RAM Footprint (`local_runtime_manager.py`):** `Qwen3-4B` never idle-unloads (`idle_unload_seconds=300` ignored), holding ~2.8 GiB VRAM + ~2.8 GiB RAM forever while idle.
5. **[HIGH] Single-Connection Serialized SQLite + Uncached Reads (`dual_db.py:50-60`, `config_service.py:113`, `turn_orchestrator.py:163`, `memory_service.py:124`, `voice_service.py:78`):**
   - Single `sqlite3.Connection` + `RLock` serializes all readers behind writes.
   - `ConfigService.get_active()` re-queries SQLite + re-parses JSON + re-validates full `ConfigDocument` on every call (zero caching).
   - `TurnOrchestratorService._load_grants()` reads ALL rows including revoked grants on every turn.
   - `MemoryVaultService.list_memories()` does full table scan + AES-GCM decrypts every sensitive row in Python.
   - `KnowledgeRagService.sync_source_root()` (`L232-235`) parses entire PDFs/DOCX *before* checking if SHA-256 changed (no `(mtime_ns, byte_size)` pre-check).
   - `LlamaCppServerAdapter` creates a fresh `httpx.AsyncClient` on every LLM request (no persistent TCP keep-alive pool).
6. **[MEDIUM] Unbounded In-Memory Caches:** `TurnOrchestratorService._session_history` (`turn_orchestrator.py:113`), `SafeWebFetchClient._cache` (`web_fetch.py:117`), and `RemoteGatewayService._limiter` (`remote_gateway_service.py:97`) have unbounded key growth over long uptime (`NFR-12` soak leak risk).

---

## 3. Authorized Performance Validation Plan (For Unmeasured Metrics)

*(Requires explicit `L3` owner approval before execution; DO NOT auto-run.)*

1. **Tier-B Latency & Conformance Benchmark (`NFR-01`, `NFR-07`):** 100 direct + 100 warm LLM + 50 adversarial JSON prompts against live `Qwen3-4B` (CUDA) and `Qwen3-1.7B` (Vulkan & CPU-only); capture p50/p95/p99 TTFT, TTFS, total latency, and Wilson 95% CIs.
2. **Real Human Voice Corpus Benchmark (`NFR-07`):** Record/replay real Indonesian & ID+EN code-switched human speech (not synthetic Piper audio!) across clean & noisy strata; measure WER, CER, end-to-end mic→first-audible-speaker TTFA, plus 20-hour negative-audio room soak for `openWakeWord` FAR/FRR.
3. **8-Hour Continuous Soak & Idle Profile (`NFR-02`, `NFR-12`):** Run installed Tauri + Core + LLM tree with periodic voice/text turns; sample RSS, VRAM (NVML), handle counts, SQLite WAL size, and queue depths every 60s.
4. **Live WebView2 Concurrent GPU Frame Pacing (`NFR-13`):** Measure frame times inside actual Tauri WebView2 while `Qwen3-4B` runs active inference on the discrete GPU across `Cinematic`, `Balanced`, `Lite`, and `Reduced Motion`.
