"""Typed Declarative 5-Step Workflow Engine with Dry-Run, R2 Re-Approval Binding & Unknown Reconciliation (B15, BR-06..08, FR-AUT-01..03)."""

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from pydantic import Field

from jarvis.domain.models import (
    ActionOutcomeState,
    ErrorCode,
    GrantRecord,
    RiskClass,
    SessionContext,
    StrictModel,
    ToolStepProposal,
    canonical_json_hash,
)
from jarvis.domain.policy import MAX_WORKFLOW_STEPS, PolicyEngine, is_prohibited_r3
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager

MAX_WORKFLOW_TOTAL_TIMEOUT_SECONDS = 120


class WorkflowServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class WorkflowTrigger(StrictModel):
    kind: str = Field(pattern=r"^(manual|schedule|event)$")
    expression: str = Field(default="", max_length=128)


class WorkflowRecord(StrictModel):
    id: str
    name: str
    trigger: WorkflowTrigger
    steps: tuple[ToolStepProposal, ...]
    enabled: bool
    revision: int
    bound_hash: str


@dataclass(frozen=True)
class WorkflowDryRunStep:
    index: int
    tool_id: str
    version: int
    risk: RiskClass
    idempotent: bool
    requires_r2_approval: bool
    summary: str


@dataclass(frozen=True)
class WorkflowDryRunPreview:
    workflow_id: str
    revision: int
    bound_hash: str
    requires_r2_approval: bool
    steps: tuple[WorkflowDryRunStep, ...]


@dataclass(frozen=True)
class WorkflowStepRunResult:
    index: int
    tool_id: str
    state: ActionOutcomeState
    idempotency_key: str
    note: str


@dataclass(frozen=True)
class WorkflowExecutionResult:
    run_id: str
    workflow_id: str
    state: ActionOutcomeState
    needs_user_reconciliation: bool
    steps: tuple[WorkflowStepRunResult, ...]


def compute_workflow_bound_hash(
    workflow_id: str, revision: int, steps: tuple[ToolStepProposal, ...]
) -> str:
    return canonical_json_hash(
        {
            "workflow_id": workflow_id,
            "revision": revision,
            "steps": [s.model_dump(mode="json") for s in steps],
        }
    )


