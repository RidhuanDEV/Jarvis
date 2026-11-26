"""Isolated No-Network Document Parser for TXT, MD, PDF (pypdfium2 + pypdf) & DOCX with ZIP-Bomb Guard (B11, DEC-029)."""

from __future__ import annotations

import contextlib
import hashlib
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from jarvis.domain.knowledge import ExtractedSection

DEFAULT_MAX_FILE_BYTES = 25 * 1024 * 1024  # 25 MiB (07-DATA-DESIGN.md §3.3)
DEFAULT_MAX_DOCX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
DEFAULT_MAX_ZIP_RATIO = 50.0


@dataclass(frozen=True)
class ParsedDocumentResult:
    index_state: Literal["indexed", "ocr_required", "unsupported", "failed"]
    mime_type: str
    sha256: str
    byte_size: int
    mtime_ns: int
    sections: tuple[ExtractedSection, ...]
    diagnostic: str = ""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _parse_text_or_markdown(path: Path) -> tuple[ExtractedSection, ...]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    sections: list[ExtractedSection] = []
    current_heading = "Document"
    para_idx = 0
    buf: list[str] = []

    def _flush() -> None:
        nonlocal para_idx
        text = "\n".join(buf).strip()
        buf.clear()
        if text:
            para_idx += 1
            sections.append(
                ExtractedSection(
                    locator={"heading": current_heading, "paragraph": para_idx},
                    text=text,
                )
            )

    for line in raw.splitlines():
        heading_match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if heading_match:
            _flush()
            current_heading = heading_match.group(2).strip()
        elif not line.strip():
            _flush()
        else:
            buf.append(line)
    _flush()
    return tuple(sections)


def _parse_pdf_pypdfium2_with_pypdf_fallback(path: Path) -> tuple[tuple[ExtractedSection, ...], int]:
    """Extract real 1-based page text via pypdfium2 (DEC-029 default) with pypdf fallback."""
    sections: list[ExtractedSection] = []
    page_count = 0

    with contextlib.suppress(Exception):
        import pypdfium2

        pdf = pypdfium2.PdfDocument(str(path))
        try:
            page_count = len(pdf)
            for idx in range(page_count):
                page = pdf[idx]
                textpage = page.get_textpage()
                try:
                    text = textpage.get_text_bounded().strip()
                finally:
                    textpage.close()
                    page.close()
                if text:
                    sections.append(ExtractedSection(locator={"page": idx + 1}, text=text))
        finally:
            pdf.close()
        return (tuple(sections), page_count)

    # Fallback: pure-Python BSD-3 pypdf
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    for idx, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            sections.append(ExtractedSection(locator={"page": idx + 1}, text=text))
    return (tuple(sections), page_count)


def _validate_docx_archive_safety(
    path: Path, *, max_uncompressed_bytes: int, max_zip_ratio: float
) -> tuple[bool, str]:
    """Defend against DOCX ZIP-bombs & embedded VBA macros before parsing (T08, FR-KNO-05)."""
    try:
        with zipfile.ZipFile(path, mode="r") as zf:
            total_uncompressed = 0
            total_compressed = 0
            for info in zf.infolist():
                lower_name = info.filename.lower()
                if "vbaproject.bin" in lower_name or lower_name.endswith(".exe"):
                    return (False, f"Embedded macro/executable rejected: '{info.filename}'.")
                total_uncompressed += max(0, info.file_size)
                total_compressed += max(1, info.compress_size)
                if total_uncompressed > max_uncompressed_bytes:
                    return (
                        False,
                        f"DOCX uncompressed size ({total_uncompressed} bytes) exceeds safety cap ({max_uncompressed_bytes}).",
                    )
            ratio = total_uncompressed / max(1, total_compressed)
            if ratio > max_zip_ratio:
                return (
                    False,
                    f"DOCX ZIP compression ratio ({ratio:.1f}x) exceeds safety limit ({max_zip_ratio:.1f}x).",
                )
    except zipfile.BadZipFile:
        return (False, "Corrupt DOCX/ZIP container.")
    return (True, "ok")


