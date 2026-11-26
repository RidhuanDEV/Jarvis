"""Integration tests for Dual SQLite WAL, Storage Manager, Portable Backup, FastAPI Auth, and Windows Ports."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from jarvis.application.backup_service import BackupService
from jarvis.application.config_service import (
    ConfigService,
    build_default_config,
    build_default_storage_roots,
)
from jarvis.application.storage_service import StorageService, StorageServiceError
from jarvis.domain.models import ErrorCode, StorageCategory
from jarvis.infrastructure.crypto import Argon2Params
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.migrations import MigrationChecksumMismatchError, apply_migrations
from jarvis.platform.portable_mock import (
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    SystemClock,
)
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter
from jarvis.platform.windows.supervisor import WindowsJobProcessSupervisor
from jarvis.transport.app import build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings

FAST_ARGON2 = Argon2Params(time_cost=1, memory_cost_kib=16384, parallelism=1)


def test_dual_sqlite_wal_revoked_root_isolation_and_migration_checksum_tamper(
    tmp_path: Path,
) -> None:
    db = DualSqliteManager(
        tmp_path / "core.db", tmp_path / "knowledge.db", load_sqlite_vec=True
    )
    db.initialize()
    try:
        health = db.check_health()
        assert health["core_db_ok"] and health["knowledge_db_ok"]
        assert db.sqlite_vec_loaded is True

        # Register active root in core.db and index chunk in knowledge.db
        with db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO source_root(id, canonical_path, scope_json, enabled, revision, revoked_at)
                VALUES ('root-1', '/docs/alpha', '{}', 1, 1, NULL)
                """
            )
        with db.knowledge_tx() as conn:
            conn.execute(
                """
                INSERT INTO document(
                    id, root_id, root_revision, relative_path, sha256, byte_size, mtime_ns, mime_type, index_state, source_revision
                ) VALUES ('doc-1', 'root-1', 1, 'notes.md', 'abc', 120, 1, 'text/markdown', 'indexed', 1)
                """
            )
            conn.execute(
                """
                INSERT INTO chunk(id, document_id, root_id, ordinal, locator_json, text, token_count, source_revision)
                VALUES ('chk-1', 'doc-1', 'root-1', 0, '{"page":1}', 'Orbital precision local architecture', 6, 1)
                """
            )

        hits_before = db.query_knowledge_fts("Orbital")
        assert len(hits_before) == 1
        assert hits_before[0].chunk_id == "chk-1"

        # Revoke root in core.db -> MUST vanish immediately from knowledge query BEFORE GC runs (DEC-007)
        with db.core_tx() as conn:
            conn.execute(
                "UPDATE source_root SET revoked_at = ? WHERE id = 'root-1'",
                (datetime.now(tz=UTC).isoformat(),),
            )
        assert db.query_knowledge_fts("Orbital") == []

        # Startup/idempotent GC purges physical orphan docs/chunks
        removed = db.gc_revoked_knowledge()
        assert removed >= 1
        assert db.gc_revoked_knowledge() == 0

        # Tampered already-applied migration MUST raise MigrationChecksumMismatchError
        tampered_dir = tmp_path / "tampered_migrations"
        tampered_dir.mkdir()
        (tampered_dir / "0001_initial_core.sql").write_text("-- tampered SQL", encoding="utf-8")
        with db.core_read() as conn, pytest.raises(MigrationChecksumMismatchError):
            apply_migrations(conn, tampered_dir)
    finally:
        db.close()


