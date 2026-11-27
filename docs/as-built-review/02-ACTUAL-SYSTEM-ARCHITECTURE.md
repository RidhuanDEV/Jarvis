# 02 — Actual System Architecture (As-Built)

This document describes the **actual implemented architecture** verified from source code as of commit `455c6aa` + working-tree voice/single-instance additions, and explicitly records every material deviation from `JARVIS-SDLC-v0.2.1/03-SDD.md` and `planning/ARCHITECTURE-REVIEW.md`.

---

## 1. Architectural Overview & Module Boundaries

J.A.R.V.I.S. is implemented as a **3-process local desktop modular monolith** on Windows x64:

1. **Desktop Shell & Native Broker (`apps/desktop/`):**
   - **Frontend (`apps/desktop/src/`):** React `19.3.1` + TypeScript `~7.0.2` + Tailwind CSS `4.3.5` + Zustand `5.1.0` + Zod `4.6.7` + `motion` `14.14.0`, bundled via Vite `8.4.0` into static assets served inside Tauri 2 WebView2 (`withGlobalTauri: false`, CSP `connect-src 'self'`).
   - **Rust Broker (`apps/desktop/src-tauri/src/`):** Tauri `2.12.7` binary (`jarvis-desktop.exe`) responsible for Win32 single-instance mutex (`single_instance.rs`), ephemeral loopback port picking & Python Core discovery (`core_launcher.rs`), Win32 Job Object supervision (`process_supervisor.rs`), 256-bit Bearer token generation (`ipc_transport.rs`), system tray (`lib.rs`), and 41 Tauri IPC proxy commands (`commands.rs`) forwarding HTTP requests over `reqwest` (`10s` global timeout).
2. **Local Core Service (`core/jarvis/`):**
   - Clean 5-layer Python `3.11.9` monolith enforced by `import-linter` (`core/pyproject.toml:99-138`, **2/2 contracts kept** across 125 files / 562 deps):
     - `domain/` — Pure Pydantic `StrictModel` entities, `PolicyEngine`, `DeterministicRouter`, security regexes, licensing, hardware recommendations, ports (`0` OS/infrastructure/transport imports).
     - `application/` — 20 use-case services (`TurnOrchestratorService`, `AiRegistryService`, `MemoryVaultService`, `KnowledgeRagService`, `ReminderSchedulerService`, `PersonalLifeService`, `WorkflowEngineService`, `ScreenAwarenessService`, `WebIntelligenceService`, `ApprovalService`, `StorageService`, `BackupService`, `ConfigService`, `LicenseInventoryService`, `VoicePipelineService`, `EcosystemGovernanceService`, `OnDemandCameraService`, `HomeAssistantService`, `RemoteGatewayService`, `PreferenceProposalService`) (`0` OS/Win32/FastAPI imports).
     - `infrastructure/` — `DualSqliteManager`, `migrations`, `crypto`, `document_parser`, `event_bus`, `logging_setup`, `web_fetch`, `live_voice_engine`, `providers/{llama_cpp_adapter,local_runtime_manager,ollama_adapter}`.
     - `platform/` — `portable_mock.py` + `windows/{hardware,audio,desktop_automation,filesystem,screen_capture,supervisor,vault}.py`.
     - `transport/` — FastAPI `0.165.0` + Uvicorn `0.54.0` (`app.py`: 96 routes; `remote_gateway_app.py`: 5 routes, **unwired dead server**; `settings.py`; `__main__.py`).
3. **Managed Local LLM Worker (`llama-server.exe`):**
   - Auto-discovered and spawned asynchronously by `LocalLlmRuntimeManager` (`core/jarvis/infrastructure/providers/local_runtime_manager.py:148-289`) under Python's `WindowsJobProcessSupervisor` on a random `127.0.0.1:<port>` (unauthenticated HTTP, `--no-webui --jinja --reasoning-budget 0`).

---

## 2. Actual Architecture Diagrams (All 9 Required Views)

*(Standalone `.mmd` sources are also persisted under `docs/as-built-review/diagrams/`.)*

### 2.1 System Context (`diagrams/01-system-context.mmd`)

