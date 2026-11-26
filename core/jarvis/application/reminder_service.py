"""Persistent IANA/UTC Reminder Scheduler, Quiet Hours, Suspend Reconciliation & Proactive Limits (B09, BR-09..11, BR-21)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Literal

from jarvis.application.config_service import ConfigService
from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort, NotificationPort
from jarvis.domain.router import resolve_user_timezone
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class ReminderServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class ReminderRecord(StrictModel):
    id: str
    title: str
    due_at_utc: datetime
    timezone_iana: str
    state: Literal["scheduled", "snoozed", "delivered", "dismissed", "missed"]
    revision: int


@dataclass(frozen=True)
class ReminderDeliveryOutcome:
    reminder_id: str
    title: str
    status: Literal["delivered", "suppressed_quiet_hours", "missed"]
    dedup_key: str


def is_within_quiet_hours(
    now_utc: datetime,
    *,
    timezone_iana: str,
    start_local_hhmm: str,
    end_local_hhmm: str,
) -> bool:
    """Evaluate configurable local quiet hours in the user's explicit IANA timezone (BR-10)."""
    tz = resolve_user_timezone(timezone_iana)
    local_t = now_utc.astimezone(tz).time().replace(tzinfo=None)
    s_h, s_m = (int(x) for x in start_local_hhmm.split(":"))
    e_h, e_m = (int(x) for x in end_local_hhmm.split(":"))
    start_t = time(s_h, s_m)
    end_t = time(e_h, e_m)
    if start_t <= end_t:
        return start_t <= local_t < end_t
    # Overnight window (e.g., 22:00 -> 07:00)
    return local_t >= start_t or local_t < end_t


class ProactiveRateLimiter:
    """Enforces BR-11 proactive limits: disabled by default, 60s debounce, max 1/hour, max 3/day."""

    def __init__(self) -> None:
        self._delivered_timestamps: list[datetime] = []

    def can_emit(self, *, enabled: bool, now_utc: datetime) -> tuple[bool, str]:
        if not enabled:
            return (False, "Proactive rules are disabled by default (BR-11).")
        if self._delivered_timestamps:
            last = self._delivered_timestamps[-1]
            if (now_utc - last).total_seconds() < 60.0:
                return (False, "Proactive 60s debounce window active (BR-11).")
        in_last_hour = [t for t in self._delivered_timestamps if (now_utc - t) < timedelta(hours=1)]
        if len(in_last_hour) >= 1:
            return (False, "Proactive hourly limit (max 1/hour) reached (BR-11).")
        in_last_day = [t for t in self._delivered_timestamps if (now_utc - t) < timedelta(hours=24)]
        if len(in_last_day) >= 3:
            return (False, "Proactive daily limit (max 3/day) reached (BR-11).")
        return (True, "Permitted.")

    def record_emitted(self, now_utc: datetime) -> None:
        self._delivered_timestamps.append(now_utc)


