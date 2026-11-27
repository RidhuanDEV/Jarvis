"""Deterministic R0-R3 Policy Engine & R2 Approval Binding (BR-01..BR-08, BR-16, BR-20, BR-21)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from jarvis.domain.app_catalog import is_prohibited_app_query, is_prohibited_binary_target
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
    "fs.delete",
    "fs.remove",
    "fs.unlink",
    "fs.recycle",
    "fs.trash",
    "fs.shred",
    "fs.format",
    "disk.format",
    "storage.wipe",
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
    "os.gui.unrestricted",
)

PROHIBITED_CAPABILITIES: frozenset[str] = frozenset(
    {
        "shell.exec",
        "code.exec",
        "fs.permanent_delete",
        "fs.delete",
        "fs.recycle",
        "fs.delete_user_data",
        "disk.format",
        "credential.extract",
        "payment.execute",
        "email.mutate",
        "iot.safety_actuation",
        "os.admin_elevate",
        "os.gui.unrestricted",
    }
)

APPROVAL_TTL_SECONDS: int = 60
MAX_WORKFLOW_STEPS: int = 5

# DEC-012 Amendment (Stage G2 / B09-B10): Tier-1 safe local actions permitted automatically
# when tier1_auto_allow is enabled, OS is unlocked, local channel, non-untrusted, and not explicitly revoked.
TIER1_ORDINARY_SAFE_TOOLS: frozenset[str] = frozenset(
    {
        "system.time.get",
        "os.app.launch",
        "os.volume.set",
        "fs.metadata.search",
        "fs.file.open",
    }
)


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

    def __init__(
        self,
        tool_registry: dict[tuple[str, int], ToolSpec],
        *,
        tier1_auto_allow: bool = False,
    ) -> None:
        self._registry = dict(tool_registry)
        self._tier1_auto_allow = tier1_auto_allow

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

        # Defense-in-depth: block Tier-3 LOLBins/shells targeted via os.app.launch regardless of grants
        if spec.tool_id == "os.app.launch":
            raw_app_id = str(args.get("app_id", "")).strip()
            raw_target = str(args.get("target", "")).strip()
            if (raw_app_id and is_prohibited_app_query(raw_app_id)) or (
                raw_target and is_prohibited_binary_target(raw_target)
            ):
                return PolicyDecision(
                    allowed=False,
                    requires_approval=False,
                    error_code=ErrorCode.DENIED,
                    reason=f"Application target '{raw_app_id or raw_target}' is permanently prohibited (Tier-3).",
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

        # 6. Explicit capability grant check with canonical scope enforcement (DEC-012)
        has_explicit_grant = self._has_active_grant(
            grants,
            session.actor_ref,
            spec.capability,
            now_utc,
            tool_id=spec.tool_id,
            args=args,
        )
        tier1_eligible = (
            self._tier1_auto_allow
            and spec.tool_id in TIER1_ORDINARY_SAFE_TOOLS
            and spec.risk in (RiskClass.R0, RiskClass.R1)
            and not spec.requires_network
            and session.channel == ChannelKind.LOCAL
            and not self._has_revoked_grant_without_active(
                grants, session.actor_ref, spec.capability, now_utc
            )
        )
        if not has_explicit_grant and not tier1_eligible:
            return PolicyDecision(
                allowed=False,
                requires_approval=False,
                error_code=ErrorCode.DENIED,
                reason=f"Missing active in-scope grant for capability '{spec.capability}' (deny-by-default).",
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
    def _normalize_scope_path(raw: str) -> tuple[str, ...] | None:
        """Normalize a Windows/POSIX path purely without IO, rejecting traversal or UNC escapes."""
        cleaned = raw.strip().replace("\\", "/")
        if not cleaned or cleaned.startswith("//") or cleaned.startswith("?/"):
            return None
        parts: list[str] = []
        for idx, segment in enumerate(cleaned.split("/")):
            if segment == "" or segment == ".":
                continue
            if segment == "..":
                return None
            parts.append(segment.lower() if idx == 0 and segment.endswith(":") else segment.lower())
        return tuple(parts) if parts else None

    @classmethod
    def _path_within_allowed_roots(cls, candidate: str, allowed_roots: tuple[str, ...]) -> bool:
        cand_parts = cls._normalize_scope_path(candidate)
        if cand_parts is None:
            return False
        for root_raw in allowed_roots:
            root_parts = cls._normalize_scope_path(root_raw)
            if root_parts is None:
                continue
            if len(cand_parts) >= len(root_parts) and cand_parts[: len(root_parts)] == root_parts:
                return True
        return False

    @classmethod
    def _scope_allows(cls, scope: dict[str, Any], *, tool_id: str, args: dict[str, Any]) -> bool:
        """Enforce non-empty grant.scope boundaries (allowed_paths/root_path, allowed_apps, allowed_tools)."""
        if not scope:
            return True

        allowed_tools = scope.get("allowed_tools")
        if (
            isinstance(allowed_tools, (list, tuple))
            and allowed_tools
            and tool_id not in {str(t) for t in allowed_tools}
        ):
            return False

        allowed_apps = scope.get("allowed_apps")
        if isinstance(allowed_apps, (list, tuple)) and allowed_apps:
            app_val = str(args.get("app_id", "")).strip().lower()
            if not app_val or app_val not in {str(a).strip().lower() for a in allowed_apps}:
                return False

        raw_roots: list[str] = []
        if isinstance(scope.get("root_path"), str) and str(scope["root_path"]).strip():
            raw_roots.append(str(scope["root_path"]))
        if isinstance(scope.get("path"), str) and str(scope["path"]).strip():
            raw_roots.append(str(scope["path"]))
        if isinstance(scope.get("allowed_paths"), (list, tuple)):
            raw_roots.extend(str(p) for p in scope["allowed_paths"] if isinstance(p, str) and p.strip())

        if raw_roots:
            roots_tuple = tuple(raw_roots)
            path_keys = (
                "path",
                "root_path",
                "target_path",
                "source_path",
                "src",
                "dst",
                "archive_path",
            )
            checked_any = False
            for k in path_keys:
                val = args.get(k)
                if isinstance(val, str) and val.strip():
                    checked_any = True
                    if not cls._path_within_allowed_roots(val, roots_tuple):
                        return False
            if not checked_any:
                return False

        return True

    @classmethod
    def _has_revoked_grant_without_active(
        cls,
        grants: tuple[GrantRecord, ...],
        actor_ref: str,
        capability: str,
        now_utc: datetime,
    ) -> bool:
        """Respect explicit owner revocation even when Tier-1 auto-allow is enabled."""
        saw_revoked = False
        for grant in grants:
            if grant.capability != capability or grant.subject_id != actor_ref:
                continue
            if grant.revoked_at is not None:
                saw_revoked = True
            elif grant.expires_at is None or grant.expires_at > now_utc:
                return False
        return saw_revoked

    @classmethod
    def _has_active_grant(
        cls,
        grants: tuple[GrantRecord, ...],
        actor_ref: str,
        capability: str,
        now_utc: datetime,
        *,
        tool_id: str = "",
        args: dict[str, Any] | None = None,
    ) -> bool:
        step_args = args or {}
        for grant in grants:
            if grant.capability != capability:
                continue
            if grant.subject_id != actor_ref:
                continue
            if grant.revoked_at is not None:
                continue
            if grant.expires_at is not None and grant.expires_at <= now_utc:
                continue
            if not cls._scope_allows(grant.scope, tool_id=tool_id, args=step_args):
                continue
            return True
        return False
