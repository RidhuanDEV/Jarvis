"""Contract schema validation & NFR-16 / T18 static portability & anti-hardcode checks."""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import jsonschema
import pytest
from jsonschema import Draft202012Validator

from jarvis.application.config_service import build_default_config, build_default_storage_roots
from jarvis.domain.models import (
    LicenseArtifact,
    LicenseArtifactCategory,
    SequencedEvent,
    ToolProposal,
    ToolStepProposal,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / "contracts"


@pytest.mark.parametrize(
    "schema_name",
    [
        "config.schema.v1.json",
        "tool-proposal.schema.v1.json",
        "events.schema.v1.json",
        "license-artifact.schema.v1.json",
    ],
)
def test_all_json_contracts_are_valid_draft_2020_12(schema_name: str) -> None:
    schema = json.loads((CONTRACTS_DIR / schema_name).read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)


def test_models_conform_to_json_contracts_and_negative_cases_fail() -> None:
    config_schema = json.loads((CONTRACTS_DIR / "config.schema.v1.json").read_text(encoding="utf-8"))
    roots = build_default_storage_roots(Path("/data/jarvis"), Path("/cache/jarvis"))
    cfg = build_default_config(roots).model_dump(mode="json")
    jsonschema.validate(instance=cfg, schema=config_schema)

    # Negative: allow_cross_zone_fallback=True MUST fail schema
    bad_cfg = json.loads(json.dumps(cfg))
    bad_cfg["ai"]["allow_cross_zone_fallback"] = True
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_cfg, schema=config_schema)

    # Tool proposal schema: 1..5 steps valid, extra property or 6 steps invalid
    tool_schema = json.loads(
        (CONTRACTS_DIR / "tool-proposal.schema.v1.json").read_text(encoding="utf-8")
    )
    prop = ToolProposal(
        steps=(ToolStepProposal(tool_id="os.volume.set", version=1, args={"percent": 50}),)
    ).model_dump(mode="json")
    jsonschema.validate(instance=prop, schema=tool_schema)

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"steps": [{"tool_id": "os.volume.set", "version": 1, "args": {}, "risk": "R0"}]},
            schema=tool_schema,
        )

    # Event envelope schema
    ev_schema = json.loads((CONTRACTS_DIR / "events.schema.v1.json").read_text(encoding="utf-8"))
    ev = SequencedEvent(
        event_id="12345678-1234-5678-1234-567812345678",
        seq=1,
        request_id="req-12345",
        correlation_id="corr-12345",
        type="approval.required",
        occurred_at=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
        payload={"approval_id": "a1"},
    ).model_dump(mode="json")
    jsonschema.validate(instance=ev, schema=ev_schema)

    # License schema blocks Unknown
    lic_schema = json.loads(
        (CONTRACTS_DIR / "license-artifact.schema.v1.json").read_text(encoding="utf-8")
    )
    lic = LicenseArtifact(
        id="pkg-demo",
        category=LicenseArtifactCategory.APP_PACKAGE,
        name="Demo",
        version_or_rev="1.0.0",
        license_spdx="MIT",
        obligations=("attribution_notice",),
        source_url="https://example.org/demo",
        notice_text="MIT",
        verified_at=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
    ).model_dump(mode="json")
    jsonschema.validate(instance=lic, schema=lic_schema)

    bad_lic = dict(lic)
    bad_lic["license_spdx"] = "Unknown"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=bad_lic, schema=lic_schema)


def test_nfr16_zero_os_win32_imports_in_domain_and_application() -> None:
    forbidden = {
        "ctypes",
        "winreg",
        "msvcrt",
        "pynvml",
        "win32api",
        "win32con",
        "fastapi",
        "uvicorn",
        "jarvis.platform",
        "jarvis.transport",
    }
    violations: list[str] = []
    for layer in ("domain", "application"):
        layer_dir = REPO_ROOT / "core" / "jarvis" / layer
        for py_file in layer_dir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if any(alias.name == f or alias.name.startswith(f"{f}.") for f in forbidden):
                            violations.append(f"{py_file.relative_to(REPO_ROOT)}: import {alias.name}")
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mod = node.module
                    if any(mod == f or mod.startswith(f"{f}.") for f in forbidden):
                        violations.append(f"{py_file.relative_to(REPO_ROOT)}: from {mod}")
    assert violations == [], f"NFR-16 portability violations: {violations}"


def test_t18_zero_hardcoded_developer_paths_or_hardware_in_product_code() -> None:
    forbidden_patterns = (
        re.compile(r"C:\\Users\\[A-Za-z0-9._-]+", re.IGNORECASE),
        re.compile(r"[D-Z]:\\[^\r\n\"']+\\Jarvis", re.IGNORECASE),
        re.compile(r"\bRTX\s*3050\b", re.IGNORECASE),
        re.compile(r"\bIntel\s+UHD\b", re.IGNORECASE),
        re.compile(r"\bAsia/Jakarta\b"),
        re.compile(r'"WIB"'),
    )
    scan_roots = (
        REPO_ROOT / "contracts",
        REPO_ROOT / "core" / "jarvis",
        REPO_ROOT / "apps" / "desktop" / "src",
        REPO_ROOT / "apps" / "desktop" / "src-tauri" / "src",
    )
    findings: list[str] = []
    for root in scan_roots:
        for path in root.rglob("*"):
            if not path.is_file() or path.suffix not in {".py", ".ts", ".tsx", ".rs", ".json", ".css"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for pat in forbidden_patterns:
                if pat.search(text):
                    findings.append(f"{path.relative_to(REPO_ROOT)} matched {pat.pattern}")
    assert findings == [], f"Hardcoded machine/developer artifacts found: {findings}"
