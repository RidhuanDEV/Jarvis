"""Windows authoritative OS workstation lock probe (IR-07, DEF-26, FR-ADM-03).

Isolated strictly inside platform/windows/ to preserve NFR-16 / DEC-023 portability boundaries.
"""

from __future__ import annotations

import ctypes
import sys

DESKTOP_SWITCHDESKTOP = 0x0100


def is_windows_workstation_locked() -> bool:
    """Query Win32 OpenInputDesktop to detect locked workstation / secure desktop without admin privileges."""
    if sys.platform != "win32":
        return False
    user32 = ctypes.windll.user32
    # OpenInputDesktop fails (returns 0) when workstation is locked or displaying secure desktop (Winlogon/UAC).
    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not hdesk:
        return True
    try:
        return False
    finally:
        user32.CloseDesktop(hdesk)
