-- J.A.R.V.I.S. Core Database Expansion Migration 0003 (Stage G6 — B23 Hardened Opt-In MCP Host)
-- Expand-Only additive tables for MCP server registry, schema rug-pull SHA-256 pinning, and quarantine state.

CREATE TABLE IF NOT EXISTS mcp_server (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    version TEXT NOT NULL,
    transport TEXT NOT NULL CHECK (transport IN ('stdio', 'https_readonly')),
    command_or_url TEXT NOT NULL,
    args_json TEXT NOT NULL DEFAULT '[]',
    trust_tier TEXT NOT NULL CHECK (trust_tier IN ('trusted_local', 'reviewed_readonly', 'untrusted')),
    data_destination TEXT NOT NULL,
    allowed_scopes_json TEXT NOT NULL DEFAULT '[]',
    credential_vault_ref TEXT NULL,
    enabled INTEGER NOT NULL DEFAULT 0 CHECK (enabled IN (0, 1)),
    quarantined INTEGER NOT NULL DEFAULT 0 CHECK (quarantined IN (0, 1)),
    quarantine_reason TEXT NULL,
    schema_pin_sha256 TEXT NULL,
    max_timeout_ms INTEGER NOT NULL DEFAULT 5000 CHECK (max_timeout_ms BETWEEN 500 AND 30000),
    max_output_bytes INTEGER NOT NULL DEFAULT 32768 CHECK (max_output_bytes BETWEEN 1024 AND 131072),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS mcp_tool_pin (
    server_id TEXT NOT NULL REFERENCES mcp_server(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    namespaced_tool_id TEXT NOT NULL UNIQUE,
    description_sha256 TEXT NOT NULL,
    input_schema_sha256 TEXT NOT NULL,
    risk_class TEXT NOT NULL CHECK (risk_class IN ('R0', 'R1', 'R2')),
    read_only INTEGER NOT NULL DEFAULT 1 CHECK (read_only IN (0, 1)),
    approved INTEGER NOT NULL DEFAULT 0 CHECK (approved IN (0, 1)),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (server_id, tool_name)
);

CREATE INDEX IF NOT EXISTS idx_mcp_tool_pin_server ON mcp_tool_pin(server_id);
