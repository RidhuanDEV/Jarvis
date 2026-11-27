# 23 — Source Evidence Index

Master cross-reference of audited repository files, line counts, key symbols, and verified line ranges supporting all claims in Docs `00`–`33`. *(Git HEAD `455c6aa` + working tree as of `2026-11-27`; zero personal paths.)*

---

## 1. Python Core (`core/`)

| Relative File Path | Lines | Key Symbols Audited | Primary Documents Referencing |
| --- | :---: | --- | --- |
| `core/pyproject.toml` | 134 | `[project.dependencies]`, `[voice]`, `[tts-piper]`, `[nvidia]`, `importlinter` contracts (`L99-138`), wheel `packages` (`L55`) | `02`, `10`, `16`, `17` |
| `core/migrations/core/0001_initial_core.sql` | 326 | 30 tables incl. unused `session`/`message`/`model_benchmark`, `extension_package` (`L355`) | `06`, `10`, `30` |
| `core/migrations/core/0002_r3_ecosystem.sql` | 51 | `ha_entity_allowlist`, `remote_gateway_config`, `remote_pairing_challenge`, `remote_device_token`, `preference_proposal` | `10`, `14` |
| `core/migrations/knowledge/0001_initial_knowledge.sql` | 63 | `document`, `chunk`, `chunk_fts` (FTS5 + 3 triggers), `embedding_index_generation`, `chunk_embedding` | `06`, `10`, `28` |
| `core/jarvis/domain/models.py` | 377 | `RiskClass`, `GrantRecord` (`scope`), `ToolProposal` (`L382`), `SessionContext` (`untrusted_origin` `L412`), `ConfigDocument` | `03`, `07`, `11`, `14`, `27` |
| `core/jarvis/domain/policy.py` | 299 | `PROHIBITED_TOOL_PREFIXES`/`CAPABILITIES` (`L23-56`), `PolicyEngine.evaluate_step` (`L164-312`), `_has_active_grant` (`L315-331`, ignores `scope`) | `07`, `14`, `19`, `27` |
| `core/jarvis/domain/router.py` | 414 | `_R3_INTENT_PATTERNS` (`L18-24`), `_APP_LAUNCH_RE` (`L37`), `_APP_ALIASES` (`L80-87`), `normalize_utterance` (`L99`), `DeterministicRouter.route` (`L120-383`), `build_static_tool_catalog_prompt` (`L386-410`), `parse_llm_assistant_or_tool` (`L429-460`) | `03`, `07`, `25`, `26`, `29` |
| `core/jarvis/domain/ai_models.py` | 250 | `LlmProviderPort` (`L133-148`), `DynamicResourceGovernor` (`L204-309`, dead code) | `04`, `12`, `15` |
| `core/jarvis/domain/voice.py` | 113 | `BoundedAudioRingBuffer`, `EndpointAwareEchoGuard` (`L60-114`, unused by `LiveVoiceEngine`) | `05`, `26` |
| `core/jarvis/domain/knowledge.py` | 169 | `EmbeddingProviderPort` (`L33-42`), `fuse_hybrid_rrf` (`L141`), `wrap_untrusted_rag_context` (`L192-202`) | `06`, `14`, `28` |
| `core/jarvis/domain/security_guards.py` | 180 | `_SECRET_PATTERNS` (`L43-60`), `is_blocked_screen_window` (`L63-95`), `redact_screen_secrets`, `is_forbidden_ip` | `14`, `27` |
| `core/jarvis/domain/iot_and_remote.py` | 273 | HA R3 safety bans (`L17-51`), private bind validation (`L174-215`), remote scope ceiling | `07`, `14`, `19` |
| `core/jarvis/domain/recommendations.py` | 236 | `recommend_configuration()` | `12`, `19` |
| `core/jarvis/domain/licensing.py` | 159 | `validate_license_artifact`, `derive_license_obligations`, SBOM/notice builders | `17` |
| `core/jarvis/domain/ports.py` | 95 | 9 platform ports (`DesktopAutomationPort`, `NotificationPort`, `StartupIntegrationPort` `L148`) | `02`, `07`, `12` |
| `core/jarvis/application/turn_orchestrator.py` | 765 | `_session_history` (`L113,130`), `submit_turn_streaming` (`L198-483`), `_execute_verified_step` (`L485-731`), `execute_approved_file_move` (`L733-813`, orphaned) | `03`, `06`, `07`, `09`, `14`, `25`–`29` |
| `core/jarvis/application/approval_service.py` | 328 | `create_challenge`, `decide` (`L180-262`, atomic consume, `TRUSTED_UI`/`LOCAL`, `target_snapshot_hash`), `cancel_all_pending_on_lock` | `07`, `09`, `14`, `27` |
| `core/jarvis/application/ai_registry_service.py` | 578 | `default_ai_profiles` (`L67`), `register_provider`, `list_providers` (`L283` 500 crash), `register_manifest` (`L315`), `upsert_profile`, `switch_profile_atomic` (`L512`) | `04`, `14`, `19` |
| `core/jarvis/application/memory_service.py` | 269 | `create_memory` (`L65`, AES-GCM `L81`), `list_memories` (`L124`, O(N)), `update_memory`, `delete_memory` (`L249`, tombstones) | `06`, `10`, `31` |
| `core/jarvis/application/knowledge_service.py` | 608 | `add_source_root` (`L83`), `sync_source_root` (`L184-350`), `build_and_promote_embedding_generation` (`L352`, dead), `search_hybrid` (`L423-562`), `answer_from_knowledge` (`L564-653`) | `06`, `10`, `14`, `28` |
| `core/jarvis/application/reminder_service.py` | 323 | `ProactiveRateLimiter` (`L62-85`, dead), `create_reminder` (`L105`), `process_due_reminders` (`L182-281`, pull-only) | `08`, `09`, `19` |
| `core/jarvis/application/personal_life_service.py` | 322 | Tasks, IANA Calendar, Integer Minor-Unit Expenses, Descriptive Habits | `06`, `08`, `19` |
| `core/jarvis/application/workflow_service.py` | 356 | `create_workflow` (`next_due_at=NULL` `L168`), `dry_run_workflow` (`L189`), `execute_workflow` (`L291` bypass, `L351-359` no-op stub) | `07`, `08`, `14`, `27` |
| `core/jarvis/application/storage_service.py` | 371 | `set_location` (`L158-218`), `migrate_location` (`L237-335`, live WAL `shutil.copy2` `L295`), `cleanup_cache_lru` (`L346-378`, unlink bypass) | `10`, `14`, `27` |
| `core/jarvis/application/backup_service.py` | 194 | `create_backup` (`L76-104`, omits DEK + unconfined path), `verify_backup` (`L139`), `restore_into_directory` (`L165-226`, no route) | `10`, `14`, `19` |
| `core/jarvis/application/config_service.py` | 236 | `CONTRACTS_DIR` (`L31`), `save_revision` (`L104`), `get_active` (`L113`, uncached) | `10`, `11`, `15` |
| `core/jarvis/application/voice_service.py` | 224 | `VoicePipelineService` (disconnected from `LiveVoiceEngine`) | `05`, `26` |
| `core/jarvis/application/screen_service.py` | 129 | `ScreenAwarenessService.analyze_window` (`L72-151`, `window_title` unredacted) | `03`, `07`, `14` |
| `core/jarvis/application/web_search_service.py` | 122 | `WebIntelligenceService` (`search_provider=None`) | `07`, `09`, `14` |
| `core/jarvis/application/ecosystem_service.py` | 347 | `register_private_lan_provider` (`L110-136`, poisons `capabilities_json`), `verify_lan_dispatch` (`L159`, dead), `install_extension` (`L230`, stub), `authorize_extension_capability` (`L332`, dead) | `04`, `14`, `30` |
| `core/jarvis/application/{camera,home_assistant,remote_gateway,preference_proposal,license}_service.py` | 1,618 | `UnavailableCameraCaptureAdapter`, `OfflineHomeAssistantClient`, `RemoteGatewayService` (SHA-256 6-digit pairing & TOCTOU), `PreferenceProposalService` (manual only), `baseline_license_artifacts` (`L19-193`) | `08`, `14`, `17`, `19`, `31` |
| `core/jarvis/infrastructure/live_voice_engine.py` | 847 | `_SileroVadRunner` (`L215`), `_OpenWakeWordRunner` (`L253`), `LiveVoiceEngine` (`L294-950`, noise inflation `L793-821`, blocking loop `L821,930`, hardcoded `lang="id"` `L845`) | `05`, `15`, `25`, `26` |
| `core/jarvis/infrastructure/providers/{llama_cpp_adapter,local_runtime_manager,ollama_adapter}.py` | 635 | `stream_complete` (`L201-274`), binary/GGUF discovery (`L53-120`), no SHA-256 (`L154-196`), `balanced` rev 2 (`L254`), dead `OllamaAdapter` | `04`, `12`, `14`, `15` |
| `core/jarvis/infrastructure/{dual_db,migrations,crypto,web_fetch,logging_setup,event_bus,document_parser}.py` | 997 | Plaintext `sqlite3.connect` (`dual_db:67`), `PRAGMA integrity_check` (`L119`), `executescript` (`migrations:102`), Argon2id header DoS (`crypto:129`), SSRF TOCTOU (`web_fetch:149-182`), traceback log order (`logging_setup:66-68`) | `10`, `11`, `14`, `15` |
| `core/jarvis/platform/windows/{hardware,audio,desktop_automation,filesystem,screen_capture,supervisor,vault}.py` | 875 | `vram=0` AMD/Intel (`hardware:167`), silent 44B OneCore (`audio:147`), `allow_live_launch` & WinMM volume (`desktop_automation:13-73`), `stat()` snapshot (`filesystem:156`), title-only screen (`screen_capture:26-55`), Job Object (`supervisor`), no DPAPI (`vault`) | `07`, `12`, `14`, `26`, `28`, `29` |
| `core/jarvis/transport/{app,remote_gateway_app,settings,__main__}.py` | 2,467 | `build_default_container` (`app:596-798`), `allow_live_launch=False` (`L620`), `FakeNotificationAdapter` (`L621`), middleware (`L842-950`), 96 routes (`L955-2399`), unwired `remote_gateway_app.py` | `02`, `04`, `07`, `11`, `14` |

