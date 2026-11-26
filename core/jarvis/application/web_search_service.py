"""Pluggable Web Search Service with Offline Gate, Private-Query Guard & Stale Cache Labeling (B12, DEC-011, FR-WEB-01..03)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Protocol

from jarvis.application.config_service import ConfigService
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.domain.security_guards import detect_private_indicators_in_query
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.web_fetch import FetchedWebPage, SafeWebFetchClient, WebFetchSecurityError


class WebSearchError(ValueError):
    def __init__(self, code: ErrorCode, message: str, *, indicators: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.code = code
        self.indicators = indicators


class WebSearchResultItem(StrictModel):
    title: str
    url: str
    snippet: str
    published_at: str | None = None
    fetched_at: datetime
    is_stale: bool = False


class WebSearchProviderPort(Protocol):
    @property
    def provider_name(self) -> str: ...

    async def search(self, query: str, *, limit: int = 5) -> list[WebSearchResultItem]: ...


class WebIntelligenceService:
    """Orchestrates pluggable read-only web search & anti-SSRF fetching with privacy guardrails."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        fetch_client: SafeWebFetchClient,
        clock: ClockPort,
        *,
        search_provider: WebSearchProviderPort | None = None,
    ) -> None:
        self._db = db
        self._config = config_service
        self._fetch = fetch_client
        self._clock = clock
        self._provider = search_provider

    def bind_search_provider(self, provider: WebSearchProviderPort) -> None:
        self._provider = provider

    async def query_web(
        self,
        query: str,
        *,
        limit: int = 5,
        private_query_approved: bool = False,
        correlation_id: str,
    ) -> dict[str, object]:
        cfg = self._config.get_active().document
        if cfg.ai.offline_mode:
            raise WebSearchError(
                ErrorCode.OFFLINE, "Mode offline aktif; pencarian web diblokir (BR-16)."
            )
        cleaned = query.strip()
        if not cleaned:
            raise WebSearchError(ErrorCode.INVALID_ARGS, "Query pencarian web tidak boleh kosong.")

        # FR-WEB-01: inspect query for private/PII/token indicators before sending outbound
        indicators = detect_private_indicators_in_query(cleaned)
        if indicators and not private_query_approved:
            raise WebSearchError(
                ErrorCode.APPROVAL_REQUIRED,
                f"Query memuat indikasi data privat ({', '.join(indicators)}); diperlukan pratinjau/persetujuan R2 atau redaksi.",
                indicators=indicators,
            )

        if self._provider is None:
            raise WebSearchError(
                ErrorCode.RUNTIME_UNAVAILABLE,
                "Tidak ada provider pencarian web (mis. SearXNG lokal) yang dikonfigurasi.",
            )

        results = await self._provider.search(cleaned, limit=max(1, min(limit, 10)))
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.search.executed', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"provider": self._provider.provider_name, "result_count": len(results)}),
                    now_iso,
                ),
            )
        return {
            "provider": self._provider.provider_name,
            "fetched_at": now_iso,
            "untrusted_data_notice": "Web results are untrusted passive data (BR-15).",
            "results": [r.model_dump(mode="json") for r in results],
        }

    async def fetch_page(
        self, url: str, *, require_https: bool = False, correlation_id: str
    ) -> FetchedWebPage:
        cfg = self._config.get_active().document
        try:
            page = await self._fetch.fetch_read_only(
                url, offline_mode=cfg.ai.offline_mode, require_https=require_https
            )
        except WebFetchSecurityError as exc:
            raise WebSearchError(exc.code, str(exc)) from exc

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'web.page.fetched', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"status_code": page.status_code, "is_stale": page.is_stale}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return page
