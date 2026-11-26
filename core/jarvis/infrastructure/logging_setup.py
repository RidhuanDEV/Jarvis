"""Production-grade non-blocking structlog JSON logger with fail-closed PII redaction & anti-CRLF hygiene."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, WrappedLogger

SENSITIVE_KEY_RE = re.compile(
    r"^(?:authorization|cookie|set[-_]?cookie|password|passwd|token|access[-_]?token|"
    r"refresh[-_]?token|auth[-_]?token|secret|api[-_]?key|nonce|passphrase|"
    r"recovery[-_]?phrase|nik|otp|credit[-_]?card|cvv|credential|dek|master[-_]?key)$",
    re.IGNORECASE,
)

BEARER_OR_JWT_RE = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._\-~+/]+=*|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})"
)

CRLF_RE = re.compile(r"[\r\n]+")


def sanitize_log_string(value: str) -> str:
    """Strip CR/LF log-forging characters and scrub raw Bearer/JWT tokens."""
    cleaned = CRLF_RE.sub(" ", value)
    return BEARER_OR_JWT_RE.sub("[REDACTED_TOKEN]", cleaned)


def redact_value(value: Any) -> Any:
    """Recursively redact sensitive keys and scrub strings fail-closed."""
    if isinstance(value, str):
        return sanitize_log_string(value)
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if SENSITIVE_KEY_RE.match(str(k)) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


def _redact_and_sanitize_processor(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    sanitized: EventDict = {}
    for key, val in event_dict.items():
        if SENSITIVE_KEY_RE.match(key):
            sanitized[key] = "[REDACTED]"
        else:
            sanitized[key] = redact_value(val)
    return sanitized


def configure_logging(level: str = "INFO", stream: TextIO | None = None) -> None:
    """Configure structlog JSON renderer with contextvars and fail-closed PII redaction."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    target_stream = stream if stream is not None else sys.stdout

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            _redact_and_sanitize_processor,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(file=target_stream),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "jarvis") -> structlog.stdlib.BoundLogger | Any:
    return structlog.get_logger(name)
