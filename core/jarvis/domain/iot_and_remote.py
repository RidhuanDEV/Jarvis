"""Pure domain guards for R3 Ecosystem: Camera, Home Assistant Safety Bans, Private Remote Gateway, Adaptive Proposals.

Zero OS/network/database imports (enforced by NFR-16 import-linter contract).
"""

from __future__ import annotations

import ipaddress
import re
from collections import deque
from dataclasses import dataclass

from jarvis.domain.models import ErrorCode, StrictModel

# --- Home Assistant Safety-Critical Hard Bans (FR-IOT-03, BR-01, T12) ---

HA_PROHIBITED_DOMAINS: frozenset[str] = frozenset(
    {
        "lock",
        "alarm_control_panel",
        "siren",
        "valve",
        "water_heater",
        "climate",
        "cover",
        "camera",
        "automation",
        "script",
        "shell_command",
        "homeassistant",
    }
)

HA_SAFE_ALLOWED_DOMAINS: frozenset[str] = frozenset(
    {
        "light",
        "media_player",
        "switch",
        "fan",
        "sensor",
        "binary_sensor",
        "scene",
    }
)

# Even inside `switch.*` or `scene.*`, safety-critical keywords remain R3 hard-banned!
HA_SAFETY_KEYWORD_RE = re.compile(
    r"(?:^|[._-])(lock|unlock|deadbolt|door|gate|garage|alarm|siren|heater|furnace|boiler|"
    r"stove|oven|gas|valve|water_main|breaker|medical|oxygen|cpap|security|camera)(?:$|[._-])",
    re.IGNORECASE,
)

HA_ENTITY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}\.[a-z0-9_]{1,80}$")

# Explicit target states ONLY — blind `toggle` retries are prohibited (11-INTEGRATION-DESIGN.md §5).
HA_EXPLICIT_STATE_ACTIONS: frozenset[str] = frozenset(
    {
        "turn_on",
        "turn_off",
        "set_brightness",
        "media_play",
        "media_pause",
        "media_stop",
        "read_state",
    }
)


@dataclass(frozen=True)
class HaSafetyVerdict:
    allowed: bool
    is_r3_prohibited: bool
    domain: str
    reason: str
    error_code: ErrorCode | None = None


def evaluate_ha_entity_safety(entity_id: str, action: str = "read_state") -> HaSafetyVerdict:
    """Deterministically enforce FR-IOT-03 hard safety bans and explicit target state rules."""
    cleaned = entity_id.strip().lower()
    if not HA_ENTITY_ID_RE.match(cleaned):
        return HaSafetyVerdict(
            allowed=False,
            is_r3_prohibited=False,
            domain="",
            reason=f"Invalid Home Assistant entity_id format: '{entity_id}'.",
            error_code=ErrorCode.INVALID_ARGS,
        )

    domain, object_id = cleaned.split(".", 1)
    if domain in HA_PROHIBITED_DOMAINS or HA_SAFETY_KEYWORD_RE.search(object_id):
        return HaSafetyVerdict(
            allowed=False,
            is_r3_prohibited=True,
            domain=domain,
            reason=f"Home Assistant entity '{cleaned}' is safety-critical and permanently blocked (R3, FR-IOT-03).",
            error_code=ErrorCode.DENIED,
        )

    if domain not in HA_SAFE_ALLOWED_DOMAINS:
        return HaSafetyVerdict(
            allowed=False,
            is_r3_prohibited=True,
            domain=domain,
            reason=f"Home Assistant domain '{domain}' is not in the safe non-critical domain catalog (FR-IOT-03).",
            error_code=ErrorCode.DENIED,
        )

    normalized_action = action.strip().lower()
    if normalized_action == "toggle":
        return HaSafetyVerdict(
            allowed=False,
            is_r3_prohibited=False,
            domain=domain,
            reason="Blind 'toggle' actions are prohibited for IoT safety; send explicit target state (turn_on/turn_off).",
            error_code=ErrorCode.INVALID_ARGS,
        )
    if normalized_action not in HA_EXPLICIT_STATE_ACTIONS:
        return HaSafetyVerdict(
            allowed=False,
            is_r3_prohibited=False,
            domain=domain,
            reason=f"Unsupported Home Assistant action '{action}'.",
            error_code=ErrorCode.INVALID_ARGS,
        )

    return HaSafetyVerdict(
        allowed=True,
        is_r3_prohibited=False,
        domain=domain,
        reason="Entity and explicit action passed safety-critical filter.",
    )


# --- Private Remote Mobile Gateway Guards (FR-REM-01/02/04, NFR-11, T11) ---

