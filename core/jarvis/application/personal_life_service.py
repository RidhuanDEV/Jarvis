"""Personal Life Management Service: Tasks, IANA Calendar, Integer Minor-Unit Multi-Currency Expenses & Habits (B14, BR-17, BR-18)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Literal

from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.domain.router import resolve_user_timezone
from jarvis.infrastructure.dual_db import DualSqliteManager


class PersonalLifeError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class TaskRecord(StrictModel):
    id: str
    title: str
    due_at_utc: datetime | None
    status: Literal["open", "in_progress", "completed", "canceled"]
    completed_at: datetime | None
    revision: int


class CalendarEventRecord(StrictModel):
    id: str
    title: str
    start_at_utc: datetime
    end_at_utc: datetime
    timezone_iana: str
    source_kind: Literal["local", "ics", "external_read"]
    external_ref: str | None = None
    revision: int


class ExpenseRecord(StrictModel):
    id: str
    amount_minor: int
    currency_iso: str
    kind: Literal["expense", "refund"]
    category: str
    occurred_at_utc: datetime
    notes: str | None = None
    revision: int


class CurrencyExpenseSummary(StrictModel):
    currency_iso: str
    total_expense_minor: int
    total_refund_minor: int
    net_spend_minor: int
    transaction_count: int


class HabitLogRecord(StrictModel):
    id: str
    habit_key: str
    local_date: str
    timezone_iana: str
    value: float
    unit: str
    revision: int


class HabitDescriptiveSummary(StrictModel):
    habit_key: str
    entries: int
    total_value: float
    average_value: float
    unit: str
    disclaimer: str = "Ringkasan deskriptif semata berdasarkan catatan lokal; bukan diagnosis atau anjuran medis (BR-18)."


class PersonalLifeService:
    """Local-first personal productivity domain enforcing integer minor-unit currency isolation & descriptive habits."""

    def __init__(self, db: DualSqliteManager, clock: ClockPort) -> None:
        self._db = db
        self._clock = clock

    # --- Tasks ---

    def create_task(
        self, *, title: str, due_at_utc: datetime | None = None, correlation_id: str
    ) -> TaskRecord:
        cleaned = title.strip()
        if not cleaned:
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "Task title cannot be empty.")
        tid = str(uuid.uuid4())
        with self._db.core_tx() as conn:
            conn.execute(
                "INSERT INTO task(id, title, due_at_utc, status, completed_at, revision) VALUES (?, ?, ?, 'open', NULL, 1)",
                (tid, cleaned, due_at_utc.isoformat() if due_at_utc else None),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'life.task.created', 'completed', ?, ?)
                """,
                (str(uuid.uuid4()), correlation_id, json.dumps({"task_id": tid}), self._clock.now_utc().isoformat()),
            )
        return TaskRecord(
            id=tid, title=cleaned, due_at_utc=due_at_utc, status="open", completed_at=None, revision=1
        )

    def list_tasks(self) -> list[TaskRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM task ORDER BY revision DESC, id ASC").fetchall()
        return [
            TaskRecord(
                id=str(r["id"]),
                title=str(r["title"]),
                due_at_utc=datetime.fromisoformat(str(r["due_at_utc"])) if r["due_at_utc"] else None,
                status=str(r["status"]),  # type: ignore[arg-type]
                completed_at=datetime.fromisoformat(str(r["completed_at"])) if r["completed_at"] else None,
                revision=int(r["revision"]),
            )
            for r in rows
        ]

    def update_task_status(
        self,
        task_id: str,
        *,
        expected_revision: int,
        status: Literal["open", "in_progress", "completed", "canceled"],
    ) -> TaskRecord:
        completed_iso = self._clock.now_utc().isoformat() if status == "completed" else None
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE task SET status = ?, completed_at = ?, revision = revision + 1 WHERE id = ? AND revision = ?",
                (status, completed_iso, task_id, expected_revision),
            )
            if cur.rowcount != 1:
                raise PersonalLifeError(
                    ErrorCode.INVALID_ARGS, f"Task '{task_id}' not found or optimistic revision mismatch."
                )
            row = conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        assert row is not None
        return TaskRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            due_at_utc=datetime.fromisoformat(str(row["due_at_utc"])) if row["due_at_utc"] else None,
            status=str(row["status"]),  # type: ignore[arg-type]
            completed_at=datetime.fromisoformat(str(row["completed_at"])) if row["completed_at"] else None,
            revision=int(row["revision"]),
        )

    # --- Calendar Events (Local IANA) ---

    def create_calendar_event(
        self,
        *,
        title: str,
        start_at_utc: datetime,
        end_at_utc: datetime,
        timezone_iana: str,
        source_kind: Literal["local", "ics", "external_read"] = "local",
        external_ref: str | None = None,
    ) -> CalendarEventRecord:
        cleaned = title.strip()
        if not cleaned:
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "Calendar event title cannot be empty.")
        if end_at_utc <= start_at_utc:
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "end_at_utc must be strictly after start_at_utc.")
        resolve_user_timezone(timezone_iana)
        eid = str(uuid.uuid4())
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO calendar_event(
                    id, title, start_at_utc, end_at_utc, timezone_iana, source_kind, external_ref, revision
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    eid,
                    cleaned,
                    start_at_utc.isoformat(),
                    end_at_utc.isoformat(),
                    timezone_iana,
                    source_kind,
                    external_ref,
                ),
            )
        return CalendarEventRecord(
            id=eid,
            title=cleaned,
            start_at_utc=start_at_utc,
            end_at_utc=end_at_utc,
            timezone_iana=timezone_iana,
            source_kind=source_kind,
            external_ref=external_ref,
            revision=1,
        )

    def list_calendar_events(self) -> list[CalendarEventRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM calendar_event ORDER BY start_at_utc ASC").fetchall()
        return [
            CalendarEventRecord(
                id=str(r["id"]),
                title=str(r["title"]),
                start_at_utc=datetime.fromisoformat(str(r["start_at_utc"])),
                end_at_utc=datetime.fromisoformat(str(r["end_at_utc"])),
                timezone_iana=str(r["timezone_iana"]),
                source_kind=str(r["source_kind"]),  # type: ignore[arg-type]
                external_ref=str(r["external_ref"]) if r["external_ref"] else None,
                revision=int(r["revision"]),
            )
            for r in rows
        ]

    # --- Expenses (Integer Minor Units, Multi-Currency Isolated — BR-17, FR-LIF-02) ---

    def record_expense(
        self,
        *,
        amount_minor: int,
        currency_iso: str,
        kind: Literal["expense", "refund"] = "expense",
        category: str,
        occurred_at_utc: datetime | None = None,
        notes: str | None = None,
        correlation_id: str,
    ) -> ExpenseRecord:
        if not isinstance(amount_minor, int) or amount_minor <= 0:
            raise PersonalLifeError(
                ErrorCode.INVALID_ARGS, "amount_minor must be a strictly positive integer (BR-17)."
            )
        iso = currency_iso.strip().upper()
        if len(iso) != 3 or not iso.isalpha():
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "currency_iso must be a 3-letter ISO 4217 code.")
        cat = category.strip()
        if not cat:
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "Expense category cannot be empty.")

        eid = str(uuid.uuid4())
        occ = occurred_at_utc or self._clock.now_utc()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO expense(id, amount_minor, currency_iso, kind, category, occurred_at_utc, notes, revision)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                (eid, amount_minor, iso, kind, cat, occ.isoformat(), notes),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'life.expense.recorded', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"expense_id": eid, "currency_iso": iso, "kind": kind}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return ExpenseRecord(
            id=eid,
            amount_minor=amount_minor,
            currency_iso=iso,
            kind=kind,
            category=cat,
            occurred_at_utc=occ,
            notes=notes,
            revision=1,
        )

    def summarize_expenses_by_currency(self) -> list[CurrencyExpenseSummary]:
        """Aggregate expenses strictly per ISO currency without automatic cross-currency conversion (BR-17)."""
        with self._db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT currency_iso,
                       SUM(CASE WHEN kind = 'expense' THEN amount_minor ELSE 0 END) AS exp_total,
                       SUM(CASE WHEN kind = 'refund' THEN amount_minor ELSE 0 END) AS ref_total,
                       COUNT(*) AS tx_count
                FROM expense
                GROUP BY currency_iso
                ORDER BY currency_iso ASC
                """
            ).fetchall()
        return [
            CurrencyExpenseSummary(
                currency_iso=str(r["currency_iso"]),
                total_expense_minor=int(r["exp_total"]),
                total_refund_minor=int(r["ref_total"]),
                net_spend_minor=int(r["exp_total"]) - int(r["ref_total"]),
                transaction_count=int(r["tx_count"]),
            )
            for r in rows
        ]

    # --- Habits (Descriptive-Only — BR-18, FR-LIF-03) ---

    def log_habit(
        self,
        *,
        habit_key: str,
        local_date: str,
        timezone_iana: str,
        value: float,
        unit: str,
    ) -> HabitLogRecord:
        key = habit_key.strip().lower()
        if not key:
            raise PersonalLifeError(ErrorCode.INVALID_ARGS, "habit_key cannot be empty.")
        resolve_user_timezone(timezone_iana)
        hid = str(uuid.uuid4())
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO habit_log(id, habit_key, local_date, timezone_iana, value, unit, revision)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (hid, key, local_date, timezone_iana, float(value), unit.strip()),
            )
        return HabitLogRecord(
            id=hid,
            habit_key=key,
            local_date=local_date,
            timezone_iana=timezone_iana,
            value=float(value),
            unit=unit.strip(),
            revision=1,
        )

    def descriptive_habit_summary(self, habit_key: str) -> HabitDescriptiveSummary:
        key = habit_key.strip().lower()
        with self._db.core_read() as conn:
            rows = conn.execute(
                "SELECT value, unit FROM habit_log WHERE habit_key = ?", (key,)
            ).fetchall()
        if not rows:
            return HabitDescriptiveSummary(
                habit_key=key, entries=0, total_value=0.0, average_value=0.0, unit=""
            )
        vals = [float(r["value"]) for r in rows]
        unit = str(rows[-1]["unit"])
        total = round(sum(vals), 4)
        return HabitDescriptiveSummary(
            habit_key=key,
            entries=len(vals),
            total_value=total,
            average_value=round(total / len(vals), 4),
            unit=unit,
        )