def test_storage_manager_wal_smb_block_staged_migration_rollback_and_lru_protection(
    tmp_path: Path,
) -> None:
    clock = SystemClock()
    fs = PortableFilesystemSafetyAdapter()
    db = DualSqliteManager(tmp_path / "core.db", tmp_path / "knowledge.db", load_sqlite_vec=False)
    db.initialize()
    try:
        roots = build_default_storage_roots(tmp_path / "data", tmp_path / "cache")
        cfg_svc = ConfigService(db, clock)
        cfg_svc.ensure_initialized(build_default_config(roots))
        storage = StorageService(db, cfg_svc, fs, clock)
        locs = storage.sync_locations_from_config()
        assert len(locs) == 11

        # 1. SMB/UNC network share MUST be rejected for core_db and knowledge_db (DEC-019)
        for wal_cat in (StorageCategory.CORE_DB, StorageCategory.KNOWLEDGE_DB):
            with pytest.raises(StorageServiceError) as exc_info:
                storage.set_location(wal_cat, r"\\nas-server\shared\jarvis_db", correlation_id="c1")
            assert exc_info.value.code == ErrorCode.UNSUPPORTED_FILESYSTEM

        # 2. Staged migration rollback on simulated mid-migration failure keeps source intact (T10)
        models_src = Path(roots.models)
        models_src.mkdir(parents=True, exist_ok=True)
        (models_src / "tiny.gguf").write_bytes(b"MODEL-WEIGHTS-V1")
        models_dst = tmp_path / "alt_drive" / "models"

        with pytest.raises(StorageServiceError):
            storage.migrate_location(
                StorageCategory.MODELS,
                str(models_dst),
                correlation_id="c2",
                simulate_failure_before_commit=True,
            )
        # Source pointer unchanged, staging cleaned up, original file intact
        assert Path(cfg_svc.get_active().document.storage.roots.models) == models_src
        assert (models_src / "tiny.gguf").read_bytes() == b"MODEL-WEIGHTS-V1"
        assert not list(models_dst.parent.glob(".staging-*")) if models_dst.parent.exists() else True

        # 3. Clean staged migration succeeds & updates pointer
        res = storage.migrate_location(
            StorageCategory.MODELS, str(models_dst), correlation_id="c3"
        )
        assert res.files_verified == 1
        assert (models_dst / "tiny.gguf").read_bytes() == b"MODEL-WEIGHTS-V1"
        assert Path(cfg_svc.get_active().document.storage.roots.models) == models_dst.resolve()

        # 4. BR-SYS-02: LRU cache eviction works on cache, REFUSES protected categories
        cache_dir = Path(roots.cache)
        cache_dir.mkdir(parents=True, exist_ok=True)
        f_old = cache_dir / "old.tmp"
        f_new = cache_dir / "new.tmp"
        f_old.write_bytes(b"A" * 1000)
        f_new.write_bytes(b"B" * 1000)
        os.utime(f_old, (1_700_000_000, 1_700_000_000))
        os.utime(f_new, (1_700_000_900, 1_700_000_900))

        evicted = storage.cleanup_cache_lru(
            StorageCategory.CACHE, max_bytes=1200, correlation_id="c4"
        )
        assert evicted.deleted_files == 1
        assert not f_old.exists() and f_new.exists()

        for protected in (StorageCategory.CORE_DB, StorageCategory.BACKUPS, StorageCategory.IMPORTED_DOCS):
            with pytest.raises(StorageServiceError) as prot_err:
                storage.cleanup_cache_lru(protected, max_bytes=0, correlation_id="c5")
            assert prot_err.value.code == ErrorCode.DENIED
    finally:
        db.close()


