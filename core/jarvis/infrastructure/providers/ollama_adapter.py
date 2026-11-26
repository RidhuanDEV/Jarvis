"""Reference OllamaAdapter (DEC-006, DEC-020, FR-AIP-08): external_local & managed_local safe client."""

from __future__ import annotations

import time
from typing import Any

import httpx

from jarvis.domain.ai_models import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    ProviderCapabilityFlags,
    ProviderProbeResult,
    is_exposed_non_loopback_host,
    strip_thinking_blocks,
)
from jarvis.domain.models import RuntimeOwnershipMode, TrustZone


class OllamaAdapter:
    """Native Ollama HTTP API adapter respecting external_local ownership (never kills user's Ollama)."""

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint_url: str = "http://127.0.0.1:11434",
        ownership_mode: RuntimeOwnershipMode = RuntimeOwnershipMode.EXTERNAL_LOCAL,
        trust_zone: TrustZone = TrustZone.LOCAL_DEVICE,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._endpoint_url = endpoint_url.rstrip("/")
        self._ownership_mode = ownership_mode
        self._trust_zone = trust_zone
        self._transport = transport

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def ownership_mode(self) -> RuntimeOwnershipMode:
        return self._ownership_mode

    @property
    def trust_zone(self) -> TrustZone:
        return self._trust_zone

    async def probe(self) -> ProviderProbeResult:
        started = time.perf_counter()
        warnings: list[str] = []
        if self._trust_zone == TrustZone.LOCAL_DEVICE and is_exposed_non_loopback_host(
            self._endpoint_url
        ):
            warnings.append(
                "External local Ollama endpoint appears exposed on 0.0.0.0; bind to 127.0.0.1 for local privacy (FR-AIP-08)."
            )

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0, trust_env=False
            ) as client:
                resp = await client.get(f"{self._endpoint_url}/api/tags")
            elapsed = round((time.perf_counter() - started) * 1000.0, 2)
            if resp.status_code != 200:
                return ProviderProbeResult(
                    healthy=False,
                    health_code=f"http_{resp.status_code}",
                    latency_ms=elapsed,
                    warnings=tuple(warnings),
                )
            data = resp.json()
            models = tuple(
                str(m["name"]) for m in data.get("models", []) if isinstance(m, dict) and "name" in m
            )
            return ProviderProbeResult(
                healthy=True,
                health_code="ok",
                latency_ms=elapsed,
                detected_models=models,
                capabilities=ProviderCapabilityFlags(
                    streaming=True,
                    structured_json=True,
                    thinking_control=True,
                    cancelable=True,
                ),
                warnings=tuple(warnings),
            )
        except Exception as exc:
            elapsed = round((time.perf_counter() - started) * 1000.0, 2)
            return ProviderProbeResult(
                healthy=False,
                health_code=f"unreachable:{type(exc).__name__}",
                latency_ms=elapsed,
                warnings=tuple(warnings),
            )

    def build_chat_payload(self, request: LlmCompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "stream": False,
            "options": {
                "temperature": request.temperature,
                "num_predict": request.max_tokens,
            },
        }
        if request.enforce_non_thinking:
            payload["think"] = False
        if request.expect_json:
            payload["format"] = "json"
        return payload

    async def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        started = time.perf_counter()
        payload = self.build_chat_payload(request)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=request.timeout_seconds, trust_env=False
        ) as client:
            resp = await client.post(f"{self._endpoint_url}/api/chat", json=payload)
            resp.raise_for_status()
            body = resp.json()

        elapsed = round((time.perf_counter() - started) * 1000.0, 2)
        raw_text = str(body.get("message", {}).get("content", ""))
        cleaned = strip_thinking_blocks(raw_text) if request.enforce_non_thinking else raw_text
        return LlmCompletionResponse(
            content=cleaned,
            raw_content=raw_text,
            model_id=str(body.get("model", request.model_id)),
            provider_id=self._provider_id,
            elapsed_ms=elapsed,
            prompt_tokens=int(body.get("prompt_eval_count", 0)),
            completion_tokens=int(body.get("eval_count", 0)),
            thinking_stripped=(cleaned != raw_text),
        )
