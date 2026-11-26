"""Unit & property tests for deterministic R0-R3 Policy Engine & R2 Approval lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from jarvis.application.approval_service import ApprovalError, ApprovalService
from jarvis.domain.models import (
    ApprovalDecisionRequest,
    ApprovalState,
    ChannelKind,
    ErrorCode,
    GrantRecord,
    InputModality,
    RiskClass,
    SessionContext,
    ToolProposal,
    ToolSpec,
    ToolStepProposal,
    canonical_json_hash,
)
from jarvis.domain.policy import PolicyEngine
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus
from jarvis.platform.portable_mock import FrozenClock
from jarvis.transport.app import default_tool_registry


def _make_session(**overrides: object) -> SessionContext:
    base: dict[str, object] = {
        "session_id": "sess-local-1",
        "actor_ref": "local_owner",
        "channel": ChannelKind.LOCAL,
        "modality": InputModality.TRUSTED_UI,
        "is_os_locked": False,
        "is_suspended": False,
        "is_muted": False,
        "offline_mode": True,
        "untrusted_origin": False,
    }
    base.update(overrides)
    return SessionContext.model_validate(base)


def _grant(capability: str, *, revoked: bool = False, expired: bool = False) -> GrantRecord:
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    return GrantRecord(
        id=f"grant-{capability}",
        subject_type="local_owner",
        subject_id="local_owner",
        capability=capability,
        expires_at=(now - timedelta(seconds=10)) if expired else (now + timedelta(hours=1)),
        revoked_at=now if revoked else None,
    )


@pytest.mark.parametrize(
    "prohibited_tool",
    [
        "os.shell.exec",
        "shell.powershell",
        "code.exec",
        "fs.delete_permanent",
        "vault.extract",
        "payment.transfer",
        "email.send",
        "email.delete",
        "iot.lock",
        "iot.alarm",
        "iot.heater",
        "iot.safety.override",
    ],
)
def test_r3_hard_bans_always_denied_even_with_grants(prohibited_tool: str) -> None:
    engine = PolicyEngine(default_tool_registry())
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
    grants = (_grant("shell.exec"), _grant("fs.permanent_delete"), _grant("os.volume"))

    decision = engine.evaluate_step(
        tool_id=prohibited_tool,
        tool_version=1,
        args={"cmd": "whoami"},
        session=_make_session(offline_mode=False),
        grants=grants,
        now_utc=now,
    )
    assert not decision.allowed
    assert not decision.requires_approval
    assert decision.risk == RiskClass.R3
    assert decision.error_code == ErrorCode.DENIED


def test_deny_by_default_and_br01_precedence_guards() -> None:
    engine = PolicyEngine(default_tool_registry())
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

    # 1. Zero grants -> DENIED (DEC-012)
    d_no_grant = engine.evaluate_step(
        tool_id="os.volume.set",
        tool_version=1,
        args={"percent": 40},
        session=_make_session(),
        grants=(),
        now_utc=now,
    )
    assert d_no_grant.error_code == ErrorCode.DENIED

    # 2. Active grant -> R1 allowed on unlocked local session
    d_ok = engine.evaluate_step(
        tool_id="os.volume.set",
        tool_version=1,
        args={"percent": 40},
        session=_make_session(),
        grants=(_grant("os.volume"),),
        now_utc=now,
    )
    assert d_ok.allowed and not d_ok.requires_approval

    # 3. Revoked or expired grant -> DENIED
    for bad_grant in (_grant("os.volume", revoked=True), _grant("os.volume", expired=True)):
        d_bad = engine.evaluate_step(
            tool_id="os.volume.set",
            tool_version=1,
            args={"percent": 40},
            session=_make_session(),
            grants=(bad_grant,),
            now_utc=now,
        )
        assert d_bad.error_code == ErrorCode.DENIED

    # 4. OS locked / suspended / muted voice -> DENIED
    for locked_ctx in (
        _make_session(is_os_locked=True),
        _make_session(is_suspended=True),
        _make_session(is_muted=True, modality=InputModality.VOICE),
    ):
        d_lock = engine.evaluate_step(
            tool_id="os.volume.set",
            tool_version=1,
            args={"percent": 40},
            session=locked_ctx,
            grants=(_grant("os.volume"),),
            now_utc=now,
        )
        assert d_lock.error_code == ErrorCode.DENIED

    # 5. Untrusted passive data cannot trigger mutating R1/R2 (BR-15)
    d_untrusted = engine.evaluate_step(
        tool_id="os.volume.set",
        tool_version=1,
        args={"percent": 90},
        session=_make_session(untrusted_origin=True),
        grants=(_grant("os.volume"),),
        now_utc=now,
    )
    assert d_untrusted.error_code == ErrorCode.DENIED

    # 6. Offline mode blocks network tools with OFFLINE (BR-16)
    d_offline = engine.evaluate_step(
        tool_id="web.search.query",
        tool_version=1,
        args={"q": "weather"},
        session=_make_session(offline_mode=True),
        grants=(_grant("web.search"),),
        now_utc=now,
    )
    assert d_offline.error_code == ErrorCode.OFFLINE

    # 7. Remote channel cannot invoke R2
    d_remote_r2 = engine.evaluate_step(
        tool_id="fs.file.move",
        tool_version=1,
        args={"src": "a", "dst": "b"},
        session=_make_session(channel=ChannelKind.REMOTE, modality=InputModality.REMOTE_API),
        grants=(_grant("fs.move"),),
        now_utc=now,
    )
    assert d_remote_r2.error_code == ErrorCode.DENIED
    assert not d_remote_r2.requires_approval


def test_proposal_max_5_steps_enforced() -> None:
    steps = tuple(
        ToolStepProposal(tool_id="system.time.get", version=1, args={}) for _ in range(5)
    )
    valid = ToolProposal(steps=steps)
    engine = PolicyEngine(default_tool_registry())
    assert engine.validate_proposal_bounds(valid) is None

    with pytest.raises(ValidationError):
        ToolProposal(
            steps=tuple(
                ToolStepProposal(tool_id="system.time.get", version=1, args={}) for _ in range(6)
            )
        )


def test_r2_approval_single_use_replay_expiry_voice_block_target_change_and_lock(
    tmp_path: Path,
) -> None:
    clock = FrozenClock(datetime(2026, 11, 26, 12, 0, tzinfo=UTC))
    db = DualSqliteManager(
        tmp_path / "core.db", tmp_path / "knowledge.db", load_sqlite_vec=False
    )
    db.initialize()
    try:
        bus = SequencedEventBus()
        svc = ApprovalService(db, clock, bus)
        session = _make_session()
        args_hash = canonical_json_hash({"src": "doc.pdf", "dst": "archive/doc.pdf"})

        # 1. Voice and remote approval attempts MUST fail with DENIED
        ch1 = svc.create_challenge(
            request_id="req-1",
            correlation_id="corr-1",
            tool_id="fs.file.move",
            tool_version=1,
            canonical_args_hash=args_hash,
            session=session,
            target_snapshot_hash="snap-v1",
            summary="Move doc.pdf",
        )
        for bad_req in (
            ApprovalDecisionRequest(
                decision="approve",
                nonce=ch1.nonce,
                bound_hash=ch1.bound_hash,
                modality=InputModality.VOICE,
                channel=ChannelKind.LOCAL,
            ),
            ApprovalDecisionRequest(
                decision="approve",
                nonce=ch1.nonce,
                bound_hash=ch1.bound_hash,
                modality=InputModality.TRUSTED_UI,
                channel=ChannelKind.REMOTE,
            ),
        ):
            with pytest.raises(ApprovalError) as exc_info:
                svc.decide(ch1.approval_id, bad_req, session=session, correlation_id="corr-1b")
            assert exc_info.value.code == ErrorCode.DENIED

        # 2. Valid local trusted UI approval succeeds once; immediate replay MUST fail!
        good_req = ApprovalDecisionRequest(
            decision="approve",
            nonce=ch1.nonce,
            bound_hash=ch1.bound_hash,
            modality=InputModality.TRUSTED_UI,
            channel=ChannelKind.LOCAL,
            current_target_snapshot_hash="snap-v1",
        )
        assert (
            svc.decide(ch1.approval_id, good_req, session=session, correlation_id="corr-1c")
            == ApprovalState.APPROVED
        )
        with pytest.raises(ApprovalError) as replay_err:
            svc.decide(ch1.approval_id, good_req, session=session, correlation_id="corr-1d")
        assert replay_err.value.code == ErrorCode.DENIED

        # 3. Target snapshot changed after preview -> TARGET_CHANGED (T04/T06)
        ch2 = svc.create_challenge(
            request_id="req-2",
            correlation_id="corr-2",
            tool_id="fs.file.move",
            tool_version=1,
            canonical_args_hash=args_hash,
            session=session,
            target_snapshot_hash="snap-original",
        )
        with pytest.raises(ApprovalError) as toctou_err:
            svc.decide(
                ch2.approval_id,
                ApprovalDecisionRequest(
                    decision="approve",
                    nonce=ch2.nonce,
                    bound_hash=ch2.bound_hash,
                    current_target_snapshot_hash="snap-tampered",
                ),
                session=session,
                correlation_id="corr-2b",
            )
        assert toctou_err.value.code == ErrorCode.TARGET_CHANGED

        # 4. 60s TTL expiration -> APPROVAL_EXPIRED (BR-03)
        ch3 = svc.create_challenge(
            request_id="req-3",
            correlation_id="corr-3",
            tool_id="fs.file.move",
            tool_version=1,
            canonical_args_hash=args_hash,
            session=session,
        )
        clock.advance_seconds(61)
        with pytest.raises(ApprovalError) as exp_err:
            svc.decide(
                ch3.approval_id,
                ApprovalDecisionRequest(
                    decision="approve", nonce=ch3.nonce, bound_hash=ch3.bound_hash
                ),
                session=session,
                correlation_id="corr-3b",
            )
        assert exp_err.value.code == ErrorCode.APPROVAL_EXPIRED

        # 5. Session lock mass-cancels pending approvals (BR-21)
        ch4 = svc.create_challenge(
            request_id="req-4",
            correlation_id="corr-4",
            tool_id="storage.location.migrate",
            tool_version=1,
            canonical_args_hash=args_hash,
            session=session,
        )
        assert svc.cancel_all_pending_on_lock(reason="win_lock", correlation_id="corr-lock") == 1
        with pytest.raises(ApprovalError) as lock_err:
            svc.decide(
                ch4.approval_id,
                ApprovalDecisionRequest(
                    decision="approve", nonce=ch4.nonce, bound_hash=ch4.bound_hash
                ),
                session=session,
                correlation_id="corr-4b",
            )
        assert lock_err.value.code == ErrorCode.DENIED
    finally:
        db.close()


@given(
    pairs=st.lists(
        st.tuples(
            st.text(min_size=1, max_size=12),
            st.one_of(st.integers(-1000, 1000), st.text(max_size=20), st.booleans()),
        ),
        min_size=1,
        max_size=10,
        unique_by=lambda kv: kv[0],
    )
)
def test_canonical_json_hash_is_key_order_invariant(
    pairs: list[tuple[str, int | str | bool]],
) -> None:
    forward = dict(pairs)
    reversed_dict = dict(reversed(pairs))
    assert canonical_json_hash(forward) == canonical_json_hash(reversed_dict)


def test_tool_spec_r3_registration_still_blocked() -> None:
    custom = {
        ("custom.danger.op", 1): ToolSpec(
            tool_id="custom.danger.op",
            version=1,
            risk=RiskClass.R3,
            channels=(ChannelKind.LOCAL,),
            capability="custom.op",
            timeout_ms=1000,
            idempotent=False,
            verification="none",
        )
    }
    engine = PolicyEngine(custom)
    res = engine.evaluate_step(
        tool_id="custom.danger.op",
        tool_version=1,
        args={},
        session=_make_session(),
        grants=(_grant("custom.op"),),
        now_utc=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
    )
    assert res.error_code == ErrorCode.DENIED