REMOTE_ALLOWED_SCOPES: frozenset[str] = frozenset(
    {
        "remote.status.read",
        "remote.chat.send",
        "remote.reminder.read",
        "remote.reminder.create",
    }
)

# Explicitly prohibited over remote channel regardless of token/grant (FR-REM-02)
REMOTE_PROHIBITED_CAPABILITY_PREFIXES: tuple[str, ...] = (
    "fs.",
    "os.",
    "screen.",
    "camera.",
    "policy.",
    "grant.",
    "config.",
    "storage.",
    "backup.",
    "extension.",
    "approval.",
    "iot.",
    "vault.",
    "shell.",
)

_CGNAT_NET = ipaddress.IPv4Network("100.64.0.0/10")  # Tailscale / private VPN mesh range


@dataclass(frozen=True)
class RemoteBindVerdict:
    allowed: bool
    reason: str
    error_code: ErrorCode | None = None


def validate_private_gateway_bind_address(bind_address: str) -> RemoteBindVerdict:
    """Enforce NFR-11 / FR-REM-01: bind ONLY to private LAN/VPN or loopback interfaces, NEVER 0.0.0.0/public IPs."""
    raw = bind_address.strip()
    if not raw:
        return RemoteBindVerdict(False, "Bind address cannot be empty.", ErrorCode.INVALID_ARGS)
    if raw in {"0.0.0.0", "::", "*", "[::]"}:  # noqa: S104
        return RemoteBindVerdict(
            False,
            "Wildcard public listener (0.0.0.0 / ::) is prohibited for Remote Gateway (NFR-11).",
            ErrorCode.DENIED,
        )
    try:
        ip = ipaddress.ip_address(raw.strip("[]"))
    except ValueError:
        return RemoteBindVerdict(
            False,
            f"Remote Gateway requires a literal private/VPN IP address, not hostname '{raw}'.",
            ErrorCode.INVALID_ARGS,
        )

    if ip.is_unspecified or ip.is_multicast:
        return RemoteBindVerdict(
            False, "Unspecified or multicast bind address is prohibited (NFR-11).", ErrorCode.DENIED
        )

    if isinstance(ip, ipaddress.IPv4Address):
        if ip.is_loopback or ip.is_private or ip in _CGNAT_NET:
            return RemoteBindVerdict(True, f"Private/VPN IPv4 interface '{ip}' permitted.")
        return RemoteBindVerdict(
            False,
            f"Public/non-private IPv4 address '{ip}' is prohibited for Remote Gateway (NFR-11).",
            ErrorCode.DENIED,
        )

    # IPv6: allow loopback (::1) or Unique Local Addresses (fc00::/7, e.g. VPN/WireGuard/Tailscale)
    if ip.is_loopback or ip.is_private:
        return RemoteBindVerdict(True, f"Private/VPN IPv6 interface '{ip}' permitted.")
    return RemoteBindVerdict(
        False,
        f"Public IPv6 address '{ip}' is prohibited for Remote Gateway (NFR-11).",
        ErrorCode.DENIED,
    )


def is_remote_action_permitted(scope_requested: str, granted_scopes: frozenset[str]) -> tuple[bool, str]:
    """Enforce FR-REM-02 narrow remote capability ceiling."""
    normalized = scope_requested.strip().lower()
    for prefix in REMOTE_PROHIBITED_CAPABILITY_PREFIXES:
        if normalized.startswith(prefix):
            return (
                False,
                f"Action '{scope_requested}' is permanently prohibited over remote mobile channel (FR-REM-02).",
            )
    if normalized not in REMOTE_ALLOWED_SCOPES:
        return (
            False,
            f"Scope '{scope_requested}' is outside the narrow remote allowlist (FR-REM-02).",
        )
    if normalized not in granted_scopes:
        return (
            False,
            f"Paired device lacks granted remote scope '{scope_requested}'.",
        )
    return (True, "Remote scope permitted.")


class SlidingWindowRateLimiter:
    """Deterministic per-device sliding-window rate limiter using injected timestamps (NFR-11)."""

    def __init__(self, *, max_requests: int = 30, window_seconds: float = 60.0) -> None:
        self._max_requests = max(1, max_requests)
        self._window_seconds = max(1.0, window_seconds)
        self._buckets: dict[str, deque[float]] = {}

    def allow(self, key: str, now_epoch_sec: float) -> tuple[bool, int]:
        """Return (allowed, remaining_quota) for key at now_epoch_sec."""
        bucket = self._buckets.setdefault(key, deque())
        cutoff = now_epoch_sec - self._window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self._max_requests:
            return (False, 0)
        bucket.append(now_epoch_sec)
        return (True, self._max_requests - len(bucket))

    def reset_key(self, key: str) -> None:
        self._buckets.pop(key, None)


