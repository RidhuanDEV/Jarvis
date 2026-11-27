"""Windows Native Non-Shell Notification Adapter (B15, FR-SCH-04).

Uses Win32 Shell_NotifyIconW (NIF_INFO) balloon/toast notification without spawning PowerShell or cmd.exe.
Reports truthful OS API acceptance (distinguishing OS accepted vs user seen).
"""

from __future__ import annotations

import ctypes
import sys

_NIM_ADD = 0x00000000
_NIM_DELETE = 0x00000002
_NIF_INFO = 0x00000010
_NIIF_INFO = 0x00000001
_NIIF_NOSOUND = 0x00000010


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint32),
        ("hWnd", ctypes.c_void_p),
        ("uID", ctypes.c_uint32),
        ("uFlags", ctypes.c_uint32),
        ("uCallbackMessage", ctypes.c_uint32),
        ("hIcon", ctypes.c_void_p),
        ("szTip", ctypes.c_wchar * 128),
        ("dwState", ctypes.c_uint32),
        ("dwStateMask", ctypes.c_uint32),
        ("szInfo", ctypes.c_wchar * 256),
        ("uTimeoutOrVersion", ctypes.c_uint32),
        ("szInfoTitle", ctypes.c_wchar * 64),
        ("dwInfoFlags", ctypes.c_uint32),
        ("guidItem", _GUID),
        ("hBalloonIcon", ctypes.c_void_p),
    ]


class WindowsToastNotificationAdapter:
    """Real non-shell Windows NotificationPort using Win32 Shell_NotifyIconW (B15)."""

    def __init__(self, *, allow_live_toast: bool = True) -> None:
        self._allow_live_toast = allow_live_toast
        self._next_id = 4000

    def send_local_notification(self, title: str, body: str, *, silent: bool = False) -> bool:
        if sys.platform != "win32" or not self._allow_live_toast:
            return False
        try:
            user32 = ctypes.windll.user32
            shell32 = ctypes.windll.shell32
            hwnd = user32.GetDesktopWindow()
            self._next_id += 1
            nid = _NOTIFYICONDATAW()
            nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
            nid.hWnd = hwnd
            nid.uID = self._next_id
            nid.uFlags = _NIF_INFO
            nid.szInfoTitle = title[:63]
            nid.szInfo = body[:255]
            nid.dwInfoFlags = _NIIF_INFO | (_NIIF_NOSOUND if silent else 0)
            added = bool(shell32.Shell_NotifyIconW(_NIM_ADD, ctypes.byref(nid)))
            if added:
                shell32.Shell_NotifyIconW(_NIM_DELETE, ctypes.byref(nid))
            return added
        except Exception:
            return False
