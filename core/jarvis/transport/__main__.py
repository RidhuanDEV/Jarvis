"""Entrypoint for J.A.R.V.I.S. local Core daemon (binds strictly to 127.0.0.1 with inherited auth token)."""

from __future__ import annotations

import os
import sys

import uvicorn

from jarvis.transport.app import build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings


def _read_inherited_token_from_stdin_if_requested() -> str | None:
    """Read per-run 256-bit auth token via inherited pipe (T07/09-SECURITY-PRIVACY §3), never CLI args."""
    if os.environ.get("JARVIS_TOKEN_FROM_STDIN") == "1":
        line = sys.stdin.readline().strip()
        if line:
            return line
    return None


def main() -> None:
    token_override = _read_inherited_token_from_stdin_if_requested()
    settings = CoreStartupSettings(auth_token=token_override) if token_override is not None else CoreStartupSettings()
    container = build_default_container(settings)
    app = create_app(container)
    uvicorn.run(
        app,
        host=settings.bind_host,
        port=settings.bind_port if settings.bind_port > 0 else 47123,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
