"""Pure Domain Guards for Read-Only OAuth 2.0 PKCE Calendar/Email Connectors (Stage G7, B26, FR-LIF-04).

Zero OS, network, or database imports (strictly enforced by NFR-16).
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlparse

from jarvis.domain.models import ErrorCode
from jarvis.domain.security_guards import validate_outbound_url_syntax

# Strict read-only scope allowlist (FR-LIF-04): NEVER allow send, write, delete, modify, or wildcard scopes!
OAUTH_READONLY_CALENDAR_SCOPES: frozenset[str] = frozenset(
    {
        "calendar.readonly",
        "calendars.read",
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/calendar.events.readonly",
    }
)

OAUTH_READONLY_MAIL_SCOPES: frozenset[str] = frozenset(
    {
        "mail.readonly",
        "mail.read",
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/gmail.metadata",
    }
)

OAUTH_ALL_READONLY_SCOPES: frozenset[str] = OAUTH_READONLY_CALENDAR_SCOPES | OAUTH_READONLY_MAIL_SCOPES

_FORBIDDEN_SCOPE_SUBSTRINGS: tuple[str, ...] = (
    "write",
    "send",
    "delete",
    "modify",
    "compose",
    "admin",
    "full",
    "manage",
    "*",
)


@dataclass(frozen=True)
class OAuthScopeVerdict:
    allowed: bool
    normalized_scopes: tuple[str, ...]
    reason: str
    error_code: ErrorCode | None = None


def generate_pkce_verifier(length: int = 64) -> str:
    """Generate RFC 7636 high-entropy code_verifier (43..128 URL-safe chars)."""
    bounded = max(43, min(128, length))
    raw = secrets.token_urlsafe(bounded)
    return raw[:bounded]


def compute_pkce_s256_challenge(code_verifier: str) -> str:
    """Compute RFC 7636 BASE64URL-ENCODE(SHA256(ASCII(code_verifier))) without padding."""
    if not (43 <= len(code_verifier) <= 128):
        raise ValueError("PKCE code_verifier must be 43..128 characters (RFC 7636).")
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def hash_pkce_verifier(code_verifier: str) -> str:
    return hashlib.sha256(code_verifier.encode("ascii")).hexdigest()


def validate_readonly_oauth_scopes(
    scopes: tuple[str, ...], *, connector_kind: str
) -> OAuthScopeVerdict:
    """Enforce FR-LIF-04 strict read-only calendar/email scopes; block any write/send/delete escalation."""
    if not scopes:
        return OAuthScopeVerdict(
            allowed=False,
            normalized_scopes=(),
            reason="At least one read-only OAuth scope is required (FR-LIF-04).",
            error_code=ErrorCode.INVALID_ARGS,
        )

    allowed_set = (
        OAUTH_READONLY_CALENDAR_SCOPES
        if connector_kind == "oauth_calendar"
        else OAUTH_READONLY_MAIL_SCOPES
        if connector_kind == "oauth_mail"
        else OAUTH_ALL_READONLY_SCOPES
    )

    normalized: list[str] = []
    for raw in scopes:
        sc = raw.strip()
        sc_low = sc.lower()
        if not sc:
            return OAuthScopeVerdict(
                allowed=False,
                normalized_scopes=(),
                reason="Empty OAuth scope is invalid.",
                error_code=ErrorCode.INVALID_ARGS,
            )
        if any(bad in sc_low for bad in _FORBIDDEN_SCOPE_SUBSTRINGS):
            return OAuthScopeVerdict(
                allowed=False,
                normalized_scopes=(),
                reason=f"Write/send/delete OAuth scope '{sc}' is prohibited; connector is strictly read-only (FR-LIF-04).",
                error_code=ErrorCode.DENIED,
            )
        if sc_low not in allowed_set:
            return OAuthScopeVerdict(
                allowed=False,
                normalized_scopes=(),
                reason=f"OAuth scope '{sc}' is outside the strict read-only allowlist for '{connector_kind}' (FR-LIF-04).",
                error_code=ErrorCode.DENIED,
            )
        if sc not in normalized:
            normalized.append(sc)

    return OAuthScopeVerdict(
        allowed=True,
        normalized_scopes=tuple(normalized),
        reason="All requested OAuth scopes are strictly read-only.",
    )


def validate_oauth_loopback_redirect_uri(redirect_uri: str) -> tuple[bool, str]:
    """Enforce RFC 8252 native desktop loopback redirect URI (`http://127.0.0.1:<port>/callback`)."""
    parsed = urlparse(redirect_uri.strip())
    if parsed.scheme.lower() != "http":
        return (False, "Native desktop OAuth PKCE redirect_uri must use loopback http://127.0.0.1:<port>/... (RFC 8252).")
    host = (parsed.hostname or "").strip().lower()
    if host not in {"127.0.0.1", "::1"}:
        return (False, f"Redirect host '{host}' is prohibited; only loopback 127.0.0.1 or [::1] is allowed.")
    if parsed.port is None or not (1024 <= parsed.port <= 65535):
        return (False, "Redirect URI must specify an unprivileged loopback port (1024..65535).")
    if parsed.username is not None or parsed.password is not None:
        return (False, "Redirect URI must not embed credentials.")
    if not parsed.path or parsed.path == "/":
        return (False, "Redirect URI must include an explicit callback path (e.g. /oauth/callback).")
    return (True, "Valid RFC 8252 loopback redirect URI.")


def validate_oauth_https_endpoint(url: str) -> tuple[bool, str]:
    """Enforce HTTPS-only public OAuth authorization/token/API endpoints with full anti-SSRF syntax checks."""
    try:
        validate_outbound_url_syntax(url, require_https=True)
    except ValueError as exc:
        return (False, str(exc))
    return (True, "Valid HTTPS OAuth endpoint.")
