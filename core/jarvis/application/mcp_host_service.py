"""Hardened Opt-In MCP Host Service: Read-Only Pilot, Rug-Pull Quarantine, Kill Switch & BR-15 Tainting (B23, U-X01).

Strictly OS-independent (NFR-16): process/transport mechanics sit behind McpTransportPort.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from datetime import datetime
from typing import Any, Protocol
from urllib.parse import urlparse

from jarvis.application.context_service import ContextAssemblerService
from jarvis.domain.mcp import (
    McpPinnedToolRecord,
    McpServerRecord,
    McpServerRegistration,
    McpToolDescriptor,
    McpToolInvocationResult,
    compute_tool_schema_pin_sha256,
    format_namespaced_mcp_tool,
    is_prohibited_mcp_binary,
    is_prohibited_mcp_tool,
    sanitize_mcp_tool_output,
)
from jarvis.domain.models import ErrorCode, RiskClass, SessionContext, canonical_json_hash
from jarvis.domain.ports import ClockPort, SecretVaultAndCryptoPort
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class McpHostError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class McpTransportPort(Protocol):
    """Abstract MCP transport (local isolated stdio or reviewed read-only HTTPS)."""

    def discover_tools(
        self, server: McpServerRecord, *, timeout_ms: int
    ) -> tuple[McpToolDescriptor, ...]: ...

    def call_tool(
        self,
        server: McpServerRecord,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> Any: ...

    def close_server(self, server_id: str) -> bool: ...

    def close_all(self) -> int: ...


class McpHostService:
    """Manages opt-in MCP connectors with default-off registration, rug-pull quarantine, kill switch & BR-15 taint."""

    def __init__(
        self,
        db: DualSqliteManager,
        vault: SecretVaultAndCryptoPort,
        clock: ClockPort,
        event_bus: SequencedEventBus,
        *,
        context_service: ContextAssemblerService | None = None,
        transport: McpTransportPort | None = None,
    ) -> None:
        self._db = db
        self._vault = vault
        self._clock = clock
        self._bus = event_bus
        self._context = context_service
        self._transport = transport

    def bind_transport(self, transport: McpTransportPort) -> None:
        self._transport = transport

    def register_server(
        self,
        reg: McpServerRegistration,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> McpServerRecord:
        """Register an opt-in MCP server (starts DISABLED by default; blocks prohibited binaries & insecure HTTP)."""
        if reg.transport == "stdio":
            if is_prohibited_mcp_binary(reg.command_or_url):
                raise McpHostError(
                    ErrorCode.DENIED,
                    f"MCP stdio command '{reg.command_or_url}' is a prohibited R3 shell/LOLBin binary.",
                )
        elif reg.transport == "https_readonly":
            parsed = urlparse(reg.command_or_url.strip())
            if parsed.scheme.lower() != "https" or not parsed.hostname:
                raise McpHostError(
                    ErrorCode.DENIED,
                    "Remote MCP servers MUST use HTTPS/TLS and explicit read-only review.",
                )

        if reg.credential_vault_ref and self._vault.get_secret(reg.credential_vault_ref) is None:
            raise McpHostError(
                ErrorCode.NOT_FOUND,
                f"Credential vault ref '{reg.credential_vault_ref}' not found in OS Vault.",
            )

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO mcp_server(
                    id, display_name, version, transport, command_or_url, args_json,
                    trust_tier, data_destination, allowed_scopes_json, credential_vault_ref,
                    enabled, quarantined, quarantine_reason, schema_pin_sha256,
                    max_timeout_ms, max_output_bytes, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, NULL, NULL, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    display_name = excluded.display_name,
                    version = excluded.version,
                    transport = excluded.transport,
                    command_or_url = excluded.command_or_url,
                    args_json = excluded.args_json,
                    trust_tier = excluded.trust_tier,
                    data_destination = excluded.data_destination,
                    allowed_scopes_json = excluded.allowed_scopes_json,
                    credential_vault_ref = excluded.credential_vault_ref,
                    enabled = 0,
                    max_timeout_ms = excluded.max_timeout_ms,
                    max_output_bytes = excluded.max_output_bytes,
                    updated_at = excluded.updated_at
                """,
                (
                    reg.id,
                    reg.display_name,
                    reg.version,
                    reg.transport,
                    reg.command_or_url.strip(),
                    json.dumps(list(reg.args)),
                    reg.trust_tier,
                    reg.data_destination,
                    json.dumps(list(reg.allowed_scopes)),
                    reg.credential_vault_ref,
                    reg.max_timeout_ms,
                    reg.max_output_bytes,
                    now_iso,
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'mcp.server.registered', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"server_id": reg.id, "transport": reg.transport, "version": reg.version}),
                    now_iso,
                ),
            )
        return self.get_server(reg.id)

    def _load_pinned_tools(self, server_id: str) -> tuple[McpPinnedToolRecord, ...]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                "SELECT * FROM mcp_tool_pin WHERE server_id = ? ORDER BY tool_name ASC",
                (server_id,),
            ).fetchall()
        return tuple(
            McpPinnedToolRecord(
                server_id=str(r["server_id"]),
                tool_name=str(r["tool_name"]),
                namespaced_tool_id=str(r["namespaced_tool_id"]),
                description_sha256=str(r["description_sha256"]),
                input_schema_sha256=str(r["input_schema_sha256"]),
                risk_class=RiskClass(str(r["risk_class"])),
                read_only=bool(r["read_only"]),
                approved=bool(r["approved"]),
            )
            for r in rows
        )

    def _hydrate_server(self, r: Any) -> McpServerRecord:
        sid = str(r["id"])
        return McpServerRecord(
            id=sid,
            display_name=str(r["display_name"]),
            version=str(r["version"]),
            transport=str(r["transport"]),  # type: ignore[arg-type]
            command_or_url=str(r["command_or_url"]),
            args=tuple(json.loads(str(r["args_json"]))),
            trust_tier=str(r["trust_tier"]),  # type: ignore[arg-type]
            data_destination=str(r["data_destination"]),
            allowed_scopes=tuple(json.loads(str(r["allowed_scopes_json"]))),
            credential_vault_ref=str(r["credential_vault_ref"]) if r["credential_vault_ref"] else None,
            enabled=bool(r["enabled"]),
            quarantined=bool(r["quarantined"]),
            quarantine_reason=str(r["quarantine_reason"]) if r["quarantine_reason"] else None,
            schema_pin_sha256=str(r["schema_pin_sha256"]) if r["schema_pin_sha256"] else None,
            max_timeout_ms=int(r["max_timeout_ms"]),
            max_output_bytes=int(r["max_output_bytes"]),
            pinned_tools=self._load_pinned_tools(sid),
            updated_at=datetime.fromisoformat(str(r["updated_at"])),
        )

    def get_server(self, server_id: str) -> McpServerRecord:
        with self._db.core_read() as conn:
            row = conn.execute("SELECT * FROM mcp_server WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            raise McpHostError(ErrorCode.NOT_FOUND, f"MCP server '{server_id}' not found.")
        return self._hydrate_server(row)

    def list_servers(self) -> list[McpServerRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM mcp_server ORDER BY id ASC").fetchall()
        return [self._hydrate_server(r) for r in rows]

    def _quarantine_server(
        self, server_id: str, reason: str, *, correlation_id: str
    ) -> None:
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                UPDATE mcp_server
                SET enabled = 0, quarantined = 1, quarantine_reason = ?, updated_at = ?
                WHERE id = ?
                """,
                (reason, now_iso, server_id),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'mcp_host', 'mcp.server.quarantined', 'denied', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"server_id": server_id, "reason": reason}),
                    now_iso,
                ),
            )
        if self._transport is not None:
            self._transport.close_server(server_id)
        self._bus.publish(
            event_type="mcp.server.quarantined",
            correlation_id=correlation_id,
            payload={"server_id": server_id, "reason": reason},
        )

    def discover_and_pin_tools(
        self,
        server_id: str,
        *,
        correlation_id: str,
        allow_initial_pin: bool = True,
    ) -> McpServerRecord:
        """Discover server tools, reject prohibited R3 tools, pin SHA-256 on first review, and auto-quarantine rug-pulls!"""
        server = self.get_server(server_id)
        if self._transport is None:
            raise McpHostError(ErrorCode.RUNTIME_UNAVAILABLE, "No MCP transport is bound.")

        try:
            discovered = self._transport.discover_tools(server, timeout_ms=server.max_timeout_ms)
        except TimeoutError as exc:
            raise McpHostError(
                ErrorCode.RUNTIME_UNAVAILABLE, f"MCP tool discovery timed out for '{server_id}'."
            ) from exc
        except Exception as exc:
            raise McpHostError(ErrorCode.RUNTIME_UNAVAILABLE, f"MCP tool discovery failed: {exc}") from exc

        for tool in discovered:
            banned, ban_reason = is_prohibited_mcp_tool(tool)
            if banned:
                self._quarantine_server(server_id, ban_reason, correlation_id=correlation_id)
                raise McpHostError(ErrorCode.DENIED, ban_reason)

        new_pin = compute_tool_schema_pin_sha256(discovered)

        # Rug-pull detection (B23 / U-X01): if server already has a pin and hash changed -> AUTO-QUARANTINE!
        if server.schema_pin_sha256 is not None:
            if not hmac.compare_digest(server.schema_pin_sha256, new_pin):
                reason = (
                    f"MCP rug-pull detected on '{server_id}': tool description/schema SHA-256 changed "
                    f"({server.schema_pin_sha256[:12]} -> {new_pin[:12]}); server auto-quarantined."
                )
                self._quarantine_server(server_id, reason, correlation_id=correlation_id)
                raise McpHostError(ErrorCode.DENIED, reason)
            return self.get_server(server_id)

        if not allow_initial_pin:
            raise McpHostError(ErrorCode.DENIED, f"MCP server '{server_id}' has no reviewed schema pin.")

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                "UPDATE mcp_server SET schema_pin_sha256 = ?, updated_at = ? WHERE id = ?",
                (new_pin, now_iso, server_id),
            )
            conn.execute("DELETE FROM mcp_tool_pin WHERE server_id = ?", (server_id,))
            for tool in discovered:
                ns_id = format_namespaced_mcp_tool(server_id, tool.name)
                desc_sha = hashlib.sha256(tool.description.encode("utf-8")).hexdigest()
                schema_sha = canonical_json_hash(tool.input_schema)
                risk = RiskClass.R0 if tool.read_only else RiskClass.R2
                # Read-only pilot tools approved upon explicit owner review; mutating MCP tools stay unapproved!
                approved_flag = 1 if tool.read_only else 0
                conn.execute(
                    """
                    INSERT INTO mcp_tool_pin(
                        server_id, tool_name, namespaced_tool_id, description_sha256,
                        input_schema_sha256, risk_class, read_only, approved, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        server_id,
                        tool.name,
                        ns_id,
                        desc_sha,
                        schema_sha,
                        risk.value,
                        1 if tool.read_only else 0,
                        approved_flag,
                        now_iso,
                    ),
                )
        return self.get_server(server_id)

    def set_server_enabled(
        self, server_id: str, *, enabled: bool, correlation_id: str
    ) -> McpServerRecord:
        server = self.get_server(server_id)
        if enabled:
            if server.quarantined:
                raise McpHostError(
                    ErrorCode.DENIED,
                    f"Cannot enable quarantined MCP server '{server_id}': {server.quarantine_reason}",
                )
            if not server.schema_pin_sha256:
                raise McpHostError(
                    ErrorCode.DENIED,
                    f"Cannot enable MCP server '{server_id}' before tool schema discovery & SHA-256 pinning.",
                )
        else:
            if self._transport is not None:
                self._transport.close_server(server_id)

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                "UPDATE mcp_server SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now_iso, server_id),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'mcp.server.toggled', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"server_id": server_id, "enabled": enabled}),
                    now_iso,
                ),
            )
        return self.get_server(server_id)

    def invoke_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session: SessionContext,
        correlation_id: str,
    ) -> McpToolInvocationResult:
        """Invoke a pinned read-only MCP tool with rug-pull re-verification, timeout, sanitization & BR-15 taint."""
        if session.is_os_locked or session.is_suspended:
            raise McpHostError(ErrorCode.DENIED, "Session is locked; MCP tool invocation denied.")

        server = self.get_server(server_id)
        if server.quarantined or not server.enabled:
            raise McpHostError(
                ErrorCode.DENIED,
                f"MCP server '{server_id}' is disabled or quarantined.",
            )
        if server.transport == "https_readonly" and session.offline_mode:
            raise McpHostError(ErrorCode.OFFLINE, "Offline mode blocks remote HTTPS MCP connectors.")
        if self._transport is None:
            raise McpHostError(ErrorCode.RUNTIME_UNAVAILABLE, "No MCP transport is bound.")

        # Re-verify schema pin before invoking so mid-session rug-pulls are caught immediately!
        self.discover_and_pin_tools(server_id, correlation_id=correlation_id, allow_initial_pin=False)
        server = self.get_server(server_id)

        pin = next((p for p in server.pinned_tools if p.tool_name == tool_name), None)
        if pin is None:
            raise McpHostError(
                ErrorCode.DENIED, f"MCP tool '{tool_name}' is not pinned on server '{server_id}'."
            )
        if not pin.read_only or not pin.approved:
            raise McpHostError(
                ErrorCode.DENIED,
                f"MCP tool '{pin.namespaced_tool_id}' is not an approved read-only pilot capability.",
            )

        started = time.perf_counter()
        try:
            raw_result = self._transport.call_tool(
                server, tool_name, arguments, timeout_ms=server.max_timeout_ms
            )
        except TimeoutError as exc:
            self._transport.close_server(server_id)
            raise McpHostError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"MCP tool '{pin.namespaced_tool_id}' timed out after {server.max_timeout_ms}ms; server terminated.",
            ) from exc
        except Exception as exc:
            raise McpHostError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"MCP tool '{pin.namespaced_tool_id}' returned malformed/failed output: {exc}",
            ) from exc

        elapsed_ms = round((time.perf_counter() - started) * 1000.0, 2)
        wrapped, truncated, inj_warn = sanitize_mcp_tool_output(
            raw_result, max_bytes=server.max_output_bytes
        )

        # BR-15 / U-X01: ALWAYS taint the active session on any MCP output so malicious output cannot trigger native mutations!
        if self._context is not None:
            self._context.mark_session_untrusted_taint(session.session_id)

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'mcp.tool.invoked', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    session.actor_ref,
                    json.dumps(
                        {
                            "server_id": server_id,
                            "namespaced_tool_id": pin.namespaced_tool_id,
                            "truncated": truncated,
                            "injection_warning": inj_warn,
                            "elapsed_ms": elapsed_ms,
                        }
                    ),
                    self._clock.now_utc().isoformat(),
                ),
            )

        return McpToolInvocationResult(
            server_id=server_id,
            namespaced_tool_id=pin.namespaced_tool_id,
            ok=True,
            wrapped_untrusted_output=wrapped,
            truncated=truncated,
            injection_warning=inj_warn,
            elapsed_ms=elapsed_ms,
        )

    def kill_all_servers(self, *, correlation_id: str = "mcp-kill-switch") -> dict[str, int]:
        """Instant global MCP Kill Switch: disable all servers in DB and terminate all child transports (0 orphans)."""
        terminated = self._transport.close_all() if self._transport is not None else 0
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE mcp_server SET enabled = 0, updated_at = ? WHERE enabled = 1",
                (now_iso,),
            )
            disabled_count = cur.rowcount
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'mcp.kill_switch', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"disabled_servers": disabled_count, "terminated_processes": terminated}),
                    now_iso,
                ),
            )
        return {"disabled_servers": disabled_count, "terminated_processes": terminated}
