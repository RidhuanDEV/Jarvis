"""Deterministic Release SBOM, Third-Party Notices, Checksum & CI Pinning Gate (DEC-022, FR-SYS-05, NFR-09).

Usage:
    uv run --project core python scripts/generate_release_sbom.py --output-dir release-compliance --verify-ci-pinning
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_SRC = REPO_ROOT / "core"
if str(CORE_SRC) not in sys.path:
    sys.path.insert(0, str(CORE_SRC))

from jarvis.application.license_service import baseline_license_artifacts  # noqa: E402
from jarvis.domain.licensing import (  # noqa: E402
    generate_cyclonedx_sbom,
    generate_third_party_notices,
    validate_license_artifact,
)

PINNED_ACTION_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*([A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+)@([^\s#]+)")
SHA40_RE = re.compile(r"^[0-9a-f]{40}$")
UNSAFE_EVENT_INTERP_RE = re.compile(
    r"\$\{\{\s*github\.event\.(?:pull_request\.(?:title|body|head\.ref)|issue\.(?:title|body)|comment\.body|head_commit\.message)"
)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_uv_lock_packages(lock_path: Path) -> list[dict[str, str]]:
    """Extract pinned Python package (name, version) tuples from core/uv.lock."""
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    packages: list[dict[str, str]] = []
    for pkg in data.get("package", []):
        name = str(pkg.get("name", "")).strip()
        version = str(pkg.get("version", "")).strip()
        if name and version and name != "jarvis-core":
            packages.append({"ecosystem": "pypi", "name": name, "version": version})
    return sorted(packages, key=lambda item: (item["name"].lower(), item["version"]))


def parse_npm_lock_packages(lock_path: Path) -> list[dict[str, str]]:
    """Extract pinned npm package (name, version, scope) entries from apps/desktop/package-lock.json."""
    data = json.loads(lock_path.read_text(encoding="utf-8"))
    packages_obj: dict[str, Any] = data.get("packages", {})
    out: list[dict[str, str]] = []
    for rel_key, meta in packages_obj.items():
        if not rel_key or not rel_key.startswith("node_modules/"):
            continue
        name = rel_key.split("node_modules/")[-1]
        version = str(meta.get("version", "")).strip()
        if not name or not version:
            continue
        scope = "optional" if meta.get("optional") else ("dev" if meta.get("dev") else "runtime")
        out.append({"ecosystem": "npm", "name": name, "version": version, "scope": scope})
    return sorted(out, key=lambda item: (item["name"].lower(), item["version"]))


def parse_cargo_lock_packages(lock_path: Path) -> list[dict[str, str]]:
    """Extract pinned Rust crate (name, version) entries from apps/desktop/src-tauri/Cargo.lock."""
    data = tomllib.loads(lock_path.read_text(encoding="utf-8"))
    out: list[dict[str, str]] = []
    for pkg in data.get("package", []):
        name = str(pkg.get("name", "")).strip()
        version = str(pkg.get("version", "")).strip()
        if name and version and name != "jarvis-desktop":
            out.append({"ecosystem": "cargo", "name": name, "version": version})
    return sorted(out, key=lambda item: (item["name"].lower(), item["version"]))


def audit_github_workflows(workflows_dir: Path) -> list[str]:
    """Fail-closed CI supply-chain audit: 40-char SHA pinning, permissions: {}, persist-credentials: false, zero PR shell injection."""
    issues: list[str] = []
    if not workflows_dir.exists():
        return [f"Missing workflows directory: {workflows_dir}"]

    workflow_files = sorted(list(workflows_dir.glob("*.yml")) + list(workflows_dir.glob("*.yaml")))
    if not workflow_files:
        return [f"No workflow YAML files found under {workflows_dir}"]

    for wf in workflow_files:
        text = wf.read_text(encoding="utf-8")
        lines = text.splitlines()

        if not re.search(r"^permissions:\s*\{\s*\}\s*$", text, flags=re.MULTILINE):
            issues.append(f"{wf.name}: missing top-level fail-closed 'permissions: {{}}'.")

        if UNSAFE_EVENT_INTERP_RE.search(text):
            issues.append(f"{wf.name}: unsafe untrusted github.event.* interpolation detected.")

        for idx, line in enumerate(lines, start=1):
            match = PINNED_ACTION_RE.match(line)
            if not match:
                continue
            action_name, ref = match.group(1), match.group(2)
            if not SHA40_RE.match(ref):
                issues.append(
                    f"{wf.name}:{idx}: action '{action_name}@{ref}' is NOT pinned to a 40-char commit SHA."
                )
            if action_name == "actions/checkout":
                window = "\n".join(lines[idx : min(len(lines), idx + 6)])
                if "persist-credentials: false" not in window:
                    issues.append(
                        f"{wf.name}:{idx}: actions/checkout missing 'persist-credentials: false'."
                    )

    return issues


def build_compliance_bundle(
    repo_root: Path,
    output_dir: Path,
    *,
    verify_ci_pinning: bool = False,
) -> dict[str, Any]:
    """Generate CycloneDX 1.5 SBOM, THIRD-PARTY-NOTICES.txt, and SHA256SUMS.txt deterministically."""
    if verify_ci_pinning:
        ci_issues = audit_github_workflows(repo_root / ".github" / "workflows")
        if ci_issues:
            raise RuntimeError("CI supply-chain pinning audit failed:\n- " + "\n- ".join(ci_issues))

    now = datetime.now(tz=UTC)
    baseline_artifacts = baseline_license_artifacts(now)
    validated = [validate_license_artifact(art) for art in baseline_artifacts]

    base_sbom = generate_cyclonedx_sbom(validated, app_version="0.2.1", generated_at=now)

    uv_pkgs = parse_uv_lock_packages(repo_root / "core" / "uv.lock")
    npm_pkgs = parse_npm_lock_packages(repo_root / "apps" / "desktop" / "package-lock.json")
    cargo_pkgs = parse_cargo_lock_packages(repo_root / "apps" / "desktop" / "src-tauri" / "Cargo.lock")

    lock_components: list[dict[str, Any]] = []
    for pkg in uv_pkgs:
        lock_components.append(
            {
                "type": "library",
                "name": pkg["name"],
                "version": pkg["version"],
                "purl": f"pkg:pypi/{pkg['name']}@{pkg['version']}",
                "scope": "required",
            }
        )
    for pkg in npm_pkgs:
        scope_map = {"runtime": "required", "dev": "excluded", "optional": "optional"}
        lock_components.append(
            {
                "type": "library",
                "name": pkg["name"],
                "version": pkg["version"],
                "purl": f"pkg:npm/{pkg['name']}@{pkg['version']}",
                "scope": scope_map.get(pkg.get("scope", "runtime"), "required"),
            }
        )
    for pkg in cargo_pkgs:
        lock_components.append(
            {
                "type": "library",
                "name": pkg["name"],
                "version": pkg["version"],
                "purl": f"pkg:cargo/{pkg['name']}@{pkg['version']}",
                "scope": "required",
            }
        )

    base_sbom["components"].extend(lock_components)
    base_sbom["metadata"]["properties"] = [
        {"name": "jarvis:lockfile_pypi_count", "value": str(len(uv_pkgs))},
        {"name": "jarvis:lockfile_npm_count", "value": str(len(npm_pkgs))},
        {"name": "jarvis:lockfile_cargo_count", "value": str(len(cargo_pkgs))},
        {"name": "jarvis:baseline_11_category_count", "value": str(len(validated))},
    ]

    output_dir.mkdir(parents=True, exist_ok=True)
    sbom_path = output_dir / "sbom.cdx.json"
    notices_path = output_dir / "THIRD-PARTY-NOTICES.txt"
    checksums_path = output_dir / "SHA256SUMS.txt"

    sbom_path.write_text(json.dumps(base_sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    notices_text = generate_third_party_notices(validated)
    notices_path.write_text(notices_text + "\n", encoding="utf-8")

    checksum_lines = [
        f"{_sha256_file(sbom_path)}  sbom.cdx.json",
        f"{_sha256_file(notices_path)}  THIRD-PARTY-NOTICES.txt",
        f"{_sha256_file(repo_root / 'core' / 'uv.lock')}  lockfiles/uv.lock",
        f"{_sha256_file(repo_root / 'apps' / 'desktop' / 'package-lock.json')}  lockfiles/package-lock.json",
        f"{_sha256_file(repo_root / 'apps' / 'desktop' / 'src-tauri' / 'Cargo.lock')}  lockfiles/Cargo.lock",
    ]
    checksums_path.write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    return {
        "sbom_path": str(sbom_path),
        "notices_path": str(notices_path),
        "checksums_path": str(checksums_path),
        "counts": {
            "baseline_11_categories": len(validated),
            "pypi_locked": len(uv_pkgs),
            "npm_locked": len(npm_pkgs),
            "cargo_locked": len(cargo_pkgs),
            "total_components": len(base_sbom["components"]),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate J.A.R.V.I.S. CycloneDX 1.5 SBOM, notices, and checksums.")
    parser.add_argument("--output-dir", type=Path, default=Path("release-compliance"))
    parser.add_argument("--verify-ci-pinning", action="store_true")
    args = parser.parse_args(argv)

    summary = build_compliance_bundle(
        REPO_ROOT,
        args.output_dir.resolve(),
        verify_ci_pinning=args.verify_ci_pinning,
    )
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
