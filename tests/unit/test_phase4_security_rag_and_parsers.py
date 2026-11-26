"""Phase 4 Unit Tests: Anti-SSRF, Screen Redaction, RRF ACL Fusion, and Isolated PDF/DOCX/ZIP-Bomb Parsers."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter

from jarvis.domain.knowledge import (
    SecurityAclViolationError,
    extract_verified_citation_ids,
    fuse_hybrid_rrf,
)
from jarvis.domain.security_guards import (
    detect_private_indicators_in_query,
    is_blocked_screen_window,
    is_forbidden_ip,
    redact_screen_secrets,
    validate_outbound_url_syntax,
)
from jarvis.infrastructure.document_parser import parse_document_safe


@pytest.mark.parametrize(
    "blocked_ip",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.5",
        "192.168.1.10",
        "169.254.169.254",
        "100.64.0.1",
        "0.0.0.0",  # noqa: S104
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "::ffff:169.254.169.254",
        "::ffff:127.0.0.1",
        "2130706433",
        "0x7f000001",
        "0177.0.0.1",
    ],
)
def test_ssrf_ip_blocklist_recall_probes(blocked_ip: str) -> None:
    assert is_forbidden_ip(blocked_ip) is True


@pytest.mark.parametrize("public_ip", ["8.8.8.8", "1.1.1.1", "93.184.216.34", "2606:2800:220:1:248:1893:25c8:1946"])
def test_ssrf_ip_blocklist_precision_probes(public_ip: str) -> None:
    assert is_forbidden_ip(public_ip) is False


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "gopher://127.0.0.1:6379/",
        "https://user:pass@example.com/hook",
        "https://2130706433/admin",
        "https://0x7f000001/admin",
        "https://0177.0.0.1/admin",
        "https://127.1/admin",
        "https://metadata.google.internal/computeMetadata/v1/",
        "https://localhost/internal",
        "https://example.org:6379/",
    ],
)
def test_ssrf_url_syntax_blocks_obfuscations_and_schemes(bad_url: str) -> None:
    with pytest.raises(ValueError):
        validate_outbound_url_syntax(bad_url, require_https=False)


def test_private_query_detector_and_screen_secret_redactor_precision_recall() -> None:
    # Private query recall vs precision (FR-WEB-01)
    assert "email_address" in detect_private_indicators_in_query("find info for alice@example.com")
    assert "nik_or_national_id" in detect_private_indicators_in_query("cek nik 3174012345678901")
    assert "api_token" in detect_private_indicators_in_query("debug sk-abcdefghijklmnopqrst1234")
    assert detect_private_indicators_in_query("resep kopi pour over v60") == ()

    # Screen secret redactor recall vs precision (FR-SCR-04)
    sample_screen = (
        "Project Status 2026: 42 items active\n"
        "OPENAI_API_KEY=sk-1234567890abcdefghijklmnop\n"
        "GITHUB_TOKEN=ghp_1234567890abcdefghij123456\n"
        "Authorization: Bearer super_secret_token_9999\n"
        "AWS: AKIAIOSFODNN7EXAMPLE\n"
        "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBgkqhkiG9w0BAQEF\n-----END PRIVATE KEY-----\n"
    )
    sanitized, count = redact_screen_secrets(sample_screen)
    assert count >= 5
    assert "Project Status 2026: 42 items active" in sanitized
    assert "sk-1234567890" not in sanitized
    assert "ghp_1234567890" not in sanitized
    assert "super_secret_token_9999" not in sanitized
    assert "AKIAIOSFODNN7EXAMPLE" not in sanitized
    assert "MIIEvQIBADANBgkqhkiG9w0BAQEF" not in sanitized

    # Blocked screen windows (FR-SCR-02)
    assert is_blocked_screen_window(window_title="KeePassXC - Vault", process_name="keepassxc.exe")[0] is True
    assert is_blocked_screen_window(window_title="Admin", process_name="app.exe", is_elevated_uac=True)[0] is True
    assert is_blocked_screen_window(window_title="Login", process_name="browser.exe", has_focused_password_field=True)[0] is True
    assert is_blocked_screen_window(window_title="Notes.md - Editor", process_name="notepad.exe")[0] is False


def test_rrf_fusion_dedup_and_acl_violation_defense_in_depth() -> None:
    allowed = frozenset({"c1", "c2", "c3"})
    fused = fuse_hybrid_rrf(
        ["c1", "c1", "c2"],  # duplicate c1 in BM25 must only earn gain once!
        ["c2", "c3"],
        allowed_ids=allowed,
        k=60,
        top_k=5,
    )
    ids = [item[0] for item in fused]
    assert len(ids) == len(set(ids)) == 3
    # c2 appears in both BM25 (rank 3) and Vector (rank 1) -> highest RRF score!
    assert ids[0] == "c2"

    # Revoked/unauthorized chunk entering RRF pool MUST fail loudly
    with pytest.raises(SecurityAclViolationError):
        fuse_hybrid_rrf(["c1", "revoked_chunk"], [], allowed_ids=allowed)

    valid, invalid = extract_verified_citation_ids(
        "Evidence [cite:c1] and hallucinated [cite:fake99].", allowed
    )
    assert valid == ["c1"] and invalid == ["fake99"]


def test_isolated_document_parser_md_docx_pdf_ocr_required_and_zip_bomb(tmp_path: Path) -> None:
    # 1. Markdown with headings
    md = tmp_path / "arch.md"
    md.write_text("# Orbital Design\n\nLocal-first architecture works offline.\n", encoding="utf-8")
    p_md = parse_document_safe(md)
    assert p_md.index_state == "indexed"
    assert p_md.sections[0].locator["heading"] == "Orbital Design"

    # 2. Valid DOCX (real heading/paragraph locators, never fake page numbers)
    docx_path = tmp_path / "guide.docx"
    doc = Document()
    doc.add_heading("Backup Policy", level=1)
    doc.add_paragraph("Backups use Argon2id and AES-256-GCM.")
    doc.save(str(docx_path))
    p_docx = parse_document_safe(docx_path)
    assert p_docx.index_state == "indexed"
    assert p_docx.sections[0].locator["heading"] == "Backup Policy"
    assert "page" not in p_docx.sections[0].locator

    # 3. DOCX ZIP-bomb defense (high compression ratio > 50x rejected!)
    bomb_path = tmp_path / "bomb.docx"
    with zipfile.ZipFile(bomb_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/document.xml", "A" * (2 * 1024 * 1024))
    p_bomb = parse_document_safe(bomb_path, max_zip_ratio=50.0)
    assert p_bomb.index_state == "failed"
    assert "ratio" in p_bomb.diagnostic.lower()

    # 4. DOCX with embedded VBA macro rejected
    macro_path = tmp_path / "macro.docx"
    with zipfile.ZipFile(macro_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("word/vbaProject.bin", b"FAKE-MACRO")
    p_macro = parse_document_safe(macro_path)
    assert p_macro.index_state == "failed"
    assert "macro" in p_macro.diagnostic.lower()

    # 5. Blank/scanned PDF with 0 text layer -> honestly flagged ocr_required (FR-KNO-01)
    scanned_pdf = tmp_path / "scanned.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with scanned_pdf.open("wb") as fh:
        writer.write(fh)
    p_pdf = parse_document_safe(scanned_pdf)
    assert p_pdf.index_state == "ocr_required"

    # 6. Unsupported extension
    unk = tmp_path / "archive.xyz"
    unk.write_bytes(b"12345")
    assert parse_document_safe(unk).index_state == "unsupported"
