"""Deterministic R0-R3 Policy Engine & R2 Approval Binding (BR-01..BR-08, BR-16, BR-20, BR-21)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.domain.models import (
    ChannelKind,
    ErrorCode,
    GrantRecord,
    InputModality,
    RiskClass,
    SessionContext,
    ToolProposal,
    ToolSpec,
    canonical_json_hash,
)

# BR-01 / R3 hard product prohibitions — always rejected deterministically across all channels.
PROHIBITED_TOOL_PREFIXES: tuple[str, ...] = (
    "os.shell",
    "shell.",
    "code.",
    "dev.",
    "git.",
    "fs.delete_permanent",
    "fs.shred",
    "vault.extract",
    "vault.autofill",
    "credential.",
    "payment.",
    "finance.transfer",
    "email.send",
    "email.delete",
    "iot.lock",
    "iot.alarm",
    "iot.heater",
    "iot.safety.",
    "system.elevate",
)

PROHIBITED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "shell.exec",
        "code.exec",
        "fs.permanent_delete",
        "credential.extract",
        "payment.execute",
        "email.mutate",
        "iot.safety_actuation",
        "os.admin_elevate",
    }
)

APPROVAL_TTL_SECONDS: int = 60
MAX_WORKFLOW_STEPS: int = 5


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    requires_approval: bool
    error_code: ErrorCode | None
    reason: str
    risk: RiskClass
    canonical_args_hash: str
    bound_hash: str | None = None


def is_prohibited_r3(tool_id: str, capability: str, risk: RiskClass) -> bool:
    """Return True if the tool or capability violates R3 hard product bans (BR-01)."""
    if risk == RiskClass.R3:
        return True
    normalized_tool = tool_id.strip().lower()
    if normalized_tool in PROHIBITED_TOOL_PREFIXES:
        return True
    for prefix in PROHIBITED_TOOL_PREFIXES:
        if normalized_tool.startswith(prefix):
            return True
    return capability.strip().lower() in PROHIBITED_CAPABILITIES


def compute_approval_bound_hash(
    *,
    tool_id: str,
    tool_version: int,
    canonical_args_hash: str,
    session_id: str,
    actor_ref: str,
    target_snapshot_hash: str | None,
) -> str:
    """Bind R2 approval to tool, version, canonical args, local session, actor, and target snapshot (BR-03)."""
    return canonical_json_hash(
        {
            "tool_id": tool_id,
            "tool_version": tool_version,
            "canonical_args_hash": canonical_args_hash,
            "session_id": session_id,
            "actor_ref": actor_ref,
            "target_snapshot_hash": target_snapshot_hash or "",
        }
    )


def hash_approval_nonce(nonce: str) -> str:
    """Hash raw single-use nonce with SHA-256 before persistence."""
    return hashlib.sha256(nonce.encode("utf-8")).hexdigest()


class PolicyEngine:
    """Pure deterministic policy evaluator enforcing BR-01 absolute authority hierarchy."""

    def __init__(self, tool_registry: dict[tuple[str, int], ToolSpec]) -> None:
        self._registry = dict(tool_registry)

    def lookup_tool(self, tool_id: str, version: int) -> ToolSpec | None:
        return self._registry.get((tool_id, version))

    def validate_proposal_bounds(self, proposal: ToolProposal) -> PolicyDecision | None:
        """Check proposal step count and immediate R3 bans before step-by-step evaluation."""
        if len(proposal.steps) == 0 or len(proposal.steps) > MAX_WORKFLOW_STEPS:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.INVALID_ARGS,
                reason=f"Proposal must contain 1..{MAX_WORKFLOW_STEPS} steps (BR-06).",
                risk=RiskClass.R3,
                canonical_args_hash=canonical_json_hash([]),
            )
        for step in proposal.steps:
            spec = self.lookup_tool(step.tool_id, step.version)
            if spec is None:
                if is_prohibited_r3(step.tool_id, "", RiskClass.R0):
                    return PolicyDecision(
                        allowed=False,
                        requires_approval=False,
                        error_code=ErrorCode.DENIED,
                        reason=f"Tool '{step.tool_id}' is permanently prohibited (R3).",
                        risk=RiskClass.R3,
                        canonical_args_hash=canonical_json_hash(step.args),
                    )
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    error_code=ErrorCode.NOT_FOUND,
                    reason=f"Unregistered tool '{step.tool_id}' v{step.version}.",
                    risk=RiskClass.R3,
                    canonical_args_hash=canonical_json_hash(step.args),
                )
            if is_prohibited_r3(spec.tool_id, spec.capability, spec.risk):
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    error_code=ErrorCode.DENIED,
                    reason=f"Tool '{spec.tool_id}' is permanently prohibited (R3).",
                    risk=RiskClass.R3,
                    canonical_args_hash=canonical_json_hash(step.args),
                )
        return None

    def evaluate_step(
        self,
        *,
        tool_id: str,
        tool_version: int,
        args: dict[str, Any],
        session: SessionContext,
        grants: tuple[GrantRecord, ...],
        now_utc: datetime,
        target_snapshot_hash: str | None = None,
    ) -> PolicyDecision:
        """Evaluate one tool invocation against BR-01 precedence order."""
        args_hash = canonical_json_hash(args)
        spec = self.lookup_tool(tool_id, tool_version)

        # 1. Hard R3 product bans — highest authority
        if spec is None:
            if is_prohibited_r3(tool_id, "", RiskClass.R0):
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    error_code=ErrorCode.DENIED,
                    reason=f"Tool '{tool_id}' is permanently prohibited (R3).",
                    risk=RiskClass.R3,
                    canonical_args_hash=args_hash,
                )
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.NOT_FOUND,
                reason=f"Tool '{tool_id}' v{tool_version} is not registered.",
                risk=RiskClass.R3,
                canonical_args_hash=args_hash,
            )

        if is_prohibited_r3(spec.tool_id, spec.capability, spec.risk):
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason=f"Tool '{spec.tool_id}' is permanently prohibited (R3).",
                risk=RiskClass.R3,
                canonical_args_hash=args_hash,
            )

        # 2. Untrusted content cannot execute side effects or elevate privilege (BR-01, BR-15)
        if session.untrusted_origin and spec.risk != RiskClass.R0:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason="Untrusted passive data cannot trigger mutating actions (BR-15).",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        # 3. OS session state: locked / suspended / muted blocks execution (BR-01, BR-21)
        if session.is_os_locked or session.is_suspended:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason="Session is locked or suspended; action denied (BR-21).",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        if session.is_muted and session.modality == InputModality.VOICE:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason="Microphone is muted; voice-initiated execution blocked.",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        # 4. Offline mode guard (BR-16)
        if session.offline_mode and spec.requires_network:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.OFFLINE,
                reason="Offline mode is active; external network tools are blocked (BR-16).",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        # 5. Channel scope check (local vs remote; R2 strictly local only)
        if session.channel not in spec.channels:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason=f"Tool '{spec.tool_id}' is not permitted on channel '{session.channel}'.",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        if spec.risk == RiskClass.R2 and session.channel != ChannelKind.LOCAL:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason="R2 sensitive actions cannot be executed or approved over remote channels.",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        # 6. Explicit capability grant check (deny-by-default, DEC-012)
        if not self._has_active_grant(grants, session.actor_ref, spec.capability, now_utc):
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason=f"Missing active grant for capability '{spec.capability}' (deny-by-default).",
                risk=spec.risk,
                canonical_args_hash=args_hash,
            )

        # 7. Per-action R2 approval requirement (BR-03)
        if spec.risk == RiskClass.R2:
            bound_hash = compute_approval_bound_hash(
                tool_id=spec.tool_id,
                tool_version=spec.version,
                canonical_args_hash=args_hash,
                session_id=session.session_id,
                actor_ref=session.actor_ref,
                target_snapshot_hash=target_snapshot_hash,
            )
            return PolicyDecision(
                allowed=False,
                requires_approval=True,
                error_code=ErrorCode.APPROVAL_REQUIRED,
                reason="R2 action requires single-use local trusted UI approval.",
                risk=spec.risk,
                canonical_args_hash=args_hash,
                bound_hash=bound_hash,
            )

        # 8. R0 and R1 permitted once all gates pass
        return PolicyDecision(
            allowed=True,
            requires_approval=False,
            error_code=None,
            reason="Permitted by deterministic policy.",
            risk=spec.risk,
            canonical_args_hash=args_hash,
        )

    @staticmethod
    def _has_active_grant(
        grants: tuple[GrantRecord, ...],
        actor_ref: str,
        capability: str,
        now_utc: datetime,
    ) -> bool:
        for grant in grants:
            if grant.capability != capability:
                continue
            if grant.subject_id != actor_ref:
                continue
            if grant.revoked_at is not None:
                continue
            if grant.expires_at is not None and grant.expires_at <= now_utc:
                continue
            return True
        return False
