# 06 — Memory and Knowledge Architecture Audit

This document audits every memory and retrieval subsystem in J.A.R.V.I.S. (`core/jarvis/application/turn_orchestrator.py`, `core/jarvis/application/memory_service.py`, `core/jarvis/application/knowledge_service.py`, `core/jarvis/domain/knowledge.py`, `core/jarvis/application/personal_life_service.py`, `core/jarvis/application/preference_proposal_service.py`, `core/jarvis/application/config_service.py`, `core/migrations/**`).

---

## 1. Master Inventory of Implemented Memory Types

| Memory Type | Implementation Status | Storage Location | Retrieved Into LLM Responses? | User Inspect / Edit / Delete |
| --- | :---: | --- | :---: | --- |
| **Working / Conversation History** | **`IMPLEMENTED`** *(RAM-only)* | `TurnOrchestratorService._session_history` (`dict[str, deque(maxlen=12)]`, `turn_orchestrator.py:113,130`). SQLite `session` & `message` tables (`0001_initial_core.sql:43-61`) are **100% UNUSED**. | **YES** — last 12 messages (6 exchanges) per `session_id` injected at `turn_orchestrator.py:276-281`. | **NO** — no UI history viewer, no inspect/export/edit; cleared only on restart or `/v1/session/lock`. |
| **Short-Term Memory** | **`NOT IMPLEMENTED`** | No TTL-tiered short-term memory store exists beyond the 6-turn RAM deque. `conversation_history_retention_enabled` (`models.py:337`) is never read. | Same as above. | None. |
| **Long-Term Personal Memory (`MemoryVault`)** | **`PARTIAL` / DISCONNECTED** | `jarvis_core.db`: `memory`, `memory_revision`, `deletion_ledger` (`memory_service.py:42-294`). AES-256-GCM field encryption when `sensitivity == "sensitive"` (`L81-82`). | **NO — NEVER RETRIEVED!** `TurnOrchestratorService` only calls `create_memory()` (`L554`), NEVER `list_memories()`. | API CRUD complete (`GET/POST/PATCH/DELETE /v1/memories`); UI delete is **BROKEN** (sends client fake ID `mem-${Date.now()}` -> `404` on Core, `App.tsx:802-805`), UI never hydrates on boot. |
| **Semantic Memory (Vectors)** | **`NOT IMPLEMENTED` (DEAD SHELL)** | `jarvis_knowledge.db`: `embedding_index_generation`, `chunk_embedding` (`0001_initial_knowledge.sql:56-74`). `sqlite-vec` loads (`dual_db.py:78`), **0 `vec0` tables/queries exist**. | **NO** — zero `EmbeddingProviderPort` implementation exists in `core/jarvis/`; `embedding_provider=None` everywhere in runtime. | None (`build_and_promote_embedding_generation` has no HTTP route). |
| **Episodic Memory** | **`NOT IMPLEMENTED`** | No event/episode summarization, temporal timeline recall, or cross-session episodic store exists (`audit_event` is an immutable security log, never queried for reasoning). | **NO**. | Audit log has no UI viewer. |
| **User Preferences** | **`PARTIAL` / UNWIRED** | `jarvis_core.db`: `config_revision` (`persona.style`, `verbosity`, `locale`, `audio`, `visual`) + `preference_proposal` (`preference_proposal_service.py:43-250`). | **NO** — `TurnOrchestratorService` never reads `persona.style` or `persona.verbosity`. `PreferenceProposalService` has zero automatic detectors (manual API only; UI shows hardcoded fixture `prop-verbosity-brief`). | API exists; UI approve/reject sends fake fixture ID (`404` on Core). |
| **Task / Life Memory** | **`PARTIAL`** | `jarvis_core.db`: `task`, `calendar_event`, `expense`, `habit_log`, `reminder` (`personal_life_service.py`, `reminder_service.py`). | Only `life.task.create` & `life.task.list` are wired as deterministic/LLM tools; calendar, expenses, habits, and existing reminders are invisible to LLM conversation. | API exists; UI never hydrates on restart; `record_expense` corrupts category to `'general'` (`App.tsx:746`). |
| **Personal Knowledge (Document RAG)** | **`PARTIAL` (BM25-only, UI mock)** | `jarvis_knowledge.db`: `document`, `chunk`, `chunk_fts` (FTS5 `unicode61`), synced manually from opt-in `source_root`s (`knowledge_service.py:68-653`). | Only on explicit `knowledge.query` tool (`turn_orchestrator.py:648-683`); BM25 lexical only; `POST /v1/knowledge/query` omits LLM synthesis (returns 240-char snippet!). | API CRUD + `/sync` exists; Desktop `KnowledgePanel` is **100% disconnected Zustand mock** (`App.tsx:727-733`, `ProductivityPanels.tsx:30-38`). |

---

## 2. Deep Architectural Audit of Each Mechanism

