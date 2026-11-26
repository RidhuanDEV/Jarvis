"""Integration tests for Phase 5 (R3): On-Demand Camera, Home Assistant, Isolated Remote Gateway,
Adaptive Preference Proposals, and 98-Case RTM Master Traceability Verification."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from jarvis.application.camera_service import RawCameraFrame
from jarvis.application.home_assistant_service import (
    HaClientDisconnectedError,
    HaEntityState,
    HaReadbackTimeoutError,
)
from jarvis.domain.models import CpuInfo, HardwareSnapshot, OsInfo
from jarvis.platform.portable_mock import (
    FakeDesktopAutomationAdapter,
    FakeNotificationAdapter,
    FrozenClock,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    StaticAudioDeviceAdapter,
    StaticHardwareDiscoveryAdapter,
)
from jarvis.transport.app import CoreContainer, build_default_container, create_app
from jarvis.transport.remote_gateway_app import create_remote_gateway_app
from jarvis.transport.settings import CoreStartupSettings

TEST_TOKEN = "e" * 64
AUTH_HEADERS = {"Authorization": f"Bearer {TEST_TOKEN}"}
REPO_ROOT = Path(__file__).resolve().parents[2]


class _FakeCameraPort:
    def __init__(self) -> None:
        self.closed_devices: list[str] = []
        self.last_frame_ref: RawCameraFrame | None = None

    def capture_single_frame(self, device_id: str) -> RawCameraFrame:
        frame = RawCameraFrame(
            device_id=device_id,
            width=1280,
            height=720,
            raw_frame_bytes=bytearray(b"\xfe\xed\xfa\xce" * 64),
            summary_caption="Desk whiteboard with token sk-secretcameratoken1234567890 visible.",
        )
        self.last_frame_ref = frame
        return frame

    def close_device(self, device_id: str) -> None:
        self.closed_devices.append(device_id)


class _FakeHomeAssistantClient:
    def __init__(self, clock: FrozenClock) -> None:
        self._clock = clock
        self.states: dict[str, str] = {"light.desk_lamp": "off"}
        self.service_calls: list[tuple[str, str, str]] = []
        self.disconnect_on_call = False
        self.timeout_on_readback = False

    def read_entity_state(self, entity_id: str) -> HaEntityState:
        if self.timeout_on_readback:
            raise HaReadbackTimeoutError("readback socket timed out")
        return HaEntityState(
            entity_id=entity_id,
            state=self.states.get(entity_id, "unknown"),
            attributes={},
            observed_at=self._clock.now_utc(),
        )

    def call_service(self, domain: str, service: str, entity_id: str, params: dict[str, Any]) -> None:
        _ = params
        if self.disconnect_on_call:
            raise HaClientDisconnectedError("connection refused")
        self.service_calls.append((domain, service, entity_id))
        if service == "turn_on":
            self.states[entity_id] = "on"
        elif service == "turn_off":
            self.states[entity_id] = "off"


def _build_r3_env(
    tmp_path: Path,
) -> tuple[TestClient, TestClient, CoreContainer, FrozenClock, _FakeCameraPort, _FakeHomeAssistantClient]:
    clock = FrozenClock(datetime(2026, 11, 26, 15, 0, tzinfo=UTC))
    camera_port = _FakeCameraPort()
    ha_client = _FakeHomeAssistantClient(clock)
    hw_snapshot = HardwareSnapshot(
        id="hw-r3-test",
        os_info=OsInfo(system="Windows", release="11", version="10.0.22631", arch="AMD64"),
        cpu=CpuInfo(model_name="Generic 6-Core", physical_cores=6, logical_cores=12),
        ram_total_bytes=16 * 1024**3,
        ram_available_bytes=10 * 1024**3,
        captured_at=clock.now_utc(),
    )
    settings = CoreStartupSettings(
        env="test",
        auth_token=TEST_TOKEN,
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
    )
    container = build_default_container(
        settings,
        clock=clock,
        fs_port=PortableFilesystemSafetyAdapter(),
        hardware_port=StaticHardwareDiscoveryAdapter(hw_snapshot),
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
        audio_port=StaticAudioDeviceAdapter(),
        desktop_port=FakeDesktopAutomationAdapter(),
        notification_port=FakeNotificationAdapter(),
        camera_port=camera_port,
        ha_client=ha_client,
    )
    core_app = create_app(container)
    remote_app = create_remote_gateway_app(
        remote_service=container.remote_gateway_service,
        reminder_service=container.reminder_service,
        turn_orchestrator=container.turn_orchestrator,
        clock=clock,
    )
    return TestClient(core_app), TestClient(remote_app), container, clock, camera_port, ha_client


def test_b17_camera_opt_in_indicator_ram_wipe_and_os_lock_revocation(tmp_path: Path) -> None:
    client, _remote, container, _clock, cam_port, _ha = _build_r3_env(tmp_path)
    try:
        # 1. Denied without per-session grant
        denied = client.post(
            "/v1/camera/snapshot",
            headers=AUTH_HEADERS,
            json={"session_id": "s1", "device_id": "cam-0", "explicit_user_request": True},
        )
        assert denied.status_code == 403

        # 2. Grant denied without explicit_local_consent
        bad_grant = client.post(
            "/v1/camera/grant",
            headers=AUTH_HEADERS,
            json={"session_id": "s1", "device_id": "cam-0", "explicit_local_consent": False},
        )
        assert bad_grant.status_code == 403

        # 3. Grant explicitly locally
        ok_grant = client.post(
            "/v1/camera/grant",
            headers=AUTH_HEADERS,
            json={"session_id": "s1", "device_id": "cam-0", "explicit_local_consent": True},
        )
        assert ok_grant.status_code == 200

        # 4. Snapshot succeeds: secrets redacted, RAM zeroed, zero files on disk, indicator toggled & cleared
        before_files = set(tmp_path.rglob("*"))
        snap = client.post(
            "/v1/camera/snapshot",
            headers=AUTH_HEADERS,
            json={"session_id": "s1", "device_id": "cam-0", "explicit_user_request": True},
        )
        assert snap.status_code == 200
        body = snap.json()["snapshot"]
        assert body["raw_bytes_persisted"] is False
        assert body["raw_memory_wiped"] is True
        assert body["indicator_cleared"] is True
        assert "sk-secretcameratoken1234567890" not in body["redacted_description"]
        assert body["redactions_applied"] >= 1
        assert cam_port.last_frame_ref is not None
        assert len(cam_port.last_frame_ref.raw_frame_bytes) == 0
        assert "cam-0" in cam_port.closed_devices
        # No raw image file written anywhere in tmp_path
        new_image_files = [
            p for p in (set(tmp_path.rglob("*")) - before_files) if p.suffix.lower() in {".png", ".jpg", ".bmp", ".raw"}
        ]
        assert new_image_files == []

        # 5. OS lock immediately closes & revokes camera session permission
        lock = client.post("/v1/session/lock", headers=AUTH_HEADERS, json={"reason": "win_lock"})
        assert lock.status_code == 200
        assert lock.json()["closed_cameras"] >= 1

        after_lock = client.post(
            "/v1/camera/snapshot",
            headers=AUTH_HEADERS,
            json={"session_id": "s1", "device_id": "cam-0", "explicit_user_request": True},
        )
        assert after_lock.status_code == 403
    finally:
        container.db.close()


def test_b18_home_assistant_allowlist_safety_bans_and_honest_readback(tmp_path: Path) -> None:
    client, _remote, container, _clock, _cam, ha_client = _build_r3_env(tmp_path)
    try:
        # Disable offline mode so LAN IoT tests reach the mock client after passing guards
        cfg = client.get("/v1/config", headers=AUTH_HEADERS).json()["config"]
        cfg["ai"]["offline_mode"] = False
        assert client.put("/v1/config", headers=AUTH_HEADERS, json=cfg).status_code == 200

        # 1. Safety-critical devices blocked at registration (R3, FR-IOT-03)
        for bad_ent in ("lock.front_door", "alarm_control_panel.home", "switch.space_heater", "valve.main_gas"):
            r = client.post(
                "/v1/iot/ha/entities",
                headers=AUTH_HEADERS,
                json={"entity_id": bad_ent, "friendly_name": "Bad", "allowed_actions": ["turn_off"]},
            )
            assert r.status_code == 403

        # 2. Safe allowlisted entity registered cleanly
        add = client.post(
            "/v1/iot/ha/entities",
            headers=AUTH_HEADERS,
            json={
                "entity_id": "light.desk_lamp",
                "friendly_name": "Desk Lamp",
                "allowed_actions": ["read_state", "turn_on", "turn_off"],
            },
        )
        assert add.status_code == 201

        # 3. Non-allowlisted safe entity denied BEFORE calling HA network client (FR-IOT-02)
        unlisted = client.post(
            "/v1/iot/ha/actuate",
            headers=AUTH_HEADERS,
            json={"entity_id": "light.kitchen", "action": "turn_on"},
        )
        assert unlisted.status_code == 403
        assert ha_client.service_calls == []

        # 4. Blind toggle prohibited
        toggle = client.post(
            "/v1/iot/ha/actuate",
            headers=AUTH_HEADERS,
            json={"entity_id": "light.desk_lamp", "action": "toggle"},
        )
        assert toggle.status_code == 422

        # 5. Explicit turn_on verified via readback
        ok = client.post(
            "/v1/iot/ha/actuate",
            headers=AUTH_HEADERS,
            json={"entity_id": "light.desk_lamp", "action": "turn_on"},
        )
        assert ok.status_code == 200
        res = ok.json()["result"]
        assert res["status"] == "verified"
        assert res["observed_state"] == "on"
        assert res["verified_readback"] is True

        # 6. Disconnect before dispatch reports `unavailable` honestly
        ha_client.disconnect_on_call = True
        disc = client.post(
            "/v1/iot/ha/actuate",
            headers=AUTH_HEADERS,
            json={"entity_id": "light.desk_lamp", "action": "turn_off"},
        )
        assert disc.status_code == 200
        assert disc.json()["result"]["status"] == "unavailable"
        assert disc.json()["result"]["verified_readback"] is False

        # 7. Readback timeout after dispatch reports `unknown` honestly without blind retry (FR-IOT-04)
        ha_client.disconnect_on_call = False
        ha_client.timeout_on_readback = True
        calls_before = len(ha_client.service_calls)
        unk = client.post(
            "/v1/iot/ha/actuate",
            headers=AUTH_HEADERS,
            json={"entity_id": "light.desk_lamp", "action": "turn_off"},
        )
        assert unk.status_code == 200
        assert unk.json()["result"]["status"] == "unknown"
        assert unk.json()["result"]["verified_readback"] is False
        assert len(ha_client.service_calls) == calls_before + 1  # Strictly 1 call, zero blind retry!
    finally:
        container.db.close()


def test_b19_separate_private_remote_gateway_pairing_scope_ratelimit_offline_and_revocation(tmp_path: Path) -> None:
    core_client, remote_client, container, clock, _cam, _ha = _build_r3_env(tmp_path)
    try:
        # 1. Disabled by default (FR-REM-01)
        assert remote_client.get("/remote/v1/status").status_code == 503

        # 2. Reject wildcard 0.0.0.0 and public IPs (NFR-11)
        for bad_ip in ("0.0.0.0", "8.8.8.8"):  # noqa: S104
            r = core_client.put(
                "/v1/remote/config",
                headers=AUTH_HEADERS,
                json={
                    "enabled": True,
                    "bind_address": bad_ip,
                    "bind_port": 47443,
                    "tls_cert_fingerprint_sha256": "a" * 64,
                    "rate_limit_per_minute": 5,
                },
            )
            assert r.status_code == 403

        # 3. Enable on private VPN CGNAT address (Tailscale/WireGuard) with TLS cert fingerprint & 5 req/min limit
        en = core_client.put(
            "/v1/remote/config",
            headers=AUTH_HEADERS,
            json={
                "enabled": True,
                "bind_address": "100.64.0.10",
                "bind_port": 47443,
                "tls_cert_fingerprint_sha256": "a" * 64,
                "rate_limit_per_minute": 5,
            },
        )
        assert en.status_code == 200

        # 4. Initiate & approve local pairing challenge
        init = core_client.post(
            "/v1/remote/pairing/initiate",
            headers=AUTH_HEADERS,
            json={"device_label": "Monarch Phone", "device_fingerprint": "fp-phone-001"},
        )
        assert init.status_code == 201
        challenge = init.json()["challenge"]

        # Wrong pairing code fails
        wrong = core_client.post(
            f"/v1/remote/pairing/{challenge['challenge_id']}/approve",
            headers=AUTH_HEADERS,
            json={"pairing_code": "000000"},
        )
        if challenge["pairing_code"] != "000000":
            assert wrong.status_code == 403

        # Valid local approval issues scoped token
        approved = core_client.post(
            f"/v1/remote/pairing/{challenge['challenge_id']}/approve",
            headers=AUTH_HEADERS,
            json={
                "pairing_code": challenge["pairing_code"],
                "scopes": ["remote.status.read", "remote.reminder.read", "remote.reminder.create"],
                "token_ttl_hours": 12,
            },
        )
        assert approved.status_code == 200
        receipt = approved.json()["receipt"]
        device_id = receipt["device"]["id"]
        remote_token = receipt["access_token"]
        rem_headers = {"Authorization": f"Bearer {remote_token}"}

        # Verify raw remote token is NOT stored in SQLite (hashed only!)
        with container.db.core_read() as conn:
            tok_row = conn.execute("SELECT token_hash FROM remote_device_token WHERE device_id = ?", (device_id,)).fetchone()
            assert tok_row is not None
            assert str(tok_row["token_hash"]) != remote_token

        # 5. Scoped status & reminder work
        st = remote_client.get("/remote/v1/status", headers=rem_headers)
        assert st.status_code == 200
        assert st.json()["status"] == "online"

        # 6. Prohibited actions over remote (file move, camera, approval, policy) return 403 (FR-REM-02)
        for forbidden_cap in ("fs.file.move", "camera.snapshot", "approval.decide", "policy.override"):
            deny = remote_client.post(f"/remote/v1/actions/{forbidden_cap}", headers=rem_headers)
            assert deny.status_code == 403

        # 7. Rate limit exceeded (already sent 5 requests in same timestamp!) -> 429 (NFR-11)
        rl = remote_client.get("/remote/v1/status", headers=rem_headers)
        assert rl.status_code == 429

        # Advance clock past 60s window
        clock.advance_seconds(65)

        # 8. Host sleeping/offline reports 503 host_unreachable & queues ZERO reminders (FR-REM-04)
        container.remote_gateway_service.set_host_availability(
            available=False, reason="host_suspend", correlation_id="test-sleep"
        )
        before_rems = len(container.reminder_service.list_reminders())
        offline_rem = remote_client.post(
            "/remote/v1/reminders",
            headers=rem_headers,
            json={
                "title": "Should not queue",
                "due_at_utc": (clock.now_utc() + timedelta(hours=1)).isoformat(),
                "timezone_iana": "UTC",
            },
        )
        assert offline_rem.status_code == 503
        assert len(container.reminder_service.list_reminders()) == before_rems

        # Host wakes up, then OS session locks -> mutating remote call denied 403 (FR-ADM-03)
        container.remote_gateway_service.set_host_availability(
            available=True, reason="host_resume", correlation_id="test-wake"
        )
        core_client.post("/v1/session/lock", headers=AUTH_HEADERS, json={"reason": "os_lock"})
        locked_rem = remote_client.post(
            "/remote/v1/reminders",
            headers=rem_headers,
            json={
                "title": "Blocked while locked",
                "due_at_utc": (clock.now_utc() + timedelta(hours=1)).isoformat(),
                "timezone_iana": "UTC",
            },
        )
        assert locked_rem.status_code == 403

        # Unlock, then revoke device instantaneously -> immediate 401 (FR-REM-01)
        container.remote_gateway_service.set_os_lock_state(False)
        rev = core_client.delete(f"/v1/remote/devices/{device_id}", headers=AUTH_HEADERS)
        assert rev.status_code == 200
        after_rev = remote_client.get("/remote/v1/status", headers=rem_headers)
        assert after_rev.status_code == 401
    finally:
        container.db.close()


def test_b20_adaptive_preference_proposals_never_mutate_silently_or_escalate(tmp_path: Path) -> None:
    client, _remote, container, _clock, _cam, _ha = _build_r3_env(tmp_path)
    try:
        # 1. Escalation proposals targeting security/policy/permissions are hard-rejected
        esc = client.post(
            "/v1/preferences/proposals",
            headers=AUTH_HEADERS,
            json={
                "preference_key": "ai.offline_mode",
                "proposed_value": "false",
                "rationale": "Attempt privilege escalation",
                "evidence_count": 5,
            },
        )
        assert esc.status_code == 403

        # 2. Valid safe UX proposal created -> active config remains completely untouched!
        cfg_before = client.get("/v1/config", headers=AUTH_HEADERS).json()
        assert cfg_before["config"]["persona"]["verbosity"] == "standard"

        created = client.post(
            "/v1/preferences/proposals",
            headers=AUTH_HEADERS,
            json={
                "preference_key": "persona.verbosity",
                "proposed_value": "brief",
                "rationale": "User explicitly asked for shorter replies 3 times.",
                "evidence_count": 3,
            },
        )
        assert created.status_code == 201
        prop_id = created.json()["proposal"]["id"]

        # Active config STILL untouched while pending
        cfg_pending = client.get("/v1/config", headers=AUTH_HEADERS).json()
        assert cfg_pending["revision"] == cfg_before["revision"]
        assert cfg_pending["config"]["persona"]["verbosity"] == "standard"

        # 3. Rejecting leaves active config untouched (FR-REM-03)
        rej = client.post(
            f"/v1/preferences/proposals/{prop_id}/decide",
            headers=AUTH_HEADERS,
            json={"decision": "reject"},
        )
        assert rej.status_code == 200
        assert rej.json()["proposal"]["status"] == "rejected"
        cfg_after_rej = client.get("/v1/config", headers=AUTH_HEADERS).json()
        assert cfg_after_rej["revision"] == cfg_before["revision"]
        assert cfg_after_rej["config"]["persona"]["verbosity"] == "standard"

        # 4. Explicit local approval applies ONLY the safe UX key
        p2 = client.post(
            "/v1/preferences/proposals",
            headers=AUTH_HEADERS,
            json={
                "preference_key": "persona.verbosity",
                "proposed_value": "brief",
                "rationale": "Confirmed preference",
                "evidence_count": 4,
            },
        ).json()["proposal"]["id"]
        app_resp = client.post(
            f"/v1/preferences/proposals/{p2}/decide",
            headers=AUTH_HEADERS,
            json={"decision": "approve"},
        )
        assert app_resp.status_code == 200
        cfg_after_app = client.get("/v1/config", headers=AUTH_HEADERS).json()
        assert cfg_after_app["revision"] == cfg_before["revision"] + 1
        assert cfg_after_app["config"]["persona"]["verbosity"] == "brief"
    finally:
        container.db.close()


def test_b21_rtm_98_complete_traceability_integrity() -> None:
    """Verify 100% 1-to-1 mapping of all 98 requirements in 17-TRACEABILITY-MATRIX.md to real evidence & honest tiers."""
    rtm_md = (REPO_ROOT / "JARVIS-SDLC-v0.2.1" / "17-TRACEABILITY-MATRIX.md").read_text(encoding="utf-8")
    req_ids_in_sdlc = re.findall(r"^\|\s*((?:FR|NFR)-[A-Z0-9-]+)\s*\|", rtm_md, flags=re.MULTILINE)
    assert len(req_ids_in_sdlc) == 98, f"Expected 98 SDLC requirements, found {len(req_ids_in_sdlc)}"
    assert len(set(req_ids_in_sdlc)) == 98

    manifest_path = REPO_ROOT / "planning" / "rtm_verification_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    assert len(entries) == 98

    manifest_ids = {e["requirement_id"] for e in entries}
    assert manifest_ids == set(req_ids_in_sdlc)

    # Every Tier-A VERIFIED_LOCAL entry MUST point to an existing real test file in the repository!
    verified_count = 0
    deferred_tier_b_count = 0
    for entry in entries:
        status = entry["verification_status"]
        assert status in {"VERIFIED_LOCAL_TIER_A", "NOT_MEASURED_TIER_B_HARDWARE_GATE"}
        if status == "VERIFIED_LOCAL_TIER_A":
            verified_count += 1
            evidence_rel = entry["evidence_test_file"]
            assert evidence_rel and (REPO_ROOT / evidence_rel).exists(), (
                f"RTM entry {entry['requirement_id']} references missing evidence file: {evidence_rel}"
            )
            assert entry["negative_probe_covered"] is True
        else:
            deferred_tier_b_count += 1
            assert entry["tier_b_reason"], f"Deferred Tier-B entry {entry['requirement_id']} lacks explicit reason."

    assert verified_count == 93
    assert deferred_tier_b_count == 5