---

## 2. Desktop Frontend & Rust Broker (`apps/desktop/`)

| Relative File Path | Lines | Key Symbols Audited | Primary Documents Referencing |
| --- | :---: | --- | --- |
| `apps/desktop/src-tauri/tauri.conf.json` | 46 | `"productName": "JARVIS"`, `"withGlobalTauri": false`, CSP, NSIS bundle (`L32-45`, missing `"resources"`) | `02`, `16` |
| `apps/desktop/src-tauri/src/lib.rs` | 156 | `run()` (`L24`), `reqwest` `10s` timeout (`L46`), Tray `stop_all` kills Core (`L95-98`), `WindowEvent::Destroyed` exits app (`L161-165`) | `02`, `11`, `14`, `16` |
| `apps/desktop/src-tauri/src/commands.rs` | 419 | 41 Tauri IPC commands (only 19 used); unencoded path interpolation (`L133, 151, 282, 321, 382, 398, 454`) | `11`, `13`, `14` |
| `apps/desktop/src-tauri/src/{core_launcher,ipc_transport,process_supervisor,single_instance}.rs` | 788 | `discover_core_runtime` (`core_launcher:130`), dead `WindowsNamedPipe` (`ipc_transport:9`), `Stdio::null` & `close_all_managed` (`process_supervisor:212, 311`), `CreateMutexW` (`single_instance:22`) | `02`, `09`, `12`, `16` |
| `apps/desktop/src/App.tsx` | 827 | Full-store subscription (`L75-137`), 350 ms poll (`L161-176`), `liveVoice.last_reply` shadow (`L595`), `record_expense` `'general'` bug (`L746`), `delete_memory` fake ID (`L802`) | `13`, `15`, `25` |
| `apps/desktop/src/lib/{brokerClient,contracts,visualEngine}.ts` | 798 | `waitForLiveCoreStatus` 5s cliff (`brokerClient:119`), `loadFoundationData` no hydration (`L140`), `armLiveVoiceMode` 4 auto-grants (`L273`), `LiveVoiceStatusSchema`, VSync pacing (`visualEngine`) | `11`, `13`, `14`, `27` |
| `apps/desktop/src/store/jarvisStore.ts` | 537 | Hardcoded fake seeds (`L158-186`), dead `applySequencedEvent` (`L299-349`) | `11`, `13` |
| `apps/desktop/src/components/{OrbitalCore,ApprovalDialog,OnboardingWizard,FoundationPanels,IntelligencePanels,ProductivityPanels,EcosystemPanels}.tsx` | 2,227 | SVG `setState` in `rAF` (`OrbitalCore:101`), native `<dialog>` (`ApprovalDialog:34`), 1-Click skips Step 9 (`OnboardingWizard:99`), mocked `KnowledgePanel`/`WorkflowsPanel`/`Storage` quotas/`RuntimeVisualPanel` | `13`, `15`, `19`, `25`–`29` |

