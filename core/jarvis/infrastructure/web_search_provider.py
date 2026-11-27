"""Real Pluggable Anti-SSRF WebSearchProviderPort Implementation (Stage G7, B26, FR-WEB-01..03, IR-04).

Supports SearXNG-compatible JSON search endpoints (either explicit opt-in local loopback SearXNG or
HTTPS public endpoints validated via upfront DNS anti-SSRF), bounded streaming byte cap, redirect
refusal, untrusted snippet sanitization, and stale offline cache fallback.
"""

from __future__ import annotations

import ipaddress
import json
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx

from jarvis.application.web_search_service import WebSearchError, WebSearchResultItem
from jarvis.domain.models import ErrorCode
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.web_fetch import (
    DEFAULT_CACHE_TTL_SECONDS,
    DEFAULT_FETCH_TIMEOUT_SECONDS,
    DnsResolverFn,
    SafeWebFetchClient,
    WebFetchSecurityError,
    strip_active_html_to_text,
)

MAX_SEARCH_RESPONSE_BYTES = 1 * 1024 * 1024  # 1 MiB ceiling for search JSON payloads
MAX_SEARCH_CACHE_ENTRIES = 64


_BOUNDARY_TAGS: tuple[str, ...] = (
    "</untrusted_web_data>",
    "</untrusted_document_data>",
    "</untrusted_mcp_data>",
)


def _escape_boundary_tags(text: str) -> str:
    out = text
    for tag in _BOUNDARY_TAGS:
        out = out.replace(tag, "[ESCAPED_TAG]").replace(tag.upper(), "[ESCAPED_TAG]")
    return out


def sanitize_untrusted_web_text(raw: str, *, max_chars: int = 400) -> str:
    """Escape prompt-injection boundary tags (pre- and post-unescape) and strip active HTML tags (BR-15)."""
    pre_escaped = _escape_boundary_tags(raw)
    cleaned = strip_active_html_to_text(pre_escaped, max_chars=max_chars)
    return _escape_boundary_tags(cleaned)[:max_chars]


def validate_search_endpoint_url(
    endpoint_url: str,
    *,
    allow_loopback_searxng: bool = False,
) -> tuple[str, bool]:
    """Validate search provider URL syntax; returns (normalized_url, is_loopback_local)."""
    raw = endpoint_url.strip()
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").strip().lower()
    if parsed.username is not None or parsed.password is not None:
        raise WebSearchError(ErrorCode.DENIED, "SSRF_BLOCKED_USERINFO: search endpoint cannot embed credentials.")
    if not host:
        raise WebSearchError(ErrorCode.INVALID_ARGS, "Search endpoint URL missing hostname.")

    is_loopback = host in {"127.0.0.1", "::1", "localhost"}
    if not is_loopback:
        try:
            is_loopback = ipaddress.ip_address(host.strip("[]")).is_loopback
        except ValueError:
            is_loopback = False

    if is_loopback:
        if not allow_loopback_searxng:
            raise WebSearchError(
                ErrorCode.DENIED,
                "Loopback search endpoint requires explicit opt-in (`allow_loopback_searxng=True`).",
            )
        if scheme not in {"http", "https"}:
            raise WebSearchError(ErrorCode.DENIED, f"Unsupported loopback search scheme '{scheme}'.")
        if parsed.port is not None and not (1024 <= parsed.port <= 65535) and parsed.port not in {80, 443}:
            raise WebSearchError(ErrorCode.DENIED, f"Invalid loopback port '{parsed.port}'.")
        return (raw, True)

    if scheme != "https":
        raise WebSearchError(
            ErrorCode.DENIED,
            "Public search provider endpoint MUST use HTTPS (IR-04 / FR-WEB-02).",
        )
    return (raw, False)