```mermaid
flowchart LR
    Owner["Local Owner (Desktop User)"]
    MicSpk["OS Default Mic & Speakers (PortAudio)"]
    LocalFS["Local Filesystem & Opt-In Folders"]
    WinOS["Windows 11 OS (Win32 / Credential Mgr / NVML)"]
    ExtWeb["Public Web (Opt-In Fetch Only)"]
    Unwired["Unwired / No Live Adapter: Camera, Home Assistant, Web Search, Remote Mobile"]

    subgraph Host["Single Local Windows Workstation (127.0.0.1 Only)"]
        Jarvis["J.A.R.V.I.S. Desktop + Core + Local LLM (v0.2.1)"]
    end

    Owner <-->|"Text UI, Voice, Native R2 Dialog, System Tray"| Jarvis
    MicSpk <-->|"16kHz PCM In / 22.05kHz PCM Out (RAM only)"| Jarvis
    LocalFS <-->|"Dual SQLite DBs, Encrypted Backups, Opt-In Docs"| Jarvis
    WinOS <-->|"Job Object, Keyring, NVML, Foreground Title"| Jarvis
    Jarvis -.->|"Opt-In /v1/web/fetch (when offline_mode=false)"| ExtWeb
    Jarvis -.->|"Policy/DB stubs only — adapters are None"| Unwired
```

### 2.2 Container Architecture (`diagrams/02-container-architecture.mmd`)

```mermaid
flowchart TB
    subgraph DesktopProc["Process 1: jarvis-desktop.exe (Tauri 2 + Rust)"]
        WebView["WebView2 React 19 UI (12 Tabs, Zustand, SVG OrbitalCore)"]
        RustBroker["Rust Broker (41 Tauri Commands, reqwest 10s, Job Object, Mutex, Tray)"]
        WebView <-->|"Tauri invoke() (19/41 cmds used)"| RustBroker
    end

    subgraph CoreProc["Process 2: python.exe -m jarvis.transport (FastAPI / Uvicorn)"]
        API["FastAPI App (96 Routes, Bearer Auth, Host/Origin Middleware)"]
        Services["20 Application Services + PolicyEngine + DeterministicRouter"]
        VoiceEng["LiveVoiceEngine Threads (sounddevice + OWW + Silero + Whisper + Piper)"]
        CoreSup["WindowsJobProcessSupervisor (Job Object #2)"]
        API --> Services
        VoiceEng <-->|"asyncio.run_coroutine_threadsafe"| Services
        Services --> CoreSup
    end

    subgraph LlmProc["Process 3: llama-server.exe (Managed Local Worker)"]
        Qwen["Qwen3-4B / 1.7B GGUF (CUDA/Vulkan/CPU, OpenAI HTTP + SSE)"]
    end

    subgraph Storage["Local Persistence (%LOCALAPPDATA%)"]
        CoreDB[("jarvis_core.db (Plain SQLite WAL + AES-GCM sensitive memory)")]
        KnowDB[("jarvis_knowledge.db (Plain SQLite WAL + FTS5 BM25)")]
        Vault[("Windows Credential Manager (keyring DEK)")]
        Models[("Local Runtime & Model Dirs (GGUF, Whisper, Piper, ONNX)")]
    end

    RustBroker <-->|"HTTP 127.0.0.1:port + Bearer (stdin-piped); NO Named Pipe, NO SSE bridge"| API
    CoreSup -->|"Spawns & terminates"| LlmProc
    Services <-->|"HTTP 127.0.0.1:port (no --api-key)"| Qwen
    Services <--> CoreDB
    Services <--> KnowDB
    Services <--> Vault
    VoiceEng -.->|"Reads models (no SHA-256)"| Models
    CoreSup -.->|"Executes binary (no SHA-256)"| Models
```

### 2.3 Component Architecture (`diagrams/03-component-architecture.mmd`)

