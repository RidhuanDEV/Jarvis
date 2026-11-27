"""Stage G2 Integration & Security Verification Suite (B07, B08, B09, B10)."""

from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from jarvis.domain.app_catalog import (
    TIER3_PROHIBITED_BINARIES,
    ApplicationCatalogEntry,
    is_prohibited_binary_target,
)
from jarvis.platform.portable_mock import (
    FakeDesktopAutomationAdapter,
    FakeFileOpenerAdapter,
    InMemoryProcessSupervisor,
    InMemoryVaultAdapter,
    PortableFilesystemSafetyAdapter,
    StaticApplicationCatalogAdapter,
)
from jarvis.platform.windows.app_catalog import WindowsApplicationCatalogAdapter, parse_windows_lnk
from jarvis.platform.windows.desktop_automation import WindowsDesktopAutomationAdapter
from jarvis.platform.windows.filesystem import WindowsFilesystemSafetyAdapter
from jarvis.transport.app import build_default_container, create_app
from jarvis.transport.settings import CoreStartupSettings


def _build_minimal_ms_shllink(target_path: str, arguments: str = "") -> bytes:
    """Build a spec-compliant [MS-SHLLINK] .lnk binary for deterministic parser testing."""
    flags = 0x02 | 0x80  # HasLinkInfo | IsUnicode
    if arguments:
        flags |= 0x20  # HasArguments

    header = bytearray(0x4C)
    struct.pack_into("<I", header, 0, 0x4C)
    header[4:20] = bytes.fromhex("0114020000000000c000000000000046")
    struct.pack_into("<I", header, 20, flags)

    # LinkInfo (HeaderSize=0x1C, Flags=VolumeIDAndLocalBasePath=1)
    vol_id = struct.pack("<IIIIB", 17, 3, 0, 16, 0)  # 17-byte minimal VolumeID
    local_bytes = target_path.encode("latin-1") + b"\x00"
    suffix_bytes = b"\x00"
    vol_offset = 0x1C
    local_offset = vol_offset + len(vol_id)
    suffix_offset = local_offset + len(local_bytes)
    link_info_size = suffix_offset + len(suffix_bytes)
    link_info = (
        struct.pack("<IIIIIII", link_info_size, 0x1C, 0x01, vol_offset, local_offset, 0, suffix_offset)
        + vol_id
        + local_bytes
        + suffix_bytes
    )

    string_data = b""
    if arguments:
        arg_u16 = arguments.encode("utf-16-le")
        string_data = struct.pack("<H", len(arguments)) + arg_u16

    return bytes(header) + link_info + string_data + struct.pack("<I", 0)


def _create_g2_app(
    tmp_path: Path,
    *,
    tier1_auto_allow: bool = True,
    catalog_entries: tuple[ApplicationCatalogEntry, ...] | None = None,
    use_windows_fs: bool = False,
) -> tuple[TestClient, dict[str, str], FakeDesktopAutomationAdapter, FakeFileOpenerAdapter]:
    token = "g" * 64
    settings = CoreStartupSettings(
        env="test",
        log_level="WARNING",
        base_data_dir=tmp_path / "data",
        base_cache_dir=tmp_path / "cache",
        auth_token=token,
    )
    fake_desktop = FakeDesktopAutomationAdapter()
    fake_opener = FakeFileOpenerAdapter(allow_live_open=True)
    catalog = StaticApplicationCatalogAdapter(catalog_entries)
    fs_adapter = WindowsFilesystemSafetyAdapter() if (use_windows_fs and sys.platform == "win32") else PortableFilesystemSafetyAdapter()
    container = build_default_container(
        settings,
        fs_port=fs_adapter,
        supervisor=InMemoryProcessSupervisor(),
        vault=InMemoryVaultAdapter(),
        desktop_port=fake_desktop,
        app_catalog=catalog,
        file_opener=fake_opener,
        tier1_auto_allow=tier1_auto_allow,
    )
    app = create_app(container)
    headers = {"Authorization": f"Bearer {token}", "Host": "127.0.0.1:47123"}
    return TestClient(app), headers, fake_desktop, fake_opener


