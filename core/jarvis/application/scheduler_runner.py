"""Persistent Async Background Scheduler Runner for Due Reminders & Sleep Reconciliation (B15, FR-SCH-01..05)."""

from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass

from jarvis.application.reminder_service import ReminderDeliveryOutcome, ReminderSchedulerService
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.logging_setup import get_logger


@dataclass(frozen=True)
class SchedulerHealthSnapshot:
    running: bool
    tick_count: int
    total_processed: int
    last_tick_utc: str | None


class BackgroundSchedulerRunner:
    """Bounded periodic background loop processing durable SQLite reminder jobs across sleep/restart."""

    def __init__(
        self,
        reminder_service: ReminderSchedulerService,
        clock: ClockPort,
        *,
        interval_seconds: float = 5.0,
    ) -> None:
        self._reminders = reminder_service
        self._clock = clock
        self._interval = max(0.5, interval_seconds)
        self._logger = get_logger("jarvis.scheduler")
        self._task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._tick_count = 0
        self._total_processed = 0
        self._last_tick_utc: str | None = None

    def snapshot(self) -> SchedulerHealthSnapshot:
        return SchedulerHealthSnapshot(
            running=self._task is not None and not self._task.done(),
            tick_count=self._tick_count,
            total_processed=self._total_processed,
            last_tick_utc=self._last_tick_utc,
        )

    def run_once(self) -> list[ReminderDeliveryOutcome]:
        """Execute a single deterministic reconciliation & delivery pass (safe for tests & manual triggers)."""
        self._tick_count += 1
        self._last_tick_utc = self._clock.now_utc().isoformat()
        outcomes = self._reminders.process_due_reminders(
            correlation_id=f"sched-tick-{self._tick_count}"
        )
        self._total_processed += len(outcomes)
        return outcomes

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._loop(), name="jarvis-reminder-scheduler")

    async def stop(self) -> None:
        self._stop_event.set()
        if self._task is not None and not self._task.done():
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None

    async def _loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.to_thread(self.run_once)
            except Exception as exc:
                self._logger.warning("scheduler.tick_error", error=str(exc))
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=self._interval)
            except TimeoutError:
                continue
