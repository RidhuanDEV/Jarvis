-- J.A.R.V.I.S. Core Database Initial Schema (v0.2.1)
-- Authoritative transactional store (jarvis_core.db)
-- Requires PRAGMA foreign_keys = ON and journal_mode = WAL per connection.

CREATE TABLE IF NOT EXISTS config_revision (
    revision INTEGER PRIMARY KEY AUTOINCREMENT,
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    config_json TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('onboarding', 'user', 'rollback')),
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    previous_healthy_revision INTEGER NULL REFERENCES config_revision(revision),
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_config_revision_active
    ON config_revision(is_active) WHERE is_active = 1;

CREATE TABLE IF NOT EXISTS storage_location (
    category TEXT PRIMARY KEY CHECK (category IN (
        'app_data', 'models', 'runtimes', 'core_db', 'knowledge_db',
        'logs', 'temp', 'cache', 'backups', 'imported_docs', 'extensions'
    )),
    resolved_path TEXT NOT NULL,
    quota_bytes INTEGER NULL CHECK (quota_bytes IS NULL OR quota_bytes >= 0),
    is_removable INTEGER NOT NULL DEFAULT 0 CHECK (is_removable IN (0, 1)),
    filesystem_kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('healthy', 'degraded', 'migrating', 'offline', 'blocked')),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS hardware_snapshot (
    id TEXT PRIMARY KEY,
    os_info_json TEXT NOT NULL,
    cpu_json TEXT NOT NULL,
    ram_bytes INTEGER NOT NULL CHECK (ram_bytes > 0),
    gpus_json TEXT NOT NULL,
    displays_json TEXT NOT NULL,
    audio_json TEXT NOT NULL,
    power_state TEXT NOT NULL,
    captured_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS session (
    id TEXT PRIMARY KEY,
    channel TEXT NOT NULL CHECK (channel IN ('local', 'remote')),
    actor_ref TEXT NOT NULL,
    started_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    ended_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES session(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system', 'tool')),
    content_cipher_or_text TEXT NOT NULL,
    is_encrypted INTEGER NOT NULL DEFAULT 0 CHECK (is_encrypted IN (0, 1)),
    expires_at TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_message_session_id ON message(session_id);

CREATE TABLE IF NOT EXISTS request (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL UNIQUE,
    actor_ref TEXT NOT NULL,
    channel TEXT NOT NULL CHECK (channel IN ('local', 'remote')),
    state TEXT NOT NULL CHECK (state IN (
        'received', 'planning', 'awaiting_approval', 'executing',
        'completed', 'partial', 'failed', 'canceled', 'unknown'
    )),
    created_at TEXT NOT NULL,
    deadline_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_run (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL REFERENCES request(id) ON DELETE CASCADE,
    tool_id TEXT NOT NULL,
    tool_version INTEGER NOT NULL CHECK (tool_version >= 1),
    canonical_args_hash TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN (
        'pending', 'awaiting_approval', 'running', 'completed',
        'partial', 'failed', 'canceled', 'unknown'
    )),
    idempotency_key TEXT NOT NULL UNIQUE,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    outcome_code TEXT NULL,
    verified INTEGER NOT NULL DEFAULT 0 CHECK (verified IN (0, 1)),
    redacted_summary TEXT NULL,
    started_at TEXT NULL,
    finished_at TEXT NULL
);

CREATE INDEX IF NOT EXISTS idx_action_run_request_id ON action_run(request_id);

CREATE TABLE IF NOT EXISTS approval (
    id TEXT PRIMARY KEY,
    action_run_id TEXT NOT NULL UNIQUE REFERENCES action_run(id) ON DELETE CASCADE,
    nonce_hash TEXT NOT NULL UNIQUE,
    bound_hash TEXT NOT NULL,
    actor_ref TEXT NOT NULL,
    session_ref TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected', 'expired', 'canceled'))
);

CREATE INDEX IF NOT EXISTS idx_approval_state_expires ON approval(state, expires_at);

CREATE TABLE IF NOT EXISTS grant (
    id TEXT PRIMARY KEY,
    subject_type TEXT NOT NULL CHECK (subject_type IN ('local_owner', 'device', 'extension')),
    subject_id TEXT NOT NULL,
    capability TEXT NOT NULL,
    scope_json TEXT NOT NULL,
    expires_at TEXT NULL,
    revoked_at TEXT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE INDEX IF NOT EXISTS idx_grant_subject_cap ON grant(subject_type, subject_id, capability);

CREATE TABLE IF NOT EXISTS audit_event (
    id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    action_run_id TEXT NULL REFERENCES action_run(id) ON DELETE SET NULL,
    actor TEXT NOT NULL,
    event_type TEXT NOT NULL,
    outcome TEXT NOT NULL,
    redacted_meta_json TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_event_ts ON audit_event(timestamp);
CREATE INDEX IF NOT EXISTS idx_audit_event_corr ON audit_event(correlation_id);

CREATE TABLE IF NOT EXISTS memory (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('fact', 'preference', 'instruction', 'note')),
    content TEXT NOT NULL,
    is_encrypted INTEGER NOT NULL DEFAULT 0 CHECK (is_encrypted IN (0, 1)),
    sensitivity TEXT NOT NULL CHECK (sensitivity IN ('normal', 'sensitive')),
    source_ref TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'proposal', 'superseded')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS memory_revision (
    id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    change_reason TEXT NOT NULL,
    timestamp TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS deletion_ledger (
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    UNIQUE(entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS source_root (
    id TEXT PRIMARY KEY,
    canonical_path TEXT NOT NULL UNIQUE,
    scope_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    revoked_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS workflow (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    trigger_json TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
    next_due_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS reminder (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_at_utc TEXT NOT NULL,
    timezone_iana TEXT NOT NULL,
    recurrence_json TEXT NULL,
    state TEXT NOT NULL CHECK (state IN ('scheduled', 'snoozed', 'delivered', 'dismissed', 'missed')),
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS job (
    id TEXT PRIMARY KEY,
    workflow_id TEXT NULL REFERENCES workflow(id) ON DELETE CASCADE,
    reminder_id TEXT NULL REFERENCES reminder(id) ON DELETE CASCADE,
    due_at_utc TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'leased', 'completed', 'failed', 'canceled', 'unknown')),
    lease_until TEXT NULL,
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    idempotency_key TEXT NOT NULL UNIQUE,
    payload_min_json TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE INDEX IF NOT EXISTS idx_job_due_state ON job(state, due_at_utc);

CREATE TABLE IF NOT EXISTS delivery (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES job(id) ON DELETE CASCADE,
    channel TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'delivered', 'suppressed_quiet_hours', 'failed')),
    dedup_key TEXT NOT NULL UNIQUE,
    delivered_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS task (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    due_at_utc TEXT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'completed', 'canceled')),
    completed_at TEXT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS calendar_event (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    start_at_utc TEXT NOT NULL,
    end_at_utc TEXT NOT NULL CHECK (end_at_utc > start_at_utc),
    timezone_iana TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK (source_kind IN ('local', 'ics', 'external_read')),
    external_ref TEXT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS expense (
    id TEXT PRIMARY KEY,
    amount_minor INTEGER NOT NULL CHECK (amount_minor > 0),
    currency_iso TEXT NOT NULL CHECK (length(currency_iso) = 3),
    kind TEXT NOT NULL CHECK (kind IN ('expense', 'refund')),
    category TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL,
    notes TEXT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS habit_log (
    id TEXT PRIMARY KEY,
    habit_key TEXT NOT NULL,
    local_date TEXT NOT NULL,
    timezone_iana TEXT NOT NULL,
    value REAL NOT NULL,
    unit TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1)
);

CREATE TABLE IF NOT EXISTS device (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    paired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS model_provider (
    id TEXT PRIMARY KEY,
    adapter_kind TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    ownership_mode TEXT NOT NULL CHECK (ownership_mode IN (
        'managed_local', 'external_local', 'authorized_lan', 'custom_compatible'
    )),
    trust_zone TEXT NOT NULL CHECK (trust_zone IN ('local_device', 'private_lan', 'custom_isolated')),
    endpoint_ref TEXT NOT NULL,
    credential_vault_ref TEXT NULL,
    capabilities_json TEXT NOT NULL,
    support_tier TEXT NOT NULL CHECK (support_tier IN ('Supported', 'Experimental', 'Unverified', 'Unsupported')),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    last_probe_at TEXT NULL,
    health_code TEXT NOT NULL DEFAULT 'unknown'
);

CREATE TABLE IF NOT EXISTS model_manifest (
    id TEXT PRIMARY KEY,
    provider_id TEXT NOT NULL REFERENCES model_provider(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('llm', 'stt', 'tts', 'embedding', 'vision', 'wake', 'reranker')),
    family TEXT NOT NULL,
    revision TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size > 0),
    storage_ref TEXT NULL,
    is_shared_external_file INTEGER NOT NULL DEFAULT 0 CHECK (is_shared_external_file IN (0, 1)),
    format TEXT NOT NULL,
    license_spdx TEXT NOT NULL CHECK (lower(license_spdx) NOT IN ('unknown', '')),
    model_card_ref TEXT NULL,
    dataset_license_note TEXT NULL,
    capability_json TEXT NOT NULL,
    resource_estimate_json TEXT NOT NULL,
    approval_state TEXT NOT NULL CHECK (approval_state IN ('pending', 'approved', 'rejected', 'revoked')),
    verified_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS ai_profile (
    id TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 1),
    mode TEXT NOT NULL CHECK (mode IN ('direct', 'eco', 'performance', 'balanced', 'quality', 'adaptive', 'custom')),
    role_bindings_json TEXT NOT NULL,
    runtime_knobs_json TEXT NOT NULL,
    resource_limits_json TEXT NOT NULL,
    fallback_allowlist_json TEXT NOT NULL,
    PRIMARY KEY (id, revision)
);

CREATE TABLE IF NOT EXISTS active_ai_profile (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    profile_id TEXT NOT NULL,
    profile_revision INTEGER NOT NULL,
    previous_healthy_profile_id TEXT NULL,
    previous_healthy_revision INTEGER NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (profile_id, profile_revision) REFERENCES ai_profile(id, revision)
);

CREATE TABLE IF NOT EXISTS model_benchmark (
    id TEXT PRIMARY KEY,
    manifest_id TEXT NOT NULL REFERENCES model_manifest(id) ON DELETE CASCADE,
    provider_id TEXT NOT NULL REFERENCES model_provider(id) ON DELETE CASCADE,
    hardware_snapshot_id TEXT NOT NULL REFERENCES hardware_snapshot(id) ON DELETE CASCADE,
    settings_hash TEXT NOT NULL,
    corpus_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS license_artifact (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL CHECK (category IN (
        'app_package', 'native_library', 'ai_runtime', 'model_weights',
        'training_dataset', 'voice_asset', 'wake_model', 'font',
        'icon_set', 'audio_sfx', 'ui_asset'
    )),
    name TEXT NOT NULL,
    version_or_rev TEXT NOT NULL,
    license_spdx TEXT NOT NULL CHECK (lower(license_spdx) NOT IN ('unknown', '')),
    obligations_json TEXT NOT NULL,
    source_url TEXT NOT NULL,
    notice_text TEXT NOT NULL,
    verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS extension_package (
    id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    sdk_version TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    capabilities_requested_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    installed_at TEXT NOT NULL
);