def test_b07_fast_health_deep_integrity_and_non_destructive_cancel(tmp_path: Path) -> None:
    client, headers, _desktop, _opener = _create_g2_app(tmp_path)
    with client:
        started = time.perf_counter()
        health = client.get("/v1/health", headers=headers)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        assert health.status_code == 200
        assert health.json()["status"] == "ready"
        assert health.json()["components"]["core_db_ok"] is True
        assert elapsed_ms < 250.0  # Fast SELECT 1 check (not full PRAGMA integrity_check)

        deep = client.get("/v1/diagnostics/integrity", headers=headers)
        assert deep.status_code == 200
        assert deep.json()["integrity"]["core_db_ok"] is True
        assert deep.json()["integrity"]["knowledge_db_ok"] is True

        # Non-destructive request cancel publishes sequenced SSE event and keeps Core alive
        cancel = client.post("/v1/requests/cancel", headers=headers, json={"request_id": "req-cancel-1"})
        assert cancel.status_code == 200
        assert cancel.json()["canceled"] is True

        sse = client.get("/v1/events?after_seq=0&once=true", headers=headers)
        assert sse.status_code == 200
        assert "request.state_changed" in sse.text
        assert "req-cancel-1" in sse.text

        # Core remains responsive after cancel
        health2 = client.get("/v1/health", headers=headers)
        assert health2.status_code == 200
        assert health2.json()["event_seq"] >= 1


def test_b09_u_a01_bilingual_app_launch_punctuation_and_tier1_auto_allow(tmp_path: Path) -> None:
    entries = (
        ApplicationCatalogEntry(
            app_id="calculator",
            display_name="Calculator",
            activation_kind="exe",
            target="C:\\Windows\\System32\\calc.exe",
            aliases=("kalkulator", "calc"),
            source="windows_inbox",
            trust_class="tier1_ordinary",
        ),
        ApplicationCatalogEntry(
            app_id="google_chrome",
            display_name="Google Chrome",
            activation_kind="exe",
            target="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            aliases=("chrome", "google chrome"),
            source="windows_start_menu",
            trust_class="tier1_ordinary",
        ),
        ApplicationCatalogEntry(
            app_id="visual_studio_code",
            display_name="Visual Studio Code",
            activation_kind="exe",
            target="C:\\Users\\Demo\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe",
            aliases=("vscode", "vs code", "code"),
            source="windows_start_menu",
            trust_class="tier1_ordinary",
        ),
        ApplicationCatalogEntry(
            app_id="file_explorer",
            display_name="File Explorer",
            activation_kind="exe",
            target="C:\\Windows\\explorer.exe",
            aliases=("explorer", "penjelajah file"),
            source="windows_inbox",
            trust_class="tier1_ordinary",
        ),
    )
    client, headers, desktop, _opener = _create_g2_app(
        tmp_path, tier1_auto_allow=True, catalog_entries=entries
    )
    with client:
        # Zero explicit grants needed for Tier-1 ordinary safe tools under DEC-012 amendment
        apps_resp = client.get("/v1/apps", headers=headers)
        assert apps_resp.status_code == 200
        assert apps_resp.json()["count"] == 4

        # Punctuation boundary & polite prefixes + Indonesian/English aliases
        for utterance, expected_id in [
            ("Buka kalkulator.", "calculator"),
            ("Hey Jarvis, tolong buka Chrome!", "google_chrome"),
            ("buka vscode", "visual_studio_code"),
            ("Tolong bukakan penjelajah file.", "file_explorer"),
        ]:
            resp = client.post("/v1/requests", headers=headers, json={"utterance": utterance})
            assert resp.status_code == 200, f"Failed for {utterance}: {resp.text}"
            body = resp.json()
            assert body["llm_called"] is False
            assert body["steps"][0]["verified"] is True
            assert body["steps"][0]["data"]["app_id"] == expected_id
            assert body["steps"][0]["data"]["verification_kind"] == "os_activation_ack"

        assert desktop.launched_apps == [
            "calculator",
            "google_chrome",
            "visual_studio_code",
            "file_explorer",
        ]

        # Owner's real Whisper variant "sekarangnya berapa?" resolves deterministically to time
        time_resp = client.post(
            "/v1/requests", headers=headers, json={"utterance": "Hey Jarvis, sekarangnya berapa?"}
        )
        assert time_resp.status_code == 200
        assert time_resp.json()["route_kind"] == "system.time"
        assert time_resp.json()["steps"][0]["verified"] is True

        # Explicit owner revocation MUST override Tier-1 auto-allow!
        grant_res = client.put("/v1/grants", headers=headers, json={"capability": "os.app.launch"})
        assert grant_res.status_code == 200
        gid = grant_res.json()["grant_id"]
        assert client.delete(f"/v1/grants/{gid}", headers=headers).status_code == 200

        blocked = client.post("/v1/requests", headers=headers, json={"utterance": "Buka kalkulator"})
        assert blocked.status_code == 403
        assert blocked.json()["code"] == "DENIED"


