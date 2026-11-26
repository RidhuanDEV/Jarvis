"""Hardened Anti-SSRF Read-Only Web Fetch Client with DNS Verification, Redirect Validation & Stale Cache (B12, T05)."""

from __future__ import annotations

import html
import re
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urljoin

import httpx

from jarvis.domain.models import ErrorCode
from jarvis.domain.ports import ClockPort
from jarvis.domain.security_guards import is_forbidden_ip, validate_outbound_url_syntax

MAX_FETCH_BYTES = 2 * 1024 * 1024  # 2 MiB (11-INTEGRATION-DESIGN §3)
DEFAULT_FETCH_TIMEOUT_SECONDS = 10.0
DEFAULT_CACHE_TTL_SECONDS = 900  # 15 minutes
MAX_REDIRECT_HOPS = 4

_SCRIPT_STYLE_RE = re.compile(r"<(?:script|style|noscript)[^>]*>[\s\S]*?</(?:script|style|noscript)>", re.I)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


class WebFetchSecurityError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class FetchedWebPage:
    url: str
    pinned_ip: str
    status_code: int
    text_excerpt: str
    fetched_at: datetime
    expires_at: datetime
    is_stale: bool
    from_cache: bool


DnsResolverFn = Callable[[str, int], list[str]]


def _default_dns_resolver(host: str, port: int) -> list[str]:
    infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    ips: list[str] = []
    for info in infos:
        ip = str(info[4][0])
        if ip not in ips:
            ips.append(ip)
    return ips


def strip_active_html_to_text(raw_html: str, *, max_chars: int = 8000) -> str:
    """Remove <script>/<style> and HTML tags, returning passive untrusted plain text."""
    no_scripts = _SCRIPT_STYLE_RE.sub(" ", raw_html)
    no_tags = _HTML_TAG_RE.sub(" ", no_scripts)
    unescaped = html.unescape(no_tags)
    collapsed = re.sub(r"\s+", " ", unescaped).strip()
    return collapsed[:max_chars]


class SafeWebFetchClient:
    """Read-only HTTP(S) fetcher enforcing DNS IP validation on every redirect hop, byte cap, and stale cache labeling."""

    def __init__(
        self,
        clock: ClockPort,
        *,
        dns_resolver: DnsResolverFn | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_bytes: int = MAX_FETCH_BYTES,
    ) -> None:
        self._clock = clock
        self._dns = dns_resolver or _default_dns_resolver
        self._transport = transport
        self._cache_ttl = cache_ttl_seconds
        self._max_bytes = max_bytes
        self._cache: dict[str, FetchedWebPage] = {}

    def validate_and_resolve_url(self, raw_url: str, *, require_https: bool = False) -> str:
        """Validate URL syntax + resolve ALL DNS A/AAAA records and block ANY non-global IP (T05)."""
        try:
            _scheme, host, port = validate_outbound_url_syntax(raw_url, require_https=require_https)
        except ValueError as exc:
            raise WebFetchSecurityError(ErrorCode.DENIED, str(exc)) from exc

        try:
            resolved_ips = self._dns(host, port)
        except OSError as exc:
            raise WebFetchSecurityError(
                ErrorCode.RUNTIME_UNAVAILABLE, f"DNS resolution failed for '{host}': {exc}"
            ) from exc

        if not resolved_ips:
            raise WebFetchSecurityError(ErrorCode.DENIED, f"DNS returned no addresses for '{host}'.")

        for ip in resolved_ips:
            if is_forbidden_ip(ip):
                raise WebFetchSecurityError(
                    ErrorCode.DENIED,
                    f"SSRF_FORBIDDEN_DESTINATION_IP: '{host}' resolved to blocked IP '{ip}'.",
                )
        return resolved_ips[0]

    def get_cached(self, url: str) -> FetchedWebPage | None:
        cached = self._cache.get(url)
        if cached is None:
            return None
        now = self._clock.now_utc()
        is_stale = now >= cached.expires_at
        return FetchedWebPage(
            url=cached.url,
            pinned_ip=cached.pinned_ip,
            status_code=cached.status_code,
            text_excerpt=cached.text_excerpt,
            fetched_at=cached.fetched_at,
            expires_at=cached.expires_at,
            is_stale=is_stale,
            from_cache=True,
        )

    async def fetch_read_only(
        self,
        raw_url: str,
        *,
        offline_mode: bool,
        require_https: bool = False,
        allow_stale_cache_when_offline: bool = True,
    ) -> FetchedWebPage:
        """Fetch public web page read-only with manual redirect validation and offline stale-cache labeling."""
        cached = self.get_cached(raw_url)
        if cached is not None and not cached.is_stale:
            return cached

        if offline_mode:
            if allow_stale_cache_when_offline and cached is not None:
                return cached
            raise WebFetchSecurityError(
                ErrorCode.OFFLINE, "Offline mode is active; outbound web fetch blocked (BR-16)."
            )

        current_url = raw_url
        pinned_ip = self.validate_and_resolve_url(current_url, require_https=require_https)

        async with httpx.AsyncClient(
            transport=self._transport,
            timeout=DEFAULT_FETCH_TIMEOUT_SECONDS,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response: httpx.Response | None = None
            for _hop in range(MAX_REDIRECT_HOPS + 1):
                response = await client.get(
                    current_url, headers={"User-Agent": "JARVIS-Local-Reader/0.2.1"}
                )
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise WebFetchSecurityError(ErrorCode.DENIED, "Redirect missing Location header.")
                    next_url = urljoin(current_url, location)
                    # Re-validate EVERY redirect hop against full SSRF + DNS guard!
                    pinned_ip = self.validate_and_resolve_url(next_url, require_https=require_https)
                    current_url = next_url
                    continue
                break
            else:
                raise WebFetchSecurityError(ErrorCode.DENIED, "Too many HTTP redirects.")

            assert response is not None
            raw_bytes = response.content
            if len(raw_bytes) > self._max_bytes:
                raise WebFetchSecurityError(
                    ErrorCode.INVALID_ARGS,
                    f"Response size ({len(raw_bytes)} bytes) exceeded 2 MiB ceiling.",
                )

        now = self._clock.now_utc()
        page = FetchedWebPage(
            url=current_url,
            pinned_ip=pinned_ip,
            status_code=response.status_code,
            text_excerpt=strip_active_html_to_text(raw_bytes.decode("utf-8", errors="replace")),
            fetched_at=now,
            expires_at=now + timedelta(seconds=self._cache_ttl),
            is_stale=False,
            from_cache=False,
        )
        self._cache[raw_url] = page
        return page
