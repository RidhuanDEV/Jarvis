"""Windows Safe Registered Document Opener (B10, DEC-032).

Opens ordinary safe non-executable documents strictly inside authorized roots via non-elevated OS handler.
Rejects executable, script, shortcut, and macro-enabled extensions as well as symlink/junction escapes.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from jarvis.domain.ports import (
    FileOpenReceipt,
    FilesystemSafetyPort,
    is_safe_document_open_extension,
)


class WindowsFileOpenerAdapter:
    """Windows FileOpenerPort enforcing root containment, anti-reparse, and safe extension allowlist."""

    def __init__(
        self,
        fs_port: FilesystemSafetyPort,
        *,
        allow_live_open: bool = False,
    ) -> None:
        self._fs = fs_port
        self._allow_live_open = allow_live_open

    def open_registered_file(
        self, canonical_path: str, *, authorized_root: str
    ) -> FileOpenReceipt:
        root_p = Path(authorized_root).resolve(strict=False)
        target_p = Path(canonical_path)
        try:
            rel = target_p.resolve(strict=False).relative_to(root_p)
        except ValueError:
            return FileOpenReceipt(
                opened=False,
                canonical_path=canonical_path,
                verification_kind="prohibited",
                detail=f"Path '{canonical_path}' escapes authorized root '{authorized_root}'.",
            )

        try:
            verified_path = self._fs.resolve_within_root(str(root_p), str(rel))
        except PermissionError as exc:
            return FileOpenReceipt(
                opened=False,
                canonical_path=canonical_path,
                verification_kind="prohibited",
                detail=str(exc),
            )

        insp = self._fs.inspect_path(verified_path)
        if insp.is_reparse_point:
            return FileOpenReceipt(
                opened=False,
                canonical_path=verified_path,
                verification_kind="prohibited",
                detail="Reparse point / symlink file targets are prohibited.",
            )
        resolved = Path(verified_path)
        if not resolved.is_file():
            return FileOpenReceipt(
                opened=False,
                canonical_path=verified_path,
                verification_kind="not_found",
                detail=f"File no longer exists on disk: '{resolved.name}'.",
            )

        ext = resolved.suffix.lower()
        if not is_safe_document_open_extension(ext):
            return FileOpenReceipt(
                opened=False,
                canonical_path=verified_path,
                verification_kind="prohibited",
                detail=f"File extension '{ext or '(none)'}' is prohibited for automatic opening.",
            )

        if sys.platform != "win32" or not self._allow_live_open:
            return FileOpenReceipt(
                opened=False,
                canonical_path=verified_path,
                verification_kind="disabled",
                detail="Live OS document opener is disabled in this environment.",
            )

        try:
            os.startfile(verified_path)  # noqa: S606
        except OSError as exc:
            return FileOpenReceipt(
                opened=False,
                canonical_path=verified_path,
                verification_kind="failed",
                detail=f"OS registered handler failed to open '{resolved.name}': {exc}",
            )
        return FileOpenReceipt(
            opened=True,
            canonical_path=verified_path,
            verification_kind="os_registered_open",
            detail=f"Opened '{resolved.name}' with its registered Windows application.",
        )
