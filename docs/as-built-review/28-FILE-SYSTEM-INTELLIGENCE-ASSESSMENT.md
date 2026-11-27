# 28 — File System Intelligence Assessment

> **Document Scope:** Comprehensive forensic evaluation of J.A.R.V.I.S.'s current local file and directory awareness against all **17 Addendum §C capabilities**, comparative engineering analysis of Windows indexing technologies (`Windows Search`, `Everything SDK`, `NTFS USN Journal`, `ReadDirectoryChangesW` / watchers, `SQLite FTS5`, and local semantic retrieval), strict architectural separation of the four knowledge tiers, and boundary/edge-case threat modeling.

---

## 1. Capability Truth Table (All 17 Addendum §C Requirements)

| # | Capability (Addendum §C) | Status | Source Evidence & Actual As-Built Behavior | Key Gap |
| :---: | --- | :---: | --- | --- |
| 1 | **Dynamic drive discovery** | `PARTIAL` | `core/jarvis/platform/windows/filesystem.py:169-191` (`list_volumes()`) backs `GET /v1/storage/volumes`, but has **0 references** in `TurnOrchestrator`, `Router`, `ToolRegistry`, or `KnowledgeService`. | Implemented in platform layer for Storage UI only; completely invisible to JARVIS intelligence. |
| 2 | **Authorized directory discovery** | `PARTIAL` | `source_root` table (`0001_initial_core.sql:196-206`) & `KnowledgeService.register_source_root` (`knowledge_service.py:114-182`) exist, but `KnowledgePanel` UI (`ProductivityPanels.tsx:30-38`) is 100% mock and never registers real folders. `policy.py:315-331` ignores `grant.scope`. | No live folder onboarding, no directory tree listing tool, broken scope enforcement. |
| 3 | **Filesystem metadata indexing** | `NOT IMPLEMENTED` | No `file_index` / metadata catalog table exists. `document` table (`0001_initial_core.sql:208-221`) stores only manually synced `.txt/.md/.pdf/.docx` RAG files. | Cannot locate `.xlsx`, `.pptx`, `.png`, `.mp4`, `.zip`, `.py`, `.ts`, or folder names at all. |
| 4 | **Incremental indexing** | `BROKEN` | `knowledge_service.py:184-350` (`sync_source_root`) walks entire root on manual trigger and **parses full PDF/DOCX text before checking SHA-256**, ignoring `mtime`/`size` fast-skip and ignoring `scope_json` extension filters. | O(N) full re-parse on manual sync; zero incremental delta tracking. |
| 5 | **File change monitoring** | `NOT IMPLEMENTED` | Zero filesystem watcher imports (`watchdog`, `ReadDirectoryChangesW`, USN Journal) anywhere in `core/` or `apps/desktop/src-tauri/`. | Index immediately goes stale the moment a user creates, renames, or saves a file. |
| 6 | **Exact filename search** | `NOT IMPLEMENTED` | `knowledge_service.py:352-415` searches `document_chunk_fts` (body text BM25), not filenames/paths. Zero `fs.search` tool exists in `tool_registry.py`. | Asking *"di mana file invoice_2026.pdf?"* fails unless exact words appear in manually synced body text. |
| 7 | **Fuzzy filename search** | `NOT IMPLEMENTED` | No trigram index, Levenshtein/Jaro-Winkler scorer, or Indonesian/English typo-tolerant filename matcher exists. | Voice STT minor spelling variants (e.g., `"skripsi"` vs `"skirpsi"`, `"budget q4"` vs `"Budget_Q4_Final.xlsx"`) cannot resolve. |
| 8 | **Extension and date filtering** | `NOT IMPLEMENTED` | No structured metadata query supporting `ext=.pdf`, `modified_after`, `size_range`, or `folder_scope`. | Cannot answer *"cari semua PDF yang saya ubah minggu ini"*. |
| 9 | **Full-text search** | `PARTIAL` | SQLite FTS5 (`document_chunk_fts`, `0001_initial_core.sql:237-244`) exists for `.txt/.md/.pdf/.docx` (`<= 25 MiB`, `document_parser.py:15,184-189`), **but** has no tool wiring in `Router` and desktop Knowledge UI is mocked. | Backend BM25 engine exists for 4 formats, but is disconnected from UI and real user queries. |
| 10 | **Semantic document retrieval** | `NOT IMPLEMENTED` | `knowledge_service.py:72-79` defines an optional `embedding_provider`, **hardcoded to `None`** in `app.py:610-619`. Zero `EmbeddingProviderPort` implementation; zero `sqlite-vec` `vec0` tables (`0001_initial_core.sql`). | Zero conceptual/paraphrase retrieval (e.g., querying `"biaya server"` will not find a doc saying `"infrastruktur cloud"`). |
| 11 | **Recent file awareness** | `NOT IMPLEMENTED` | Zero tracking of Windows Recent Items (`%APPDATA%\Microsoft\Windows\Recent`), `mtime` descending index queries, or active editor/document signals. | Cannot answer *"file apa yang barusan saya kerjakan?"*. |
| 12 | **Conversation-aware file resolution** | `NOT IMPLEMENTED` | No structured `active_entities` / `recent_search_results` slot in `TurnOrchestrator` or `SessionContext`. | Follow-ups like *"buka yang kedua"* or *"ringkas file yang tadi"* fail completely. |
| 13 | **Opening files using registered apps** | `NOT IMPLEMENTED` | Zero `os.startfile`, `ShellExecuteW`, or `fs.file.open` tool exists in `tool_registry.py` or `desktop_automation.py`. | Even if JARVIS finds a document path, it cannot open it in Word, Excel, Acrobat, or Explorer. |
| 14 | **Installed application discovery** | `NOT IMPLEMENTED` | Hardcoded 3-app System32 map (`desktop_automation.py:13-17`). Detailed in [29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md). | Zero awareness of Chrome, VS Code, Office, Spotify, Discord, etc. |
| 15 | **Dynamic application launching** | `BROKEN` | `allow_live_launch=False` (`app.py:620`) + 3-app allowlist + R1 grant blocker. Detailed in [29-APPLICATION-DISCOVERY-ASSESSMENT.md](./29-APPLICATION-DISCOVERY-ASSESSMENT.md). | Fails or silently fakes every app launch. |
| 16 | **Application alias management** | `PARTIAL` (Static) | Hardcoded 6-key dict `_APP_ALIASES` (`router.py:80-87`); zero DB table, API, or UI for user-defined aliases. | Users cannot map *"koding"* -> VS Code or *"browser"* -> Edge/Chrome. |
| 17 | **User-defined file and folder aliases** | `NOT IMPLEMENTED` | Zero alias registry table or prompt/resolver hook for nicknames (e.g., *"folder skripsi"*, *"proyek jarvis"*, *"laporan bulanan"*). | Users must recite awkward full paths instead of natural personal shorthand. |

