"""Opt-In Private LAN TLS Provider Governance & Trusted Extension SDK (B27, B34, FR-AIP-06, FR-SYS-06, DEC-024)."""

from __future__ import annotations

import hmac
import ipaddress
import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

from pydantic import Field

from jarvis.domain.ai_models import ProviderCapabilityFlags
from jarvis.domain.licensing import LicenseValidationError, derive_license_obligations
from jarvis.domain.models import (
    ErrorCode,
    LicenseArtifactCategory,
    RuntimeOwnershipMode,
    StrictModel,
    SupportTier,
    TrustZone,
)
from jarvis.domain.policy import PROHIBITED_CAPABILITIES
from jarvis.domain.ports import ClockPort, SecretVaultAndCryptoPort
from jarvis.infrastructure.dual_db import DualSqliteManager

SUPPORTED_EXTENSION_SDK_VERSION = "1.0"


class EcosystemServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class PrivateLanProviderRegistration(StrictModel):
    provider_id: str = Field(min_length=2, max_length=128)
    endpoint_url: str = Field(min_length=10, max_length=512)
    tls_fingerprint_sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    credential_vault_ref: str = Field(min_length=3, max_length=128)
    allowed_data_scopes: tuple[str, ...] = Field(min_length=1, max_length=12)
    consent_acknowledged: bool = False


@dataclass(frozen=True)
class LanDispatchDecision:
    allowed: bool
    reason: str
    error_code: ErrorCode | None = None


class ExtensionManifest(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,64}$")
    version: str = Field(min_length=1, max_length=32)
    sdk_version: str = Field(min_length=1, max_length=16)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")
    license_spdx: str = Field(min_length=2, max_length=128)
    capabilities_requested: tuple[str, ...] = Field(min_length=1, max_length=16)


class InstalledExtensionRecord(StrictModel):
    id: str
    version: str
    sdk_version: str
    sha256: str
    capabilities_requested: tuple[str, ...]
    enabled: bool
    installed_at: datetime