def test_b09_u_a02_negation_meta_question_and_ambiguity_disambiguation(tmp_path: Path) -> None:
    entries = (
        ApplicationCatalogEntry(
            app_id="google_chrome",
            display_name="Google Chrome",
            activation_kind="exe",
            target="C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
            aliases=("chrome",),
        ),
        ApplicationCatalogEntry(
            app_id="visual_studio_code",
            display_name="Visual Studio Code",
            activation_kind="exe",
            target="C:\\Apps\\VSCode\\Code.exe",
            aliases=("vs code",),
        ),
        ApplicationCatalogEntry(
            app_id="visual_studio_2022",
            display_name="Visual Studio 2022",
            activation_kind="exe",
            target="C:\\Apps\\VS2022\\devenv.exe",
            aliases=("vs 2022",),
        ),
    )
    client, headers, desktop, _opener = _create_g2_app(
        tmp_path, tier1_auto_allow=True, catalog_entries=entries
    )
    with client:
        # Negations MUST NOT launch any app
        for negation in ("Jangan buka Chrome", "Tidak usah buka Chrome.", "Don't open Chrome"):
            res = client.post("/v1/requests", headers=headers, json={"utterance": negation})
            assert res.status_code == 200
            assert res.json()["route_kind"] == "direct_mode_no_match"
        assert desktop.launched_apps == []

        # Educational meta-questions about shells MUST NOT trigger false R3 DENIED
        for meta_q in ("Apa itu PowerShell?", "What is cmd.exe?", "Jelaskan tentang terminal"):
            res = client.post("/v1/requests", headers=headers, json={"utterance": meta_q})
            assert res.status_code == 200, f"Meta-question falsely blocked: {meta_q} -> {res.text}"
            assert res.json()["route_kind"] == "direct_mode_no_match"

        # Ambiguous query "Buka Visual Studio" MUST ask clarification instead of launching wrong app
        ambig = client.post("/v1/requests", headers=headers, json={"utterance": "Buka Visual Studio"})
        assert ambig.status_code == 200
        assert ambig.json()["steps"][0]["data"]["status"] == "ambiguous"
        assert desktop.launched_apps == []


