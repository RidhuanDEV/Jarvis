"""Stage G1 Safety Kernel Negative Security & Regression Suite (IR-01..IR-09, IR-12, B02..B06).

All filesystem fixtures run strictly inside isolated pytest tmp_path sandboxes (ZERO owner files touched).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.application.approval_service import ApprovalError
from jarvis.application.storage_service import CACHE_OWNERSHIP_SENTINEL
from jarvis.domain.models import (
    ApprovalDecisionRequest,
    ChannelKind,
    CpuInfo,
    ErrorCode,
    GrantRecord,
    HardwareSnapshot,
    InputModality,
    OsInfo,
    SessionContext,
)
from jarvis.domain.policy import PolicyEngine
from jarvis.infrastructure.crypto import (
    Argon2Params,
    CryptoIntegrityError,
    decrypt_portable_backup,
    encrypt_portable_backup,
)
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.logging_setup import configure_logging, get_logger
from jarvis.infrastructure.provenance import (
    ArtifactProvenanceError,
    ArtifactProvenanceVerifier,
)
from jarvis.infrastructure.providers.local_runtime_manager import LocalLlmRuntimeManager
from jarvis.infrastructure.web_fetch import SafeWebFetchClient, WebFetchSecurityError
from jarvis.platform.portable_mock import (
    FrozenClock,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    SystemClock,
    UnavailableNotificationAdapter,
)
from jarvis.platform.windows.desktop_automation import WindowsDesktopAutomationAdapter
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter
from jarvis.transport.app import (
    CoreContainer,
    build_default_container,
    create_app,
    default_tool_registry,
)
from jarvis.transport.settings import CoreStartupSettings

FAST_ARGON2 = Argon2Params(time_cost=1, memory_cost_kib=16384, parallelism=1)
TOKEN = "g" * 64
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Host": "127.0.0.1:47123"}


def _make_test_app(
    tmp_path: Path, *, env: str = "test"
) -> tuple[TestClient, CoreContainer]:
    settings = CoreStartupSettings(
        env=env,  # type: ignore[arg-type]
        log_level="WARNING",
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
        auth_token=TOKEN,
        auto_start_local_llm=False,
    )
    container = build_default_container(
        settings,
        fs_port=WindowsFilesystemSafetyAdapter() if sys.platform == "win32" else PortableFilesystemSafetyAdapter(),
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
    )
    app = create_app(container)
    return TestClient(app), container


def test_ir01_cache_repoint_and_cleanup_cannot_delete_user_files_or_junction_targets(tmp_path: Path) -> None:
    """Negative vector: 2-step user-file deletion via cache repointing + cleanup(max_bytes=0) MUST fail."""
    client, container = _make_test_app(tmp_path)
    try:
        user_docs = tmp_path / "owner_docs_fixture"
        user_docs.mkdir()
        precious_a = user_docs / "thesis.docx"
        precious_b = user_docs / "tax_2026.pdf"
        precious_a.write_bytes(b"IMPORTANT_USER_DOC_A" * 50)
        precious_b.write_bytes(b"IMPORTANT_USER_DOC_B" * 50)

        # 1. Attempting to assign non-empty user folder as cache root MUST be denied (403)
        repoint = client.put(
            "/v1/storage/locations/cache",
            headers=HEADERS,
            json={"path": str(user_docs)},
        )
        assert repoint.status_code == 403
        assert repoint.json()["code"] == "DENIED"

        # 2. Even if someone manually removes the ownership sentinel from cache root, cleanup MUST refuse!
        cache_dir = Path(container.config_service.get_active().document.storage.roots.cache)
        sentinel = cache_dir / CACHE_OWNERSHIP_SENTINEL
        assert sentinel.is_file()
        sentinel.unlink()
        stray_file = cache_dir / "stray_unowned.dat"
        stray_file.write_bytes(b"DO_NOT_DELETE")
        no_sentinel = client.post(
            "/v1/storage/cleanup",
            headers=HEADERS,
            json={"category": "cache", "max_bytes": 0},
        )
        assert no_sentinel.status_code == 403
        assert stray_file.exists()

        # 3. Restore sentinel and place an NTFS junction inside cache pointing to user_docs -> junction target MUST survive!
        sentinel.write_text(
            json.dumps({"owner": "jarvis", "category": "cache", "created_at": "2026-11-27T00:00:00Z"}),
            encoding="utf-8",
        )
        link_path = cache_dir / "evil_junction"
        linked = False
        if sys.platform == "win32":
            res = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(user_docs)],
                capture_output=True,
                check=False,
            )
            linked = res.returncode == 0
        else:
            link_path.symlink_to(user_docs, target_is_directory=True)
            linked = True
        assert linked is True

        evict = client.post(
            "/v1/storage/cleanup",
            headers=HEADERS,
            json={"category": "cache", "max_bytes": 0},
        )
        assert evict.status_code == 200
        # Precious user files behind the junction MUST be 100% untouched AND sentinel preserved!
        assert precious_a.read_bytes() == b"IMPORTANT_USER_DOC_A" * 50
        assert precious_b.read_bytes() == b"IMPORTANT_USER_DOC_B" * 50
        assert sentinel.is_file()
    finally:
        container.db.close()


def test_ir02_backup_no_clobber_and_managed_root_containment(tmp_path: Path) -> None:
    """Negative vector: /v1/backups/create MUST refuse arbitrary paths AND refuse overwriting existing files."""
    client, container = _make_test_app(tmp_path)
    try:
        outside_user_file = tmp_path / "outside_important.txt"
        outside_user_file.write_text("ORIGINAL_CONTENT_MUST_SURVIVE", encoding="utf-8")

        # 1. Arbitrary path outside managed backups root -> 403 DENIED, original untouched
        escape_resp = client.post(
            "/v1/backups/create",
            headers=HEADERS,
            json={
                "archive_path": str(outside_user_file),
                "recovery_passphrase": "strong-passphrase-123",
            },
        )
        assert escape_resp.status_code == 403
        assert outside_user_file.read_text(encoding="utf-8") == "ORIGINAL_CONTENT_MUST_SURVIVE"

        # 2. First backup inside managed backups root succeeds (201)
        backups_root = Path(container.config_service.get_active().document.storage.roots.backups)
        valid_archive = backups_root / "snap_g1.jarvis-backup"
        ok_resp = client.post(
            "/v1/backups/create",
            headers=HEADERS,
            json={
                "archive_path": str(valid_archive),
                "recovery_passphrase": "strong-passphrase-123",
            },
        )
        assert ok_resp.status_code == 201
        first_bytes = valid_archive.read_bytes()

        # 3. Second backup targeting the SAME existing file -> 403 DENIED (no-clobber), bytes unchanged!
        clobber_resp = client.post(
            "/v1/backups/create",
            headers=HEADERS,
            json={
                "archive_path": str(valid_archive),
                "recovery_passphrase": "strong-passphrase-123",
            },
        )
        assert clobber_resp.status_code == 403
        assert valid_archive.read_bytes() == first_bytes

        # 4. Direct HTTP /v1/storage/migrate disabled in Stage G1 (503 UNSUPPORTED)
        mig_resp = client.post(
            "/v1/storage/migrate",
            headers=HEADERS,
            json={"category": "core_db", "target_path": str(tmp_path / "new_core")},
        )
        assert mig_resp.status_code == 503
        assert mig_resp.json()["code"] == "UNSUPPORTED"
    finally:
        container.db.close()


def test_ir03_policy_grant_scope_deduplication_and_atomic_cascade_revoke(tmp_path: Path) -> None:
    """Negative vector: grant.scope MUST be enforced, duplicate grants deduplicated, and revoke atomic."""
    engine = PolicyEngine(default_tool_registry())
    now = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    session = SessionContext(
        session_id="s-scope",
        actor_ref="local_owner",
        channel=ChannelKind.LOCAL,
        modality=InputModality.TRUSTED_UI,
    )
    scoped_grant = (
        GrantRecord(
            id="g-scoped-1",
            subject_type="local_owner",
            subject_id="local_owner",
            capability="fs.move",
            scope={"allowed_paths": [r"D:\SafeNotes"]},
        ),
    )

    # Path inside allowed scope -> reaches R2 APPROVAL_REQUIRED
    in_scope = engine.evaluate_step(
        tool_id="fs.file.move",
        tool_version=1,
        args={"source_path": r"D:\SafeNotes\a.txt", "target_path": r"D:\SafeNotes\b.txt"},
        session=session,
        grants=scoped_grant,
        now_utc=now,
    )
    assert in_scope.requires_approval is True

    # Path OUTSIDE allowed scope -> 403 DENIED!
    out_scope = engine.evaluate_step(
        tool_id="fs.file.move",
        tool_version=1,
        args={"source_path": r"D:\Secrets\key.txt", "target_path": r"D:\SafeNotes\b.txt"},
        session=session,
        grants=scoped_grant,
        now_utc=now,
    )
    assert out_scope.allowed is False and out_scope.requires_approval is False
    assert out_scope.error_code == ErrorCode.DENIED

    # Path traversal inside args -> 403 DENIED!
    traversal = engine.evaluate_step(
        tool_id="fs.file.move",
        tool_version=1,
        args={"source_path": r"D:\SafeNotes\..\Secrets\key.txt", "target_path": r"D:\SafeNotes\b.txt"},
        session=session,
        grants=scoped_grant,
        now_utc=now,
    )
    assert traversal.error_code == ErrorCode.DENIED

    # Tier-3 hard bans (delete/recycle/format/shell) unconditionally DENIED even with grants
    for bad_tool in ("fs.delete", "fs.recycle", "fs.format", "os.shell.exec", "os.gui.unrestricted"):
        r3 = engine.evaluate_step(
            tool_id=bad_tool,
            tool_version=1,
            args={},
            session=session,
            grants=scoped_grant,
            now_utc=now,
        )
        assert r3.allowed is False and r3.error_code == ErrorCode.DENIED

    # HTTP deduplication + atomic revoke invalidates pending R2 approvals
    client, container = _make_test_app(tmp_path)
    try:
        g1 = client.put("/v1/grants", headers=HEADERS, json={"capability": "fs.move"}).json()["grant_id"]
        g2 = client.put("/v1/grants", headers=HEADERS, json={"capability": "fs.move"}).json()["grant_id"]
        assert g1 == g2  # No duplicate UUID row created!

        ch = client.post(
            "/v1/policy/evaluate",
            headers=HEADERS,
            json={"tool_id": "fs.file.move", "tool_version": 1, "args": {"src": "a", "dst": "b"}},
        )
        assert ch.status_code == 202
        approval = ch.json()["approval"]

        rev = client.delete(f"/v1/grants/{g1}", headers=HEADERS)
        assert rev.status_code == 200
        assert rev.json()["canceled_approvals"] >= 1

        # Pending approval was atomically canceled on grant revoke -> cannot be approved anymore!
        late_approve = client.post(
            f"/v1/approvals/{approval['approval_id']}/decision",
            headers=HEADERS,
            json={
                "decision": "approve",
                "nonce": approval["nonce"],
                "bound_hash": approval["bound_hash"],
                "modality": "trusted_ui",
                "channel": "local",
            },
        )
        assert late_approve.status_code == 403
    finally:
        container.db.close()


def test_ir03_ir12_workflow_blocks_self_echo_replay_and_fake_step_execution(tmp_path: Path) -> None:
    """Negative vector: workflow execute MUST reject self-echo bound_hash, replay, and production mocks."""
    client, container = _make_test_app(tmp_path)
    try:
        for cap in ("system.time", "fs.move", "workflow.execute"):
            assert client.put("/v1/grants", headers=HEADERS, json={"capability": cap}).status_code == 200

        wf = client.post(
            "/v1/workflows",
            headers=HEADERS,
            json={
                "name": "R2 Workflow",
                "steps": [
                    {"tool_id": "system.time.get", "version": 1, "args": {}},
                    {"tool_id": "fs.file.move", "version": 1, "args": {"src": "a", "dst": "b"}},
                ],
            },
        ).json()["workflow"]
        dry = client.get(f"/v1/workflows/{wf['id']}/dry-run", headers=HEADERS).json()

        # 1. Self-echoing dry-run bound_hash without GUI approval_id -> rejected (202 APPROVAL_REQUIRED)
        echo_resp = client.post(
            f"/v1/workflows/{wf['id']}/execute",
            headers=HEADERS,
            json={"approved_bound_hash": dry["bound_hash"]},
        )
        assert echo_resp.status_code == 202

        # 2. Unwired WorkflowEngineService MUST still block fake step execution (zero mock completion!),
        #    while the Stage G4 wired HTTP workflow executor runs the REAL system.time.get step.
        from jarvis.application.workflow_service import WorkflowEngineService, WorkflowServiceError

        unwired = WorkflowEngineService(
            container.db,
            container.policy_engine,
            container.clock,
            approval_service=container.approval_service,
            allow_simulated_steps=False,
        )
        r0_wf = client.post(
            "/v1/workflows",
            headers=HEADERS,
            json={"name": "R0 Only", "steps": [{"tool_id": "system.time.get", "version": 1, "args": {}}]},
        ).json()["workflow"]
        with pytest.raises(WorkflowServiceError) as unwired_err:
            unwired.execute_workflow(
                r0_wf["id"],
                session=SessionContext(
                    session_id="local-session-1",
                    actor_ref="local_owner",
                    channel=ChannelKind.LOCAL,
                    modality=InputModality.TRUSTED_UI,
                ),
                grants=(),
                correlation_id="corr-unwired-wf",
            )
        assert unwired_err.value.code == ErrorCode.UNSUPPORTED

        real_exec = client.post(f"/v1/workflows/{r0_wf['id']}/execute", headers=HEADERS, json={})
        assert real_exec.status_code == 200
        exec_data = real_exec.json()
        assert exec_data["state"] == "completed"
        assert "Sekarang pukul" in exec_data["steps"][0]["note"]
        assert "Verified step completion." not in exec_data["steps"][0]["note"]

        # 3. ApprovalService single-use execution consumption blocks replay after first consume
        session = SessionContext(
            session_id="local-session-1",
            actor_ref="local_owner",
            channel=ChannelKind.LOCAL,
            modality=InputModality.TRUSTED_UI,
        )
        ch = container.approval_service.create_challenge(
            request_id="req-wf-1",
            correlation_id="corr-wf-1",
            tool_id="workflow.execute",
            tool_version=1,
            canonical_args_hash="0" * 64,
            session=session,
        )
        container.approval_service.decide(
            ch.approval_id,
            ApprovalDecisionRequest(
                decision="approve",
                nonce=ch.nonce,
                bound_hash=ch.bound_hash,
                modality=InputModality.TRUSTED_UI,
                channel=ChannelKind.LOCAL,
            ),
            session=session,
            correlation_id="corr-wf-2",
        )
        container.approval_service.consume_approved_for_execution(
            ch.approval_id,
            expected_bound_hash=ch.bound_hash,
            session_id=session.session_id,
            actor_ref=session.actor_ref,
            expected_tool_id="workflow.execute",
        )
        with pytest.raises(ApprovalError) as replay_err:
            container.approval_service.consume_approved_for_execution(
                ch.approval_id,
                expected_bound_hash=ch.bound_hash,
                session_id=session.session_id,
                actor_ref=session.actor_ref,
            )
        assert replay_err.value.code == ErrorCode.DENIED
    finally:
        container.db.close()


@pytest.mark.asyncio
async def test_ir04_web_fetch_pinned_socket_builder_and_streaming_byte_cap() -> None:
    """Negative vector: DNS-pinned socket URL preserves Host/SNI AND streaming cap aborts > max_bytes."""
    clock = FrozenClock(datetime(2026, 11, 27, 12, 0, tzinfo=UTC))

    # 1. Verify pinned socket request connects directly to validated IP with Host & SNI intact
    pinned_url, hdrs, exts = SafeWebFetchClient._build_pinned_request_params(
        "https://docs.example.com/guide?v=1", "93.184.216.34", use_pinned_socket=True
    )
    assert pinned_url == "https://93.184.216.34:443/guide?v=1"
    assert hdrs["Host"] == "docs.example.com"
    assert exts["sni_hostname"] == b"docs.example.com"

    # 2. Streaming byte cap aborts oversized chunked response WITHOUT buffering unbounded payload
    class _OversizedStream(httpx.AsyncByteStream):
        def __init__(self) -> None:
            self.chunks_yielded = 0

        async def __aiter__(self):  # type: ignore[no-untyped-def]
            for _ in range(500):
                self.chunks_yielded += 1
                yield b"X" * 8192

    stream = _OversizedStream()

    def _mock_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=stream)

    fetcher = SafeWebFetchClient(
        clock,
        dns_resolver=lambda _h, _p: ["93.184.216.34"],
        transport=httpx.MockTransport(_mock_handler),
        max_bytes=32_768,
    )
    with pytest.raises(WebFetchSecurityError) as err:
        await fetcher.fetch_read_only("https://docs.example.com/huge", offline_mode=False)
    assert err.value.code == ErrorCode.INVALID_ARGS
    assert stream.chunks_yielded <= 6  # Aborted immediately upon crossing 32 KiB (never read all 500 chunks!)


@pytest.mark.asyncio
async def test_ir05_provenance_verifier_blocks_unverified_or_tampered_runtime_and_model(tmp_path: Path) -> None:
    """Negative vector: LocalLlmRuntimeManager MUST NOT spawn unverified or hash-mismatched llama-server/GGUF."""
    rt_dir = tmp_path / "runtimes" / "llama-cpu"
    rt_dir.mkdir(parents=True)
    bin_path = rt_dir / "llama-server.exe"
    bin_path.write_bytes(b"FAKE-BINARY-V1")

    mod_dir = tmp_path / "models"
    mod_dir.mkdir(parents=True)
    gguf_path = mod_dir / "qwen3-4b.gguf"
    gguf_path.write_bytes(b"FAKE-GGUF-V1")

    manifest_path = tmp_path / "trusted_artifacts.json"
    # 1. Missing manifest -> fails closed, 0 processes spawned!
    sup = InMemoryProcessSupervisor()
    db = DualSqliteManager(tmp_path / "c.db", tmp_path / "k.db", load_sqlite_vec=False)
    db.initialize()
    try:
        from jarvis.application.ai_registry_service import AiRegistryService
        from jarvis.infrastructure.event_bus import SequencedEventBus

        ai_reg = AiRegistryService(db, SystemClock(), SequencedEventBus())
        hw = HardwareSnapshot(
            id="hw1",
            os_info=OsInfo(system="Windows", release="11", version="10.0", arch="AMD64"),
            cpu=CpuInfo(model_name="Test CPU", physical_cores=4, logical_cores=8),
            ram_total_bytes=16 * 1024**3,
            ram_available_bytes=8 * 1024**3,
            captured_at=datetime.now(tz=UTC),
        )
        mgr = LocalLlmRuntimeManager(
            supervisor=sup,
            ai_registry=ai_reg,
            runtimes_dirs=(tmp_path / "runtimes",),
            models_dirs=(mod_dir,),
            hardware_snapshot=hw,
            provenance_verifier=ArtifactProvenanceVerifier(manifest_path=manifest_path, require_manifest=True),
        )
        st1 = await mgr.start_if_available()
        assert st1.ready is False
        assert sup.close_all_managed() == 0

        # 2. Tampered hash in manifest -> fails closed, 0 processes spawned!
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "artifacts": {
                        "llama-server.exe": "0" * 64,
                        "qwen3-4b.gguf": hashlib.sha256(b"FAKE-GGUF-V1").hexdigest(),
                    },
                }
            ),
            encoding="utf-8",
        )
        st2 = await mgr.start_if_available()
        assert st2.ready is False
        assert "SHA-256" in st2.note
        assert sup.close_all_managed() == 0

        # 3. Direct verifier accepts exact matching SHA-256 and rejects untrusted files
        good_verifier = ArtifactProvenanceVerifier(
            trusted_digests={"qwen3-4b.gguf": hashlib.sha256(b"FAKE-GGUF-V1").hexdigest()}
        )
        assert good_verifier.verify_artifact(gguf_path) == hashlib.sha256(b"FAKE-GGUF-V1").hexdigest()
        with pytest.raises(ArtifactProvenanceError):
            good_verifier.verify_artifact(bin_path)

        # 4. LiveVoiceEngine refuses to load unverified Silero/Whisper/Piper models when provenance verifier is wired
        from jarvis.infrastructure.live_voice_engine import LiveVoiceEngine

        (mod_dir / "silero_vad.onnx").write_bytes(b"UNVERIFIED-VAD")
        whisper_dir = mod_dir / "faster-whisper-small"
        whisper_dir.mkdir()
        (whisper_dir / "model.bin").write_bytes(b"UNVERIFIED-WHISPER")

        async def _dummy_turn(text: str) -> tuple[str, str, bool]:
            return (text, "direct", False)

        voice_eng = LiveVoiceEngine(
            models_dirs=(mod_dir,),
            turn_callback=_dummy_turn,
            provenance_verifier=ArtifactProvenanceVerifier(manifest_path=manifest_path, require_manifest=True),
        )
        assert voice_eng._ensure_vad_loaded() is None  # noqa: SLF001
        assert voice_eng._ensure_stt_loaded() is None  # noqa: SLF001
        assert voice_eng.snapshot().error is not None
    finally:
        db.close()


def test_ir07_ir08_transport_host_ipv6_chunked_422_os_lock_and_direct_route_gateway(tmp_path: Path) -> None:
    """Negative vector: Host IPv6/empty check, chunked >256KiB cap, 422 ErrorEnvelope, OS lock, screen/web grants."""
    client, container = _make_test_app(tmp_path)
    try:
        # 1. Valid IPv6 bracketed Host [::1]:47123 works (DEF-22 fixed)
        ipv6_ok = client.get(
            "/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}", "Host": "[::1]:47123"},
        )
        assert ipv6_ok.status_code == 200
        assert ipv6_ok.json()["capability_states"]["file_move"] == "ready_tier2_gui_approval"

        # 2. Empty Host header rejected (403)
        empty_host = client.get(
            "/v1/health",
            headers={"Authorization": f"Bearer {TOKEN}", "Host": ""},
        )
        assert empty_host.status_code == 403

        # 3. HTTP 422 validation error returns canonical ErrorEnvelope (DEF-22 fixed)
        bad_payload = client.post(
            "/v1/tasks",
            headers=HEADERS,
            json={"unexpected_field": 123},
        )
        assert bad_payload.status_code == 422
        assert bad_payload.json()["code"] == "INVALID_ARGS"

        # 4. Oversized chunked body without Content-Length blocked with 413!
        def _big_chunks():  # type: ignore[no-untyped-def]
            for _ in range(40):
                yield b"a" * 8192

        chunked = client.post(
            "/v1/tasks",
            headers={**HEADERS, "Content-Type": "application/json"},
            content=_big_chunks(),
        )
        assert chunked.status_code == 413

        # 5. Direct /v1/screen/analyze without screen.read grant MUST be denied (403)
        scr_no_grant = client.post(
            "/v1/screen/analyze",
            headers=HEADERS,
            json={"window_selector": "active", "explicit_user_request": True},
        )
        assert scr_no_grant.status_code == 403

        # 6. Direct /v1/web/fetch without web.search grant MUST be denied (403/503)
        web_no_grant = client.post(
            "/v1/web/fetch",
            headers=HEADERS,
            json={"url": "https://example.com"},
        )
        assert web_no_grant.status_code in (403, 503)

        # 7. Server-side OS lock cannot be bypassed by client passing is_os_locked=False!
        assert client.put("/v1/grants", headers=HEADERS, json={"capability": "system.time"}).status_code == 200
        assert client.post("/v1/session/lock", headers=HEADERS, json={"reason": "win_l"}).status_code == 200
        bypass_lock = client.post(
            "/v1/policy/evaluate",
            headers=HEADERS,
            json={"tool_id": "system.time.get", "tool_version": 1, "is_os_locked": False},
        )
        assert bypass_lock.status_code == 403
        assert client.post("/v1/session/unlock", headers=HEADERS).status_code == 200
    finally:
        container.db.close()


def test_ir09_ir12_no_fake_success_on_disabled_launch_file_move_or_production_notifications(tmp_path: Path) -> None:
    """Negative vector: disabled launch, disabled G1 file_move, and production container MUST NOT fake success."""
    # 1. WindowsDesktopAutomationAdapter(allow_live_launch=False) MUST return False (never fake True)
    adapter = WindowsDesktopAutomationAdapter(allow_live_launch=False)
    assert adapter.launch_allowlisted_app("calculator") is False

    # 2. Production non-test container wires real WindowsToastNotificationAdapter (NEVER FakeNotificationAdapter!)
    from jarvis.platform.portable_mock import FakeNotificationAdapter
    from jarvis.platform.windows.notifications import WindowsToastNotificationAdapter

    prod_client, prod_container = _make_test_app(tmp_path / "prod_case", env="production")
    try:
        assert not isinstance(prod_container.notification_port, FakeNotificationAdapter)
        if sys.platform == "win32":
            assert isinstance(prod_container.notification_port, WindowsToastNotificationAdapter)
            assert WindowsToastNotificationAdapter(allow_live_toast=False).send_local_notification("t", "b") is False
        else:
            assert isinstance(prod_container.notification_port, UnavailableNotificationAdapter)
            assert prod_container.notification_port.send_local_notification("t", "b") is False

        rem = prod_client.put(
            "/v1/remote/config",
            headers=HEADERS,
            json={"enabled": True, "bind_address": "127.0.0.1", "bind_port": 47443},
        )
        assert rem.status_code == 503

        # 3. fs.file.move execution disabled in G1 per Owner Decision A2
        move_res = prod_container.turn_orchestrator.execute_approved_file_move(
            approval_id="any",
            root_path=str(tmp_path),
            source_relative_path="a.txt",
            target_relative_path="b.txt",
            correlation_id="c-move",
        )
        assert move_res.verified is False
        assert move_res.error_code == ErrorCode.UNSUPPORTED
    finally:
        prod_container.db.close()


def test_def23_def24_log_traceback_redaction_and_argon2_header_bounds() -> None:
    """Negative vector: secrets inside exception tracebacks MUST be redacted; unbounded Argon2 headers rejected."""
    buf = io.StringIO()
    configure_logging("INFO", stream=buf)
    logger = get_logger("test.redaction")
    try:
        raise RuntimeError("Failed with Bearer supersecretjwtvalue123456 and sk-secretapikey1234567890")
    except RuntimeError:
        logger.exception(
            "boom",
            recovery_passphrase="my-secret-passphrase",
            bearer_token="tok-12345",
            pairing_code="987654",
        )
    logged = buf.getvalue()
    assert "supersecretjwtvalue123456" not in logged
    assert "sk-secretapikey1234567890" not in logged
    assert "my-secret-passphrase" not in logged
    assert "tok-12345" not in logged
    assert "987654" not in logged
    assert "[REDACTED]" in logged

    # Crafted Argon2id header requesting 8 GiB RAM (8_388_608 KiB) MUST fail before KDF execution!
    malicious_header = json.dumps(
        {
            "v": 1,
            "kdf": "argon2id",
            "t": 3,
            "m": 8_388_608,
            "p": 2,
            "salt": base64.b64encode(b"0" * 16).decode("ascii"),
            "nonce": base64.b64encode(b"1" * 12).decode("ascii"),
        }
    ).encode("utf-8")
    crafted = b"JRVB" + len(malicious_header).to_bytes(4, "big") + malicious_header + (b"\x00" * 32)
    with pytest.raises(CryptoIntegrityError) as kdf_err:
        decrypt_portable_backup(crafted, "valid-passphrase-123")
    assert "bounds" in str(kdf_err.value).lower()

    # Valid encrypted archive still decrypts cleanly
    good = encrypt_portable_backup(b"hello-backup", "valid-passphrase-123", params=FAST_ARGON2)
    assert decrypt_portable_backup(good, "valid-passphrase-123") == b"hello-backup"