class SearxngWebSearchProvider:
    """Real SearXNG-compatible JSON WebSearchProviderPort with anti-SSRF pinning, byte cap, and stale cache."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        clock: ClockPort,
        provider_name: str = "searxng_json",
        allow_loopback_searxng: bool = False,
        dns_resolver: DnsResolverFn | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout_seconds: float = DEFAULT_FETCH_TIMEOUT_SECONDS,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        max_bytes: int = MAX_SEARCH_RESPONSE_BYTES,
    ) -> None:
        normalized_url, is_loopback = validate_search_endpoint_url(
            endpoint_url, allow_loopback_searxng=allow_loopback_searxng
        )
        self._endpoint_url = normalized_url
        self._is_loopback = is_loopback
        self._clock = clock
        self._provider_name = provider_name
        self._transport = transport
        self._timeout = timeout_seconds
        self._cache_ttl = cache_ttl_seconds
        self._max_bytes = max_bytes
        self._ssrf_guard = SafeWebFetchClient(clock, dns_resolver=dns_resolver, transport=transport)
        self._cache: OrderedDict[str, tuple[datetime, list[WebSearchResultItem]]] = OrderedDict()

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def endpoint_url(self) -> str:
        return self._endpoint_url

    def get_cached_results(self, query: str) -> tuple[list[WebSearchResultItem], bool] | None:
        key = query.strip().lower()
        entry = self._cache.get(key)
        if entry is None:
            return None
        expires_at, items = entry
        is_stale = self._clock.now_utc() >= expires_at
        labeled = [item.model_copy(update={"is_stale": is_stale}) for item in items]
        return (labeled, is_stale)

    async def search(self, query: str, *, limit: int = 5) -> list[WebSearchResultItem]:
        cleaned = query.strip()
        bounded_limit = max(1, min(limit, 10))
        cached = self.get_cached_results(cleaned)
        if cached is not None and not cached[1]:
            return cached[0][:bounded_limit]

        pinned_ip: str | None = None
        if not self._is_loopback:
            try:
                pinned_ip = self._ssrf_guard.validate_and_resolve_url(
                    self._endpoint_url, require_https=True
                )
            except WebFetchSecurityError as exc:
                raise WebSearchError(exc.code, str(exc)) from exc

        use_pinned_socket = (not self._is_loopback) and (self._transport is None) and (pinned_ip is not None)
        req_url = self._endpoint_url
        headers: dict[str, str] = {
            "User-Agent": "JARVIS-Local-Search/0.2.2",
            "Accept": "application/json",
        }
        extensions: dict[str, object] = {}
        if use_pinned_socket and pinned_ip is not None:
            req_url, pinned_headers, extensions = SafeWebFetchClient._build_pinned_request_params(
                self._endpoint_url, pinned_ip, use_pinned_socket=True
            )
            headers.update(pinned_headers)

        raw_chunks = bytearray()
        try:
            async with (
                httpx.AsyncClient(
                    transport=self._transport,
                    timeout=self._timeout,
                    follow_redirects=False,
                    trust_env=False,
                ) as client,
                client.stream(
                    "GET",
                    req_url,
                    params={"q": cleaned, "format": "json"},
                    headers=headers,
                    extensions=extensions,
                ) as response,
            ):
                if response.status_code in (301, 302, 303, 307, 308):
                    raise WebSearchError(
                        ErrorCode.DENIED,
                        "Search provider attempted HTTP redirect; redirects are blocked for anti-SSRF safety.",
                    )
                if response.status_code != 200:
                    raise WebSearchError(
                        ErrorCode.RUNTIME_UNAVAILABLE,
                        f"Search provider '{self._provider_name}' returned HTTP {response.status_code}.",
                    )
                async for chunk in response.aiter_bytes(chunk_size=16384):
                    raw_chunks.extend(chunk)
                    if len(raw_chunks) > self._max_bytes:
                        raise WebSearchError(
                            ErrorCode.INVALID_ARGS,
                            f"Search response exceeded {self._max_bytes} byte ceiling; aborted.",
                        )
        except WebSearchError:
            raise
        except httpx.HTTPError as exc:
            # Offline / transient network degradation: serve labeled stale cache if present, else fail honestly
            if cached is not None:
                return [item.model_copy(update={"is_stale": True}) for item in cached[0][:bounded_limit]]
            raise WebSearchError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Search provider '{self._provider_name}' unreachable: {exc}",
            ) from exc

        try:
            payload = json.loads(bytes(raw_chunks).decode("utf-8"))
        except Exception as exc:
            raise WebSearchError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Search provider '{self._provider_name}' returned malformed JSON.",
            ) from exc

        raw_results = payload.get("results", []) if isinstance(payload, dict) else []
        if not isinstance(raw_results, list):
            raise WebSearchError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                f"Search provider '{self._provider_name}' returned unexpected results structure.",
            )

        now = self._clock.now_utc()
        items: list[WebSearchResultItem] = []
        for entry in raw_results:
            if len(items) >= bounded_limit:
                break
            if not isinstance(entry, dict):
                continue
            url = str(entry.get("url", "")).strip()
            if not url.startswith(("https://", "http://")):
                continue
            title = sanitize_untrusted_web_text(str(entry.get("title", "")), max_chars=200) or url
            snippet = sanitize_untrusted_web_text(
                str(entry.get("content") or entry.get("snippet") or ""), max_chars=500
            )
            published_raw = entry.get("publishedDate") or entry.get("published_at")
            published_at = str(published_raw).strip() if published_raw else None
            items.append(
                WebSearchResultItem(
                    title=title,
                    url=url,
                    snippet=snippet,
                    published_at=published_at,
                    fetched_at=now,
                    is_stale=False,
                )
            )

        cache_key = cleaned.lower()
        self._cache[cache_key] = (now + timedelta(seconds=self._cache_ttl), items)
        self._cache.move_to_end(cache_key)
        while len(self._cache) > MAX_SEARCH_CACHE_ENTRIES:
            self._cache.popitem(last=False)
        return items