```mermaid
flowchart TB
    subgraph Transport["transport/"]
        App["app.py (96 routes)"]
        RemoteDead["remote_gateway_app.py (UNWIRED DEAD SERVER)"]
        Settings["settings.py (CoreStartupSettings)"]
    end

    subgraph AppLayer["application/ (20 Services)"]
        Turn["TurnOrchestratorService (RAM 12-msg history, NO memory recall)"]
        PolicyWrap["ApprovalService + PolicyEngine (domain)"]
        AIReg["AiRegistryService"]
        VoiceSvc["VoicePipelineService (DISCONNECTED from LiveVoiceEngine)"]
        Mem["MemoryVaultService"]
        Know["KnowledgeRagService (BM25 only, embedding=None)"]
        Life["PersonalLifeService + ReminderSchedulerService (NO cron loop)"]
        ScreenWeb["ScreenAwarenessService + WebIntelligenceService (search=None)"]
        WorkEco["WorkflowEngineService (NO-OP stub) + EcosystemGovernanceService (metadata stub)"]
        InfraSvc["ConfigService + StorageService + BackupService + LicenseInventoryService"]
        R3Svc["Camera (port=None) + HA (client=None) + Remote + PreferenceProposal"]
    end

    subgraph InfraLayer["infrastructure/"]
        DualDB["DualSqliteManager + migrations"]
        LiveVoice["LiveVoiceEngine (sounddevice/OWW/Silero/Whisper/Piper)"]
        LlmMgr["LocalLlmRuntimeManager + LlamaCppServerAdapter"]
        OllamaDead["OllamaAdapter (DEAD CODE)"]
        Bus["SequencedEventBus (SSE unwired to UI)"]
        WebFetch["SafeWebFetchClient (SSRF DNS TOCTOU)"]
    end

    subgraph PlatformLayer["platform/windows/"]
        WinAdapters["Hardware, Audio (WinMM), Desktop (allow_live_launch=False), FS, Screen (title only), Vault, Supervisor"]
        FakeNotif["FakeNotificationAdapter (in production!)"]
    end

    App --> Turn & PolicyWrap & AIReg & VoiceSvc & Mem & Know & Life & ScreenWeb & WorkEco & InfraSvc & R3Svc
    App --> LiveVoice & LlmMgr & Bus
    Turn --> PolicyWrap & AIReg & Mem & Know & Life & ScreenWeb
    Turn --> WinAdapters
    LlmMgr --> AIReg
    AppLayer --> DualDB & WebFetch & WinAdapters & FakeNotif
```

### 2.4 Process & Thread Architecture (`diagrams/04-process-architecture.mmd`)

```mermaid
flowchart TB
    subgraph P1["Process 1: jarvis-desktop.exe"]
        T1Main["Main GUI Thread (Tauri Event Loop + Tray + Win32 Mutex)"]
        T1Web["WebView2 Renderer Process(es) (React + 350ms setInterval + SVG rAF)"]
        T1Tokio["Tokio Async Pool (reqwest HTTP 10s client)"]
        Job1["Win32 Job Object #1 (KILL_ON_JOB_CLOSE)"]
    end

    subgraph P2["Process 2: python.exe -m jarvis.transport"]
        T2Loop["Main Thread: Uvicorn Asyncio Event Loop (BLOCKS on sync SQLite/Argon2/SHA256!)"]
        T2Boot["One-Shot Task: local_llm_manager.start_if_available()"]
        T2PA["PortAudio C Callback Thread (_audio_cb -> queue max 250)"]
        T2Cap["Daemon Thread: _capture_loop (BLOCKS synchronously on Whisper + LLM fut.result 65s + TTS join 60s!)"]
        T2Tts["Ephemeral Thread(s): _consume_streaming_tts_queue / _speak_blocking (sd.play blocking)"]
        Job2["Win32 Job Object #2 (KILL_ON_JOB_CLOSE)"]
    end

    subgraph P3["Process 3: llama-server.exe"]
        T3Gpu["CUDA/Vulkan Inference Threads (Qwen3-4B / 1.7B, -c 4096, -ngl 99)"]
    end

    Job1 -->|"owns"| P2
    Job2 -->|"owns"| P3
    T1Web -->|"invoke()"| T1Tokio
    T1Tokio <-->|"HTTP loopback"| T2Loop
    T2PA -->|"32ms chunks"| T2Cap
    T2Cap -->|"run_coroutine_threadsafe"| T2Loop
    T2Cap -->|"sentence_q"| T2Tts
    T2Loop <-->|"SSE HTTP"| T3Gpu
```

