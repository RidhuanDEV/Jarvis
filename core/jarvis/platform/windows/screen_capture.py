"""Windows On-Demand Active Window Metadata Reader with Real TokenElevation & Password-Focus Guards (B17, FR-SCR-01..04).

RAM-only metadata observation (zero screenshots written to disk).
Fails closed when foreground process is elevated (TokenElevation / AccessDenied) or focused control uses ES_PASSWORD.
"""

from __future__ import annotations

import contextlib
import ctypes
import sys

import psutil

from jarvis.application.screen_service import RawWindowObservation

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_TOKEN_QUERY = 0x0008
_TOKEN_ELEVATION_CLASS = 20
_GWL_STYLE = -16
_ES_PASSWORD = 0x0020
_EM_GETPASSWORDCHAR = 0x00D2


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class _GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("hwndActive", ctypes.c_void_p),
        ("hwndFocus", ctypes.c_void_p),
        ("hwndCapture", ctypes.c_void_p),
        ("hwndMenuOwner", ctypes.c_void_p),
        ("hwndMoveSize", ctypes.c_void_p),
        ("hwndCaret", ctypes.c_void_p),
        ("rcCaret", _RECT),
    ]


def _is_process_elevated_fail_closed(pid: int) -> bool:
    """Check Win32 TokenElevation; fail closed (return True) if non-elevated process gets AccessDenied."""
    if sys.platform != "win32" or pid <= 0:
        return False
    kernel32 = ctypes.windll.kernel32
    advapi32 = ctypes.windll.advapi32
    h_proc = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        # AccessDenied opening foreground window process typically indicates elevated/protected process -> fail closed!
        return True
    h_token = ctypes.c_void_p()
    try:
        if not advapi32.OpenProcessToken(h_proc, _TOKEN_QUERY, ctypes.byref(h_token)):
            return True
        elevated = ctypes.c_uint32(0)
        ret_len = ctypes.c_uint32(0)
        ok = advapi32.GetTokenInformation(
            h_token,
            _TOKEN_ELEVATION_CLASS,
            ctypes.byref(elevated),
            ctypes.sizeof(elevated),
            ctypes.byref(ret_len),
        )
        if not ok:
            return True
        return bool(elevated.value)
    finally:
        if h_token.value:
            kernel32.CloseHandle(h_token)
        kernel32.CloseHandle(h_proc)


def _has_focused_password_control(hwnd: int) -> bool:
    """Inspect focused Win32 control style for ES_PASSWORD / EM_GETPASSWORDCHAR."""
    if sys.platform != "win32" or not hwnd:
        return False
    with contextlib.suppress(Exception):
        user32 = ctypes.windll.user32
        thread_id = int(user32.GetWindowThreadProcessId(hwnd, None))
        if not thread_id:
            return False
        info = _GUITHREADINFO()
        info.cbSize = ctypes.sizeof(_GUITHREADINFO)
        if not user32.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
            return False
        focus_hwnd = info.hwndFocus
        if not focus_hwnd:
            return False
        style = int(user32.GetWindowLongW(focus_hwnd, _GWL_STYLE))
        if style & _ES_PASSWORD:
            return True
        pw_char = int(user32.SendMessageW(focus_hwnd, _EM_GETPASSWORDCHAR, 0, 0))
        return pw_char != 0
    return False


class WindowsActiveWindowCaptureAdapter:
    """Honest active-window metadata reader with TokenElevation & password-field fail-closed blocking (B17)."""

    def observe_window(self, window_selector: str) -> RawWindowObservation:
        if sys.platform != "win32":
            return RawWindowObservation(
                window_title=f"Active Window ({window_selector})",
                process_name="unknown",
                extraction_method="uia",
                extracted_text="Pengamatan metadata jendela aktif hanya tersedia pada host desktop Windows.",
                raw_frame_bytes=None,
            )

        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow() or 0)
        title = ""
        proc_name = "unknown"
        pid_val = 0
        if hwnd:
            length = int(user32.GetWindowTextLengthW(hwnd))
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            pid_val = int(pid.value)
            if pid_val:
                try:
                    proc_name = psutil.Process(pid_val).name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    proc_name = f"pid:{pid_val}"

        is_elevated = (
            proc_name.lower() in {"consent.exe", "credentialuibroker.exe", "logonui.exe"}
            or (pid_val > 0 and _is_process_elevated_fail_closed(pid_val))
        )
        has_pw_focus = _has_focused_password_control(hwnd)

        selector_norm = window_selector.strip().lower()
        if selector_norm and selector_norm != "active" and selector_norm not in title.lower() and selector_norm not in proc_name.lower():
            summary_text = (
                f"Jendela aktif saat ini ('{title or 'Tanpa Judul'}', {proc_name}) "
                f"tidak cocok dengan selector '{window_selector}'."
            )
        else:
            summary_text = (
                f"Metadata jendela aktif: '{title or 'Tanpa Judul'}' (aplikasi: {proc_name})."
            )
        return RawWindowObservation(
            window_title=title or "Active Window",
            process_name=proc_name,
            extraction_method="uia",
            extracted_text=summary_text,
            is_elevated_uac=is_elevated,
            has_focused_password_field=has_pw_focus,
            raw_frame_bytes=None,
        )
