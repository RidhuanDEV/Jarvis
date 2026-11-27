"""Verified Private-LAN / Loopback Home Assistant REST Client (Stage G7, B26, FR-IOT-02..04).

Strict invariants:
- Private LAN (RFC1918 / ULA / .local / .lan) or loopback ONLY; public internet endpoints are denied so
  long-lived access tokens NEVER leak outside the owner's local network.
- HTTPS required for private LAN endpoints; HTTP permitted ONLY on explicit loopback (`127.0.0.1` / `::1`).
- Token retrieved strictly from `SecretVaultAndCryptoPort` (`vault_ref`) — NEVER stored in SQLite or logged.
- `trust_env=False`, `follow_redirects=False`, strict timeout (5s), ZERO blind retries on timeout!
"""

from __future__ import annotations

import ipaddress
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from jarvis.application.home_assistant_service import (
    HaClientDisconnectedError,
    HaEntityState,
    HaReadbackTimeoutError,
    HomeAssistantError,
)
from jarvis.domain.models import ErrorCode
from jarvis.domain.ports import ClockPort, SecretVaultAndCryptoPort

HA_HTTP_TIMEOUT_SECONDS = 5.0


def validate_ha_lan_endpoint(base_url: str, *, allow_loopback_http: bool = False) -> tuple[str, bool]:
    """Validate Home Assistant base URL is strictly private LAN / loopback (returns normalized URL, is_loopback)."""
    raw = base_url.strip().rstrip("/")
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").strip().lower()
    if parsed.username is not None or parsed.password is not None:
        raise HomeAssistantError(ErrorCode.DENIED, "Home Assistant URL cannot embed credentials.")
    if not host:
        raise HomeAssistantError(ErrorCode.INVALID_ARGS, "Home Assistant URL missing hostname.")

    is_loopback = host in {"127.0.0.1", "::1", "localhost"}
    is_private_lan = host.endswith((".local", ".lan", ".internal"))
    if not is_loopback and not is_private_lan:
        try:
            ip_obj = ipaddress.ip_address(host.strip("[]"))
            is_loopback = ip_obj.is_loopback
            is_private_lan = ip_obj.is_private
        except ValueError:
            is_private_lan = False

    if not (is_loopback or is_private_lan):
        raise HomeAssistantError(
            ErrorCode.DENIED,
            f"Home Assistant endpoint '{host}' is not a private LAN / loopback address; public internet endpoints are blocked.",
        )

    if scheme == "https":
        return (raw, is_loopback)
    if scheme == "http" and is_loopback and allow_loopback_http:
        return (raw, True)
    raise HomeAssistantError(
        ErrorCode.DENIED,
        "Private LAN Home Assistant endpoints MUST use HTTPS/TLS (HTTP allowed only on explicit loopback opt-in).",
    )


class PrivateLanHomeAssistantClient:
    """Real HomeAssistantClientPort implementation talking to a verified Private LAN / loopback HA REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        vault: SecretVaultAndCryptoPort,
        credential_vault_ref: str,
        clock: ClockPort,
        allow_loopback_http: bool = False,
        transport: httpx.BaseTransport | None = None,
        timeout_seconds: float = HA_HTTP_TIMEOUT_SECONDS,
    ) -> None:
        normalized_url, _is_loopback = validate_ha_lan_endpoint(
            base_url, allow_loopback_http=allow_loopback_http
        )
        self._base_url = normalized_url
        self._vault = vault
        self._vault_ref = credential_vault_ref
        self._clock = clock
        self._transport = transport
        self._timeout = timeout_seconds

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        token = self._vault.get_secret(self._vault_ref)
        if not token:
            raise HaClientDisconnectedError(
                f"Home Assistant credential '{self._vault_ref}' is missing from OS Credential Vault."
            )
        return {
            "Authorization": f"Bearer {token.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def read_entity_state(self, entity_id: str) -> HaEntityState:
        safe_id = quote(entity_id.strip().lower(), safe="._-")
        url = f"{self._base_url}/api/states/{safe_id}"
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = client.get(url, headers=self._headers())
        except httpx.TimeoutException as exc:
            raise HaReadbackTimeoutError(f"Home Assistant readback timed out for '{entity_id}'.") from exc
        except httpx.HTTPError as exc:
            raise HaClientDisconnectedError(f"Home Assistant unreachable for '{entity_id}': {exc}") from exc

        if resp.status_code != 200:
            raise HaClientDisconnectedError(
                f"Home Assistant state read for '{entity_id}' failed with HTTP {resp.status_code}."
            )
        payload = resp.json()
        if not isinstance(payload, dict) or "state" not in payload:
            raise HaClientDisconnectedError("Home Assistant returned malformed entity state JSON.")
        attrs = payload.get("attributes")
        return HaEntityState(
            entity_id=str(payload.get("entity_id", entity_id)),
            state=str(payload["state"]),
            attributes=dict(attrs) if isinstance(attrs, dict) else {},
            observed_at=self._clock.now_utc(),
        )

    def call_service(self, domain: str, service: str, entity_id: str, params: dict[str, Any]) -> None:
        safe_domain = quote(domain.strip().lower(), safe="_-")
        safe_service = quote(service.strip().lower(), safe="_-")
        url = f"{self._base_url}/api/services/{safe_domain}/{safe_service}"
        body: dict[str, Any] = {"entity_id": entity_id.strip().lower(), **params}
        try:
            with httpx.Client(
                transport=self._transport,
                timeout=self._timeout,
                follow_redirects=False,
                trust_env=False,
            ) as client:
                resp = client.post(url, headers=self._headers(), json=body)
        except httpx.TimeoutException as exc:
            # Post-dispatch uncertainty: raise generic runtime error so service reports `unknown` (never blind retry!)
            raise RuntimeError(f"Home Assistant service call timed out for '{entity_id}'.") from exc
        except httpx.ConnectError as exc:
            raise HaClientDisconnectedError(f"Home Assistant unreachable before dispatch: {exc}") from exc
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Home Assistant transport error during dispatch: {exc}") from exc

        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Home Assistant service call {domain}.{service} failed with HTTP {resp.status_code}."
            )
