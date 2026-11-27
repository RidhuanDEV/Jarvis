"""Reference LlamaCppServerAdapter (DEC-006, DEC-027): Vulkan/CUDA, --jinja --reasoning-budget 0, no WebUI."""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator
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
from jarvis.domain.models import BackendPreference, RuntimeOwnershipMode, TrustZone


def build_llama_server_args(
    *,
    binary_path: str,
    model_path: str,
    host: str = "127.0.0.1",
    port: int = 8081,
    context_tokens: int = 4096,
    cpu_threads: int = 4,
    backend: BackendPreference = BackendPreference.VULKAN,
    gpu_layers: int = 99,
    kv_quant_q8: bool = True,
) -> list[str]:
    """Construct hardened llama-server CLI arguments enforcing DEC-027 non-thinking & no-WebUI."""
    ngl = 0 if backend == BackendPreference.CPU else max(0, gpu_layers)
    cmd = [
        binary_path,
        "-m",
        model_path,
        "--host",
        host,
        "--port",
        str(port),
        "-c",
        str(context_tokens),
        "-t",
        str(cpu_threads),
        "-ngl",
        str(ngl),
        "--jinja",
        "--reasoning-budget",
        "0",
        "--no-webui",
    ]
    if ngl > 0:
        cmd.extend(["-fa", "on"])
        if kv_quant_q8:
            cmd.extend(["-ctk", "q8_0", "-ctv", "q8_0"])
    return cmd


class LlamaCppServerAdapter:
    """OpenAI-compatible local llama-server adapter with mandatory non-thinking normalization."""

    def __init__(
        self,
        *,
        provider_id: str,
        endpoint_url: str,
        ownership_mode: RuntimeOwnershipMode = RuntimeOwnershipMode.MANAGED_LOCAL,
        trust_zone: TrustZone = TrustZone.LOCAL_DEVICE,
        api_key: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._provider_id = provider_id
        self._endpoint_url = endpoint_url.rstrip("/")
        self._ownership_mode = ownership_mode
        self._trust_zone = trust_zone
        self._api_key = api_key
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

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    async def probe(self) -> ProviderProbeResult:
        started = time.perf_counter()
        warnings: list[str] = []
        if self._trust_zone == TrustZone.LOCAL_DEVICE and is_exposed_non_loopback_host(
            self._endpoint_url
        ):
            warnings.append(
                "Local llama-server endpoint appears bound to a non-loopback address (0.0.0.0)."
            )

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=5.0, trust_env=False
            ) as client:
                health_resp = await client.get(f"{self._endpoint_url}/health", headers=self._headers())
                models_resp = await client.get(f"{self._endpoint_url}/v1/models", headers=self._headers())

            elapsed = round((time.perf_counter() - started) * 1000.0, 2)
            if health_resp.status_code != 200:
                return ProviderProbeResult(
                    healthy=False,
                    health_code=f"http_{health_resp.status_code}",
                    latency_ms=elapsed,
                    warnings=tuple(warnings),
                )

            detected: list[str] = []
            if models_resp.status_code == 200:
                data = models_resp.json()
                for item in data.get("data", []):
                    if isinstance(item, dict) and "id" in item:
                        detected.append(str(item["id"]))

            return ProviderProbeResult(
                healthy=True,
                health_code="ok",
                latency_ms=elapsed,
                detected_models=tuple(detected),
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

    def build_completion_payload(self, request: LlmCompletionRequest) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": request.model_id,
            "messages": [{"role": m.role, "content": m.content} for m in request.messages],
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "top_p": 0.8,
            "top_k": 20,
            "stream": False,
        }
        if request.enforce_non_thinking:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        if request.expect_json:
            payload["response_format"] = {"type": "json_object"}
        return payload

    async def complete(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        started = time.perf_counter()
        payload = self.build_completion_payload(request)
        async with httpx.AsyncClient(
            transport=self._transport, timeout=request.timeout_seconds, trust_env=False
        ) as client:
            resp = await client.post(
                f"{self._endpoint_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            body = resp.json()

        elapsed = round((time.perf_counter() - started) * 1000.0, 2)
        raw_text = str(body["choices"][0]["message"]["content"])
        cleaned = strip_thinking_blocks(raw_text) if request.enforce_non_thinking else raw_text
        usage = body.get("usage", {})
        return LlmCompletionResponse(
            content=cleaned,
            raw_content=raw_text,
            model_id=str(body.get("model", request.model_id)),
            provider_id=self._provider_id,
            elapsed_ms=elapsed,
            prompt_tokens=int(usage.get("prompt_tokens", 0)),
            completion_tokens=int(usage.get("completion_tokens", 0)),
            thinking_stripped=(cleaned != raw_text),
        )

    async def stream_complete(self, request: LlmCompletionRequest) -> AsyncIterator[str]:
        """Stream OpenAI-compatible SSE tokens from llama-server while suppressing <think> blocks."""
        payload = self.build_completion_payload(request)
        payload["stream"] = True
        in_think = False
        pending = ""

        async with (
            httpx.AsyncClient(
                transport=self._transport, timeout=request.timeout_seconds, trust_env=False
            ) as client,
            client.stream(
                "POST",
                f"{self._endpoint_url}/v1/chat/completions",
                headers=self._headers(),
                json=payload,
            ) as resp,
        ):
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    event = json.loads(data_str)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices")
                if not isinstance(choices, list) or not choices:
                    continue
                delta = choices[0].get("delta")
                if not isinstance(delta, dict):
                    continue
                token = delta.get("content")
                if not isinstance(token, str) or not token:
                    continue

                if not request.enforce_non_thinking:
                    yield token
                    continue

                # Strip <think>...</think> inline across chunk boundaries
                pending += token
                while pending:
                    if in_think:
                        end_idx = pending.find("</think>")
                        if end_idx == -1:
                            if len(pending) > 16:
                                pending = pending[-16:]
                            break
                        pending = pending[end_idx + len("</think>") :]
                        in_think = False
                    else:
                        start_idx = pending.find("<think>")
                        if start_idx != -1:
                            if start_idx > 0:
                                yield pending[:start_idx]
                            pending = pending[start_idx + len("<think>") :]
                            in_think = True
                        else:
                            # Hold trailing '<' fragment in case '<think>' splits across chunks
                            lt_idx = pending.rfind("<")
                            if lt_idx != -1 and "<think>".startswith(pending[lt_idx:]):
                                if lt_idx > 0:
                                    yield pending[:lt_idx]
                                pending = pending[lt_idx:]
                                break
                            yield pending
                            pending = ""

        if pending and not in_think:
            yield pending