---

## 3. Contracts, Scripts, Workflows & Tests

| Relative File Path | Lines | Key Artifacts Audited | Primary Documents Referencing |
| --- | :---: | --- | --- |
| `contracts/*.schema.v1.json` (4 files) | 358 | `config`, `events`, `license-artifact`, `tool-proposal` JSON Schemas | `11`, `19` |
| `.github/workflows/{ci-tier-a,release-windows}.yml` | 206 | 40-char SHA pinning, Tier-A jobs, SLSA provenance, missing Release publish/signing | `16`, `17` |
| `scripts/{generate_release_sbom,build_sdlc_complete}.py`, `scripts/install_local_windows.ps1` | 378 | SBOM transitive-license omission (`L148-196`), local dev pointer script (`Jarvis-R0-Sandbox`) | `12`, `16`, `17` |
| `tests/**` (12 files) + `apps/desktop/src/__tests__/**` (4 files) | 3,421 | 150 pytest + 15 Vitest + 6 Cargo = 171 cases (audited for mocks & masked bugs) | `18`, `19` |
| `JARVIS-SDLC-v0.2.1/**` (19 files) + `planning/**` (14 files) | ~2,100 | Approved `v0.2.1` specs, `DEC-001`–`DEC-030`, `R0` report, 98-case RTM manifest | `01`, `15`, `19` |
