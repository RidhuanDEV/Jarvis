# 04 — AI Model and Runtime Management Audit

This document audits provider abstractions, runtime adapters, auto-discovery, model lifecycle, resource governance, streaming, cancellation, and failure handling (`core/jarvis/domain/ai_models.py`, `core/jarvis/application/ai_registry_service.py`, `core/jarvis/infrastructure/providers/{llama_cpp_adapter.py,local_runtime_manager.py,ollama_adapter.py}`, `core/jarvis/transport/app.py`).

---

## 1. Provider Abstraction & Adapter Inventory

| Component | Source File & Lines | Status | Forensic Findings |
| --- | --- | :---: | --- |
| `LlmProviderPort` Protocol | `core/jarvis/domain/ai_models.py:133-148` | **`IMPLEMENTED`** | Defines `provider_id`, `ownership_mode`, `trust_zone`, `probe()`, `complete()`. Omits `stream_complete()` (duck-typed ad-hoc via `_StreamingLlmAdapter` in `turn_orchestrator.py:49-50`) and omits cancellation token. |
| `LlamaCppServerAdapter` | `core/jarvis/infrastructure/providers/llama_cpp_adapter.py:63-274` | **`VERIFIED`** | OpenAI-compatible `/health`, `/v1/models`, `/v1/chat/completions` (both blocking and SSE `stream_complete`), `--jinja --reasoning-budget 0 --no-webui`, `-fa on -ctk q8_0 -ctv q8_0`, `top_p=0.8`, `top_k=20`, `<think>` stripping. **Defects:** omits `--api-key` (unauthenticated local port); creates fresh `httpx.AsyncClient` per request (no connection pool); streaming `<think>` check is case-sensitive (`L257`) unlike regex `re.IGNORECASE` (`ai_models.py:22`). |
| `OllamaAdapter` | `core/jarvis/infrastructure/providers/ollama_adapter.py:21-138` | **`MOCK` / DEAD CODE** | Never imported or instantiated anywhere in `core/jarvis/` (tested only with `httpx.MockTransport` in `test_phase3_ai_voice_router.py`). Lacks `stream_complete()` despite claiming `streaming=True, cancelable=True` (`L84-87`). |
| `custom_openai_compatible` | `core/jarvis/domain/ai_models.py:46` | **`NOT IMPLEMENTED`** | Allowed enum value in `ModelProviderRecord`, but zero adapter factory exists to bind it. |
| `LocalLlmRuntimeManager` | `core/jarvis/infrastructure/providers/local_runtime_manager.py:123-297` | **`VERIFIED` (with defects)** | Auto-discovers `llama-server.exe` & `.gguf`, spawns under Win32 Job Object, polls `/health` <=45s, registers provider + binds adapter + activates `balanced` rev 2. **Critical defects:** zero SHA-256 verification, hardcoded model ranking, CPU-only binary bug, zero crash watchdog/auto-restart, zero idle unload. |
| `AiRegistryService` | `core/jarvis/application/ai_registry_service.py:129-615` | **`PARTIAL` / `BROKEN`** | Persists `model_provider`, `model_manifest`, `ai_profile`, `active_ai_profile`. **Critical bugs:** dynamically registered providers are never bound to runtime adapters; profile switch defaults to rev 1 detaching local LLM; Private LAN registration breaks `GET /v1/providers` with HTTP 500. |
| `DynamicResourceGovernor` | `core/jarvis/domain/ai_models.py:204-309` | **`NOT IMPLEMENTED` (DEAD CODE)** | Pure domain logic exists and passes unit tests, but is **never imported or called anywhere in runtime code**. |

---

## 2. Model & Binary Discovery, Ranking & Portability Audit