### 2.1 How Information Is Captured, Classified, Retrieved, and Used
- **Capture:**
  - Conversation turns: recorded automatically into RAM `deque(maxlen=12)` on completed LLM or tool turns (`turn_orchestrator.py:342, 473`).
  - Long-term memories: captured only via explicit command (`"ingat bahwa ..."` -> `memory.create`, `router.py:39-42`), `POST /v1/memories`, or proposal approval (`POST /v1/memories/{id}/approve`). Classified by `kind` (`fact|preference|instruction|note`), `sensitivity` (`normal|sensitive`), and `status` (`active|proposal`).
  - Personal documents: captured ONLY when a user adds an opt-in `source_root` (`POST /v1/roots`) AND manually calls `POST /v1/roots/{id}/sync` (`.txt`, `.md`, `.pdf`, `.docx`, `<= 25 MiB`, `document_parser.py:15,184-189`).
- **Retrieval & Relevance:**
  - `MemoryVaultService.list_memories()` (`memory_service.py:124-160`): O(N) full table scan decrypting every `sensitive` row in Python and doing case-insensitive `query.lower() in content.lower()` substring matching (no FTS5, no ranking, and **never called by `TurnOrchestratorService`**).
  - `KnowledgeRagService.search_hybrid()` (`knowledge_service.py:423-562`): executes SQLite FTS5 `bm25(chunk_fts)` filtered by `active_roots` + `deletion_ledger` tombstones, then applies `fuse_hybrid_rrf()` (`domain/knowledge.py:141-178`). Because `embedding_provider` is always `None` in production (`app.py:1753, 1773`, `turn_orchestrator.py:662`), `vec_ids` is permanently empty — hybrid RRF degrades to pure BM25 lexical matching.
- **Outdated & Conflicting Information:**
  - `MemoryVaultService.update_memory()` (`memory_service.py:162-215`) uses optimistic locking (`expected_revision`, returning `CONFLICT`/error on mismatch) and records immutable history in `memory_revision`. No automatic contradiction detection exists between memories.
  - `KnowledgeRagService.sync_source_root()` (`knowledge_service.py:184-350`) detects edited files via SHA-256 and deletes stale disk-removed files (`L320-329`), but only when manually triggered (zero file watchers) and inefficiently parses full PDFs/DOCX *before* checking if SHA-256 changed (`L232-235`).
- **Deletion & Anti-Resurrection (`deletion_ledger`):**
  - `delete_memory()` (`memory_service.py:249-294`) and `revoke_source_root()` (`knowledge_service.py:130-182`) record tombstones in `deletion_ledger` (`UNIQUE(entity_type, entity_id)`). `DualSqliteManager.gc_revoked_knowledge()` (`dual_db.py:167-200`) purges revoked roots on startup, and `BackupService.restore_into_directory()` replays preserved tombstones (`backup_service.py:194-215`) — **note:** `preserve_local_tombstones` defaults to `None` unless the caller explicitly harvests them first.

### 2.2 Memory Poisoning & Sensitive-Data Exposure Audit
- **Protections implemented (`VERIFIED` in tests):**
  - `MemoryVaultService` requires explicit consent/approval for proposals (`BR-14`); `sensitivity="sensitive"` rows are encrypted with AES-256-GCM + per-row AAD (`memory:{id}:content`, `memory_service.py:81-82`).
  - `KnowledgeRagService.answer_from_knowledge()` (`knowledge_service.py:604-626`) wraps chunks in `<untrusted_document_data>` and enforces `tools_disabled=True` (`BR-15`) plus post-synthesis citation filename verification.
- **Confirmed Gaps / Vulnerabilities:**
  1. **Second-order memory/history poisoning (`turn_orchestrator.py:473`, `domain/knowledge.py:192-202`):** `<untrusted_document_data>` does not escape closing tags inside chunk text, and RAG/`screen.analyze` summaries are appended verbatim as `assistant` messages into `_session_history` — feeding directly into the tool-calling LLM planner on the next turn with `untrusted_origin=False`!
  2. **Cross-machine DEK loss (`backup_service.py:85-98`):** Encrypted `sensitive` memories become permanently unreadable after restoring a backup onto another machine because `jarvis.memory.master_dek.v1` is not exported/re-wrapped.
  3. **Plaintext storage of `normal` memories & all knowledge chunks (`dual_db.py:67`):** Both `jarvis_core.db` and `jarvis_knowledge.db` are unencrypted SQLite files on disk.
  4. **Unenforced `source_root.scope_json` (`knowledge_service.py:102, 192-232`):** Extension allowlists stored in `scope_json` are never checked during `sync_source_root()`.

---

## 3. Verdict: Persistent Intelligence vs Transcript Storage

**J.A.R.V.I.S. currently has NEITHER persistent conversational intelligence NOR even persistent conversation transcripts.**

- Conversation history vanishes on every restart (`RAM deque(maxlen=12)`).
- Long-term memories stored in `jarvis_core.db` are a **write-only vault from the AI's perspective** because `TurnOrchestratorService` never retrieves them.
- Personal documents require manual API sync (UI is mocked), lack semantic embeddings, and are only searched when the user says an exact keyword trigger (`"cari di dokumen ..."`).
- **Zero learning or self-improvement exists** anywhere in the codebase (`PreferenceProposalService` has zero detectors, `PersonaConfig` is unused in prompts, and zero feedback/training loops exist).