### 2.5 Data Flow (`diagrams/05-data-flow.mmd`)

```mermaid
flowchart LR
    Mic["Default Mic (16kHz f32)"] -->|"RAM queue"| OWW["openWakeWord 80ms / Silero VAD"]
    OWW -->|"RAM PCM"| STT["faster-whisper-small (CPU int8, lang=id)"]
    TextIn["Desktop Text Box"] -->|"POST /v1/requests"| Router["DeterministicRouter (10 regexes)"]
    STT -->|"transcript"| Router
    Router -->|"deterministic ToolProposal"| Policy["PolicyEngine + Grant Check"]
    Router -->|"llm_candidate"| Orchestrator["TurnOrchestrator (RAM 12-msg history + OS clock; NO MemoryVault)"]
    Orchestrator <-->|"SSE /v1/chat/completions"| Qwen["llama-server (Qwen3)"]
    Qwen -->|"JSON ToolProposal"| Policy
    Qwen -->|"prose sentences"| TtsQ["Sentence Queue -> PiperVoice (RAM BytesIO) -> sd.play"]
    Policy -->|"R0/R1 ALLOWED"| Exec["Tool Adapters (app.launch mocked; RAG BM25-only; Screen title-only)"]
    Policy -->|"R2 APPROVAL_REQUIRED"| AppDB[("approval table (60s TTL, nonce)")]
    Policy -->|"R3 / DENIED"| Err["ErrorEnvelope / Spoken Refusal"]
    Exec -->|"summary"| CoreDB[("jarvis_core.db / jarvis_knowledge.db")]
    Exec -->|"reply"| TtsQ
```

### 2.6 Application Startup & Shutdown (`diagrams/06-startup-shutdown.mmd`)

```mermaid
sequenceDiagram
    participant User
    participant Rust as jarvis-desktop.exe (Rust)
    participant Core as python.exe (FastAPI Core)
    participant LLM as llama-server.exe
    participant UI as WebView2 (React)

    User->>Rust: Launch jarvis-desktop.exe
    Rust->>Rust: CreateMutexW single-instance check (focus & exit if duplicate)
    Rust->>Rust: Pick ephemeral 127.0.0.1 port + OsRng 256-bit token
    Rust->>Rust: discover_core_runtime() (env / repo / runtime-pointer.json)
    Rust->>Core: Spawn under Win32 Job Object #1 (stdout/stderr = NULL!)
    Rust->>Core: Pipe token via stdin + close EOF
    Core->>Core: DualSqliteManager.initialize() + migrations + seed profiles/licenses
    Core->>Core: Hardware discover() (sync) + bind Uvicorn 127.0.0.1:port
    Core->>LLM: Async lifespan task: spawn llama-server under Job Object #2 (poll /health <=45s)
    Rust->>UI: Show main window (1280x800) + Tray (3 items)
    UI->>Rust: waitForLiveCoreStatus (max 5s cliff -> else preview_fixture!)
    UI->>Rust: loadFoundationData() (caps, storage, licenses ONLY — 0 user data hydrated)
    UI->>Rust: setInterval(350ms) -> get_live_voice_status

    Note over User,LLM: Shutdown (Window X close exits app — does NOT hide to tray!)
    User->>Rust: Close Window X or Tray Quit
    Rust->>Core: supervisor.close_all_managed() (TerminateJobObject #1)
    Core--xLLM: Killed via Job Object #2 (or Core lifespan finally: stop + db.close)
```

### 2.7 AI Inference Flow (`diagrams/07-ai-inference-flow.mmd`)

