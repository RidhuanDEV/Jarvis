-- J.A.R.V.I.S. Core Database Expansion Migration 0004 (Stage G7 — B26 Optional Ecosystem Capability Packs)
-- Expand-Only additive tables for opt-in connector consent metadata and ephemeral OAuth 2.0 PKCE state.
-- Zero destructive DDL; secrets/tokens live strictly in OS Credential Vault (vault_ref only).

CREATE TABLE IF NOT EXISTS ecosystem_connector (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('web_search', 'home_assistant', 'oauth_calendar', 'oauth_mail')),
    display_name TEXT NOT NULL,
    endpoint_url TEXT NOT NULL,
    allowed_scopes_json TEXT NOT NULL,
    vault_ref TEXT NULL,
    tls_fingerprint_sha256 TEXT NOT NULL DEFAULT '',
    consent_acknowledged INTEGER NOT NULL DEFAULT 0 CHECK (consent_acknowledged IN (0, 1)),
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    revoked_at TEXT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_ecosystem_connector_kind ON ecosystem_connector(kind, enabled);

CREATE TABLE IF NOT EXISTS oauth_pkce_state (
    state_nonce TEXT PRIMARY KEY,
    connector_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('oauth_calendar', 'oauth_mail')),
    provider_name TEXT NOT NULL,
    authorize_url TEXT NOT NULL,
    token_url TEXT NOT NULL,
    api_base_url TEXT NOT NULL,
    redirect_uri TEXT NOT NULL,
    client_id TEXT NOT NULL,
    requested_scopes_json TEXT NOT NULL,
    code_verifier_hash TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    consumed_at TEXT NULL,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_oauth_pkce_state_expires ON oauth_pkce_state(expires_at);
