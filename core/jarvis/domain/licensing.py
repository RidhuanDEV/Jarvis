"""11-Category Artifact & License Compliance Inventory, CycloneDX SBOM & NOTICE generator (DEC-022, BR-SYS-03)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.domain.models import ErrorCode, LicenseArtifact, LicenseArtifactCategory

BLOCKED_LICENSE_TOKENS: frozenset[str] = frozenset(
    {"", "unknown", "unlicensed_unknown", "none", "tbd", "n/a", "proprietary_unknown"}
)

PERMISSIVE_SPDX_PREFIXES: tuple[str, ...] = (
    "MIT",
    "Apache-2.0",
    "BSD-2-Clause",
    "BSD-3-Clause",
    "ISC",
    "PSF-2.0",
    "Zlib",
    "BSL-1.0",
    "Unlicense",
    "CC0-1.0",
    "OFL-1.1",
    "SIL-OFL-1.1",
)

WEAK_COPYLEFT_PREFIXES: tuple[str, ...] = ("MPL-2.0", "LGPL-2.1", "LGPL-3.0")
STRONG_COPYLEFT_PREFIXES: tuple[str, ...] = ("GPL-2.0", "GPL-3.0")
NETWORK_COPYLEFT_PREFIXES: tuple[str, ...] = ("AGPL-3.0",)
ATTRIBUTION_CONTENT_PREFIXES: tuple[str, ...] = ("CC-BY-",)


class LicenseValidationError(ValueError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_code = ErrorCode.LICENSE_UNVERIFIED


def _matches_prefix(spdx: str, prefixes: tuple[str, ...]) -> bool:
    upper = spdx.upper()
    return any(upper.startswith(p.upper()) for p in prefixes)


def derive_license_obligations(license_spdx: str, category: LicenseArtifactCategory) -> tuple[str, ...]:
    """Validate SPDX string (blocking Unknown) and derive compliance obligations (DEC-022)."""
    normalized = license_spdx.strip()
    if normalized.lower() in BLOCKED_LICENSE_TOKENS or "unknown" in normalized.lower():
        raise LicenseValidationError(
            f"Artifact license '{license_spdx}' is unverified/unknown and blocked by BR-SYS-03."
        )

    obligations: list[str] = []

    if _matches_prefix(normalized, NETWORK_COPYLEFT_PREFIXES):
        obligations.extend(
            [
                "attribution_notice",
                "include_license_text",
                "preserve_copyright",
                "state_changes",
                "source_offer_or_distribution",
                "network_source_offer",
            ]
        )
    elif _matches_prefix(normalized, STRONG_COPYLEFT_PREFIXES):
        obligations.extend(
            [
                "attribution_notice",
                "include_license_text",
                "preserve_copyright",
                "state_changes",
                "source_offer_or_distribution",
            ]
        )
    elif _matches_prefix(normalized, WEAK_COPYLEFT_PREFIXES):
        obligations.extend(
            [
                "attribution_notice",
                "include_license_text",
                "preserve_copyright",
                "file_level_copyleft",
            ]
        )
    elif _matches_prefix(normalized, PERMISSIVE_SPDX_PREFIXES):
        obligations.extend(["attribution_notice", "include_license_text", "preserve_copyright"])
    elif _matches_prefix(normalized, ATTRIBUTION_CONTENT_PREFIXES):
        obligations.extend(["attribution_notice", "preserve_copyright"])
    else:
        raise LicenseValidationError(
            f"License SPDX '{normalized}' is not in the reviewed open-source compliance registry."
        )

    if category in (
        LicenseArtifactCategory.VOICE_ASSET,
        LicenseArtifactCategory.MODEL_WEIGHTS,
        LicenseArtifactCategory.TRAINING_DATASET,
    ):
        obligations.append("model_card_notice")
        obligations.append("upstream_dataset_review")

    return tuple(dict.fromkeys(obligations))


def validate_license_artifact(artifact: LicenseArtifact) -> LicenseArtifact:
    """Validate artifact license and ensure all mandatory compliance obligations are recorded."""
    required = derive_license_obligations(artifact.license_spdx, artifact.category)
    merged = tuple(dict.fromkeys((*artifact.obligations, *required)))
    return artifact.model_copy(update={"obligations": merged})


def generate_cyclonedx_sbom(
    artifacts: tuple[LicenseArtifact, ...],
    *,
    generated_at: datetime,
    app_version: str = "0.2.1",
) -> dict[str, Any]:
    """Generate CycloneDX 1.5 JSON SBOM covering all 11 artifact categories."""
    components: list[dict[str, Any]] = []
    for raw in sorted(artifacts, key=lambda a: (a.category.value, a.id)):
        art = validate_license_artifact(raw)
        components.append(
            {
                "type": "data"
                if art.category
                in (
                    LicenseArtifactCategory.MODEL_WEIGHTS,
                    LicenseArtifactCategory.TRAINING_DATASET,
                    LicenseArtifactCategory.VOICE_ASSET,
                    LicenseArtifactCategory.WAKE_MODEL,
                )
                else "library",
                "bom-ref": art.id,
                "name": art.name,
                "version": art.version_or_rev,
                "licenses": [{"license": {"id": art.license_spdx}}],
                "externalReferences": [{"type": "website", "url": art.source_url}],
                "properties": [
                    {"name": "jarvis:category", "value": art.category.value},
                    {"name": "jarvis:obligations", "value": ",".join(art.obligations)},
                ],
            }
        )

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "version": 1,
        "metadata": {
            "timestamp": generated_at.isoformat(),
            "component": {
                "type": "application",
                "name": "jarvis-personal-intelligence-os",
                "version": app_version,
            },
        },
        "components": components,
    }


def generate_third_party_notices(artifacts: tuple[LicenseArtifact, ...]) -> str:
    """Render deterministic THIRD-PARTY-NOTICES text grouped by the 11 artifact categories."""
    lines: list[str] = [
        "J.A.R.V.I.S. — THIRD-PARTY SOFTWARE, MODEL & ASSET NOTICES",
        "==========================================================",
        "",
    ]
    for raw in sorted(artifacts, key=lambda a: (a.category.value, a.name.lower(), a.id)):
        art = validate_license_artifact(raw)
        lines.extend(
            [
                f"[{art.category.value}] {art.name} ({art.version_or_rev})",
                f"  ID:          {art.id}",
                f"  License:     {art.license_spdx}",
                f"  Obligations: {', '.join(art.obligations)}",
                f"  Source:      {art.source_url}",
                f"  Notice:      {art.notice_text}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"
