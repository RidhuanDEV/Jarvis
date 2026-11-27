"""Trusted Binary & Model Artifact Provenance Verifier (IR-05, DEF-05, B06, DEC-021).

Enforces independent SHA-256 verification against a trusted local manifest before spawning
external inference binaries (e.g., llama-server.exe) or loading untrusted model/voice weights.
Never trusts hashes supplied alongside the untrusted artifact itself.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

from jarvis.domain.models import ErrorCode


class ArtifactProvenanceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


def compute_file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest().lower()


class ArtifactProvenanceVerifier:
    """Validates candidate runtime binaries and model files against independently trusted SHA-256 digests."""

    def __init__(
        self,
        *,
        manifest_path: Path | None = None,
        trusted_digests: dict[str, str] | None = None,
        require_manifest: bool = True,
    ) -> None:
        self._manifest_path = manifest_path
        self._explicit_digests = (
            {k.lower(): v.strip().lower() for k, v in trusted_digests.items()}
            if trusted_digests is not None
            else None
        )
        self._require_manifest = require_manifest

    def _load_trusted_digests(self) -> dict[str, str]:
        if self._explicit_digests is not None:
            return self._explicit_digests
        if self._manifest_path is None or not self._manifest_path.is_file():
            if self._require_manifest:
                raise ArtifactProvenanceError(
                    ErrorCode.DENIED,
                    "Trusted artifact manifest (trusted_artifacts.json) is missing; refusing unverified binary/model.",
                )
            return {}
        if self._manifest_path.is_symlink():
            raise ArtifactProvenanceError(
                ErrorCode.DENIED, "Trusted artifact manifest must not be a symlink."
            )
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ArtifactProvenanceError(
                ErrorCode.INVALID_ARGS, f"Corrupt trusted artifact manifest: {exc}"
            ) from exc
        artifacts = raw.get("artifacts") if isinstance(raw, dict) else None
        if not isinstance(artifacts, dict):
            raise ArtifactProvenanceError(
                ErrorCode.INVALID_ARGS, "Trusted artifact manifest missing 'artifacts' object."
            )
        normalized: dict[str, str] = {}
        for key, digest in artifacts.items():
            if isinstance(key, str) and isinstance(digest, str) and len(digest.strip()) == 64:
                normalized[key.strip().lower()] = digest.strip().lower()
        return normalized

    def verify_artifact(self, artifact_path: Path, *, artifact_key: str | None = None) -> str:
        """Verify that artifact_path exists, is not a symlink, and matches its trusted SHA-256 digest."""
        if artifact_path.is_symlink():
            raise ArtifactProvenanceError(
                ErrorCode.DENIED, f"Refusing symlink artifact '{artifact_path.name}'."
            )
        if not artifact_path.is_file():
            raise ArtifactProvenanceError(
                ErrorCode.NOT_FOUND, f"Artifact not found: '{artifact_path.name}'."
            )
        digests = self._load_trusted_digests()
        lookup_keys = [
            k.lower()
            for k in (
                artifact_key,
                artifact_path.name,
                str(artifact_path.resolve(strict=False)),
            )
            if k
        ]
        expected: str | None = None
        for key in lookup_keys:
            if key in digests:
                expected = digests[key]
                break
        if expected is None:
            if self._require_manifest:
                raise ArtifactProvenanceError(
                    ErrorCode.DENIED,
                    f"Artifact '{artifact_path.name}' is not listed in trusted SHA-256 manifest; execution/load blocked.",
                )
            return compute_file_sha256(artifact_path)

        actual = compute_file_sha256(artifact_path)
        if not hmac.compare_digest(actual, expected):
            raise ArtifactProvenanceError(
                ErrorCode.DENIED,
                f"SHA-256 provenance mismatch for '{artifact_path.name}': expected {expected[:12]}..., got {actual[:12]}....",
            )
        return actual