### 2.1 Binary Discovery Bug (`local_runtime_manager.py:53-87`)
```python
ordered_subdirs: list[tuple[str, BackendPreference]] = []
if has_cuda:
    ordered_subdirs.append(("llama-cuda", BackendPreference.CUDA))
if has_vulkan:
    ordered_subdirs.append(("llama-vulkan", BackendPreference.VULKAN))
ordered_subdirs.extend([
    ("llama-vulkan", BackendPreference.VULKAN),
    ("llama-cuda", BackendPreference.CUDA),
    ("llama-cpu", BackendPreference.CPU),
    ("", BackendPreference.CPU),
])
```
- **Defect:** On a CPU-only machine (`has_cuda=False, has_vulkan=False`), lines 67–68 still unconditionally prepend `llama-vulkan` and `llama-cuda` ahead of `llama-cpu`, launching GPU binaries with `-ngl 99` (`L191`).

### 2.2 Hardcoded Model Ranking (`local_runtime_manager.py:90-120`)
```python
def _rank(p: Path) -> tuple[int, int]:
    low = p.name.lower()
    if vram_mib >= 3800 and "4b" in low and "qwen" in low:
        return (0, p.stat().st_size)
    if "1.7b" in low and "qwen" in low:
        return (1, p.stat().st_size)
    if "3b" in low or "4b" in low:
        return (2, p.stat().st_size)
    return (3, p.stat().st_size)
```
- **Does replacing an AI model require modifying source code?**
  - **Partially no / practically flawed:** Dropping any `.gguf` into `models_dir` will load it without code edits *if no Qwen 4B/1.7B file is present*. However, on a 24 GB GPU containing both `Qwen3-4B-Q4_K_M.gguf` and `Qwen3-14B-Q4_K_M.gguf`, hardcoded `"4b" in low and "qwen" in low` forces rank `0` for `4B` and rank `3` for `14B`! There is zero UI or API mechanism to pick which GGUF `LocalLlmRuntimeManager` launches.
  - **Replacing the runtime (e.g., switching to Ollama or a custom OpenAI endpoint) DOES require code changes today:** `POST /v1/providers` (`app.py:1437-1452`) saves a DB row only and never instantiates/binds an adapter (`OllamaAdapter` is dead code; `AiRegistryService` never hydrates adapters from SQLite on boot).

### 2.3 Hardcoded Inference Knobs Ignoring User Config
`local_runtime_manager.py:170, 183-193` completely ignores `ConfigDocument.ai` (`max_ram_mib`, `max_vram_mib`, `context_tokens`, `backend_preference`, `lifecycle_policy`, `idle_unload_seconds`):
- `context_tokens = 4096` (hardcoded)
- `gpu_layers = 99 if backend != CPU else 0` (hardcoded; no partial layer offload for low-VRAM GPUs!)
- `kv_quant_q8 = True` (hardcoded)
- `cpu_threads = max(2, min(8, physical_cores))` (hardcoded)

---

## 3. Lifecycle Capabilities Matrix

