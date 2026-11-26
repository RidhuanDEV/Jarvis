"""Unit precision & recall probes for Phase 5 (R3) IoT safety bans, private remote gateway, and preference guards."""

from __future__ import annotations

import pytest

from jarvis.domain.iot_and_remote import (
    REMOTE_ALLOWED_SCOPES,
    SlidingWindowRateLimiter,
    evaluate_ha_entity_safety,
    is_remote_action_permitted,
    validate_adaptive_preference_proposal,
    validate_private_gateway_bind_address,
)
from jarvis.domain.models import ErrorCode


@pytest.mark.parametrize(
    "entity_id,action",
    [
        ("lock.front_door", "turn_off"),
        ("alarm_control_panel.home_security", "turn_off"),
        ("climate.master_heater", "turn_on"),
        ("water_heater.boiler_main", "turn_on"),
        ("valve.main_gas", "turn_on"),
        ("cover.garage_door", "turn_on"),
        ("switch.space_heater", "turn_on"),
        ("switch.water_main_shutoff", "turn_off"),
        ("switch.medical_cpap", "turn_off"),
        ("scene.unlock_all_doors", "turn_on"),
        ("shell_command.reboot", "turn_on"),
    ],
)
def test_ha_safety_ban_recall_blocks_all_critical_entities(entity_id: str, action: str) -> None:
    verdict = evaluate_ha_entity_safety(entity_id, action)
    assert verdict.allowed is False
    assert verdict.is_r3_prohibited is True
    assert verdict.error_code == ErrorCode.DENIED


def test_ha_blind_toggle_prohibited_while_explicit_safe_actions_allowed() -> None:
    toggle_verdict = evaluate_ha_entity_safety("light.desk_lamp", "toggle")
    assert toggle_verdict.allowed is False
    assert toggle_verdict.error_code == ErrorCode.INVALID_ARGS

    for entity_id, action in [
        ("light.desk_lamp", "turn_on"),
        ("light.desk_lamp", "turn_off"),
        ("media_player.studio_speaker", "media_pause"),
        ("fan.office_ceiling", "turn_on"),
        ("sensor.room_temperature", "read_state"),
    ]:
        ok = evaluate_ha_entity_safety(entity_id, action)
        assert ok.allowed is True, f"Safe entity/action unexpectedly blocked: {entity_id} {action}"
        assert ok.is_r3_prohibited is False


@pytest.mark.parametrize(
    "bad_bind",
    [
        "0.0.0.0",  # noqa: S104
        "::",
        "*",
        "8.8.8.8",
        "1.1.1.1",
        "2001:4860:4860::8888",
        "jarvis.example.com",
        "224.0.0.1",
        "",
    ],
)
def test_remote_gateway_bind_blocks_public_and_wildcard(bad_bind: str) -> None:
    verdict = validate_private_gateway_bind_address(bad_bind)
    assert verdict.allowed is False


@pytest.mark.parametrize(
    "good_bind",
    [
        "127.0.0.1",
        "::1",
        "100.64.0.10",  # Tailscale / VPN CGNAT range
        "10.8.0.2",  # WireGuard private subnet
        "192.168.1.50",  # Private LAN
        "172.16.4.12",
        "fd7a:115c:a1e0::1",  # IPv6 ULA VPN
    ],
)
def test_remote_gateway_bind_allows_private_and_vpn_interfaces(good_bind: str) -> None:
    verdict = validate_private_gateway_bind_address(good_bind)
    assert verdict.allowed is True


def test_remote_action_scope_ceiling_enforced() -> None:
    granted = frozenset({"remote.status.read", "remote.chat.send"})
    assert is_remote_action_permitted("remote.status.read", granted)[0] is True
    assert is_remote_action_permitted("remote.reminder.create", granted)[0] is False
    for forbidden in (
        "fs.file.move",
        "camera.snapshot",
        "screen.capture",
        "policy.override",
        "grant.upsert",
        "config.update",
        "approval.decide",
        "iot.actuate",
        "os.app.launch",
        "storage.migrate",
    ):
        ok, _ = is_remote_action_permitted(forbidden, REMOTE_ALLOWED_SCOPES)
        assert ok is False, f"Forbidden remote action allowed: {forbidden}"


def test_sliding_window_rate_limiter_enforces_quota_and_recovers() -> None:
    limiter = SlidingWindowRateLimiter(max_requests=3, window_seconds=60.0)
    assert limiter.allow("dev-1", 100.0) == (True, 2)
    assert limiter.allow("dev-1", 101.0) == (True, 1)
    assert limiter.allow("dev-1", 102.0) == (True, 0)
    assert limiter.allow("dev-1", 103.0) == (False, 0)
    # After 60s window passes from t=100.0, slot opens cleanly
    assert limiter.allow("dev-1", 160.1) == (True, 0)
    limiter.reset_key("dev-1")
    assert limiter.allow("dev-1", 160.2) == (True, 2)


def test_adaptive_preference_proposal_blocks_security_escalation() -> None:
    for bad_key, bad_val in [
        ("permissions.deny_by_default", "false"),
        ("ai.offline_mode", "false"),
        ("ai.allow_cross_zone_fallback", "true"),
        ("policy.r3_bypass", "true"),
        ("persona.verbosity", "unlimited_arbitrary"),
        ("persona.quiet_hours.start_local", "25:99"),
    ]:
        res = validate_adaptive_preference_proposal(bad_key, bad_val)
        assert res.allowed is False

    for good_key, good_val in [
        ("persona.verbosity", "brief"),
        ("persona.style", "concise"),
        ("locale.primary_language", "en-US"),
        ("persona.quiet_hours.start_local", "23:00"),
        ("visual.quality_tier", "lite"),
    ]:
        res = validate_adaptive_preference_proposal(good_key, good_val)
        assert res.allowed is True