class ReminderSchedulerService:
    """Persistent UTC+IANA reminder scheduler with quiet hours, deduplication & missed-due reconciliation."""

    def __init__(
        self,
        db: DualSqliteManager,
        config_service: ConfigService,
        notification_port: NotificationPort,
        clock: ClockPort,
        event_bus: SequencedEventBus,
    ) -> None:
        self._db = db
        self._config = config_service
        self._notify = notification_port
        self._clock = clock
        self._bus = event_bus
        self.proactive_limiter = ProactiveRateLimiter()

    def create_reminder(
        self,
        *,
        title: str,
        due_at_utc: datetime,
        timezone_iana: str | None = None,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> ReminderRecord:
        cleaned = title.strip()
        if not cleaned:
            raise ReminderServiceError(ErrorCode.INVALID_ARGS, "Reminder title cannot be empty.")

        tz_name = timezone_iana or self._config.get_active().document.locale.timezone_iana
        # Validate IANA timezone cleanly
        resolve_user_timezone(tz_name)
        rem_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        due_iso = due_at_utc.isoformat()
        idem_key = f"rem:{rem_id}:{due_iso}"

        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO reminder(id, title, due_at_utc, timezone_iana, recurrence_json, state, revision)
                VALUES (?, ?, ?, ?, NULL, 'scheduled', 1)
                """,
                (rem_id, cleaned, due_iso, tz_name),
            )
            conn.execute(
                """
                INSERT INTO job(
                    id, workflow_id, reminder_id, due_at_utc, state, lease_until, attempt,
                    idempotency_key, payload_min_json, revision
                ) VALUES (?, NULL, ?, ?, 'queued', NULL, 0, ?, ?, 1)
                """,
                (job_id, rem_id, due_iso, idem_key, json.dumps({"title": cleaned})),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'reminder.created', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"reminder_id": rem_id, "due_at_utc": due_iso, "timezone_iana": tz_name}),
                    self._clock.now_utc().isoformat(),
                ),
            )

        return ReminderRecord(
            id=rem_id,
            title=cleaned,
            due_at_utc=due_at_utc,
            timezone_iana=tz_name,
            state="scheduled",
            revision=1,
        )

    def list_reminders(self) -> list[ReminderRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM reminder ORDER BY due_at_utc ASC").fetchall()
        return [
            ReminderRecord(
                id=str(r["id"]),
                title=str(r["title"]),
                due_at_utc=datetime.fromisoformat(str(r["due_at_utc"])),
                timezone_iana=str(r["timezone_iana"]),
                state=str(r["state"]),  # type: ignore[arg-type]
                revision=int(r["revision"]),
            )
            for r in rows
        ]

    def process_due_reminders(
        self, *, missed_grace_seconds: int = 300, correlation_id: str = "scheduler-tick"
    ) -> list[ReminderDeliveryOutcome]:
        """Deliver due reminders idempotently, respect quiet hours, and record missed-during-sleep honestly."""
        now = self._clock.now_utc()
        now_iso = now.isoformat()
        cfg = self._config.get_active().document
        qh = cfg.persona.quiet_hours
        outcomes: list[ReminderDeliveryOutcome] = []

        with self._db.core_tx() as conn:
            rows = conn.execute(
                """
                SELECT j.id AS job_id, j.reminder_id, j.due_at_utc, r.title, r.timezone_iana, r.state
                FROM job j
                JOIN reminder r ON r.id = j.reminder_id
                WHERE j.state = 'queued' AND j.due_at_utc <= ?
                ORDER BY j.due_at_utc ASC
                """,
                (now_iso,),
            ).fetchall()

            for row in rows:
                job_id = str(row["job_id"])
                rem_id = str(row["reminder_id"])
                title = str(row["title"])
                tz_iana = str(row["timezone_iana"])
                due_dt = datetime.fromisoformat(str(row["due_at_utc"]))
                dedup_key = f"delivery:{rem_id}:{row['due_at_utc']}"

                # Guard against double-delivery across restarts
                existing_deliv = conn.execute(
                    "SELECT id FROM delivery WHERE dedup_key = ?", (dedup_key,)
                ).fetchone()
                if existing_deliv is not None:
                    conn.execute("UPDATE job SET state = 'completed' WHERE id = ?", (job_id,))
                    continue

                overdue_sec = (now - due_dt).total_seconds()
                if overdue_sec > missed_grace_seconds:
                    # Honest missed-due reconciliation after machine off/suspend (BR-21)
                    conn.execute(
                        "UPDATE reminder SET state = 'missed', revision = revision + 1 WHERE id = ?",
                        (rem_id,),
                    )
                    conn.execute("UPDATE job SET state = 'completed' WHERE id = ?", (job_id,))
                    conn.execute(
                        """
                        INSERT INTO delivery(id, job_id, channel, status, dedup_key, delivered_at)
                        VALUES (?, ?, 'local_missed_reconciliation', 'delivered', ?, ?)
                        """,
                        (str(uuid.uuid4()), job_id, dedup_key, now_iso),
                    )
                    outcomes.append(
                        ReminderDeliveryOutcome(
                            reminder_id=rem_id, title=title, status="missed", dedup_key=dedup_key
                        )
                    )
                    continue

                quiet_active = qh.enabled and is_within_quiet_hours(
                    now,
                    timezone_iana=tz_iana,
                    start_local_hhmm=qh.start_local,
                    end_local_hhmm=qh.end_local,
                )
                silent = quiet_active and not qh.allow_voice_priority
                self._notify.send_local_notification("J.A.R.V.I.S. Reminder", title, silent=silent)
                deliv_status: Literal["delivered", "suppressed_quiet_hours"] = (
                    "suppressed_quiet_hours" if silent else "delivered"
                )
                conn.execute(
                    "UPDATE reminder SET state = 'delivered', revision = revision + 1 WHERE id = ?",
                    (rem_id,),
                )
                conn.execute("UPDATE job SET state = 'completed' WHERE id = ?", (job_id,))
                conn.execute(
                    """
                    INSERT INTO delivery(id, job_id, channel, status, dedup_key, delivered_at)
                    VALUES (?, ?, 'local_notification', ?, ?, ?)
                    """,
                    (str(uuid.uuid4()), job_id, deliv_status, dedup_key, now_iso),
                )
                outcomes.append(
                    ReminderDeliveryOutcome(
                        reminder_id=rem_id, title=title, status=deliv_status, dedup_key=dedup_key
                    )
                )

        for out in outcomes:
            self._bus.publish(
                event_type="reminder.delivered",
                correlation_id=correlation_id,
                payload={
                    "reminder_id": out.reminder_id,
                    "title": out.title,
                    "status": out.status,
                },
            )
        return outcomes

    def snooze_reminder(
        self, reminder_id: str, *, expected_revision: int, minutes: int, correlation_id: str
    ) -> ReminderRecord:
        if minutes < 1 or minutes > 1440:
            raise ReminderServiceError(ErrorCode.INVALID_ARGS, "Snooze minutes must be 1..1440.")
        new_due = self._clock.now_utc() + timedelta(minutes=minutes)
        new_due_iso = new_due.isoformat()
        with self._db.core_tx() as conn:
            cur = conn.execute(
                """
                UPDATE reminder
                SET due_at_utc = ?, state = 'snoozed', revision = revision + 1
                WHERE id = ? AND revision = ?
                """,
                (new_due_iso, reminder_id, expected_revision),
            )
            if cur.rowcount != 1:
                raise ReminderServiceError(
                    ErrorCode.INVALID_ARGS, f"Reminder '{reminder_id}' not found or revision mismatch."
                )
            row = conn.execute("SELECT * FROM reminder WHERE id = ?", (reminder_id,)).fetchone()
            assert row is not None
            conn.execute(
                """
                INSERT INTO job(
                    id, workflow_id, reminder_id, due_at_utc, state, lease_until, attempt,
                    idempotency_key, payload_min_json, revision
                ) VALUES (?, NULL, ?, ?, 'queued', NULL, 0, ?, ?, 1)
                """,
                (
                    str(uuid.uuid4()),
                    reminder_id,
                    new_due_iso,
                    f"rem:{reminder_id}:snooze:{new_due_iso}",
                    json.dumps({"title": str(row["title"])}),
                ),
            )
        return ReminderRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            due_at_utc=new_due,
            timezone_iana=str(row["timezone_iana"]),
            state="snoozed",
            revision=int(row["revision"]),
        )

    def dismiss_reminder(self, reminder_id: str, *, expected_revision: int) -> ReminderRecord:
        with self._db.core_tx() as conn:
            cur = conn.execute(
                """
                UPDATE reminder
                SET state = 'dismissed', revision = revision + 1
                WHERE id = ? AND revision = ?
                """,
                (reminder_id, expected_revision),
            )
            if cur.rowcount != 1:
                raise ReminderServiceError(
                    ErrorCode.INVALID_ARGS, f"Reminder '{reminder_id}' not found or revision mismatch."
                )
            conn.execute(
                "UPDATE job SET state = 'canceled' WHERE reminder_id = ? AND state = 'queued'",
                (reminder_id,),
            )
            row = conn.execute("SELECT * FROM reminder WHERE id = ?", (reminder_id,)).fetchone()
        assert row is not None
        return ReminderRecord(
            id=str(row["id"]),
            title=str(row["title"]),
            due_at_utc=datetime.fromisoformat(str(row["due_at_utc"])),
            timezone_iana=str(row["timezone_iana"]),
            state="dismissed",
            revision=int(row["revision"]),
        )
