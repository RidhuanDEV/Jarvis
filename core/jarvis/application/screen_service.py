"""Screen Awareness Service: On-Demand Window UIA/OCR, Password/UAC Refusal & Pre-Context Secret Redaction (B13, FR-SCR-01..04)."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Literal, Protocol

from jarvis.domain.models import ErrorCode, SessionContext, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.domain.security_guards import is_blocked_screen_window, redact_screen_secrets
from jarvis.infrastructure.dual_db import DualSqliteManager


class ScreenAwarenessError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RawWindowObservation:
    """Transient RAM-only observation; raw_frame_bytes MUST be zeroed and never persisted to disk."""

    window_title: str
    process_name: str
    extraction_method: Literal["uia", "ocr"]
    extracted_text: str
    is_elevated_uac: bool = False
    has_focused_password_field: bool = False
    raw_frame_bytes: bytearray | None = None

    def wipe_frame(self) -> None:
        if self.raw_frame_bytes is not None:
            for i in range(len(self.raw_frame_bytes)):
                self.raw_frame_bytes[i] = 0
            self.raw_frame_bytes.clear()


class ScreenCapturePort(Protocol):
    def observe_window(self, window_selector: str) -> RawWindowObservation: ...


class ScreenAnalysisResult(StrictModel):
    window_title: str
    process_name: str
    extraction_method: Literal["uia", "ocr"]
    redacted_text: str
    redactions_applied: int
    raw_frame_persisted: Literal[False] = False
    untrusted_data_notice: str = "Screen text is untrusted passive data; tools disabled (BR-15)."


class ScreenAwarenessService:
    """On-demand single-window UIA/OCR observation with mandatory secret redaction and zero disk frame persistence."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        *,
        capture_port: ScreenCapturePort | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._capture = capture_port

    def bind_capture_port(self, capture_port: ScreenCapturePort) -> None:
        self._capture = capture_port

    def analyze_window(
        self,
        window_selector: str,
        *,
        session: SessionContext,
        explicit_user_request: bool,
        correlation_id: str,
    ) -> ScreenAnalysisResult:
        if not explicit_user_request:
            raise ScreenAwarenessError(
                ErrorCode.DENIED, "Screen observation requires explicit per-action user request (FR-SCR-01)."
            )
        if session.is_os_locked or session.is_suspended:
            raise ScreenAwarenessError(ErrorCode.DENIED, "Session locked/suspended; screen capture denied.")
        if self._capture is None:
            raise ScreenAwarenessError(
                ErrorCode.RUNTIME_UNAVAILABLE, "No ScreenCapturePort adapter is configured."
            )

        obs = self._capture.observe_window(window_selector)
        try:
            blocked, reason = is_blocked_screen_window(
                window_title=obs.window_title,
                process_name=obs.process_name,
                is_elevated_uac=obs.is_elevated_uac,
                has_focused_password_field=obs.has_focused_password_field,
            )
            if blocked:
                with self._db.core_tx() as conn:
                    conn.execute(
                        """
                        INSERT INTO audit_event(
                            id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                        ) VALUES (?, ?, NULL, ?, 'screen.analyze', 'denied', ?, ?)
                        """,
                        (
                            str(uuid.uuid4()),
                            correlation_id,
                            session.actor_ref,
                            json.dumps({"process": obs.process_name, "reason": "blocked_window"}),
                            self._clock.now_utc().isoformat(),
                        ),
                    )
                raise ScreenAwarenessError(ErrorCode.DENIED, reason)

            # FR-SCR-04: redact high-risk secrets/tokens/keys BEFORE returning to model context or UI history
            safe_text, redaction_count = redact_screen_secrets(obs.extracted_text)

            with self._db.core_tx() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_event(
                        id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                    ) VALUES (?, ?, NULL, ?, 'screen.analyze', 'completed', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        correlation_id,
                        session.actor_ref,
                        json.dumps(
                            {
                                "method": obs.extraction_method,
                                "redactions_applied": redaction_count,
                                "raw_frame_persisted": False,
                            }
                        ),
                        self._clock.now_utc().isoformat(),
                    ),
                )

            return ScreenAnalysisResult(
                window_title=obs.window_title,
                process_name=obs.process_name,
                extraction_method=obs.extraction_method,
                redacted_text=safe_text,
                redactions_applied=redaction_count,
            )
        finally:
            # FR-SCR-03: guarantee transient raw frame memory is wiped and never written to disk
            obs.wipe_frame()