```mermaid
flowchart TD
    In["Normalized Utterance"] --> Det{"DeterministicRouter matches regex?"}
    Det -->|"Yes (0 LLM calls)"| ToolPath["ToolProposal -> PolicyEngine"]
    Det -->|"No (llm_candidate)"| Prof{"Active Profile != DIRECT & adapter bound?"}
    Prof -->|"No"| Direct["Static Direct Mode Notice (llm_called=false)"]
    Prof -->|"Yes"| Ctx["Build Prompt: ID-first system + OS clock + RAM history (<=12 msgs; NO MemoryVault)"]
    Ctx --> StreamCheck{"on_sentence != None & adapter has stream_complete?"}
    StreamCheck -->|"Yes (Voice)"| SSE["LlamaCppServerAdapter.stream_complete (POST stream=true, strip think)"]
    StreamCheck -->|"No (Text HTTP)"| Comp["adapter.complete (POST stream=false, 60s timeout; Rust cuts at 10s!)"]
    SSE --> Lead{"First non-space char is '{' or '`'?"}
    Lead -->|"No (Prose)"| Flush["Flush each sentence (. ! ? newline) -> Piper TTS Queue immediately"]
    Lead -->|"Yes (JSON)"| Hold["Buffer full JSON without speaking"]
    Flush --> Parse["parse_llm_assistant_or_tool(raw_content)"]
    Hold --> Parse
    Comp --> Parse
    Parse -->|"Conversational reply"| SaveHist["Record in RAM deque(maxlen=12) + return COMPLETED"]
    Parse -->|"Valid ToolProposal (1..5 steps)"| ToolPath
    Parse -->|"Invalid schema"| Reject["Return FAILED (INVALID_ARGS)"]
```

### 2.8 Tool Execution Flow (`diagrams/08-tool-execution-flow.mmd`)

```mermaid
flowchart TD
    Prop["ToolProposal (1..5 steps)"] --> Bounds["PolicyEngine.validate_proposal_bounds (<=5 steps)"]
    Bounds -->|"Fail"| Deny1["FAILED (INVALID_ARGS)"]
    Bounds -->|"Pass"| Grants["Load ALL rows from SQLite grant table"]
    Grants --> Loop["For each ToolStepProposal (sequential, 1-shot, NO ReAct feedback)"]
    Loop --> Eval["PolicyEngine.evaluate_step (R3 > Lock/Mute > Channel > Grant > R2)"]
    Eval -->|"R3 / Missing Grant / Denied"| Deny2["FAILED (DENIED 403)"]
    Eval -->|"R2 Approval Required"| Chall["ApprovalService.create_challenge (60s TTL, nonce, bound_hash; target_snapshot_hash=None)"]
    Chall --> Wait["Return 202 AWAITING_APPROVAL (NOTE: voice drops approval; post-approve file move orphaned!)"]
    Eval -->|"R0/R1 Allowed"| Exec["_execute_verified_step()"]
    Exec -->|"system.time / tasks / memory / reminder"| LiveDB["Execute & commit SQLite"]
    Exec -->|"os.app.launch"| MockApp["allow_live_launch=False -> returns True WITHOUT launching!"]
    Exec -->|"os.volume.set"| WinMM["winmm.waveOutSetVolume (process channel, NOT master volume)"]
    Exec -->|"knowledge.query"| Rag["BM25-only search (embedding_provider=None)"]
    Exec -->|"screen.analyze"| Scr["Foreground title + process name ONLY (no UIA/OCR)"]
    Exec -->|"web.search.query / storage.migrate"| Unsup["Return UNSUPPORTED"]
```

### 2.9 Security & Authorization Flow (`diagrams/09-security-authorization-flow.mmd`)

```mermaid
flowchart TD
    Req["Incoming HTTP Request to FastAPI"] --> Mid["security_and_wide_event_middleware (app.py:842)"]
    Mid --> Host["Host Check (BUG: empty Host bypasses; IPv6 [::1] broken; 'testserver' in prod)"]
    Host --> Orig["Origin Check (rejects any Origin header -> 403)"]
    Orig --> Size["Content-Length <= 256 KiB (BUG: chunked transfer bypasses)"]
    Size --> Auth{"Path == /healthz?"}
    Auth -->|"Yes"| OK0["200 liveness"]
    Auth -->|"No"| Bearer["Authorization: Bearer <token> (hmac.compare_digest)"]
    Bearer -->|"Invalid"| E401["401 DENIED"]
    Bearer -->|"Valid"| Split{"Route Path?"}
    Split -->|"POST /v1/requests"| Pol["PolicyEngine (trusted Python code) + ApprovalService"]
    Split -->|"POST /v1/storage/migrate, /cleanup, /screen/analyze, /web/*, /knowledge/query, /workflows/*/execute"| Bypass["DIRECT EXECUTION — BYPASSES PolicyEngine / ApprovalService!"]
    Pol -->|"R2"| Dialog["Native <dialog> (TRUSTED_UI + LOCAL + single-use nonce + 60s TTL)"]
    Pol -->|"R3"| HardBan["Deterministic 403 DENIED"]
    Pol -->|"R0/R1 + Grant"| SafeExec["Execute (NOTE: grant.scope ignored; brokerClient auto-grants 4 caps incl. screen.read)"]
