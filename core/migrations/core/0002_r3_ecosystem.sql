-- J.A.R.V.I.S. Core Database Expansion Migration 0002 (Phase 5 — R3 Ecosystem)
-- Expand-Only additive tables for Home Assistant allowlist, separate private remote gateway,
-- and local adaptive preference proposals. Zero destructive DDL.

CREATE TABLE IF NOT EXISTS ha_entity_allowlist (
    entity_id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    friendly_name TEXT NOT NULL,
    allowed_actions_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    added_at TEXT NOT NULL,
    revoked_at TEXT NULL
);

CREATE TABLE IF NOT EXISTS remote_gateway_config (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    bind_address TEXT NOT NULL,
    bind_port INTEGER NOT NULL CHECK (bind_port BETWEEN 1024 AND 65535),
    tls_cert_fingerprint_sha256 TEXT NOT NULL,
    rate_limit_per_minute INTEGER NOT NULL DEFAULT 30 CHECK (rate_limit_per_minute BETWEEN 1 AND 120),
    host_available INTEGER NOT NULL DEFAULT 1 CHECK (host_available IN (0, 1)),
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remote_pairing_challenge (
    id TEXT PRIMARY KEY,
    device_label TEXT NOT NULL,
    device_fingerprint TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'approved', 'rejected', 'expired')),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS remote_device_token (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES device(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    scopes_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    revoked_at TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_remote_device_token_device ON remote_device_token(device_id);

CREATE TABLE IF NOT EXISTS preference_proposal (
    id TEXT PRIMARY KEY,
    preference_key TEXT NOT NULL,
    proposed_value_json TEXT NOT NULL,
    rationale TEXT NOT NULL,
    evidence_count INTEGER NOT NULL CHECK (evidence_count >= 1),
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected', 'dismissed')),
    created_at TEXT NOT NULL,
    decided_at TEXT NULL
);