class EcosystemGovernanceService:
    """Enforces opt-in Private LAN TLS pinning/scope consent (FR-AIP-06) and sandboxed Extension SDK (DEC-024)."""

    def __init__(
        self,
        db: DualSqliteManager,
        vault: SecretVaultAndCryptoPort,
        clock: ClockPort,
    ) -> None:
        self._db = db
        self._vault = vault
        self._clock = clock

    # --- Opt-In Private LAN Provider (FR-AIP-06, T17) ---

    def register_private_lan_provider(
        self,
        reg: PrivateLanProviderRegistration,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> dict[str, object]:
        parsed = urlparse(reg.endpoint_url.strip())
        if parsed.scheme.lower() != "https":
            raise EcosystemServiceError(
                ErrorCode.DENIED, "Private LAN providers MUST use HTTPS/TLS (FR-AIP-06)."
            )
        host = (parsed.hostname or "").strip().lower()
        if not host:
            raise EcosystemServiceError(ErrorCode.INVALID_ARGS, "Private LAN endpoint URL missing hostname.")
        # B20: verify hostname is strictly RFC1918/ULA private LAN, loopback, or .local/.lan mDNS (reject public hosts!)
        is_private_host = host in ("localhost", "127.0.0.1", "::1") or host.endswith((".local", ".lan", ".internal"))
        if not is_private_host:
            try:
                ip_obj = ipaddress.ip_address(host)
                is_private_host = ip_obj.is_private or ip_obj.is_loopback
            except ValueError:
                is_private_host = False
        if not is_private_host:
            raise EcosystemServiceError(
                ErrorCode.DENIED,
                f"Host '{host}' is not a private LAN / RFC1918 / .local address; public cloud endpoints cannot register as authorized_lan.",
            )
        if not reg.consent_acknowledged:
            raise EcosystemServiceError(
                ErrorCode.APPROVAL_REQUIRED,
                "Explicit owner consent acknowledging LAN server data retention policy is required (FR-AIP-06).",
            )
        if self._vault.get_secret(reg.credential_vault_ref) is None:
            raise EcosystemServiceError(
                ErrorCode.NOT_FOUND,
                f"Vault credential reference '{reg.credential_vault_ref}' not found in OS Credential Vault.",
            )

        now_iso = self._clock.now_utc().isoformat()
        caps_model = ProviderCapabilityFlags(
            streaming=True,
            structured_json=True,
            thinking_control=False,
            cancelable=True,
            max_context_tokens=4096,
            tls_fingerprint_sha256=reg.tls_fingerprint_sha256.lower(),
            allowed_data_scopes=tuple(reg.allowed_data_scopes),
            allow_cross_zone_fallback=False,
        )
        caps_meta = {
            "tls_fingerprint_sha256": reg.tls_fingerprint_sha256.lower(),
            "allowed_data_scopes": list(reg.allowed_data_scopes),
            "allow_cross_zone_fallback": False,
        }
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO model_provider(
                    id, adapter_kind, adapter_version, ownership_mode, trust_zone, endpoint_ref,
                    credential_vault_ref, capabilities_json, support_tier, enabled, last_probe_at, health_code
                ) VALUES (?, 'custom_openai_compatible', '1.0.0', ?, ?, ?, ?, ?, ?, 1, NULL, 'registered')
                ON CONFLICT(id) DO UPDATE SET
                    endpoint_ref = excluded.endpoint_ref,
                    credential_vault_ref = excluded.credential_vault_ref,
                    capabilities_json = excluded.capabilities_json,
                    enabled = 1
                """,
                (
                    reg.provider_id,
                    RuntimeOwnershipMode.AUTHORIZED_LAN.value,
                    TrustZone.PRIVATE_LAN.value,
                    reg.endpoint_url.strip(),
                    reg.credential_vault_ref,
                    caps_model.model_dump_json(),
                    SupportTier.EXPERIMENTAL.value,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'provider.lan_registered', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps(
                        {
                            "provider_id": reg.provider_id,
                            "allowed_data_scopes": list(reg.allowed_data_scopes),
                        }
                    ),
                    now_iso,
                ),
            )
        return {"provider_id": reg.provider_id, "trust_zone": TrustZone.PRIVATE_LAN.value, **caps_meta}

    def verify_lan_dispatch(
        self,
        provider_id: str,
        *,
        data_scope: str,
        presented_tls_fingerprint_sha256: str,
        offline_mode: bool,
    ) -> LanDispatchDecision:
        """Gate every Private LAN inference request on registration, TLS pin match, and approved data scope."""
        if offline_mode:
            return LanDispatchDecision(False, "Offline mode blocks Private LAN traffic.", ErrorCode.OFFLINE)

        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT ownership_mode, trust_zone, capabilities_json, enabled FROM model_provider WHERE id = ?",
                (provider_id,),
            ).fetchone()
        if row is None or not bool(row["enabled"]):
            return LanDispatchDecision(
                False,
                f"Private LAN provider '{provider_id}' is unregistered or revoked.",
                ErrorCode.DENIED,
            )
        if str(row["ownership_mode"]) != RuntimeOwnershipMode.AUTHORIZED_LAN.value:
            return LanDispatchDecision(False, "Provider is not an authorized_lan endpoint.", ErrorCode.DENIED)

        caps = json.loads(str(row["capabilities_json"]))
        expected_fp = str(caps.get("tls_fingerprint_sha256", "")).lower()
        if not expected_fp or not hmac.compare_digest(
            expected_fp, presented_tls_fingerprint_sha256.strip().lower()
        ):
            return LanDispatchDecision(
                False,
                "TLS certificate fingerprint mismatch; Private LAN dispatch refused (FR-AIP-06).",
                ErrorCode.DENIED,
            )

        allowed_scopes = set(caps.get("allowed_data_scopes", []))
        if data_scope not in allowed_scopes:
            return LanDispatchDecision(
                False,
                f"Data scope '{data_scope}' is not approved for Private LAN provider '{provider_id}' (T17).",
                ErrorCode.DENIED,
            )
        return LanDispatchDecision(True, "Authorized Private LAN dispatch verified.")

    def revoke_private_lan_provider(self, provider_id: str, *, correlation_id: str) -> bool:
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE model_provider SET enabled = 0, health_code = 'revoked' WHERE id = ? AND ownership_mode = 'authorized_lan'",
                (provider_id,),
            )
            if cur.rowcount == 0:
                return False
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, 'local_owner', 'provider.lan_revoked', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    json.dumps({"provider_id": provider_id}),
                    self._clock.now_utc().isoformat(),
                ),
            )
        return True

    # --- Trusted Extension SDK (DEC-024, FR-SYS-06, U26) ---

    def install_extension(
        self,
        manifest: ExtensionManifest,
        *,
        expected_sha256: str,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> InstalledExtensionRecord:
        if manifest.sdk_version != SUPPORTED_EXTENSION_SDK_VERSION:
            raise EcosystemServiceError(
                ErrorCode.UNSUPPORTED,
                f"Unsupported extension sdk_version '{manifest.sdk_version}' (expected '{SUPPORTED_EXTENSION_SDK_VERSION}').",
            )
        if not hmac.compare_digest(manifest.sha256.lower(), expected_sha256.strip().lower()):
            raise EcosystemServiceError(
                ErrorCode.INVALID_ARGS, "Extension package SHA-256 verification failed (T09)."
            )
        try:
            derive_license_obligations(manifest.license_spdx, LicenseArtifactCategory.APP_PACKAGE)
        except LicenseValidationError as exc:
            raise EcosystemServiceError(ErrorCode.LICENSE_UNVERIFIED, str(exc)) from exc

        for cap in manifest.capabilities_requested:
            if cap.strip().lower() in PROHIBITED_CAPABILITIES:
                raise EcosystemServiceError(
                    ErrorCode.DENIED,
                    f"Extension requests R3 prohibited capability '{cap}' and cannot be installed.",
                )

        now = self._clock.now_utc()
        now_iso = now.isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO extension_package(
                    id, version, sdk_version, sha256, capabilities_requested_json, enabled, installed_at
                ) VALUES (?, ?, ?, ?, ?, 0, ?)
                ON CONFLICT(id) DO UPDATE SET
                    version = excluded.version,
                    sdk_version = excluded.sdk_version,
                    sha256 = excluded.sha256,
                    capabilities_requested_json = excluded.capabilities_requested_json,
                    enabled = 0,
                    installed_at = excluded.installed_at
                """,
                (
                    manifest.id,
                    manifest.version,
                    manifest.sdk_version,
                    manifest.sha256.lower(),
                    json.dumps(list(manifest.capabilities_requested)),
                    now_iso,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'extension.installed', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"extension_id": manifest.id, "version": manifest.version}),
                    now_iso,
                ),
            )
        return InstalledExtensionRecord(
            id=manifest.id,
            version=manifest.version,
            sdk_version=manifest.sdk_version,
            sha256=manifest.sha256.lower(),
            capabilities_requested=manifest.capabilities_requested,
            enabled=False,
            installed_at=now,
        )

    def set_extension_enabled(
        self, extension_id: str, *, enabled: bool, correlation_id: str
    ) -> InstalledExtensionRecord:
        with self._db.core_tx() as conn:
            cur = conn.execute(
                "UPDATE extension_package SET enabled = ? WHERE id = ?",
                (1 if enabled else 0, extension_id),
            )
            if cur.rowcount == 0:
                raise EcosystemServiceError(
                    ErrorCode.NOT_FOUND, f"Extension '{extension_id}' is not installed."
                )
            row = conn.execute("SELECT * FROM extension_package WHERE id = ?", (extension_id,)).fetchone()
        assert row is not None
        return InstalledExtensionRecord(
            id=str(row["id"]),
            version=str(row["version"]),
            sdk_version=str(row["sdk_version"]),
            sha256=str(row["sha256"]),
            capabilities_requested=tuple(json.loads(str(row["capabilities_requested_json"]))),
            enabled=bool(row["enabled"]),
            installed_at=datetime.fromisoformat(str(row["installed_at"])),
        )

    def authorize_extension_capability(
        self, extension_id: str, *, requested_capability: str, correlation_id: str
    ) -> tuple[bool, str]:
        """Enforce declared extension capability boundaries (U26 — undeclared capabilities blocked & audited)."""
        with self._db.core_read() as conn:
            row = conn.execute(
                "SELECT capabilities_requested_json, enabled FROM extension_package WHERE id = ?",
                (extension_id,),
            ).fetchone()
        if row is None or not bool(row["enabled"]):
            return (False, f"Extension '{extension_id}' is not installed or disabled.")

        declared = set(json.loads(str(row["capabilities_requested_json"])))
        if requested_capability not in declared:
            with self._db.core_tx() as conn:
                conn.execute(
                    """
                    INSERT INTO audit_event(
                        id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                    ) VALUES (?, ?, NULL, ?, 'extension.capability_denied', 'denied', ?, ?)
                    """,
                    (
                        str(uuid.uuid4()),
                        correlation_id,
                        f"ext:{extension_id}",
                        json.dumps({"requested_capability": requested_capability}),
                        self._clock.now_utc().isoformat(),
                    ),
                )
            return (
                False,
                f"Extension '{extension_id}' attempted undeclared capability '{requested_capability}' (blocked by DEC-024).",
            )
        return (True, "Extension capability authorized.")

    def list_extensions(self) -> list[InstalledExtensionRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM extension_package ORDER BY id ASC").fetchall()
        return [
            InstalledExtensionRecord(
                id=str(r["id"]),
                version=str(r["version"]),
                sdk_version=str(r["sdk_version"]),
                sha256=str(r["sha256"]),
                capabilities_requested=tuple(json.loads(str(r["capabilities_requested_json"]))),
                enabled=bool(r["enabled"]),
                installed_at=datetime.fromisoformat(str(r["installed_at"])),
            )
            for r in rows
        ]