def test_b09_tier3_lolbins_and_malicious_lnk_shortcuts_blocked_zero_bypass(tmp_path: Path) -> None:
    # 1. Construct real MS-SHLLINK .lnk fixtures in a simulated Start Menu directory
    bin_dir = tmp_path / "bins"
    bin_dir.mkdir()
    benign_exe = bin_dir / "SafeBrowser.exe"
    benign_exe.write_bytes(b"MZ-fake-exe")
    unins_exe = bin_dir / "unins000.exe"
    unins_exe.write_bytes(b"MZ-fake-unins")
    ps_exe = bin_dir / "powershell.exe"
    ps_exe.write_bytes(b"MZ-fake-ps")

    start_menu = tmp_path / "StartMenu"
    start_menu.mkdir()
    benign_lnk = start_menu / "Safe Browser.lnk"
    benign_lnk.write_bytes(_build_minimal_ms_shllink(str(benign_exe)))

    mal_ps_lnk = start_menu / "Friendly Helper.lnk"
    mal_ps_lnk.write_bytes(_build_minimal_ms_shllink(str(ps_exe), "-enc SQBFAFgA"))

    mal_args_lnk = start_menu / "Trojan Browser.lnk"
    mal_args_lnk.write_bytes(_build_minimal_ms_shllink(str(benign_exe), "/c powershell -command whoami"))

    unins_lnk = start_menu / "Uninstall Safe Browser.lnk"
    unins_lnk.write_bytes(_build_minimal_ms_shllink(str(unins_exe)))

    # Verify raw parser extracts target & args accurately
    t_benign, a_benign = parse_windows_lnk(benign_lnk)
    assert t_benign is not None and t_benign.endswith("SafeBrowser.exe") and a_benign == ""
    t_mal, a_mal = parse_windows_lnk(mal_ps_lnk)
    assert t_mal is not None and t_mal.endswith("powershell.exe") and "-enc" in a_mal

    # Catalog discovery MUST include ONLY Safe Browser and reject all 3 malicious/uninstaller shortcuts
    adapter = WindowsApplicationCatalogAdapter(
        start_menu_dirs=(start_menu,),
        scan_registry=False,
        include_inbox_apps=False,
    )
    discovered = adapter.list_apps()
    assert [e.display_name for e in discovered] == ["Safe Browser"]

    # 2. Live host Windows catalog check: discovers real apps & contains ZERO Tier-3 binaries
    if sys.platform == "win32":
        live_adapter = WindowsApplicationCatalogAdapter(scan_registry=True, include_inbox_apps=True)
        live_apps = live_adapter.list_apps()
        assert len(live_apps) >= 5
        for entry in live_apps:
            assert entry.trust_class != "tier3_prohibited"
            if entry.activation_kind == "exe":
                assert not is_prohibited_binary_target(entry.target, entry.arguments), (
                    f"Prohibited binary leaked into live catalog: {entry}"
                )
                assert Path(entry.target).name.lower() not in TIER3_PROHIBITED_BINARIES

    # 3. Honest disabled launcher check: allow_live_launch=False MUST NEVER claim accepted=True
    disabled_launcher = WindowsDesktopAutomationAdapter(allow_live_launch=False)
    disabled_receipt = disabled_launcher.launch_catalog_entry(discovered[0])
    assert disabled_receipt.accepted is False
    assert disabled_receipt.verification_kind == "disabled"

    # 4. End-to-end API Tier-3 bypass probes with tier1_auto_allow=True -> 100% 403 DENIED
    client, headers, desktop, _opener = _create_g2_app(tmp_path, tier1_auto_allow=True)
    with client:
        for evil_cmd in (
            "buka powershell",
            "buka cmd.exe",
            "buka regedit",
            "buka diskpart",
            "jalankan powershell whoami",
            "hapus file penting.docx",
        ):
            r = client.post("/v1/requests", headers=headers, json={"utterance": evil_cmd})
            assert r.status_code == 403, f"Tier-3 command NOT blocked: {evil_cmd} -> {r.status_code} {r.text}"
            assert r.json()["code"] == "DENIED"
        assert desktop.launched_apps == []