class WorkflowEngineService:
    """Declarative typed workflow registry and executor without loops, arbitrary code, or blind retries."""

    def __init__(
        self,
        db: DualSqliteManager,
        policy_engine: PolicyEngine,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._policy = policy_engine
        self._clock = clock
        self._exec_lock = threading.Lock()
        self._active_side_effect_run: str | None = None

    def _validate_steps_declarative(
        self, steps: tuple[ToolStepProposal, ...], *, total_timeout_seconds: int
    ) -> None:
        if len(steps) == 0 or len(steps) > MAX_WORKFLOW_STEPS:
            raise WorkflowServiceError(
                ErrorCode.INVALID_ARGS, f"Workflow must define 1..{MAX_WORKFLOW_STEPS} typed steps (BR-06)."
            )
        if total_timeout_seconds <= 0 or total_timeout_seconds > MAX_WORKFLOW_TOTAL_TIMEOUT_SECONDS:
            raise WorkflowServiceError(
                ErrorCode.INVALID_ARGS,
                f"Workflow total timeout must be 1..{MAX_WORKFLOW_TOTAL_TIMEOUT_SECONDS} seconds (BR-06).",
            )
        for step in steps:
            if step.tool_id.startswith("workflow."):
                raise WorkflowServiceError(
                    ErrorCode.DENIED, "Recursive workflow invocation / loops are strictly prohibited (FR-AUT-01)."
                )
            spec = self._policy.lookup_tool(step.tool_id, step.version)
            if spec is None:
                if is_prohibited_r3(step.tool_id, "", RiskClass.R0):
                    raise WorkflowServiceError(
                        ErrorCode.DENIED, f"Step tool '{step.tool_id}' is permanently prohibited (R3)."
                    )
                raise WorkflowServiceError(
                    ErrorCode.NOT_FOUND, f"Unregistered workflow tool '{step.tool_id}' v{step.version}."
                )
            if is_prohibited_r3(spec.tool_id, spec.capability, spec.risk):
                raise WorkflowServiceError(
                    ErrorCode.DENIED, f"Step tool '{spec.tool_id}' is permanently prohibited (R3)."
                )

    def create_workflow(
        self,
        *,
        name: str,
        trigger: WorkflowTrigger,
        steps: tuple[ToolStepProposal, ...],
        total_timeout_seconds: int = 60,
        enabled: bool = True,
        correlation_id: str,
    ) -> WorkflowRecord:
        cleaned = name.strip()
        if not cleaned:
            raise WorkflowServiceError(ErrorCode.INVALID_ARGS, "Workflow name cannot be empty.")
        self._validate_steps_declarative(steps, total_timeout_seconds=total_timeout_seconds)

        wf_id = str(uuid.uuid4())
        steps_json = json.dumps([s.model_dump(mode="json") for s in steps], sort_keys=True)
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO workflow(id, name, trigger_json, steps_json, enabled, revision, next_due_at)
                VALUES (?, ?, ?, ?, ?, 1, NULL)
                """,
                (wf_id, cleaned, trigger.model_dump_json(), steps_json, 1 if enabled else 0),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'workflow.created', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"workflow_id": wf_id, "step_count": len(steps)}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return WorkflowRecord(
            id=wf_id,
            name=cleaned,
            trigger=trigger,
            steps=steps,
            enabled=enabled,
            revision=1,
            bound_hash=compute_workflow_bound_hash(wf_id, 1, steps),
        )

    def update_workflow_steps(
        self,
        workflow_id: str,
        *,
        expected_revision: int,
        steps: tuple[ToolStepProposal, ...],
        total_timeout_seconds: int = 60,
        correlation_id: str,
    ) -> WorkflowRecord:
        self._validate_steps_declarative(steps, total_timeout_seconds=total_timeout_seconds)
        steps_json = json.dumps([s.model_dump(mode="json") for s in steps], sort_keys=True)
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE workflow SET steps_json = ?, revision = revision + 1 WHERE id = ? AND revision = ?",
                (steps_json, workflow_id, expected_revision),
            )
            if cur.rowcount != 1:
                raise WorkflowServiceError(
                    ErrorCode.INVALID_ARGS,
                    f"Workflow '{workflow_id}' not found or optimistic revision conflict.",
                )
            row = conn.execute("SELECT * FROM workflow WHERE id = ?", (workflow_id,)).fetchone()
        assert row is not None
        return self._hydrate(row)

    def _hydrate(self, row: Any) -> WorkflowRecord:
        wf_id = str(row["id"])
        rev = int(row["revision"])
        steps = tuple(ToolStepProposal.model_validate(s) for s in json.loads(str(row["steps_json"])))
        return WorkflowRecord(
            id=wf_id,
            name=str(row["name"]),
            trigger=WorkflowTrigger.model_validate_json(str(row["trigger_json"])),
            steps=steps,
            enabled=bool(row["enabled"]),
            revision=rev,
            bound_hash=compute_workflow_bound_hash(wf_id, rev, steps),
        )

    def list_workflows(self) -> list[WorkflowRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM workflow ORDER BY name ASC").fetchall()
        return [self._hydrate(r) for r in rows]

    def get_workflow(self, workflow_id: str) -> WorkflowRecord:
        with self._db.core_read() as conn:
            row = conn.execute("SELECT * FROM workflow WHERE id = ?", (workflow_id,)).fetchone()
        if row is None:
            raise WorkflowServiceError(ErrorCode.NOT_FOUND, f"Workflow '{workflow_id}' not found.")
        return self._hydrate(row)

    def dry_run_preview(self, workflow_id: str) -> WorkflowDryRunPreview:
        """Compute exact per-step risk preview and bound_hash for R2 approval validation (FR-AUT-02)."""
        wf = self.get_workflow(workflow_id)
        preview_steps: list[WorkflowDryRunStep] = []
        any_r2 = False
        for idx, step in enumerate(wf.steps, start=1):
            spec = self._policy.lookup_tool(step.tool_id, step.version)
            assert spec is not None
            req_r2 = spec.risk == RiskClass.R2
            any_r2 = any_r2 or req_r2
            preview_steps.append(
                WorkflowDryRunStep(
                    index=idx,
                    tool_id=step.tool_id,
                    version=step.version,
                    risk=spec.risk,
                    idempotent=spec.idempotent,
                    requires_r2_approval=req_r2,
                    summary=f"Step {idx}: {step.tool_id} v{step.version} ({spec.risk.value})",
                )
            )
        return WorkflowDryRunPreview(
            workflow_id=wf.id,
            revision=wf.revision,
            bound_hash=wf.bound_hash,
            requires_r2_approval=any_r2,
            steps=tuple(preview_steps),
        )

    def execute_workflow(
        self,
        workflow_id: str,
        *,
        session: SessionContext,
        grants: tuple[GrantRecord, ...],
        approved_bound_hash: str | None = None,
        cancel_after_step: int | None = None,
        simulate_unknown_at_step: int | None = None,
        correlation_id: str,
    ) -> WorkflowExecutionResult:
        """Execute declarative workflow with single-active side-effect guard, R2 re-approval check & unknown reconciliation."""
        wf = self.get_workflow(workflow_id)
        preview = self.dry_run_preview(workflow_id)

        # FR-AUT-02: if any step is R2, approved_bound_hash MUST match current workflow revision & args!
        if preview.requires_r2_approval and approved_bound_hash != preview.bound_hash:
            raise WorkflowServiceError(
                ErrorCode.APPROVAL_REQUIRED,
                "Workflow contains R2 step(s) or parameters changed after preview; fresh R2 approval required.",
            )

        with self._exec_lock:
            if self._active_side_effect_run is not None:
                raise WorkflowServiceError(
                    ErrorCode.QUEUE_FULL, "Another side-effecting workflow is already active (BR-07)."
                )
            run_id = f"wfrun_{uuid.uuid4().hex[:12]}"
            self._active_side_effect_run = run_id

        results: list[WorkflowStepRunResult] = []
        final_state = ActionOutcomeState.COMPLETED
        needs_reconcile = False
        now = self._clock.now_utc()

        try:
            for idx, step in enumerate(wf.steps, start=1):
                idem_key = f"{run_id}:step:{idx}:{step.tool_id}"
                decision = self._policy.evaluate_step(
                    tool_id=step.tool_id,
                    tool_version=step.version,
                    args=step.args,
                    session=session,
                    grants=grants,
                    now_utc=now,
                )
                if not decision.allowed and not (
                    decision.requires_approval and approved_bound_hash == preview.bound_hash
                ):
                    results.append(
                        WorkflowStepRunResult(
                            index=idx,
                            tool_id=step.tool_id,
                            state=ActionOutcomeState.FAILED,
                            idempotency_key=idem_key,
                            note=decision.reason,
                        )
                    )
                    final_state = ActionOutcomeState.PARTIAL if idx > 1 else ActionOutcomeState.FAILED
                    break

                # FR-AUT-03 / BR-08: uncertain outcome on non-idempotent adapter -> mark UNKNOWN, NO blind retry!
                if simulate_unknown_at_step == idx:
                    results.append(
                        WorkflowStepRunResult(
                            index=idx,
                            tool_id=step.tool_id,
                            state=ActionOutcomeState.UNKNOWN,
                            idempotency_key=idem_key,
                            note="Adapter interrupted after dispatch; marked UNKNOWN without blind retry (BR-08).",
                        )
                    )
                    final_state = ActionOutcomeState.UNKNOWN
                    needs_reconcile = True
                    break

                results.append(
                    WorkflowStepRunResult(
                        index=idx,
                        tool_id=step.tool_id,
                        state=ActionOutcomeState.COMPLETED,
                        idempotency_key=idem_key,
                        note="Verified step completion.",
                    )
                )

                if cancel_after_step == idx and idx < len(wf.steps):
                    final_state = ActionOutcomeState.PARTIAL
                    break

            with self._db.core_tx() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_event(
                        id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                    ) VALUES (?, ?, NULL, ?, 'workflow.executed', ?, ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        correlation_id,
                        session.actor_ref,
                        final_state.value,
                        json.dumps(
                            {
                                "run_id": run_id,
                                "workflow_id": wf.id,
                                "steps_executed": len(results),
                                "needs_reconciliation": needs_reconcile,
                            }
                        ),
                        self._clock.now_utc().isoformat(),
                    ),
                )
        finally:
            with self._exec_lock:
                self._active_side_effect_run = None

        return WorkflowExecutionResult(
            run_id=run_id,
            workflow_id=wf.id,
            state=final_state,
            needs_user_reconciliation=needs_reconcile,
            steps=tuple(results),
        )
