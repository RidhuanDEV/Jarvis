"""Phase 3 Integration Tests: AI Registry Atomic Switch, Encrypted Memory, IANA Reminders, Voice & Turn E2E."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.application.ai_registry_service import AiRegistryError, AiRegistryService
from jarvis.application.config_service import (
    ConfigService,
    build_default_config,
    build_default_storage_roots,
)
from jarvis.application.memory_service import MemoryServiceError, MemoryVaultService
from jarvis.application.reminder_service import ReminderSchedulerService
from jarvis.domain.ai_models import (
    ModelManifestRecord,
    ModelProviderRecord,
    ModelResourceEstimate,
)
from jarvis.domain.models import (
    AudioEndpointInfo,
    ErrorCode,
    RuntimeOwnershipMode,
    SupportTier,
    TrustZone,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus
from jarvis.platform.portable_mock import (
    FakeDesktopAutomationAdapter,
    FakeNotificationAdapter,
    FakeSttAdapter,
    FakeTtsAdapter,
    FrozenClock,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    StaticAudioDeviceAdapter,
)
from jarvis.transport.app import build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings


def test_ai_registry_manifest_sha256_license_and_atomic_profile_rollback(tmp_path: Path) -> None:
    clock = FrozenClock(datetime(2026, 11, 26, 12, 0, tzinfo=UTC))
    db = DualSqliteManager(tmp_path / "core.db", tmp_path / "knowledge.db", load_sqlite_vec=False)
    db.initialize()
    try:
        bus = SequencedEventBus()
        reg = AiRegistryService(db, clock, bus)
        reg.seed_default_profiles()
        assert reg.get_active_profile().profile.id == "direct"

        # Register external_local Ollama on 0.0.0.0 -> emits exposure warning
        prov, warnings = reg.register_provider(
            ModelProviderRecord(
                id="ollama-user",
                adapter_kind="ollama",
                ownership_mode=RuntimeOwnershipMode.EXTERNAL_LOCAL,
                trust_zone=TrustZone.LOCAL_DEVICE,
                endpoint_ref="http://0.0.0.0:11434",
                support_tier=SupportTier.SUPPORTED,
                enabled=True,
            ),
            correlation_id="c-prov",
        )
        assert prov.id == "ollama-user"
        assert len(warnings) == 1

        # Create real dummy GGUF file and test SHA-256 + license verification
        model_file = tmp_path / "qwen3-1.7b.gguf"
        model_file.write_bytes(b"GGUF-VERIFIED-CONTENT")
        good_sha = hashlib.sha256(b"GGUF-VERIFIED-CONTENT").hexdigest()

        # Unknown license blocked
        with pytest.raises(AiRegistryError) as lic_err:
            reg.register_manifest(
                ModelManifestRecord(
                    id="bad-lic-model",
                    provider_id="ollama-user",
                    role="llm",
                    family="qwen3",
                    revision="r1",
                    sha256=good_sha,
                    byte_size=21,
                    storage_ref=str(model_file),
                    license_spdx="Unknown",
                    resource_estimate=ModelResourceEstimate(ram_mib=2048, vram_mib=1500),
                ),
                correlation_id="c-m1",
            )
        assert lic_err.value.code == ErrorCode.LICENSE_UNVERIFIED

        # Tampered SHA-256 rejected
        with pytest.raises(AiRegistryError) as sha_err:
            reg.register_manifest(
                ModelManifestRecord(
                    id="bad-sha-model",
                    provider_id="ollama-user",
                    role="llm",
                    family="qwen3",
                    revision="r1",
                    sha256="0" * 64,
                    byte_size=21,
                    storage_ref=str(model_file),
                    license_spdx="Apache-2.0",
                    resource_estimate=ModelResourceEstimate(ram_mib=2048, vram_mib=1500),
                ),
                correlation_id="c-m2",
            )
        assert sha_err.value.code == ErrorCode.INVALID_ARGS

        # Valid manifest passes
        saved = reg.register_manifest(
            ModelManifestRecord(
                id="qwen3-1.7b-q4",
                provider_id="ollama-user",
                role="llm",
                family="qwen3",
                revision="r1",
                sha256=good_sha,
                byte_size=21,
                storage_ref=str(model_file),
                is_shared_external_file=True,
                license_spdx="Apache-2.0",
                resource_estimate=ModelResourceEstimate(ram_mib=2048, vram_mib=1500),
            ),
            correlation_id="c-m3",
        )
        assert saved.verified_at is not None

        # Atomic switch to balanced succeeds
        ok_sw = reg.switch_profile_atomic("balanced", correlation_id="c-sw1")
        assert ok_sw.committed and reg.get_active_profile().profile.id == "balanced"

        # Simulated OOM failure during switch to quality -> automatically retains balanced (BR-AI-03)
        fail_sw = reg.switch_profile_atomic(
            "quality",
            probe_candidate=lambda _p: (False, "WORKER_OOM: insufficient VRAM"),
            correlation_id="c-sw2",
        )
        assert not fail_sw.committed and fail_sw.rolled_back
        assert reg.get_active_profile().profile.id == "balanced"

        # Explicit rollback restores direct
        rb = reg.rollback_profile(correlation_id="c-rb")
        assert rb.profile.id == "direct"
    finally:
        db.close()


def test_encrypted_memory_vault_proposals_and_iana_reminders_quiet_hours_and_missed_suspend(
    tmp_path: Path,
) -> None:
    # 03:30 UTC == 22:30 EST in America/New_York (inside 22:00-07:00 quiet hours!)
    clock = FrozenClock(datetime(2026, 11, 26, 3, 30, tzinfo=UTC))
    db = DualSqliteManager(tmp_path / "core.db", tmp_path / "knowledge.db", load_sqlite_vec=False)
    db.initialize()
    try:
        roots = build_default_storage_roots(tmp_path / "data", tmp_path / "cache")
        cfg_svc = ConfigService(db, clock)
        cfg_svc.ensure_initialized(build_default_config(roots, timezone_iana="America/New_York"))
        vault = InMemoryVaultAdapter()
        notify = FakeNotificationAdapter()
        bus = SequencedEventBus()

        # 1. Encrypted Memory Vault (AES-256-GCM + Proposal separation + Optimistic Lock + Tombstone)
        mem_svc = MemoryVaultService(db, vault, clock)
        sens = mem_svc.create_memory(
            kind="fact",
            content="Passport renewal is in June",
            sensitivity="sensitive",
            correlation_id="m1",
        )
        assert sens.is_encrypted is True
        # Raw SQLite row MUST store ciphertext (v1:...), never plaintext!
        with db.core_read() as conn:
            raw_content = str(
                conn.execute("SELECT content FROM memory WHERE id = ?", (sens.id,)).fetchone()[0]
            )
        assert raw_content.startswith("v1:")
        assert "Passport" not in raw_content

        # Pending preference proposal MUST NOT appear in default active list (BR-14)
        prop = mem_svc.create_memory(
            kind="preference",
            content="Prefers dark mode always",
            status="proposal",
            correlation_id="m2",
        )
        assert [m.id for m in mem_svc.list_memories(include_proposals=False)] == [sens.id]
        assert len(mem_svc.list_memories(include_proposals=True)) == 2

        approved = mem_svc.approve_proposal(prop.id, expected_revision=1, correlation_id="m3")
        assert approved.status == "active" and approved.revision == 2

        # Stale revision update fails
        with pytest.raises(MemoryServiceError):
            mem_svc.update_memory(prop.id, expected_revision=1, new_content="stale", correlation_id="m4")

        # Hard delete writes deletion_ledger tombstone (T13)
        assert mem_svc.delete_memory(sens.id, correlation_id="m5") is True
        with db.core_read() as conn:
            tomb = conn.execute(
                "SELECT entity_id FROM deletion_ledger WHERE entity_type='memory' AND entity_id=?",
                (sens.id,),
            ).fetchone()
        assert tomb is not None

        # 2. Persistent IANA Reminders: Quiet Hours suppression + dedup + suspend missed reconciliation
        rem_svc = ReminderSchedulerService(db, cfg_svc, notify, clock, bus)
        r_quiet = rem_svc.create_reminder(
            title="Take vitamins",
            due_at_utc=clock.now_utc() + timedelta(seconds=30),
            timezone_iana="America/New_York",
            correlation_id="r1",
        )
        r_missed = rem_svc.create_reminder(
            title="Morning standup",
            due_at_utc=clock.now_utc() + timedelta(minutes=5),
            timezone_iana="America/New_York",
            correlation_id="r2",
        )

        # Advance 45 seconds -> r_quiet fires silently inside America/New_York quiet hours!
        clock.advance_seconds(45)
        out1 = rem_svc.process_due_reminders(correlation_id="tick-1")
        assert len(out1) == 1
        assert out1[0].reminder_id == r_quiet.id
        assert out1[0].status == "suppressed_quiet_hours"
        assert notify.sent[-1][2] is True  # silent=True!

        # Re-ticking MUST NOT double-deliver (dedup_key idempotency)
        assert rem_svc.process_due_reminders(correlation_id="tick-1b") == []

        # Simulate machine asleep for 30 minutes -> r_missed reconciled honestly as 'missed' (BR-21)
        clock.advance_seconds(30 * 60)
        out2 = rem_svc.process_due_reminders(correlation_id="tick-2")
        assert len(out2) == 1
        assert out2[0].reminder_id == r_missed.id
        assert out2[0].status == "missed"

        # 3. Proactive Rate Limiter (BR-11: disabled default, 60s debounce, 1/hr, 3/day)
        assert rem_svc.proactive_limiter.can_emit(enabled=False, now_utc=clock.now_utc())[0] is False
        assert rem_svc.proactive_limiter.can_emit(enabled=True, now_utc=clock.now_utc())[0] is True
        rem_svc.proactive_limiter.record_emitted(clock.now_utc())
        clock.advance_seconds(30)
        assert rem_svc.proactive_limiter.can_emit(enabled=True, now_utc=clock.now_utc())[0] is False
        clock.advance_seconds(600)  # still within 1 hour
        assert rem_svc.proactive_limiter.can_emit(enabled=True, now_utc=clock.now_utc())[0] is False
        clock.advance_seconds(3700)  # > 1 hour
        assert rem_svc.proactive_limiter.can_emit(enabled=True, now_utc=clock.now_utc())[0] is True
    finally:
        db.close()


def test_phase3_fastapi_turns_r2_file_move_voice_and_vault_end_to_end(tmp_path: Path) -> None:
    token = "b" * 64
    settings = CoreStartupSettings(
        env="test",
        log_level="WARNING",
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
        auth_token=token,
    )
    fake_desktop = FakeDesktopAutomationAdapter()
    fake_audio = StaticAudioDeviceAdapter(
        endpoints=(
            AudioEndpointInfo(id="mic-1", name="USB Mic", direction="input", is_default=True, form_factor="microphone"),
            AudioEndpointInfo(id="spk-1", name="Desktop Speakers", direction="output", is_default=True, form_factor="speakers"),
        )
    )
    container = build_default_container(
        settings,
        fs_port=PortableFilesystemSafetyAdapter(),
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
        audio_port=fake_audio,
        desktop_port=fake_desktop,
    )
    # Wire deterministic fake STT/TTS for offline voice check
    container.voice_service._stt = FakeSttAdapter()
    container.voice_service._tts_providers = (FakeTtsAdapter(),)
    app = create_app(container)
    headers = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:47123"}

    with TestClient(app) as client:
        # 1. Grant baseline R0/R1/R2 capabilities explicitly (deny-by-default verified first!)
        denied_time = client.post("/v1/requests", headers=headers, json={"utterance": "jam berapa"})
        assert denied_time.status_code == 403

        for cap in ("system.time", "os.volume", "os.app.launch", "memory.write", "reminder.write", "fs.move"):
            assert client.put("/v1/grants", headers=headers, json={"capability": cap}).status_code == 200

        # 2. Deterministic R0/R1 turns execute with 0 LLM calls and verified readback
        t_time = client.post("/v1/requests", headers=headers, json={"utterance": "jam berapa"})
        assert t_time.status_code == 200
        assert t_time.json()["llm_called"] is False
        assert t_time.json()["steps"][0]["verified"] is True

        t_vol = client.post("/v1/requests", headers=headers, json={"utterance": "atur volume ke 42"})
        assert t_vol.status_code == 200
        assert fake_desktop.get_volume_percent() == 42

        # 3. R3 shell command is ALWAYS rejected (403 DENIED)
        t_shell = client.post("/v1/requests", headers=headers, json={"utterance": "jalankan powershell whoami"})
        assert t_shell.status_code == 403
        assert t_shell.json()["code"] == "DENIED"

        # 4. R2 file move returns 202 awaiting approval -> approve -> handle-pinned move + anti-overwrite!
        t_move = client.post("/v1/requests", headers=headers, json={"utterance": "pindahkan file a.txt ke b.txt"})
        assert t_move.status_code == 202
        approval = t_move.json()["approval"]

        dec = client.post(
            f"/v1/approvals/{approval['approval_id']}/decision",
            headers=headers,
            json={
                "decision": "approve",
                "nonce": approval["nonce"],
                "bound_hash": approval["bound_hash"],
                "modality": "trusted_ui",
                "channel": "local",
            },
        )
        assert dec.status_code == 200

        safe_root = tmp_path / "docs_root"
        safe_root.mkdir()
        (safe_root / "a.txt").write_text("hello", encoding="utf-8")
        mv_ok = container.turn_orchestrator.execute_approved_file_move(
            approval_id=approval["approval_id"],
            root_path=str(safe_root),
            source_relative_path="a.txt",
            target_relative_path="b.txt",
            correlation_id="mv-1",
        )
        assert mv_ok.verified is True
        assert (safe_root / "b.txt").read_text(encoding="utf-8") == "hello"

        # Anti-overwrite protection (T04)
        (safe_root / "c.txt").write_text("source", encoding="utf-8")
        mv_overwrite = container.turn_orchestrator.execute_approved_file_move(
            approval_id=approval["approval_id"],
            root_path=str(safe_root),
            source_relative_path="c.txt",
            target_relative_path="b.txt",
            correlation_id="mv-2",
        )
        assert mv_overwrite.error_code == ErrorCode.DENIED

        # 5. Voice endpoints & lock wipes ring buffer
        assert client.put("/v1/audio/mode", headers=headers, json={"mode": "ptt"}).status_code == 200
        accepted, _ = container.voice_service.ingest_mic_frame(b"\x00\x01" * 1600, is_ptt_pressed=True)
        assert accepted is True
        assert client.get("/v1/audio/state", headers=headers).json()["ring_buffer_seconds"] > 0.0
        assert client.post("/v1/session/lock", headers=headers, json={"reason": "test_lock"}).status_code == 200
        assert client.get("/v1/audio/state", headers=headers).json()["ring_buffer_seconds"] == 0.0
        assert client.post("/v1/audio/test", headers=headers).json()["echo_guard_ready"] is True

        # 6. Memory & Reminder & Profile HTTP CRUD
        m_resp = client.post(
            "/v1/memories",
            headers=headers,
            json={"kind": "fact", "content": "Sensitive secret note", "sensitivity": "sensitive"},
        )
        assert m_resp.status_code == 201
        mem_id = m_resp.json()["memory"]["id"]
        assert client.patch(
            f"/v1/memories/{mem_id}",
            headers=headers,
            json={"expected_revision": 99, "content": "conflict"},
        ).status_code == 409
        assert client.delete(f"/v1/memories/{mem_id}", headers=headers).status_code == 200

        rem_resp = client.post(
            "/v1/reminders",
            headers=headers,
            json={
                "title": "Stretch break",
                "due_at_utc": (datetime.now(tz=UTC) + timedelta(minutes=10)).isoformat(),
                "timezone_iana": "UTC",
            },
        )
        assert rem_resp.status_code == 201
        assert len(client.get("/v1/reminders", headers=headers).json()["reminders"]) == 1

        profs = client.get("/v1/profiles", headers=headers)
        assert profs.status_code == 200
        assert profs.json()["active_profile_id"] == "direct"
        assert client.post("/v1/profiles/balanced/activate", headers=headers).status_code == 200
        assert client.post("/v1/profiles/rollback", headers=headers).json()["active_profile"]["id"] == "direct"
