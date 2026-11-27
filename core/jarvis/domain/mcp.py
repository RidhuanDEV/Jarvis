"""Pure-Domain Hardened MCP Host Contracts, Rug-Pull Pinning & Stripped-Env Guards (B23, DEC-024, NFR-16).

Strictly OS-independent. Enforces:
- Canonical `mcp.<server_id>.<tool_name>` namespacing.
- SHA-256 schema + description pinning to auto-quarantine rug-pull mutations.
- Hard R3 denial for shell/delete/destructive MCP server commands or tools.
- Stripped child process environment (NEVER inherits JARVIS_AUTH_TOKEN or ambient secrets).
- Untrusted output sanitization & delimiter escaping (BR-15).
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from jarvis.domain.app_catalog import TIER3_PROHIBITED_BINARIES
from jarvis.domain.models import RiskClass, StrictModel, canonical_json_hash

_PROHIBITED_MCP_TOOL_KEYWORDS: tuple[str, ...] = (
    "delete",
    "remove_file",
    "unlink",
    "rmdir",
    "shred",
    "wipe",
    "format",
    "shell",
    "exec_cmd",
    "run_command",
    "powershell",
    "bash",
    "registry_write",
    "credential_dump",
    "send_email",
    "transfer_payment",
)

_MCP_BREAKOUT_RE = re.compile(
    r"</?\s*untrusted_(?:mcp|document)_data\s*>",
    re.IGNORECASE,
)

_PROMPT_INJECTION_HINT_RE = re.compile(
    r"\b(?:ignore\s+(?:all\s+)?previous\s+instructions|system\s+override|execute\s+shell|delete\s+all\s+files|call\s+os\.volume\.set)\b",
    re.IGNORECASE,
)


class McpServerRegistration(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{1,48}$")
    display_name: str = Field(min_length=2, max_length=128)
    version: str = Field(min_length=1, max_length=32)
    transport: Literal["stdio", "https_readonly"]
    command_or_url: str = Field(min_length=2, max_length=512)
    args: tuple[str, ...] = ()
    trust_tier: Literal["trusted_local", "reviewed_readonly", "untrusted"] = "reviewed_readonly"
    data_destination: str = Field(default="local_only", min_length=2, max_length=128)
    allowed_scopes: tuple[str, ...] = ("read_only",)
    credential_vault_ref: str | None = None
    max_timeout_ms: int = Field(default=5000, ge=500, le=30000)
    max_output_bytes: int = Field(default=32768, ge=1024, le=131072)


class McpToolDescriptor(StrictModel):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{1,64}$")
    description: str = Field(default="", max_length=2000)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    read_only: bool = True


class McpPinnedToolRecord(StrictModel):
    server_id: str
    tool_name: str
    namespaced_tool_id: str
    description_sha256: str
    input_schema_sha256: str
    risk_class: RiskClass
    read_only: bool
    approved: bool


class McpServerRecord(StrictModel):
    id: str
    display_name: str
    version: str
    transport: Literal["stdio", "https_readonly"]
    command_or_url: str
    args: tuple[str, ...]
    trust_tier: Literal["trusted_local", "reviewed_readonly", "untrusted"]
    data_destination: str
    allowed_scopes: tuple[str, ...]
    credential_vault_ref: str | None
    enabled: bool
    quarantined: bool
    quarantine_reason: str | None
    schema_pin_sha256: str | None
    max_timeout_ms: int
    max_output_bytes: int
    pinned_tools: tuple[McpPinnedToolRecord, ...] = ()
    updated_at: datetime


class McpToolInvocationResult(StrictModel):
    server_id: str
    namespaced_tool_id: str
    ok: bool
    wrapped_untrusted_output: str
    truncated: bool
    injection_warning: bool
    session_tainted: Literal[True] = True
    elapsed_ms: float


def format_namespaced_mcp_tool(server_id: str, tool_name: str) -> str:
    return f"mcp.{server_id.strip().lower()}.{tool_name.strip().lower()}"


def is_prohibited_mcp_binary(command_path: str) -> bool:
    """Block shells, interpreters used as LOLBins, and destructive OS binaries as raw MCP server commands."""
    base = command_path.replace("\\", "/").rsplit("/", 1)[-1].strip().lower()
    return base in TIER3_PROHIBITED_BINARIES


def is_prohibited_mcp_tool(tool: McpToolDescriptor) -> tuple[bool, str]:
    """Reject MCP tools advertising R3 destructive/shell/exfiltration capabilities."""
    haystack = f"{tool.name} {tool.description}".casefold()
    for kw in _PROHIBITED_MCP_TOOL_KEYWORDS:
        if kw in haystack:
            return (True, f"MCP tool '{tool.name}' matches prohibited R3 capability keyword '{kw}'.")
    return (False, "")


def compute_tool_schema_pin_sha256(tools: tuple[McpToolDescriptor, ...]) -> str:
    """Deterministic SHA-256 fingerprint over sorted MCP tool names, descriptions, schemas, and read_only flags."""
    canonical_items = [
        {
            "name": t.name,
            "description_sha256": hashlib.sha256(t.description.encode("utf-8")).hexdigest(),
            "input_schema_sha256": canonical_json_hash(t.input_schema),
            "read_only": t.read_only,
        }
        for t in sorted(tools, key=lambda item: item.name)
    ]
    return canonical_json_hash({"tools": canonical_items})


def sanitize_mcp_tool_output(
    raw_output: Any, *, max_bytes: int = 32768
) -> tuple[str, bool, bool]:
    """Bound, escape, and wrap untrusted MCP tool output for BR-15 prompt-injection defense (U-X01)."""
    text = raw_output if isinstance(raw_output, str) else json.dumps(raw_output, ensure_ascii=False, sort_keys=True)

    encoded = text.encode("utf-8", errors="replace")
    truncated = len(encoded) > max_bytes
    if truncated:
        text = encoded[:max_bytes].decode("utf-8", errors="ignore") + "\n[TRUNCATED_BY_HOST_LIMIT]"

    injection_warning = bool(_PROMPT_INJECTION_HINT_RE.search(text))
    escaped = _MCP_BREAKOUT_RE.sub("[ESCAPED_TAG]", text)
    wrapped = (
        "<untrusted_mcp_data>\n"
        f"{escaped}\n"
        "</untrusted_mcp_data>"
    )
    return (wrapped, truncated, injection_warning)


def build_stripped_mcp_env(
    explicit_vault_secrets: dict[str, str] | None = None,
    *,
    system_root: str | None = None,
) -> dict[str, str]:
    """Construct a minimal, stripped child-process environment for stdio MCP servers (NEVER inherits ambient tokens!)."""
    env: dict[str, str] = {
        "PYTHONUNBUFFERED": "1",
        "PYTHONNOUSERSITE": "1",
        "NO_PROXY": "*",
    }
    if system_root:
        env["SYSTEMROOT"] = system_root
    if explicit_vault_secrets:
        for k, v in explicit_vault_secrets.items():
            clean_k = k.strip().upper()
            if clean_k.startswith("JARVIS_"):
                continue
            env[clean_k] = v
    return env