def test_portable_backup_restore_replays_deletion_ledger_preventing_resurrection(
    tmp_path: Path,
) -> None:
    clock = SystemClock()
    src_db = DualSqliteManager(
        tmp_path / "src" / "core.db", tmp_path / "src" / "knowledge.db", load_sqlite_vec=False
    )
    src_db.initialize()
    try:
        now_iso = clock.now_utc().isoformat()
        with src_db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO memory(id, kind, content, is_encrypted, sensitivity, source_ref, status, revision, created_at, updated_at)
                VALUES ('mem-keep', 'fact', 'Prefers concise answers', 0, 'normal', 'user', 'active', 1, ?, ?),
                       ('mem-delete-later', 'fact', 'Old deleted secret', 0, 'sensitive', 'user', 'active', 1, ?, ?)
                """,
                (now_iso, now_iso, now_iso, now_iso),
            )

        backup_svc = BackupService(src_db, clock, argon2_params=FAST_ARGON2)
        archive_path = tmp_path / "backups" / "snapshot.jarvis-backup"
        meta = backup_svc.create_backup(
            archive_path, "recovery-passphrase-alpha", correlation_id="bk-1"
        )
        verified = backup_svc.verify_backup(archive_path, "recovery-passphrase-alpha")
        assert verified.core_db_sha256 == meta.core_db_sha256

        # User later hard-deletes mem-delete-later -> tombstone recorded
        src_db.record_deletion_tombstone("memory", "mem-delete-later")
        tombstones = [("memory", "mem-delete-later", clock.now_utc().isoformat())]

        # Restore older snapshot onto a new machine path while preserving tombstones (T13)
        remapped = build_default_storage_roots(tmp_path / "new_machine" / "data", tmp_path / "new_machine" / "cache")
        summary = backup_svc.restore_into_directory(
            archive_path,
            "recovery-passphrase-alpha",
            target_core_db_path=tmp_path / "new_machine" / "core.db",
            target_knowledge_db_path=tmp_path / "new_machine" / "knowledge.db",
            preserve_local_tombstones=tombstones,
            remapped_storage_roots=remapped,
        )
        assert summary.replayed_tombstones >= 1

        # Verify mem-delete-later was NOT resurrected while mem-keep survived
        check_db = DualSqliteManager(
            tmp_path / "new_machine" / "core.db",
            tmp_path / "new_machine" / "knowledge.db",
            load_sqlite_vec=False,
        )
        try:
            with check_db.core_read() as conn:
                ids = [str(r[0]) for r in conn.execute("SELECT id FROM memory").fetchall()]
            assert ids == ["mem-keep"]
        finally:
            check_db.close()
    finally:
        src_db.close()


def test_authenticated_fastapi_transport_security_and_end_to_end_routes(tmp_path: Path) -> None:
    token = "a" * 64
    settings = CoreStartupSettings(
        env="test",
        log_level="WARNING",
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
        auth_token=token,
    )
    container = build_default_container(
        settings,
        fs_port=PortableFilesystemSafetyAdapter(),
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
    )
    app = create_app(container)
    headers = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:47123"}

    with TestClient(app) as client:
        # Liveness probe works without auth
        assert client.get("/healthz").status_code == 200

        # Auth required on /v1/*
        assert client.get("/v1/health").status_code == 401
        assert client.get("/v1/health", headers={"Authorization": "Bearer wrong"}).status_code == 401

        # Anti-DNS-rebinding Host header check & zero CORS Origin check
        assert (
            client.get("/v1/health", headers={"Authorization": f"Bearer {token}", "Host": "evil.example"}).status_code
            == 403
        )
        cors_resp = client.get(
            "/v1/health",
            headers={**headers, "Origin": "https://evil.example"},
        )
        assert cors_resp.status_code == 403
        assert "access-control-allow-origin" not in {k.lower() for k in cors_resp.headers}

        # Readiness & Capabilities
        ready = client.get("/v1/ready", headers=headers)
        assert ready.status_code == 200
        assert ready.json()["status"] == "ready"
        assert "X-Request-Id" in ready.headers

        caps = client.get("/v1/system/capabilities", headers=headers)
        assert caps.status_code == 200
        assert caps.json()["recommendation"]["support_tier"] in {
            "Supported",
            "Experimental",
            "Unverified",
            "Unsupported",
        }

        # Storage 11 locations & UNC rejection over HTTP (422)
        locs = client.get("/v1/storage/locations", headers=headers)
        assert locs.status_code == 200
        assert len(locs.json()["locations"]) == 11

        unc = client.put(
            "/v1/storage/locations/core_db",
            headers=headers,
            json={"path": r"\\fileserver\share\db"},
        )
        assert unc.status_code == 422
        assert unc.json()["code"] == "UNSUPPORTED_FILESYSTEM"

        # Deny-by-default -> Grant -> R2 Challenge -> Single-Use Approve -> Replay 403
        r2_denied = client.post(
            "/v1/policy/evaluate",
            headers=headers,
            json={"tool_id": "fs.file.move", "tool_version": 1, "args": {"src": "a", "dst": "b"}},
        )
        assert r2_denied.status_code == 403

        grant_resp = client.put(
            "/v1/grants",
            headers=headers,
            json={"capability": "fs.move", "subject_type": "local_owner", "subject_id": "local_owner"},
        )
        assert grant_resp.status_code == 200

        r2_ch = client.post(
            "/v1/policy/evaluate",
            headers=headers,
            json={"tool_id": "fs.file.move", "tool_version": 1, "args": {"src": "a", "dst": "b"}},
        )
        assert r2_ch.status_code == 202
        approval = r2_ch.json()["approval"]

        dec_ok = client.post(
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
        assert dec_ok.status_code == 200
        assert dec_ok.json()["state"] == "approved"

        # Replay fails closed (403)
        dec_replay = client.post(
            f"/v1/approvals/{approval['approval_id']}/decision",
            headers=headers,
            json={
                "decision": "approve",
                "nonce": approval["nonce"],
                "bound_hash": approval["bound_hash"],
            },
        )
        assert dec_replay.status_code == 403

        # License SBOM, NOTICE, and Unknown license blocker
        sbom = client.get("/v1/licenses/sbom", headers=headers)
        assert sbom.status_code == 200
        assert sbom.json()["bomFormat"] == "CycloneDX"
        notices = client.get("/v1/licenses/notices", headers=headers)
        assert notices.status_code == 200
        assert "GPL-3.0-or-later" in notices.text

        bad_lic = client.post(
            "/v1/licenses/inventory",
            headers=headers,
            json={
                "schema_version": 1,
                "id": "bad-unknown",
                "category": "app_package",
                "name": "Mystery",
                "version_or_rev": "0.1",
                "license_spdx": "Unknown",
                "obligations": [],
                "source_url": "https://example.org",
                "notice_text": "unknown",
                "verified_at": datetime.now(tz=UTC).isoformat(),
            },
        )
        assert bad_lic.status_code == 422
        assert bad_lic.json()["code"] == "LICENSE_UNVERIFIED"

        # Sequenced SSE stream returns monotonic events with cursor support
        sse = client.get("/v1/events?after_seq=0&once=true", headers=headers)
        assert sse.status_code == 200
        assert "event: approval.required" in sse.text
        assert "event: approval.resolved" in sse.text


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific NTFS junction & Job Object test")
def test_windows_filesystem_junction_escape_and_job_object_ownership_isolation(
    tmp_path: Path,
) -> None:
    fs = WindowsFilesystemSafetyAdapter()
    ok_unc, _ = fs.is_wal_supported_path(r"\\fileserver\share\jarvis")
    assert ok_unc is False

    # Build authorized root and outside target, link NTFS junction inside root -> outside (T04)
    root_dir = tmp_path / "authorized_root"
    outside_dir = tmp_path / "outside_secret"
    root_dir.mkdir()
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("top-secret", encoding="utf-8")
    junction_path = root_dir / "escape_link"

    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction_path), str(outside_dir)],
        check=True,
        capture_output=True,
    )
    try:
        with pytest.raises(PermissionError):
            fs.resolve_within_root(str(root_dir), "escape_link\\secret.txt")
        with pytest.raises(PermissionError):
            fs.resolve_within_root(str(root_dir), "..\\outside_secret\\secret.txt")
    finally:
        if junction_path.exists():
            os.rmdir(junction_path)

    # Windows Job Object managed_local kill <= 5s vs external_local untouched (NFR-15, BR-AI-04)
    supervisor = WindowsJobProcessSupervisor()
    external_proc = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        ext_handle = supervisor.register_external(external_proc.pid, "mock-external-ollama")
        managed_handle = supervisor.spawn_managed(
            [sys.executable, "-c", "import time; time.sleep(30)"], "mock-managed-worker"
        )
        assert supervisor.is_alive(managed_handle.process_id)
        assert supervisor.is_alive(ext_handle.process_id)

        # BR-AI-04: external_local MUST NOT be killed without explicit approval
        assert supervisor.terminate_process(ext_handle, force_external_approved=False) is False
        assert supervisor.is_alive(ext_handle.process_id)

        started = time.perf_counter()
        closed = supervisor.close_all_managed()
        elapsed = time.perf_counter() - started
        assert closed == 1
        assert elapsed <= 5.0
        assert not supervisor.is_alive(managed_handle.process_id)
        assert supervisor.is_alive(ext_handle.process_id)
    finally:
        supervisor.close_all_managed()
        if external_proc.poll() is None:
            external_proc.terminate()
            external_proc.wait(timeout=5)
