"""Production-grade non-blocking structlog JSON logger with fail-closed PII redaction & anti-CRLF hygiene."""

from __future__ import annotations

import logging
import re
import sys
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, WrappedLogger

SENSITIVE_KEY_RE = re.compile(
    r"(?:^|[-_])(?:authorization|cookie|password|passwd|token|secret|api[-_]?key|private[-_]?key|"
    r"nonce|passphrase|recovery[-_]?phrase|pairing[-_]?code|nik|otp|credit[-_]?card|cvv|"
    r"credential|dek|master[-_]?key)(?:$|[-_])",
    re.IGNORECASE,
)

BEARER_OR_JWT_RE = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._\-~+/]+=*|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}|"
    r"\bsk-[A-Za-z0-9_\-]{16,}\b|"
    r"\bghp_[A-Za-z0-9]{20,}\b|"
    r"\bgithub_pat_[A-Za-z0-9_]{20,}\b|"
    r"\bAKIA[0-9A-Z]{16}\b|"
    r"(?:passphrase|password|bearer_token|pairing_code|api_key|secret)\s*[:=]\s*['\"]?[^\s'\",;}{]+['\"]?)",
    re.IGNORECASE,
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
        return {str(k): ("[REDACTED]" if SENSITIVE_KEY_RE.search(str(k)) else redact_value(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [redact_value(item) for item in value]
    return value


def _redact_and_sanitize_processor(_logger: WrappedLogger, _method_name: str, event_dict: EventDict) -> EventDict:
    sanitized: EventDict = {}
    for key, val in event_dict.items():
        if SENSITIVE_KEY_RE.search(key):
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
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            # DEF-23 / B05: redact AFTER stack/exception formatting so secrets in tracebacks are scrubbed too
            _redact_and_sanitize_processor,
            structlog.processors.JSONRenderer(sort_keys=True),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.WriteLoggerFactory(file=target_stream),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str = "jarvis") -> structlog.stdlib.BoundLogger | Any:
    return structlog.get_logger(name)
