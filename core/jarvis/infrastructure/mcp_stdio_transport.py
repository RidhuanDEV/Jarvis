"""Isolated Local JSON-RPC 2.0 Stdio MCP Transport with Stripped Env, Deadline Timeout & Zero-Orphan Teardown (B23).

- Spawns local stdio MCP servers with build_stripped_mcp_env() (NEVER inherits JARVIS_AUTH_TOKEN or ambient secrets!).
- Enforces strict per-call wall-clock timeout and bounded stdout line size.
- Terminates managed child processes cleanly on timeout, quarantine, kill switch, or Core shutdown.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any

from jarvis.domain.mcp import McpServerRecord, McpToolDescriptor, build_stripped_mcp_env


class McpStdioTransport:
    """Bounded local JSON-RPC 2.0 over stdio transport for opt-in read-only MCP pilot servers."""

    MAX_LINE_BYTES = 256 * 1024

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._procs: dict[str, subprocess.Popen[bytes]] = {}
        self._req_id = 0

    def _ensure_process(self, server: McpServerRecord) -> subprocess.Popen[bytes]:
        with self._lock:
            existing = self._procs.get(server.id)
            if existing is not None and existing.poll() is None:
                return existing

            env = build_stripped_mcp_env(system_root=os.environ.get("SYSTEMROOT"))
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            proc = subprocess.Popen(  # noqa: S603
                [server.command_or_url, *server.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                env=env,
                creationflags=creationflags,
            )
            self._procs[server.id] = proc
            return proc

    def _rpc(
        self,
        server: McpServerRecord,
        method: str,
        params: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> dict[str, Any]:
        proc = self._ensure_process(server)
        if proc.stdin is None or proc.stdout is None:
            raise RuntimeError("MCP stdio pipes unavailable.")

        with self._lock:
            self._req_id += 1
            req_id = self._req_id
            payload = (
                json.dumps({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}) + "\n"
            ).encode("utf-8")
            proc.stdin.write(payload)
            proc.stdin.flush()

            result_q: queue.Queue[bytes | Exception] = queue.Queue(maxsize=1)

            def _read_line() -> None:
                try:
                    assert proc.stdout is not None
                    line = proc.stdout.readline(self.MAX_LINE_BYTES + 1)
                    result_q.put(line)
                except Exception as exc:  # pragma: no cover
                    result_q.put(exc)

            reader = threading.Thread(target=_read_line, daemon=True)
            reader.start()
            try:
                raw_item = result_q.get(timeout=max(0.2, timeout_ms / 1000.0))
            except queue.Empty as exc:
                self.close_server(server.id)
                raise TimeoutError(f"MCP stdio server '{server.id}' timed out on '{method}'.") from exc

            if isinstance(raw_item, Exception):
                raise raw_item
            if not raw_item:
                self.close_server(server.id)
                raise RuntimeError(f"MCP stdio server '{server.id}' closed stdout unexpectedly.")
            if len(raw_item) > self.MAX_LINE_BYTES:
                self.close_server(server.id)
                raise RuntimeError("MCP stdio response exceeded maximum frame limit.")

            parsed = json.loads(raw_item.decode("utf-8"))
            if not isinstance(parsed, dict):
                raise RuntimeError("Malformed MCP JSON-RPC response (non-object).")
            if "error" in parsed and parsed["error"] is not None:
                raise RuntimeError(f"MCP JSON-RPC error: {parsed['error']}")
            res = parsed.get("result")
            if not isinstance(res, dict):
                raise RuntimeError("Malformed MCP JSON-RPC result payload.")
            return res

    def discover_tools(
        self, server: McpServerRecord, *, timeout_ms: int
    ) -> tuple[McpToolDescriptor, ...]:
        res = self._rpc(server, "tools/list", {}, timeout_ms=timeout_ms)
        raw_tools = res.get("tools", [])
        if not isinstance(raw_tools, list):
            raise RuntimeError("Malformed MCP tools/list response.")
        return tuple(
            McpToolDescriptor(
                name=str(item["name"]),
                description=str(item.get("description", "")),
                input_schema=dict(item.get("inputSchema", {})),
                read_only=bool(item.get("readOnly", item.get("annotations", {}).get("readOnlyHint", True))),
            )
            for item in raw_tools
            if isinstance(item, dict) and "name" in item
        )

    def call_tool(
        self,
        server: McpServerRecord,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_ms: int,
    ) -> Any:
        res = self._rpc(
            server,
            "tools/call",
            {"name": tool_name, "arguments": arguments},
            timeout_ms=timeout_ms,
        )
        return res.get("content", res)

    def close_server(self, server_id: str) -> bool:
        with self._lock:
            proc = self._procs.pop(server_id, None)
        if proc is None:
            return False
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=2.0)
        return True

    def close_all(self) -> int:
        with self._lock:
            ids = list(self._procs.keys())
        closed = 0
        for sid in ids:
            if self.close_server(sid):
                closed += 1
        return closed
