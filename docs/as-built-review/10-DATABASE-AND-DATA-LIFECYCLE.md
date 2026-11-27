# 10 — Database and Data Lifecycle Audit

This document audits the dual SQLite schema, migration engine, encryption at rest, cross-DB consistency, storage migration, backup/restore cryptography, and database concurrency/performance (`core/migrations/**`, `core/jarvis/infrastructure/{dual_db.py,migrations.py,crypto.py}`, `core/jarvis/application/{storage_service.py,backup_service.py,config_service.py}`).

---

## 1. Dual-SQLite Persistence Topology (`core/jarvis/infrastructure/dual_db.py`)

J.A.R.V.I.S. separates authoritative state (`jarvis_core.db`) from rebuildable search indexes (`jarvis_knowledge.db`):
- **PRAGMAs applied on open (`dual_db.py:67-86`):** `journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `temp_store=MEMORY`; loads `sqlite_vec` extension on `jarvis_knowledge.db` (`L75-80`).
- **Connection model (`dual_db.py:50-60`):** **Single `sqlite3.Connection` per database** protected by `threading.RLock` (`core_tx()`, `core_read()`, `knowledge_tx()`, `knowledge_read()`). Because reads and writes share one connection + mutex, **WAL concurrent reads are serialized behind every write**.

---

## 2. Complete Schema Inventory (35 Core Tables + 5 Knowledge Tables)

### 2.1 `jarvis_core.db` (`core/migrations/core/0001_initial_core.sql` & `0002_r3_ecosystem.sql`)
- **Active tables (31):** `schema_migration`, `config_revision` (+ `uq_config_revision_active`), `storage_location`, `hardware_snapshot`, `approval` (+ `idx_approval_state_expires`), `grant` (+ `idx_grant_subject_cap`), `audit_event` (+ `idx_audit_event_ts`, `idx_audit_event_corr`), `memory` *(missing index on `(status, updated_at)`)*, `memory_revision` *(missing FK index on `memory_id`)*, `deletion_ledger` (`UNIQUE(entity_type, entity_id)`), `source_root`, `workflow`, `reminder`, `job` (+ `idx_job_due_state`), `delivery`, `task`, `calendar_event`, `expense`, `habit_log`, `device`, `model_provider`, `model_manifest`, `ai_profile`, `active_ai_profile`, `license_artifact`, `extension_package`, `ha_entity_allowlist`, `remote_gateway_config`, `remote_pairing_challenge`, `remote_device_token` (+ `idx_remote_device_token_device`), `preference_proposal`.
- **Partially used (2):** `request` and `action_run` (+ `idx_action_run_request_id`) — written ONLY by `ApprovalService.create_challenge` for R2 approvals; NEVER written for R0/R1/LLM turns.
- **100% UNUSED tables (3):**
  1. `session` (`0001_initial_core.sql:43-50`) — zero queries in `core/jarvis/`.
  2. `message` (`0001_initial_core.sql:52-59`, `idx_message_session_id`) — zero queries in `core/jarvis/`.
  3. `model_benchmark` (`0001_initial_core.sql:328-337`) — zero queries in `core/jarvis/`.

### 2.2 `jarvis_knowledge.db` (`core/migrations/knowledge/0001_initial_knowledge.sql`)
- `schema_migration`, `document` (+ `idx_document_root_id`), `chunk` (+ `idx_chunk_root_id`, `idx_chunk_document_id`), `chunk_fts` (FTS5 `unicode61` virtual table + 3 sync triggers `trg_chunk_ai`, `trg_chunk_ad`, `trg_chunk_au`), `embedding_index_generation` (+ `uq_embedding_generation_active`), `chunk_embedding`.
- **Forensic Note:** Although `sqlite_vec` (`v0.1.9`) is loaded on `jarvis_knowledge.db`, **zero `vec0` virtual tables exist** and `chunk_embedding` is permanently empty in production (no `EmbeddingProviderPort` exists).

---

## 3. Critical Data-Lifecycle & Integrity Findings

1. **[CRITICAL] Plaintext SQLite at Rest (`dual_db.py:67`):** Both `jarvis_core.db` and `jarvis_knowledge.db` use standard unencrypted `sqlite3.connect` (no SQLCipher). Only `memory.content` where `sensitivity == "sensitive"` is AES-256-GCM encrypted (`memory_service.py:81-82`). All normal memories, tasks, expenses, reminders, audit logs, and **100% of indexed personal document chunks/FTS5 text** are plaintext on disk.
2. **[CRITICAL] Cross-Machine Backup Permanently Bricks Encrypted Memories (`backup_service.py:85-98` + `vault.py:32-40`):**
   - `BackupService.create_backup()` snapshots `jarvis_core.db` (using `online_backup_sqlite`), zips `manifest.json` + `jarvis_core.db`, and encrypts with Argon2id (`t=3, m=65536 KiB, p=2`) + AES-256-GCM (`JRVB` container, `crypto.py:90-111`).
   - **Fatal bug:** `jarvis.memory.master_dek.v1` (stored in source host's Windows Credential Manager) is **never exported or re-wrapped inside the backup**. Restoring onto another machine causes `WindowsVaultAndCryptoAdapter` to generate a new random DEK → `decrypt_field()` throws `CryptoIntegrityError` → every sensitive memory is lost and `list_memories()` crashes.
   - *(Masked in `test_dual_db_storage_backup_api_and_windows.py:188`, which inserted the test sensitive memory with `is_encrypted=0`!)*
3. **[HIGH] Unbounded Argon2id KDF Header DoS & Missing Restore Route (`crypto.py:129-139`, `backup_service.py:165-226`):**
   - `decrypt_portable_backup()` reads untrusted `t`, `m`, `p` from the unauthenticated JSON header directly into `argon2.low_level.hash_secret_raw` with zero bounds (allows instant OOM DoS before GCM auth).
   - `restore_into_directory()` has **no HTTP endpoint**, decrypts the archive twice (double Argon2id + TOCTOU), overwrites `target_core_db_path` without closing live connections or clearing `-wal`/`-shm` sidecars, and defaults `preserve_local_tombstones=None`.
   - `POST /v1/backups/create` (`app.py:2332-2337`) accepts arbitrary unconfined `archive_path` and runs `staging.replace(dest_archive_path)` (arbitrary file overwrite).
4. **[HIGH] Unsafe Live-WAL Migration & Restart Reset (`storage_service.py:237-335`, `app.py:623-628`):**
   - `migrate_location()` copies `CORE_DB`/`KNOWLEDGE_DB` via `shutil.copy2()` (`L295`) while SQLite WAL connections are open (risk of torn/corrupt DB copy), never reopens `DualSqliteManager` on the new path, and Core restart unconditionally opens DBs at default `build_default_storage_roots()`.
5. **[HIGH] Non-Atomic SQL Migrations (`migrations.py:102-110`):**
   - Calls `conn.executescript(sql_text)` inside `with conn:`. In Python `sqlite3`, `executescript()` implicitly commits before running, leaving partial DDL applied if a statement fails mid-file.
   - Pre-migration backup (`dual_db.py:106-116`) only creates a plaintext SQLite copy (not encrypted as specified in `DEC-025`).
6. **[HIGH] Packaging Defect (`dual_db.py:21`, `config_service.py:31`):** Both `MIGRATIONS_BASE = Path(__file__).resolve().parents[2] / "migrations"` and `CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"` fail with `FileNotFoundError` when `jarvis-core` is installed as a wheel outside the git checkout (`pyproject.toml:55-56` packages only `packages = ["jarvis"]`).
7. **[MEDIUM] `PRAGMA integrity_check` on Every Health Check (`app.py:959-969`, `dual_db.py:119-125`):** `GET /v1/health` and `/v1/ready` run synchronous full `PRAGMA integrity_check` across both databases on Uvicorn's asyncio event loop.