```

---

## 3. Explicit Deviations from Approved SDD (`JARVIS-SDLC-v0.2.1/03-SDD.md` & `DEC-001`–`DEC-030`)

| SDD / DEC Mandate | Actual Implemented Architecture | Source Evidence | Deviation Impact |
| --- | --- | --- | --- |
| **`DEC-008` / SDD §5:** Windows Named Pipe (current-SID DACL) primary IPC | Loopback `http://127.0.0.1:<port>` + Bearer token only; `WindowsNamedPipe` enum is dead code | `ipc_transport.rs:9,62`, `app.py:756`, `__main__.py:28` | Higher local-host attack surface; Host/Origin parsing bugs exposed |
| **`DEC-023` / SDD §3:** 9 complete platform ports | `NotificationPort` uses `FakeNotificationAdapter()` in prod; `StartupIntegrationPort` has 0 impl; `Camera`/`HA`/`WebSearch` ports are `None` | `app.py:621,660,691-692`, `ports.py:148` | Core promises (reminders, notifications, startup, IoT, search) non-functional |
| **`DEC-009/013` / SDD §4:** Single unified voice pipeline with hotplug & echo guard | Two completely disconnected stacks: `VoicePipelineService` (unused in prod) vs `LiveVoiceEngine` (ignores config/devices/EventBus) | `app.py:647,750`, `live_voice_engine.py:673` | Device selection, audio mode, speech rate, and headphone barge-in broken |
| **`DEC-007` / SDD §6:** Encrypted sensitive data + portable cross-machine restore | Plaintext SQLite + AES-GCM on `sensitive` memory only; backup omits `master_dek` | `dual_db.py:67`, `backup_service.py:85-98` | Cross-machine restore permanently bricks all sensitive memories |
| **`DEC-018` / SDD §9:** Minimal standalone base installer | NSIS installs only `jarvis-desktop.exe` + static UI; requires local repo `.venv` | `tauri.conf.json:32-45`, `core_launcher.rs:130-192` | Unusable by external users on clean Windows machines |
| **`DEC-020/021` / SDD §4:** Manifest SHA-256 verification + `DynamicResourceGovernor` + idle unload | `LocalLlmRuntimeManager` executes unhashed binaries/GGUFs; `DynamicResourceGovernor` & `OllamaAdapter` are dead code; zero idle unload | `local_runtime_manager.py:154-196`, `domain/ai_models.py:204` | Integrity bypass + permanent VRAM occupation until exit |
| **SDD §7 / `FR-UX-01`:** Monotonic SSE `/v1/events` driving UI state + Canvas 2D renderer | Zero SSE bridge in Rust/React (`Event Cursor` permanently `seq #0`); UI polls `/v1/voice/live-status` every 350 ms; `OrbitalCore` is inline DOM `<svg>` | `App.tsx:161-176`, `OrbitalCore.tsx:135-235` | High re-render CPU churn; voice R2 approvals never appear in UI |
| **`BR-22` / SDD §7:** Tray residency + `<= 2` clicks for Stop/Mute/Offline | Window `X` kills app; Tray has only Show/Stop/Quit; Stop kills Python Core | `lib.rs:64-105, 161-165` | Closing window terminates background wake-word and Core |
| **`FR-SCH-02` / SDD §4:** Persistent background scheduler | Zero background timer/cron loop anywhere in `core/jarvis/` | `app.py:808-830`, `reminder_service.py:182` | Reminders and scheduled workflows never trigger autonomously |
