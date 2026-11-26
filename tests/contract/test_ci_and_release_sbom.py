"""Contract tests for CI 40-char SHA pinning and deterministic CycloneDX 1.5 SBOM / Notices generation."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from generate_release_sbom import audit_github_workflows, build_compliance_bundle  # noqa: E402


def test_real_github_workflows_pass_40_char_sha_and_least_privilege_audit() -> None:
    issues = audit_github_workflows(REPO_ROOT / ".github" / "workflows")
    assert issues == [], f"CI supply-chain audit violations: {issues}"


def test_ci_audit_recall_rejects_mutable_tags_missing_permissions_and_pr_injection(tmp_path: Path) -> None:
    wf_dir = tmp_path / "workflows"
    wf_dir.mkdir()
    bad_wf = wf_dir / "insecure.yml"
    bad_wf.write_text(
        """name: bad
on: [pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: echo "${{ github.event.pull_request.title }}"
""",
        encoding="utf-8",
    )
    issues = audit_github_workflows(wf_dir)
    joined = "\n".join(issues)
    assert "permissions: {}" in joined
    assert "NOT pinned to a 40-char commit SHA" in joined
    assert "persist-credentials: false" in joined
    assert "github.event.*" in joined


def test_release_sbom_and_notices_generation_matches_lockfiles_and_checksums(tmp_path: Path) -> None:
    out_dir = tmp_path / "compliance"
    summary = build_compliance_bundle(REPO_ROOT, out_dir, verify_ci_pinning=True)

    sbom_path = out_dir / "sbom.cdx.json"
    notices_path = out_dir / "THIRD-PARTY-NOTICES.txt"
    checksums_path = out_dir / "SHA256SUMS.txt"

    assert sbom_path.exists()
    assert notices_path.exists()
    assert checksums_path.exists()

    sbom = json.loads(sbom_path.read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert summary["counts"]["pypi_locked"] > 20
    assert summary["counts"]["npm_locked"] > 50
    assert summary["counts"]["cargo_locked"] > 50
    assert summary["counts"]["baseline_11_categories"] >= 10

    notices = notices_path.read_text(encoding="utf-8")
    assert "Apache-2.0" in notices
    assert "GPL-3.0-or-later" in notices

    # Verify SHA256SUMS matches actual generated sbom.cdx.json bytes
    actual_sbom_sha = hashlib.sha256(sbom_path.read_bytes()).hexdigest()
    checksums = checksums_path.read_text(encoding="utf-8")
    assert f"{actual_sbom_sha}  sbom.cdx.json" in checksums