def _parse_docx_safe(
    path: Path, *, max_uncompressed_bytes: int, max_zip_ratio: float
) -> tuple[tuple[ExtractedSection, ...], str | None]:
    ok, reason = _validate_docx_archive_safety(
        path, max_uncompressed_bytes=max_uncompressed_bytes, max_zip_ratio=max_zip_ratio
    )
    if not ok:
        return ((), reason)

    from docx import Document

    doc = Document(str(path))
    sections: list[ExtractedSection] = []
    current_heading = "Document"
    para_idx = 0
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        style_name = (para.style.name if para.style is not None and para.style.name else "").lower()
        if style_name.startswith("heading"):
            current_heading = text
            continue
        para_idx += 1
        sections.append(
            ExtractedSection(
                locator={"heading": current_heading, "paragraph": para_idx},
                text=text,
            )
        )
    return (tuple(sections), None)


def parse_document_safe(
    path: Path,
    *,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_docx_uncompressed_bytes: int = DEFAULT_MAX_DOCX_UNCOMPRESSED_BYTES,
    max_zip_ratio: float = DEFAULT_MAX_ZIP_RATIO,
) -> ParsedDocumentResult:
    """Parse supported local documents safely without network access or script execution."""
    st = path.stat()
    size = int(st.st_size)
    mtime_ns = int(st.st_mtime_ns)
    ext = path.suffix.lower()
    mime_map = {
        ".txt": "text/plain",
        ".md": "text/markdown",
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    mime = mime_map.get(ext, "application/octet-stream")

    if size > max_file_bytes:
        return ParsedDocumentResult(
            index_state="failed",
            mime_type=mime,
            sha256="",
            byte_size=size,
            mtime_ns=mtime_ns,
            sections=(),
            diagnostic=f"File exceeds size limit ({size} > {max_file_bytes} bytes).",
        )

    sha = _sha256_file(path)

    if ext in (".txt", ".md"):
        secs = _parse_text_or_markdown(path)
        return ParsedDocumentResult(
            index_state="indexed",
            mime_type=mime,
            sha256=sha,
            byte_size=size,
            mtime_ns=mtime_ns,
            sections=secs,
        )

    if ext == ".pdf":
        try:
            secs, page_count = _parse_pdf_pypdfium2_with_pypdf_fallback(path)
        except Exception as exc:
            return ParsedDocumentResult(
                index_state="failed",
                mime_type=mime,
                sha256=sha,
                byte_size=size,
                mtime_ns=mtime_ns,
                sections=(),
                diagnostic=f"PDF extraction failed: {type(exc).__name__}",
            )
        if page_count > 0 and not secs:
            # Honest scanned-PDF detection (FR-KNO-01)
            return ParsedDocumentResult(
                index_state="ocr_required",
                mime_type=mime,
                sha256=sha,
                byte_size=size,
                mtime_ns=mtime_ns,
                sections=(),
                diagnostic=f"PDF has {page_count} page(s) with no extractable text layer; OCR required.",
            )
        return ParsedDocumentResult(
            index_state="indexed",
            mime_type=mime,
            sha256=sha,
            byte_size=size,
            mtime_ns=mtime_ns,
            sections=secs,
        )

    if ext == ".docx":
        secs, err = _parse_docx_safe(
            path,
            max_uncompressed_bytes=max_docx_uncompressed_bytes,
            max_zip_ratio=max_zip_ratio,
        )
        if err is not None:
            return ParsedDocumentResult(
                index_state="failed",
                mime_type=mime,
                sha256=sha,
                byte_size=size,
                mtime_ns=mtime_ns,
                sections=(),
                diagnostic=err,
            )
        return ParsedDocumentResult(
            index_state="indexed",
            mime_type=mime,
            sha256=sha,
            byte_size=size,
            mtime_ns=mtime_ns,
            sections=secs,
        )

    return ParsedDocumentResult(
        index_state="unsupported",
        mime_type=mime,
        sha256=sha,
        byte_size=size,
        mtime_ns=mtime_ns,
        sections=(),
        diagnostic=f"Unsupported file extension '{ext}'.",
    )