| Capability | Status | Exact Implementation & Failure Behavior |
| --- | :---: | --- |
| **Model download / install** | **`NOT IMPLEMENTED`** | Zero download manager, progress tracking, resume, or UI. `POST /v1/models` only registers metadata for an already-present file. |
| **Offline model import** | **`PARTIAL`** | Files placed manually in `models_dir` or `shared_model_directories` are scanned at boot only (`app.py:701-706`); no runtime rescan endpoint; `LocalLlmRuntimeManager` bypasses `model_manifest` SHA-256 verification. |
| **Model & profile switching** | **`BROKEN`** | `LocalLlmRuntimeManager` saves active bindings into `("balanced", revision=2)` (`local_runtime_manager.py:251-271`), while `POST /v1/profiles/{id}/activate` (`app.py:1497-1513`) calls `switch_profile_atomic(profile_id)` with default `target_revision=1` (empty `role_bindings={}`) and `probe_candidate=None`. Switching away from and back to `balanced` permanently disconnects the live LLM until Core restart. Furthermore, switching profiles never restarts `llama-server` with a different model or parameters. |
| **Dynamic provider selection** | **`BROKEN`** | `POST /v1/providers` never calls `bind_adapter()`; `POST /v1/providers/{id}/probe` fails with `404 No bound runtime adapter` for every user-registered provider. |
| **Private LAN provider registration** | **`BROKEN`** | `ecosystem_service.py:110-136` writes non-schema keys (`tls_fingerprint_sha256`, `allowed_data_scopes`, `allow_cross_zone_fallback`) into `model_provider.capabilities_json`; subsequent `GET /v1/providers` crashes with HTTP `500 ValidationError` (`ai_registry_service.py:283`). `verify_lan_dispatch()` is dead code. |
| **Context window & KV cache** | **`PARTIAL`** | Static `-c 4096 -fa on -ctk q8_0 -ctv q8_0` in `llama-server` args; no dynamic token counting, no context-overflow truncation of `_session_history` beyond fixed 12-message deque, no KV-cache eviction policy. |
| **Streaming** | **`VERIFIED` (Voice) / `NOT IMPLEMENTED` (Text HTTP)** | Voice path uses `LlamaCppServerAdapter.stream_complete()` SSE (`~1.19s` TTFS measured on `Qwen3-4B CUDA`). Text `POST /v1/requests` uses blocking `complete()` only. |
| **Request cancellation** | **`NOT IMPLEMENTED`** | Zero abort controller or `/v1/requests/{id}/cancel` endpoint. |
| **Model loading / unloading** | **`PARTIAL`** | Loads once asynchronously at boot; **zero idle unload** (`idle_unload_seconds=300` ignored) and **zero VRAM-pressure / gaming-mode eviction**. Holds ~2.8 GiB VRAM permanently until Core exits. |
| **Timeout handling** | **`BROKEN` (End-to-End)** | Core adapter allows `60.0s` (`turn_orchestrator.py:289`), `LiveVoiceEngine` allows `65.0s`, **but Rust `reqwest::Client` hardcodes `10s` (`lib.rs:46`)**, aborting slow/cold text turns prematurely. |

---

## 4. Failure Modes Matrix

| Failure Condition | Actual Observed / Traced System Behavior |
| --- | --- |
| **Unsupported or malformed GGUF model** | `llama-server.exe` exits during 45s `/health` poll (`local_runtime_manager.py:208-227`); `LocalLlmRuntimeManager` calls `stop()`, marks `ready=False`, and stays in Direct Mode. Error details from `llama-server` stderr are **lost (`DEVNULL`)**. |
| **Insufficient VRAM (OOM or partial spill)** | Hardcoded `-ngl 99` tries to offload all layers regardless of available VRAM (only selects `4B` vs `1.7B` at `vram_mib >= 3800`). On 4 GB GPU with concurrent VRAM consumers, `llama-server` either crashes at boot (Direct Mode fallback) or silently spills layers to RAM (measured jump from ~400 ms to ~5,925 ms when two instances coexisted). No runtime VRAM monitor or automatic downgrade to `1.7B`/CPU exists. |
| **Post-startup `llama-server` crash** | **BROKEN:** Zero watchdog or health monitor exists after initial boot. `local_llm_manager.status.ready` remains `True` indefinitely; every subsequent LLM turn fails with `httpx.ConnectError` (`ErrorCode.RUNTIME_UNAVAILABLE`) with zero auto-restart and zero `fallback_allowlist` execution. |
| **Unavailable runtime / missing GGUF** | Cleanly enters Direct Mode (`ready=False`, `note="Direct Mode aktif..."`, `local_runtime_manager.py:159-165`); deterministic regex commands still work (subject to grants). |
| **Invalid config / manifest SHA mismatch** | `ConfigService.save_revision()` validates against `config.schema.v1.json` and rejects invalid configs; `AiRegistryService.register_manifest()` rejects SHA-256 mismatch unless bypassed with `?verify_local_file=false` (`app.py:1472`), **but `LocalLlmRuntimeManager` never checks manifests at all**. |
