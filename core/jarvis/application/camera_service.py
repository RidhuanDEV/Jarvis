"""On-Demand Camera Understanding Service (B17, FR-IOT-01).

Strict invariants:
- Disabled by default; requires explicit per-session grant + explicit_user_request per snapshot.
- Displays active hardware/UI indicator via SequencedEventBus before capture and clears it in finally.
- Immediate capture abort and session revocation on user cancel, OS lock, or OS suspend (FR-ADM-03).
- Raw camera bytes live ONLY in RAM (bytearray) and are zero-filled in finally; NEVER written to disk.
- Zero background polling and zero facial recognition / biometric identification.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import Field

from jarvis.domain.models import ErrorCode, StrictModel
from jarvis.domain.ports import ClockPort
from jarvis.domain.security_guards import redact_screen_secrets
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class CameraServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RawCameraFrame:
    device_id: str
    width: int
    height: int
    raw_frame_bytes: bytearray
    summary_caption: str = ""


class CameraCapturePort(Protocol):
    """Platform-abstracted on-demand single-frame camera snapshot provider."""

    def capture_single_frame(self, device_id: str) -> RawCameraFrame: ...

    def close_device(self, device_id: str) -> None: ...


class UnavailableCameraCaptureAdapter:
    """Default safe adapter: refuses capture unless an explicit opt-in device provider is wired."""

    def capture_single_frame(self, device_id: str) -> RawCameraFrame:
        raise CameraServiceError(
            ErrorCode.UNSUPPORTED,
            f"No authorized camera capture adapter configured for '{device_id}'.",
        )

    def close_device(self, device_id: str) -> None:
        _ = device_id


class CameraSessionState(StrictModel):
    active: bool
    session_id: str | None = None
    device_id: str | None = None
    indicator_visible: bool = False
    facial_recognition_enabled: bool = False
    background_monitoring_enabled: bool = False


class CameraSnapshotResult(StrictModel):
    device_id: str
    width: int
    height: int
    redacted_description: str
    redactions_applied: int = Field(ge=0)
    raw_bytes_persisted: bool = False
    raw_memory_wiped: bool = True
    indicator_cleared: bool = True
    captured_at: datetime


class OnDemandCameraService:
    """Manages opt-in single-snapshot camera understanding with immediate lock/cancel teardown."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        event_bus: SequencedEventBus,
        capture_port: CameraCapturePort | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._event_bus = event_bus
        self._capture_port: CameraCapturePort = capture_port or UnavailableCameraCaptureAdapter()
        self._authorized_sessions: dict[str, str] = {}  # session_id -> device_id
        self._active_capture_device: str | None = None
        self._active_session_id: str | None = None
        self._cancel_requested: bool = False

    def get_state(self) -> CameraSessionState:
        return CameraSessionState(
            active=self._active_capture_device is not None,
            session_id=self._active_session_id,
            device_id=self._active_capture_device,
            indicator_visible=self._active_capture_device is not None,
            facial_recognition_enabled=False,
            background_monitoring_enabled=False,
        )

    def grant_session_permission(
        self,
        *,
        session_id: str,
        device_id: str,
        explicit_local_consent: bool,
        is_os_locked: bool = False,
        correlation_id: str,
    ) -> CameraSessionState:
        if is_os_locked:
            raise CameraServiceError(
                ErrorCode.DENIED, "Cannot grant camera session permission while OS session is locked (FR-ADM-03)."
            )
        if not explicit_local_consent:
            raise CameraServiceError(
                ErrorCode.DENIED, "Camera access requires explicit local per-session owner consent (FR-IOT-01)."
            )
        self._authorized_sessions[session_id] = device_id
        self._record_audit(
            correlation_id=correlation_id,
            actor="local_owner",
            event_type="camera.session_granted",
            outcome="completed",
            meta={"session_id": session_id, "device_id": device_id},
        )
        return self.get_state()

    def stop_and_revoke_all(self, *, reason: str, correlation_id: str) -> int:
        """Immediately close any active camera device and revoke all per-session grants (cancel / OS lock / suspend)."""
        self._cancel_requested = True
        closed_count = 0
        devices_to_close = set(self._authorized_sessions.values())
        if self._active_capture_device is not None:
            devices_to_close.add(self._active_capture_device)
        for dev in devices_to_close:
            self._capture_port.close_device(dev)
            closed_count += 1
        self._authorized_sessions.clear()
        self._active_capture_device = None
        self._active_session_id = None
        self._event_bus.publish(
            event_type="camera.indicator_changed",
            payload={"active": False, "reason": reason},
            correlation_id=correlation_id,
        )
        self._record_audit(
            correlation_id=correlation_id,
            actor="system",
            event_type="camera.revoked",
            outcome="completed",
            meta={"reason": reason, "devices_closed": closed_count},
        )
        return closed_count

    def capture_on_demand_snapshot(
        self,
        *,
        session_id: str,
        device_id: str,
        explicit_user_request: bool,
        channel: str = "local",
        is_os_locked: bool = False,
        is_suspended: bool = False,
        correlation_id: str,
    ) -> CameraSnapshotResult:
        """Capture one RAM-only snapshot with active indicator, zero disk persistence, and secret redaction."""
        if channel != "local":
            raise CameraServiceError(
                ErrorCode.DENIED, "Camera access is prohibited on remote channels (FR-REM-02)."
            )
        if is_os_locked or is_suspended:
            self.stop_and_revoke_all(reason="os_locked_or_suspended", correlation_id=correlation_id)
            raise CameraServiceError(
                ErrorCode.DENIED, "Camera capture blocked because OS session is locked or suspended (FR-IOT-01)."
            )
        if not explicit_user_request:
            raise CameraServiceError(
                ErrorCode.DENIED, "Camera snapshot requires explicit per-action user request (FR-IOT-01)."
            )
        granted_device = self._authorized_sessions.get(session_id)
        if granted_device != device_id:
            raise CameraServiceError(
                ErrorCode.DENIED,
                f"Session '{session_id}' lacks active explicit camera permission for device '{device_id}' (FR-IOT-01).",
            )

        self._cancel_requested = False
        self._active_capture_device = device_id
        self._active_session_id = session_id
        self._event_bus.publish(
            event_type="camera.indicator_changed",
            payload={"active": True, "device_id": device_id, "session_id": session_id},
            correlation_id=correlation_id,
        )

        frame: RawCameraFrame | None = None
        try:
            frame = self._capture_port.capture_single_frame(device_id)
            if self._cancel_requested:
                raise CameraServiceError(ErrorCode.DENIED, "Camera capture canceled mid-flight.")
            redacted_text, redactions = redact_screen_secrets(frame.summary_caption or "Snapshot captured.")
            now = self._clock.now_utc()
            result = CameraSnapshotResult(
                device_id=frame.device_id,
                width=frame.width,
                height=frame.height,
                redacted_description=redacted_text,
                redactions_applied=redactions,
                raw_bytes_persisted=False,
                raw_memory_wiped=True,
                indicator_cleared=True,
                captured_at=now,
            )
            self._record_audit(
                correlation_id=correlation_id,
                actor="local_owner",
                event_type="camera.snapshot_captured",
                outcome="completed",
                meta={
                    "device_id": frame.device_id,
                    "width": frame.width,
                    "height": frame.height,
                    "redactions_applied": redactions,
                    "raw_bytes_persisted": False,
                },
            )
            return result
        finally:
            if frame is not None and frame.raw_frame_bytes:
                for i in range(len(frame.raw_frame_bytes)):
                    frame.raw_frame_bytes[i] = 0
                frame.raw_frame_bytes.clear()
            self._capture_port.close_device(device_id)
            self._active_capture_device = None
            self._active_session_id = None
            self._event_bus.publish(
                event_type="camera.indicator_changed",
                payload={"active": False, "device_id": device_id},
                correlation_id=correlation_id,
            )

    def _record_audit(
        self,
        *,
        correlation_id: str,
        actor: str,
        event_type: str,
        outcome: str,
        meta: dict[str, object],
    ) -> None:
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    event_type,
                    outcome,
                    json.dumps(meta, sort_keys=True),
                    self._clock.now_utc().isoformat(),
                ),
            )