---

## 2. Comparative Evaluation of Windows Indexing & Retrieval Technologies

> **Critical Design Principle (Addendum §C):** Do **NOT** embed every file on every drive. Blind whole-disk vector embedding wastes tens of gigabytes of disk/RAM, thrashes SSDs and laptops on battery, leaks excluded sensitive files into vector stores, and degrades retrieval precision with noise.

| Technology | Requires Admin / Elevation? | Latency (100k Files) | Coverage & Capability | Reliability / Operational Trade-Offs on Windows | Audit Recommendation for J.A.R.V.I.S. |
| --- | :---: | :---: | --- | --- | --- |
| **SQLite Metadata Catalog + FTS5 Trigram + `ReadDirectoryChangesW` (`watchdog`)** | **No** (Standard User) | `< 15 ms` | Authorized user directories across NTFS, FAT32, exFAT, removable drives; exact + fuzzy filename, path, ext, size, mtime | Self-contained, 100% deterministic scope boundaries, works out-of-the-box with zero external services, bounded RAM (`< 100 MB`); initial crawl of 100k files takes `3–8s` (stat-only, no content reads). | **RECOMMENDED PRIMARY ENGINE** for Layer 1 (Filesystem Metadata Index) inside authorized user scopes. |
| **Windows Search (`SystemIndex` via OLE DB / WinRT)** | **No** (Standard User) | `20–80 ms` | Pre-indexed Windows Libraries (`Documents`, `Desktop`, `Downloads`, Start Menu, Outlook) + system IFilters | Zero duplicate background I/O when enabled, **but** unreliable as sole engine: users frequently disable `WSearch`, exclude developer drives (`D:\`), or have stale/corrupt EDB indexes; returns paths outside JARVIS's explicit authorized scopes unless post-filtered. | **RECOMMENDED OPTIONAL READ-ONLY ADAPTER** (fast fallback/accelerator strictly post-filtered by JARVIS's canonical scope & exclusion rules). |
| **Everything SDK (`Everything64.dll` / IPC)** | **Yes** (Requires Everything Service installed & running as SYSTEM to read NTFS MFT) | `< 5 ms` (millions of files) | Ultra-fast NTFS filename/size/date lookup across all fixed NTFS volumes | Extraordinary speed, **but** requires third-party Voidtools Everything installation + privileged service; does not index FAT32/exFAT without folder-monitoring; exposes **entire disk** if not strictly filtered by JARVIS's authorized-scope policy. | **OPTIONAL POWER-USER ACCELERATOR ONLY** (auto-detected read-only if owner already installed Everything; NEVER a mandatory dependency and ALWAYS filtered through JARVIS's scope allowlist + exclusion denylist). |
| **Raw NTFS USN Change Journal (`FSCTL_READ_USN_JOURNAL`)** | **Yes** (Requires `SeManageVolumePrivilege` / Admin) | Near-instant delta | Volume-wide NTFS change journal | Violates least-privilege desktop execution (standard non-elevated Tauri/Python process cannot open `\\.\C:` volume handles); NTFS-only (breaks on exFAT USB drives). | **REJECT for standard desktop agent** (unnecessary privilege escalation; `ReadDirectoryChangesW` achieves real-time monitoring per authorized root without elevation). |
| **SQLite FTS5 Full-Text Body Index** | **No** | `10–40 ms` | Exact keyword, phrase, prefix, and BM25 ranking over extracted text chunks of authorized documents | Already present in `0001_initial_core.sql` (`document_chunk_fts`), zero extra dependencies, low RAM/CPU footprint; needs `mtime+size` fast-skip before SHA-256 & expanded parsers (`.xlsx`, `.pptx`, `.csv`, `.json`, source code). | **RECOMMENDED PRIMARY ENGINE** for Layer 2 (Full-Text Search) strictly on explicitly authorized knowledge roots. |
| **Local Semantic Retrieval (ONNX Embeddings + `sqlite-vec` `vec0`)** | **No** | `30–120 ms` | Conceptual/bilingual ID+EN semantic similarity (e.g., `multilingual-e5-small` / `bge-m3-small` ONNX int8) + hybrid RRF fusion with FTS5 | High intelligence value for curated document folders (notes, specs, PDFs, research), **but** expensive if applied to raw bulk folders (`Downloads`, media, `node_modules`). Must be opt-in per curated Knowledge Root and hardware-throttled (pause on battery / high CPU). | **RECOMMENDED SELECTIVE ENGINE** for Layer 3 (Semantic RAG) strictly on curated Knowledge Roots—never whole-disk. |

---

## 3. Mandatory 4-Layer Architectural Separation

To keep J.A.R.V.I.S. fast, private, and hardware-adaptive, the external reviewer should enforce strict separation across four independent stores:

```text
Layer 1: Filesystem Metadata Index (Fast, Broad Within Authorized Scopes)
  - Stores ONLY: canonical_path, parent_dir, filename, ext, size_bytes, mtime_ns, is_dir, volume_serial, last_seen_at
  - Search: Exact + FTS5 trigram fuzzy + ext/date/size filters + Recent Files
  - Cost: ~150 bytes/file (~15 MB for 100,000 files), zero file content reads

Layer 2: Full-Text Document Index (Selective, Authorized Document Roots)
  - Stores: extracted text chunks in SQLite FTS5 (BM25) for supported doc/code formats
  - Update: incremental via ReadDirectoryChangesW + (mtime_ns, size_bytes) fast-skip -> SHA-256 check

Layer 3: Semantic Vector Index (Curated Knowledge Scopes Only)
  - Stores: quantized ONNX multilingual embeddings in sqlite-vec (vec0), fused with Layer 2 via RRF
  - Budgeted: paused on battery / thermal load / active voice STT-LLM turn; capped max file size & chunk count

Layer 4: Personal Memory, Conversation Context & User Aliases (High-Trust Curated Facts)
  - Stores: Memory Vault facts, user preferences, file/folder/app aliases ("folder skripsi" -> canonical path),
    and ephemeral conversation entity stack ("last_mentioned_files[1..5]") for pronoun resolution ("buka yang kedua")
```

---

## 4. Boundary Conditions, Threat Model & Operational Limits

Every finding below includes the mandatory 8-field audit structure:

### Finding FSI-01: Missing Scope Boundaries, Excluded Directories & Symlink/Reparse-Point Defenses
- **Source Evidence:** `core/jarvis/application/knowledge_service.py:184-350` (`os.walk` / `rglob` without reparse-point rejection or secret-folder exclusion); `core/jarvis/domain/policy.py:315-331` (`grant.scope` ignored).
- **Current Behavior:** Indexing and permission checks do not systematically exclude sensitive credential stores, OS directories, or build/dependency trees, and do not guard against NTFS junctions/symbolic links escaping authorized scopes or creating directory cycles.
- **Expected Behavior:**
  - **Hard Non-Overridable Exclusion Denylist (Index + Read):** `C:\Windows`, `C:\ProgramData`, `C:\$Recycle.Bin`, `System Volume Information`, `%LOCALAPPDATA%\Jarvis` (internal DB/vault), browser credential stores (`Login Data`, `Cookies`, `Local State`), `.ssh`, `.gnupg`, `.aws`, `.azure`, `.kube`, `.env*`, `*.pem`, `*.key`, `*.pfx`, `*.kdbx`, `id_rsa*`.
  - **Performance Noise Exclusions (Metadata/Content):** `node_modules`, `.venv`, `venv`, `__pycache__`, `.git\objects`, `target\debug`, `target\release`, `dist`, `build`, `AppData\Local\Temp`.
  - **Symlinks & NTFS Reparse Points:** Never follow directory junctions/symlinks during recursive crawl (`follow_symlinks=False` + Win32 `FILE_ATTRIBUTE_REPARSE_POINT` check); verify `os.path.realpath(candidate)` remains strictly contained inside an authorized canonical root before opening or reading any file.
- **Probable Root Cause:** Confirmed omission of canonical filesystem boundary hygiene in `KnowledgeService` and `PolicyEngine`.
- **Verification Status:** `BROKEN` (scope bypass verified in `policy.py:315-331`; exclusion/reparse guards `NOT IMPLEMENTED`).
- **Proposed Improvements:** Implement a single shared `SafePathBoundary` module (used by Indexer, Watcher, Search, Reader, Document Opener, and Move/Edit tools) enforcing canonical path containment, reparse-point refusal, and immutable secret/system exclusions.
- **Security Implications:** Without reparse-point and secret-file exclusions, a benign authorized root (e.g., a code workspace containing `.env` or a symlink to `%USERPROFILE%\.ssh`) could leak private keys into FTS5/vector indexes or LLM context.
- **Acceptance Criteria:** Unit & Windows NTFS junction tests prove `0` files inside `.ssh`, `.env`, `jarvis_core.db`, or junction targets outside authorized roots are ever indexed, returned in search, or passed to LLM prompts.

### Finding FSI-02: External Drives, Permissions Errors, Stale Index Recovery & Resource Caps
- **Source Evidence:** `core/jarvis/platform/windows/filesystem.py:169-191` (static snapshot `list_volumes()`; no `WM_DEVICECHANGE` mount/unmount watcher); `core/jarvis/application/knowledge_service.py:210-330` (synchronous foreground parsing; no CPU/RAM/battery throttling or tombstone pruning for disappeared removable volumes).
- **Current Behavior:** Unplugging a USB drive or encountering `PermissionError` / locked files (e.g., open Excel/Outlook `.pst` locks) has no graceful offline-volume state, retry backoff, or resource throttling. Re-syncing a large folder parses PDFs synchronously without yielding to active voice or LLM inference.
- **Expected Behavior:**
  - **External/Removable Drives:** Key metadata records by `(volume_serial_number, relative_path)` with `volume_status = ONLINE | OFFLINE`. When unplugged (`WM_DEVICECHANGE`), mark volume `OFFLINE` (do not thrash/delete metadata immediately; surface `"Drive E: sedang tidak terpasang"` if queried) and reconcile incrementally on reconnect.
  - **Permissions & Locked Files:** Catch `PermissionError` / `WinError 32` (sharing violation) per-file cleanly, record transient status with exponential retry cap, never abort the whole directory scan.
  - **Stale Index Handling:** On startup, run lightweight incremental mtime reconciliation per online root; verify `os.path.exists()` before opening/returning a file (self-heal stale entry if moved/deleted externally).
  - **Resource Caps:** Run background indexing at `BELOW_NORMAL_PRIORITY_CLASS` / `PROCESS_MODE_BACKGROUND_BEGIN` I/O priority, pause immediately while `LiveVoiceEngine` is actively running STT/LLM or when laptop battery `< 20%`, cap max concurrent parsers (`1–2` threads), and enforce per-root file-count/size ceilings.
- **Probable Root Cause:** Confirmed absence of lifecycle/resource engineering in `KnowledgeService` and missing volume-event hooks.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Introduce a low-priority background `FileIndexWorker` governed by hardware telemetry (CPU, battery, active voice state) with `volume_serial` tracking, live pre-open existence verification, and bounded parser queues.
- **Security Implications:** Auto-indexing unknown newly plugged USB drives without explicit owner authorization could ingest untrusted documents (indirect prompt injection) or sensitive third-party data. Removable drives MUST default to `UNTRUSTED / NOT INDEXED` until explicitly authorized by the owner.
- **Acceptance Criteria:** Unplugging an authorized external drive cleanly marks entries `OFFLINE` within `<= 2s`; querying a deleted file self-heals the stale record rather than crashing; background indexing keeps sustained CPU `< 10%` and pauses within `100ms` of wake-word activation.

### Finding FSI-03: Missing Safe Document Opening & Conversation-Aware File Resolution
- **Source Evidence:** `core/jarvis/transport/app.py:120-255` (`default_tool_registry()`, 0 file-search or file-open tools); `core/jarvis/application/turn_orchestrator.py:113-135` (`_session_history` stores plain strings only, zero structured entity memory).
- **Current Behavior:** JARVIS cannot open a found document in its registered Windows application and cannot resolve referential follow-ups (*"buka file yang pertama"*, *"ringkas dokumen tadi"*).
- **Expected Behavior:**
  - Add Tier-1 `fs.search` (metadata + FTS5 + hybrid semantic), `fs.recent`, and `fs.file.open` tools.
  - `fs.file.open` validates: (1) canonical path is inside an authorized scope and not excluded; (2) extension is on an explicit **safe non-executable data allowlist** (`.pdf`, `.docx`, `.xlsx`, `.pptx`, `.txt`, `.md`, `.csv`, `.png`, `.jpg`, `.jpeg`, `.webp`, `.svg`, `.mp3`, `.wav`, `.mp4`, `.mkv`, `.json`, `.yaml`, `.log`, plus folder open via `explorer.exe /select,`); (3) **never** invokes `ShellExecuteW` on executable/script/shortcut types (`.exe`, `.bat`, `.cmd`, `.ps1`, `.vbs`, `.js`, `.hta`, `.msi`, `.scr`, `.lnk`, `.reg`, `.jar`).
  - Maintain a structured per-session `EntityWorkingSet` (last 10 referenced files/folders/apps with 1-based ordinal index and timestamp) so *"buka nomor dua"* or *"buka yang tadi"* resolves deterministically without guessing.
- **Probable Root Cause:** Confirmed missing native tools and absent structured working-set entity tracking.
- **Verification Status:** `NOT IMPLEMENTED`.
- **Proposed Improvements:** Implement `fs.search`, `fs.recent`, `fs.file.open`, and `EntityWorkingSet` backed by `SafePathBoundary` and Tier-1 policy rules; wire `KnowledgePanel` UI to real Core APIs so the owner can inspect, add, pause, or revoke authorized roots visually.
- **Security Implications:** Safe extension allowlisting on `fs.file.open` is mandatory to prevent disguised execution of scripts or binaries (Tier-3 enforcement).
- **Acceptance Criteria:** `"Cari laporan PDF bulan ini"` -> `"Buka yang pertama"` opens the exact verified PDF in the OS default viewer under Tier 1 with zero confirmation friction; attempting to open a `.ps1`/`.bat`/`.exe`/`.lnk` via `fs.file.open` is unconditionally rejected and logged (`0%` bypass).