def test_b10_u_f01_scoped_metadata_index_exact_fuzzy_stale_junction_and_safe_open(tmp_path: Path) -> None:
    # Build synthetic authorized folder tree
    root = tmp_path / "AuthorizedDocs"
    (root / "Finance").mkdir(parents=True)
    (root / "Archive").mkdir(parents=True)
    (root / "Notes").mkdir(parents=True)
    (root / ".ssh").mkdir(parents=True)
    (root / "node_modules" / "pkg").mkdir(parents=True)

    f_tax_1 = root / "Finance" / "Laporan_Pajak_2026.pdf"
    f_tax_2 = root / "Archive" / "Laporan_Pajak_2026.pdf"
    f_unicode = root / "Notes" / "Catatan_Rapat_Keuangan_Élan.docx"
    f_sheet = root / "Finance" / "Anggaran_Q4.xlsx"
    f_stale = root / "Notes" / "Draft_Sementara.txt"
    f_ps1 = root / "Notes" / "deploy.ps1"
    f_exe = root / "Notes" / "installer.exe"
    f_bat = root / "Notes" / "run.bat"
    f_docm = root / "Notes" / "macro.docm"

    for p, content in [
        (f_tax_1, b"%PDF-1.4 tax 2026 final"),
        (f_tax_2, b"%PDF-1.4 tax 2026 archive"),
        (f_unicode, b"docx-content"),
        (f_sheet, b"xlsx-content"),
        (f_stale, b"will be deleted externally"),
        (f_ps1, b"Write-Host 'blocked'"),
        (f_exe, b"MZ-blocked"),
        (f_bat, b"@echo off"),
        (f_docm, b"macro-blocked"),
        (root / ".ssh" / "id_rsa", b"PRIVATE KEY"),
        (root / ".env", b"SECRET_KEY=123"),
        (root / "Notes" / "server.pem", b"PEM"),
        (root / "node_modules" / "pkg" / "index.js", b"console.log(1)"),
    ]:
        p.write_bytes(content)

    # Set distinct mtimes so recent-file ordering is deterministic
    now_ts = time.time()
    os.utime(f_tax_2, (now_ts - 86400 * 30, now_ts - 86400 * 30))
    os.utime(f_sheet, (now_ts - 3600, now_ts - 3600))
    os.utime(f_tax_1, (now_ts - 60, now_ts - 60))

    # Create outside-scope directory + real Windows NTFS junction inside root
    outside = tmp_path / "OutsideSecret"
    outside.mkdir()
    (outside / "secret_bank.pdf").write_bytes(b"%PDF-secret")
    junction_created = False
    if sys.platform == "win32":
        junction_path = root / "EscapeJunction"
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction_path), str(outside)],
            capture_output=True,
            text=True,
            check=False,
        )
        junction_created = proc.returncode == 0

    client, headers, _desktop, opener = _create_g2_app(
        tmp_path, tier1_auto_allow=True, use_windows_fs=True
    )
    with client:
        # 1. Register authorized root & index Layer-1 metadata
        add_r = client.post("/v1/roots", headers=headers, json={"path": str(root)})
        assert add_r.status_code == 201
        root_id = add_r.json()["root"]["id"]

        idx_r = client.post(f"/v1/files/index/{root_id}", headers=headers)
        assert idx_r.status_code == 200
        idx_body = idx_r.json()
        assert idx_body["indexed_files"] == 9
        assert idx_body["skipped_excluded"] >= 4  # .ssh, node_modules, .env, server.pem
        if junction_created:
            assert idx_body["skipped_reparse_points"] >= 1

        # 2. Verify excluded secrets & outside junction files NEVER appear in search
        for leak_query in ("id_rsa", ".env", "server.pem", "secret_bank"):
            leak_res = client.post("/v1/files/search", headers=headers, json={"query": leak_query})
            assert leak_res.status_code == 200
            assert leak_res.json()["hits"] == [], f"Sensitive/escaped file leaked: {leak_query}"

        # 3. Exact filename search -> 100% top-1 accuracy (newest duplicate first)
        exact_res = client.post(
            "/v1/files/search", headers=headers, json={"query": "Laporan_Pajak_2026.pdf"}
        )
        assert exact_res.status_code == 200
        exact_hits = exact_res.json()["hits"]
        assert len(exact_hits) == 2
        assert exact_hits[0]["relative_path"] == "Finance/Laporan_Pajak_2026.pdf"

        # 4. Fuzzy search with typos & Unicode filename -> found in top-3
        fuzzy_1 = client.post("/v1/files/search", headers=headers, json={"query": "Laporn Pajk"})
        assert any(h["display_name"] == "Laporan_Pajak_2026.pdf" for h in fuzzy_1.json()["hits"][:3])

        fuzzy_2 = client.post("/v1/files/search", headers=headers, json={"query": "Catatan Rapat Elan"})
        assert any("Élan" in h["display_name"] for h in fuzzy_2.json()["hits"][:3])

        # 5. Extension & modified_after filter
        ext_res = client.post(
            "/v1/files/search",
            headers=headers,
            json={
                "query": "",
                "ext": ".xlsx",
                "modified_after_utc": (datetime.now(tz=UTC) - timedelta(days=1)).isoformat(),
            },
        )
        assert ext_res.status_code == 200
        assert [h["display_name"] for h in ext_res.json()["hits"]] == ["Anggaran_Q4.xlsx"]

        # 6. Warm search latency check: p95 <= 300 ms across 20 queries
        latencies: list[float] = []
        for q in ("Laporan_Pajak_2026", "Anggaran", "Catatan", ""):
            for _ in range(5):
                t0 = time.perf_counter()
                r = client.post("/v1/files/search", headers=headers, json={"query": q})
                assert r.status_code == 200
                latencies.append((time.perf_counter() - t0) * 1000.0)
        latencies.sort()
        p95_ms = latencies[int(len(latencies) * 0.95) - 1]
        assert p95_ms <= 300.0, f"Warm search p95 exceeded 300ms: {p95_ms:.2f}ms"

        # 7. Externally vanished stale file detection -> flagged unavailable & refuses open
        f_stale.unlink()
        stale_search = client.post(
            "/v1/files/search", headers=headers, json={"query": "Draft_Sementara.txt"}
        )
        assert stale_search.status_code == 200
        assert stale_search.json()["hits"][0]["availability"] == "unavailable"
        stale_open = client.post(
            "/v1/files/open", headers=headers, json={"file_query": "Draft_Sementara.txt"}
        )
        assert stale_open.status_code == 404

        # 8. Conversational working-set flow via /v1/requests: search -> "buka nomor 1"
        turn_search = client.post(
            "/v1/requests",
            headers=headers,
            json={"utterance": "Cari file pdf pajak", "session_id": "sess-files-1"},
        )
        assert turn_search.status_code == 200
        assert turn_search.json()["steps"][0]["data"]["count"] == 2

        turn_open = client.post(
            "/v1/requests",
            headers=headers,
            json={"utterance": "Buka nomor 1", "session_id": "sess-files-1"},
        )
        assert turn_open.status_code == 200
        assert turn_open.json()["steps"][0]["verified"] is True
        assert opener.opened_paths[-1].endswith("Laporan_Pajak_2026.pdf")

        # 9. Prohibited executable/script/macro extensions MUST be 403 DENIED
        for dangerous_file in ("deploy.ps1", "installer.exe", "run.bat", "macro.docm"):
            bad_open = client.post(
                "/v1/requests",
                headers=headers,
                json={"utterance": f"Buka file {dangerous_file}", "session_id": "sess-files-1"},
            )
            assert bad_open.status_code == 403, f"Dangerous file was not blocked: {dangerous_file}"
            assert bad_open.json()["code"] == "DENIED"

        # 10. Revoking root purges file_metadata immediately (zero stale recall!)
        rev = client.delete(f"/v1/roots/{root_id}", headers=headers)
        assert rev.status_code == 200
        after_revoke = client.post(
            "/v1/files/search", headers=headers, json={"query": "Laporan_Pajak_2026.pdf"}
        )
        assert after_revoke.status_code == 200
        assert after_revoke.json()["hits"] == []
