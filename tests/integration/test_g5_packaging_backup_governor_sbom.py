"""Stage G5 Integration & Security Suite (B18, B19, B20, B24, U-D02, U-R01).

All tests run strictly inside isolated pytest tmp_path sandboxes (ZERO owner files touched).
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.application.backup_service import BackupServiceError
from jarvis.application.memory_service import MemoryVaultService
from jarvis.domain.models import (
    AiProfileMode,
    CpuInfo,
    GpuInfo,
    HardwareSnapshot,
    OsInfo,
    PowerState,
)
from jarvis.domain.recommendations import DynamicResourceGovernor
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.migrations import apply_migrations
from jarvis.platform.portable_mock import (
    FrozenClock,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
)
from jarvis.transport.app import CoreContainer, build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings

TOKEN = "g5-test-token-" + "c" * 32
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Host": "127.0.0.1"}


def _make_g5_app(
    root: Path, *, vault: InMemoryVaultAdapter | None = None
) -> tuple[TestClient, CoreContainer, InMemoryVaultAdapter]:
    vlt = vault or InMemoryVaultAdapter()
    clk = FrozenClock(datetime(2026, 11, 27, 10, 0, tzinfo=UTC))
    settings = CoreStartupSettings(
        env="test",
        auth_token=TOKEN,
        base_data_dir=root / "data",
        base_cache_dir=root / "cache",
        release_sha="g5-test-sha",
    )
    container = build_default_container(
        settings,
        clock=clk,
        fs_port=PortableFilesystemSafetyAdapter(),
        supervisor=InMemoryProcessSupervisor(),
        vault=vlt,
    )
    return (TestClient(create_app(container)), container, vlt)


def test_b19_u_d02_cross_machine_portable_dek_backup_restore_and_tombstone_replay(
    tmp_path: Path,
) -> None:
    """B19 / U-D02: backup wraps memory DEK; restoring onto a brand-new machine vault decrypts is_encrypted=1 rows & replays tombstones."""
    machine_a_dir = tmp_path / "machine_a"
    client_a, container_a, vault_a = _make_g5_app(machine_a_dir)
    archive_path = Path(container_a.config_service.get_active().document.storage.roots.backups) / "portable.jrvb"
    try:
        # Create 2 sensitive encrypted memories on Machine A, then delete 1 to create a tombstone
        r_keep = client_a.post(
            "/v1/memories",
            headers=HEADERS,
            json={"kind": "note", "content": "Rahasia lintas mesin 774411", "sensitivity": "sensitive"},
        )
        assert r_keep.status_code == 201
        keep_id = r_keep.json()["memory"]["id"]

        r_del = client_a.post(
            "/v1/memories",
            headers=HEADERS,
            json={"kind": "note", "content": "Harus tetap terhapus 889900", "sensitivity": "sensitive"},
        )
        assert r_del.status_code == 201
        del_id = r_del.json()["memory"]["id"]
        assert client_a.delete(f"/v1/memories/{del_id}", headers=HEADERS).status_code == 200

        # Create Argon2id + AES-256-GCM encrypted backup with wrapped DEK
        meta = container_a.backup_service.create_backup(
            archive_path,
            "super-strong-recovery-passphrase",
            correlation_id="corr-b19-bk",
        )
        assert meta.has_wrapped_dek is True

        # Wrong passphrase MUST fail closed
        with pytest.raises(BackupServiceError):
            container_a.backup_service.verify_backup(archive_path, "wrong-passphrase-123")

        # Restore onto brand-new Machine B with a COMPLETELY DIFFERENT Vault DEK!
        vault_b = InMemoryVaultAdapter()
        assert vault_b.get_or_create_master_dek("jarvis.memory.master_dek.v1") != vault_a.get_or_create_master_dek(
            "jarvis.memory.master_dek.v1"
        )
        machine_b_core = tmp_path / "machine_b" / "jarvis_core.db"
        machine_b_know = tmp_path / "machine_b" / "jarvis_knowledge.db"
        summary = container_a.backup_service.restore_into_directory(
            archive_path,
            "super-strong-recovery-passphrase",
            target_core_db_path=machine_b_core,
            target_knowledge_db_path=machine_b_know,
            target_vault=vault_b,
        )
        assert summary.reencrypted_sensitive_memories == 1

        # Verify Machine B opens & decrypts the surviving encrypted memory using Machine B's own DEK!
        db_b = DualSqliteManager(machine_b_core, machine_b_know, load_sqlite_vec=False)
        try:
            db_b.initialize()
            mem_b = MemoryVaultService(db_b, vault_b, container_a.clock)
            items = mem_b.list_memories()
            assert len(items) == 1
            assert items[0].id == keep_id
            assert items[0].content == "Rahasia lintas mesin 774411"
            assert items[0].is_encrypted is True
        finally:
            db_b.close()
    finally:
        container_a.db.close()


def test_b19_transactional_migrations_rollback_atomically_and_quiesced_r2_storage_migration(
    tmp_path: Path,
) -> None:
    """B19: broken SQL migration rolls back completely (zero half-applied tables); R2 storage migration uses Online Backup API."""
    # 1. Verify transactional migration rollback (no implicit executescript COMMIT!)
    mig_dir = tmp_path / "migs"
    mig_dir.mkdir()
    (mig_dir / "0001_atomic_fail.sql").write_text(
        "CREATE TABLE should_rollback (id TEXT PRIMARY KEY);\n"
        "INSERT INTO should_rollback VALUES ('a');\n"
        "THIS IS INVALID SQL SYNTAX;\n",
        encoding="utf-8",
    )
    conn = sqlite3.connect(str(tmp_path / "atomic_test.db"))
    try:
        with pytest.raises(sqlite3.OperationalError):
            apply_migrations(conn, mig_dir)
        tbl = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='should_rollback'"
        ).fetchone()
        assert tbl is None
    finally:
        conn.close()

    # 2. Verify R2 GUI-approved quiesced Online Backup migration of core_db keeps source intact!
    client, container, _ = _make_g5_app(tmp_path / "mig_app")
    try:
        assert client.put("/v1/grants", headers=HEADERS, json={"capability": "storage.migrate"}).status_code == 200
        target_dir = tmp_path / "new_core_db_root"
        target_dir.mkdir()

        # Direct unapproved POST /v1/storage/migrate remains blocked (503)
        direct = client.post(
            "/v1/storage/migrate",
            headers=HEADERS,
            json={"category": "core_db", "target_path": str(target_dir)},
        )
        assert direct.status_code == 503

        # Propose -> approve via trusted_ui -> apply quiesced Online Backup migration
        prop = client.post(
            "/v1/storage/migrate/propose",
            headers=HEADERS,
            json={"category": "core_db", "target_path": str(target_dir)},
        )
        assert prop.status_code == 202
        appr = prop.json()["approval"]
        assert (
            client.post(
                f"/v1/approvals/{appr['approval_id']}/decision",
                headers=HEADERS,
                json={
                    "decision": "approve",
                    "nonce": appr["nonce"],
                    "bound_hash": appr["bound_hash"],
                    "modality": "trusted_ui",
                    "channel": "local",
                },
            ).status_code
            == 200
        )

        applied = client.post(
            "/v1/storage/migrate/apply",
            headers=HEADERS,
            json={"approval_id": appr["approval_id"]},
        )
        assert applied.status_code == 200
        assert applied.json()["files_verified"] == 1
        migrated_db = target_dir / "jarvis_core.db"
        assert migrated_db.is_file()
        # Source DB MUST NOT be deleted
        assert container.db.core_db_path.is_file()
        # Migrated DB passes full SQLite PRAGMA integrity_check!
        chk = sqlite3.connect(str(migrated_db))
        try:
            assert chk.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            chk.close()
    finally:
        container.db.close()


def test_b20_u_r01_lan_provider_no_500_public_host_blocked_and_resource_governor(
    tmp_path: Path,
) -> None:
    """B20 / U-R01: Private LAN registration never crashes GET /v1/providers, blocks public IPs, and DynamicResourceGovernor adapts."""
    client, container, vault = _make_g5_app(tmp_path)
    try:
        vault.set_secret("lan.api.key", "secret-lan-token")

        # 1. Public cloud/internet host rejected as private_lan (403 DENIED)
        r_pub = client.post(
            "/v1/providers/lan/register",
            headers=HEADERS,
            json={
                "provider_id": "bad-public",
                "endpoint_url": "https://api.openai.com/v1",
                "tls_fingerprint_sha256": "a" * 64,
                "credential_vault_ref": "lan.api.key",
                "allowed_data_scopes": ["chat"],
                "consent_acknowledged": True,
            },
        )
        assert r_pub.status_code == 403

        # 2. Valid RFC1918 private LAN registers cleanly AND GET /v1/providers returns 200 (DEF-35 fixed!)
        r_lan = client.post(
            "/v1/providers/lan/register",
            headers=HEADERS,
            json={
                "provider_id": "home-gpu-lan",
                "endpoint_url": "https://192.168.1.50:8443/v1",
                "tls_fingerprint_sha256": "b" * 64,
                "credential_vault_ref": "lan.api.key",
                "allowed_data_scopes": ["chat"],
                "consent_acknowledged": True,
            },
        )
        assert r_lan.status_code == 201
        r_list = client.get("/v1/providers", headers=HEADERS)
        assert r_list.status_code == 200
        lan_items = [p for p in r_list.json()["providers"] if p["id"] == "home-gpu-lan"]
        assert len(lan_items) == 1
        assert lan_items[0]["capabilities"]["tls_fingerprint_sha256"] == "b" * 64

        # 3. DynamicResourceGovernor responds cleanly via GET /v1/system/governor and enforces battery/gaming/idle/unhealthy policies
        r_gov = client.get(
            "/v1/system/governor", headers=HEADERS, params={"idle_seconds": 600, "gaming_active": True}
        )
        assert r_gov.status_code == 200
        assert r_gov.json()["decision"]["unload_vram_now"] is True

        gov = DynamicResourceGovernor(idle_vram_unload_seconds=300)
        snap_gpu = HardwareSnapshot(
            id="hw-1",
            os_info=OsInfo(system="Windows", release="11", version="10.0", arch="AMD64"),
            cpu=CpuInfo(model_name="Generic CPU", physical_cores=8, logical_cores=16),
            ram_total_bytes=16 * 1024**3,
            ram_available_bytes=10 * 1024**3,
            gpus=(
                GpuInfo(
                    index=0,
                    vendor="amd",
                    name="Radeon RX",
                    vram_total_mib=8192,
                    vram_free_mib=7000,
                    supports_vulkan=True,
                    supports_rocm=True,
                ),
            ),
            power_state=PowerState.BATTERY_SAVER,
            captured_at=datetime(2026, 11, 27, 10, 0, tzinfo=UTC),
        )
        dec_batt = gov.evaluate(snap_gpu, requested_mode=AiProfileMode.QUALITY, idle_seconds=400)
        assert dec_batt.effective_ai_mode == AiProfileMode.ECO
        assert dec_batt.unload_vram_now is True

        dec_crash = gov.evaluate(snap_gpu, requested_mode=AiProfileMode.BALANCED, llm_runtime_healthy=False)
        assert dec_crash.fallback_to_direct is True
        assert dec_crash.effective_ai_mode == AiProfileMode.DIRECT
    finally:
        container.db.close()


def test_b24_sbom_zero_unknown_and_accurate_onecore_pyav_licensing(tmp_path: Path) -> None:
    """B24: CycloneDX SBOM has zero Unknown licenses, honest OneCore Proprietary-Windows-OS & PyAV/FFmpeg GPL disclosure."""
    client, container, _ = _make_g5_app(tmp_path)
    try:
        sbom = client.get("/v1/licenses/sbom", headers=HEADERS).json()
        assert sbom["bomFormat"] == "CycloneDX"
        comps = {c["bom-ref"]: c for c in sbom["components"]}
        assert "voice-windows-onecore-os" in comps
        assert comps["voice-windows-onecore-os"]["licenses"][0]["license"]["id"] == "Proprietary-Windows-OS"
        assert "native-pyav-ffmpeg" in comps
        assert comps["native-pyav-ffmpeg"]["licenses"][0]["license"]["id"] == "GPL-3.0-or-later"
        for comp in sbom["components"]:
            lic_id = comp["licenses"][0]["license"]["id"]
            assert "unknown" not in lic_id.lower()

        notices = client.get("/v1/licenses/notices", headers=HEADERS).text
        assert "Windows OneCore OS Speech Voices" in notices
        assert "PyAV" in notices
    finally:
        container.db.close()