class RemoteReplayGuard:
    """Deterministic anti-replay nonce & timestamp-skew guard for Remote Gateway requests (Stage G7, NFR-11)."""

    def __init__(self, *, max_skew_seconds: float = 60.0, max_tracked_nonces: int = 2048) -> None:
        self._max_skew = max(5.0, max_skew_seconds)
        self._max_tracked = max(64, max_tracked_nonces)
        self._seen: dict[tuple[str, str], float] = {}

    def verify_and_record(
        self,
        *,
        device_id: str,
        nonce: str,
        timestamp_epoch_sec: float,
        now_epoch_sec: float,
    ) -> tuple[bool, str]:
        clean_nonce = nonce.strip()
        if len(clean_nonce) < 12 or len(clean_nonce) > 128:
            return (False, "Remote request replay nonce must be 12..128 characters.")
        if abs(now_epoch_sec - timestamp_epoch_sec) > self._max_skew:
            return (False, f"Remote request timestamp outside +-{int(self._max_skew)}s replay window.")

        # Evict expired nonces before lookup
        cutoff = now_epoch_sec - (self._max_skew * 2.0)
        expired_keys = [k for k, ts in self._seen.items() if ts < cutoff]
        for k in expired_keys:
            self._seen.pop(k, None)

        composite = (device_id, clean_nonce)
        if composite in self._seen:
            return (False, "Replayed remote request nonce rejected (NFR-11).")

        if len(self._seen) >= self._max_tracked:
            oldest_key = min(self._seen, key=lambda item: self._seen[item])
            self._seen.pop(oldest_key, None)
        self._seen[composite] = now_epoch_sec
        return (True, "Fresh remote request nonce accepted.")

    def clear_device(self, device_id: str) -> None:
        for k in [key for key in self._seen if key[0] == device_id]:
            self._seen.pop(k, None)


# --- Adaptive Preference Proposal Guard (FR-REM-03, B20) ---

# Strictly limited to non-privilege UX / persona preferences; NEVER permissions, policy, or trust zones!
ALLOWED_ADAPTIVE_PREFERENCE_KEYS: frozenset[str] = frozenset(
    {
        "persona.verbosity",
        "persona.style",
        "locale.primary_language",
        "persona.quiet_hours.start_local",
        "persona.quiet_hours.end_local",
        "visual.quality_tier",
    }
)

ALLOWED_PREFERENCE_VALUES: dict[str, frozenset[str]] = {
    "persona.verbosity": frozenset({"brief", "standard", "detailed"}),
    "persona.style": frozenset({"concise", "balanced", "formal", "warm"}),
    "locale.primary_language": frozenset({"id-ID", "en-US", "en-GB"}),
    "visual.quality_tier": frozenset({"cinematic", "balanced", "lite", "reduced_motion"}),
}

_HHMM_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class PreferenceProposalCheck(StrictModel):
    allowed: bool
    reason: str
    error_code: ErrorCode | None = None


def validate_adaptive_preference_proposal(preference_key: str, proposed_value: str) -> PreferenceProposalCheck:
    """Enforce FR-REM-03: proposals may ONLY target safe UX preferences, never permissions/policy/models."""
    key = preference_key.strip()
    if key not in ALLOWED_ADAPTIVE_PREFERENCE_KEYS:
        return PreferenceProposalCheck(
            allowed=False,
            reason=(
                f"Preference key '{key}' cannot be proposed adaptively; security, policy, model, "
                "and permission changes require direct explicit owner configuration (FR-REM-03)."
            ),
            error_code=ErrorCode.DENIED,
        )

    val = proposed_value.strip()
    if key in ALLOWED_PREFERENCE_VALUES:
        if val not in ALLOWED_PREFERENCE_VALUES[key]:
            return PreferenceProposalCheck(
                allowed=False,
                reason=f"Invalid value '{val}' for adaptive preference '{key}'.",
                error_code=ErrorCode.INVALID_ARGS,
            )
    elif key in {"persona.quiet_hours.start_local", "persona.quiet_hours.end_local"} and not _HHMM_RE.match(val):
        return PreferenceProposalCheck(
            allowed=False,
            reason=f"Quiet hours value '{val}' must be HH:MM (24-hour).",
            error_code=ErrorCode.INVALID_ARGS,
        )

    return PreferenceProposalCheck(allowed=True, reason="Adaptive preference proposal is within safe UX scope.")
