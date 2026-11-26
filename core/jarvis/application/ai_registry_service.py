"""AI Provider Registry, Model Manifest Verification & Atomic Profile Switching (B24, DEC-020, DEC-021, BR-AI-01..04)."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jarvis.domain.ai_models import (
    AiProfileRecord,
    LlmProviderPort,
    ModelManifestRecord,
    ModelProviderRecord,
    ModelResourceEstimate,
    ProviderCapabilityFlags,
    ProviderProbeResult,
    is_exposed_non_loopback_host,
)
from jarvis.domain.licensing import LicenseValidationError, derive_license_obligations
from jarvis.domain.models import (
    AiProfileMode,
    ErrorCode,
    LicenseArtifactCategory,
    RuntimeOwnershipMode,
    SupportTier,
    TrustZone,
)
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager
from jarvis.infrastructure.event_bus import SequencedEventBus


class AiRegistryError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ActiveProfileState:
    profile: AiProfileRecord
    previous_healthy_profile_id: str | None
    previous_healthy_revision: int | None
    updated_at: str


@dataclass(frozen=True)
class ProfileSwitchOutcome:
    committed: bool
    rolled_back: bool
    active_profile: AiProfileRecord
    reason: str


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def default_ai_profiles() -> tuple[AiProfileRecord, ...]:
    """Canonical Direct + 6 AI profiles (Eco, Performance, Balanced, Quality, Adaptive, Custom)."""
    return (
        AiProfileRecord(
            id="direct",
            revision=1,
            mode=AiProfileMode.DIRECT,
            role_bindings={},
            runtime_knobs={"llm_enabled": False},
            resource_limits={"max_ram_mib": 1024, "max_vram_mib": 0},
        ),
        AiProfileRecord(
            id="eco",
            revision=1,
            mode=AiProfileMode.ECO,
            runtime_knobs={"enforce_non_thinking": True, "context_tokens": 2048},
            resource_limits={"max_ram_mib": 3584, "max_vram_mib": 1536},
            fallback_allowlist=("direct",),
        ),
        AiProfileRecord(
            id="performance",
            revision=1,
            mode=AiProfileMode.PERFORMANCE,
            runtime_knobs={"enforce_non_thinking": True, "context_tokens": 2048},
            resource_limits={"max_ram_mib": 6144, "max_vram_mib": 2048},
            fallback_allowlist=("eco", "direct"),
        ),
        AiProfileRecord(
            id="balanced",
            revision=1,
            mode=AiProfileMode.BALANCED,
            runtime_knobs={"enforce_non_thinking": True, "context_tokens": 4096},
            resource_limits={"max_ram_mib": 8192, "max_vram_mib": 3300},
            fallback_allowlist=("eco", "direct"),
        ),
        AiProfileRecord(
            id="quality",
            revision=1,
            mode=AiProfileMode.QUALITY,
            runtime_knobs={"enforce_non_thinking": False, "context_tokens": 8192},
            resource_limits={"max_ram_mib": 12288, "max_vram_mib": 10240},
            fallback_allowlist=("balanced", "eco", "direct"),
        ),
        AiProfileRecord(
            id="adaptive",
            revision=1,
            mode=AiProfileMode.ADAPTIVE,
            runtime_knobs={"enforce_non_thinking": True, "context_tokens": 4096},
            resource_limits={"max_ram_mib": 8192, "max_vram_mib": 3300},
            fallback_allowlist=("eco", "direct"),
        ),
        AiProfileRecord(
            id="custom",
            revision=1,
            mode=AiProfileMode.CUSTOM,
            runtime_knobs={"enforce_non_thinking": True, "context_tokens": 4096},
            resource_limits={"max_ram_mib": 8192, "max_vram_mib": 3300},
            fallback_allowlist=("direct",),
        ),
    )


class AiRegistryService:
    """Manages providers, SHA-256 verified manifests, and atomic profile switching with rollback."""

    def __init__(
        self,
        db: DualSqliteManager,
        clock: ClockPort,
        event_bus: SequencedEventBus,
    ) -> None:
        self._db = db
        self._clock = clock
        self._bus = event_bus
        self._adapters: dict[str, LlmProviderPort] = {}

    def seed_default_profiles(self) -> None:
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            for prof in default_ai_profiles():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO ai_profile(
                        id, revision, mode, role_bindings_json, runtime_knobs_json,
                        resource_limits_json, fallback_allowlist_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        prof.id,
                        prof.revision,
                        prof.mode.value,
                        json.dumps(prof.role_bindings, sort_keys=True),
                        json.dumps(prof.runtime_knobs, sort_keys=True),
                        json.dumps(prof.resource_limits, sort_keys=True),
                        json.dumps(list(prof.fallback_allowlist)),
                    ),
                )
            existing_active = conn.execute(
                "SELECT singleton_id FROM active_ai_profile WHERE singleton_id = 1"
            ).fetchone()
            if existing_active is None:
                conn.execute(
                    """
                    INSERT INTO active_ai_profile(
                        singleton_id, profile_id, profile_revision,
                        previous_healthy_profile_id, previous_healthy_revision, updated_at
                    ) VALUES (1, 'direct', 1, NULL, NULL, ?)
                    """,
                    (now_iso,),
                )

    def bind_adapter(self, adapter: LlmProviderPort) -> None:
        self._adapters[adapter.provider_id] = adapter

    def get_adapter(self, provider_id: str) -> LlmProviderPort | None:
        return self._adapters.get(provider_id)

    def register_provider(
        self,
        provider: ModelProviderRecord,
        *,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> tuple[ModelProviderRecord, list[str]]:
        """Persist a provider with ownership/trust-zone guardrails (DEC-020, BR-AI-02)."""
        warnings: list[str] = []
        if (
            provider.ownership_mode in (RuntimeOwnershipMode.MANAGED_LOCAL, RuntimeOwnershipMode.EXTERNAL_LOCAL)
            and provider.trust_zone != TrustZone.LOCAL_DEVICE
        ):
            raise AiRegistryError(
                ErrorCode.INVALID_ARGS,
                "Local ownership modes must belong to the 'local_device' trust zone.",
            )
        if provider.ownership_mode == RuntimeOwnershipMode.AUTHORIZED_LAN and provider.trust_zone != TrustZone.PRIVATE_LAN:
            raise AiRegistryError(
                ErrorCode.INVALID_ARGS,
                "authorized_lan providers must declare trust_zone='private_lan'.",
            )
        if provider.trust_zone == TrustZone.LOCAL_DEVICE and is_exposed_non_loopback_host(
            provider.endpoint_ref
        ):
            warnings.append(
                "Provider endpoint appears exposed on 0.0.0.0; bind to 127.0.0.1 for local-only security."
            )

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO model_provider(
                    id, adapter_kind, adapter_version, ownership_mode, trust_zone, endpoint_ref,
                    credential_vault_ref, capabilities_json, support_tier, enabled, last_probe_at, health_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    adapter_kind = excluded.adapter_kind,
                    adapter_version = excluded.adapter_version,
                    ownership_mode = excluded.ownership_mode,
                    trust_zone = excluded.trust_zone,
                    endpoint_ref = excluded.endpoint_ref,
                    credential_vault_ref = excluded.credential_vault_ref,
                    capabilities_json = excluded.capabilities_json,
                    support_tier = excluded.support_tier,
                    enabled = excluded.enabled,
                    last_probe_at = excluded.last_probe_at,
                    health_code = excluded.health_code
                """,
                (
                    provider.id,
                    provider.adapter_kind,
                    provider.adapter_version,
                    provider.ownership_mode.value,
                    provider.trust_zone.value,
                    provider.endpoint_ref,
                    provider.credential_vault_ref,
                    provider.capabilities.model_dump_json(),
                    provider.support_tier.value,
                    1 if provider.enabled else 0,
                    provider.last_probe_at.isoformat() if provider.last_probe_at else None,
                    provider.health_code,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'provider.registered', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps(
                        {
                            "provider_id": provider.id,
                            "ownership_mode": provider.ownership_mode.value,
                            "trust_zone": provider.trust_zone.value,
                        }
                    ),
                    now_iso,
                ),
            )
        return provider, warnings

    def list_providers(self) -> list[ModelProviderRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM model_provider ORDER BY id ASC").fetchall()
        return [
            ModelProviderRecord(
                id=str(r["id"]),
                adapter_kind=str(r["adapter_kind"]),  # type: ignore[arg-type]
                adapter_version=str(r["adapter_version"]),
                ownership_mode=RuntimeOwnershipMode(str(r["ownership_mode"])),
                trust_zone=TrustZone(str(r["trust_zone"])),
                endpoint_ref=str(r["endpoint_ref"]),
                credential_vault_ref=str(r["credential_vault_ref"]) if r["credential_vault_ref"] else None,
                capabilities=ProviderCapabilityFlags.model_validate_json(str(r["capabilities_json"])),
                support_tier=SupportTier(str(r["support_tier"])),
                enabled=bool(r["enabled"]),
                last_probe_at=datetime.fromisoformat(str(r["last_probe_at"])) if r["last_probe_at"] else None,
                health_code=str(r["health_code"]),
            )
            for r in rows
        ]

    async def probe_provider(self, provider_id: str, *, correlation_id: str) -> ProviderProbeResult:
        adapter = self._adapters.get(provider_id)
        if adapter is None:
            raise AiRegistryError(ErrorCode.NOT_FOUND, f"No bound runtime adapter for provider '{provider_id}'.")
        result = await adapter.probe()
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                "UPDATE model_provider SET last_probe_at = ?, health_code = ?, capabilities_json = ? WHERE id = ?",
                (now_iso, result.health_code, result.capabilities.model_dump_json(), provider_id),
            )
        self._bus.publish(
            event_type="provider.health_changed",
            correlation_id=correlation_id,
            payload={
                "provider_id": provider_id,
                "healthy": result.healthy,
                "health_code": result.health_code,
                "latency_ms": result.latency_ms,
            },
        )
        return result

    def register_manifest(
        self,
        manifest: ModelManifestRecord,
        *,
        verify_local_file: bool = True,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> ModelManifestRecord:
        """Verify license SPDX (no Unknown), optional local file SHA-256, and persist manifest (DEC-021)."""
        try:
            derive_license_obligations(manifest.license_spdx, LicenseArtifactCategory.MODEL_WEIGHTS)
        except LicenseValidationError as exc:
            raise AiRegistryError(ErrorCode.LICENSE_UNVERIFIED, str(exc)) from exc

        verified_at = manifest.verified_at
        if verify_local_file and manifest.storage_ref is not None:
            file_path = Path(manifest.storage_ref)
            if not file_path.is_file():
                raise AiRegistryError(
                    ErrorCode.NOT_FOUND, f"Model artifact file not found: '{manifest.storage_ref}'."
                )
            actual_sha = _sha256_file(file_path)
            if actual_sha.lower() != manifest.sha256.lower():
                raise AiRegistryError(
                    ErrorCode.INVALID_ARGS,
                    f"Model SHA-256 mismatch for '{manifest.id}': expected {manifest.sha256}, got {actual_sha}.",
                )
            verified_at = self._clock.now_utc()

        saved = manifest.model_copy(update={"verified_at": verified_at})
        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO model_manifest(
                    id, provider_id, role, family, revision, sha256, byte_size, storage_ref,
                    is_shared_external_file, format, license_spdx, model_card_ref, dataset_license_note,
                    capability_json, resource_estimate_json, approval_state, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    sha256 = excluded.sha256,
                    storage_ref = excluded.storage_ref,
                    is_shared_external_file = excluded.is_shared_external_file,
                    license_spdx = excluded.license_spdx,
                    approval_state = excluded.approval_state,
                    verified_at = excluded.verified_at
                """,
                (
                    saved.id,
                    saved.provider_id,
                    saved.role,
                    saved.family,
                    saved.revision,
                    saved.sha256,
                    saved.byte_size,
                    saved.storage_ref,
                    1 if saved.is_shared_external_file else 0,
                    saved.format,
                    saved.license_spdx,
                    saved.model_card_ref,
                    saved.dataset_license_note,
                    json.dumps(
                        {
                            "structured_output": saved.supports_structured_output,
                            "thinking_control": saved.supports_thinking_control,
                        }
                    ),
                    saved.resource_estimate.model_dump_json(),
                    saved.approval_state,
                    saved.verified_at.isoformat() if saved.verified_at else None,
                ),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'model.manifest_registered', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"manifest_id": saved.id, "role": saved.role, "license": saved.license_spdx}),
                    now_iso,
                ),
            )
        return saved

    def list_manifests(self) -> list[ModelManifestRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM model_manifest ORDER BY id ASC").fetchall()
        results: list[ModelManifestRecord] = []
        for r in rows:
            caps = json.loads(str(r["capability_json"]))
            results.append(
                ModelManifestRecord(
                    id=str(r["id"]),
                    provider_id=str(r["provider_id"]),
                    role=str(r["role"]),  # type: ignore[arg-type]
                    family=str(r["family"]),
                    revision=str(r["revision"]),
                    sha256=str(r["sha256"]),
                    byte_size=int(r["byte_size"]),
                    storage_ref=str(r["storage_ref"]) if r["storage_ref"] else None,
                    is_shared_external_file=bool(r["is_shared_external_file"]),
                    format=str(r["format"]),  # type: ignore[arg-type]
                    license_spdx=str(r["license_spdx"]),
                    model_card_ref=str(r["model_card_ref"]) if r["model_card_ref"] else None,
                    dataset_license_note=str(r["dataset_license_note"]) if r["dataset_license_note"] else None,
                    supports_structured_output=bool(caps.get("structured_output", True)),
                    supports_thinking_control=bool(caps.get("thinking_control", True)),
                    resource_estimate=ModelResourceEstimate.model_validate_json(str(r["resource_estimate_json"])),
                    approval_state=str(r["approval_state"]),  # type: ignore[arg-type]
                    verified_at=datetime.fromisoformat(str(r["verified_at"])) if r["verified_at"] else None,
                )
            )
        return results

    def list_profiles(self) -> list[AiProfileRecord]:
        with self._db.core_read() as conn:
            rows = conn.execute("SELECT * FROM ai_profile ORDER BY id ASC, revision DESC").fetchall()
        return [
            AiProfileRecord(
                id=str(r["id"]),
                revision=int(r["revision"]),
                mode=AiProfileMode(str(r["mode"])),
                role_bindings=json.loads(str(r["role_bindings_json"])),
                runtime_knobs=json.loads(str(r["runtime_knobs_json"])),
                resource_limits=json.loads(str(r["resource_limits_json"])),
                fallback_allowlist=tuple(json.loads(str(r["fallback_allowlist_json"]))),
            )
            for r in rows
        ]

    def get_active_profile(self) -> ActiveProfileState:
        with self._db.core_read() as conn:
            row = conn.execute(
                """
                SELECT a.profile_id, a.profile_revision, a.previous_healthy_profile_id,
                       a.previous_healthy_revision, a.updated_at,
                       p.mode, p.role_bindings_json, p.runtime_knobs_json,
                       p.resource_limits_json, p.fallback_allowlist_json
                FROM active_ai_profile a
                JOIN ai_profile p ON p.id = a.profile_id AND p.revision = a.profile_revision
                WHERE a.singleton_id = 1
                """
            ).fetchone()
        if row is None:
            raise AiRegistryError(ErrorCode.NOT_FOUND, "No active AI profile configured.")
        profile = AiProfileRecord(
            id=str(row["profile_id"]),
            revision=int(row["profile_revision"]),
            mode=AiProfileMode(str(row["mode"])),
            role_bindings=json.loads(str(row["role_bindings_json"])),
            runtime_knobs=json.loads(str(row["runtime_knobs_json"])),
            resource_limits=json.loads(str(row["resource_limits_json"])),
            fallback_allowlist=tuple(json.loads(str(row["fallback_allowlist_json"]))),
        )
        return ActiveProfileState(
            profile=profile,
            previous_healthy_profile_id=(
                str(row["previous_healthy_profile_id"]) if row["previous_healthy_profile_id"] else None
            ),
            previous_healthy_revision=(
                int(row["previous_healthy_revision"]) if row["previous_healthy_revision"] else None
            ),
            updated_at=str(row["updated_at"]),
        )

    def switch_profile_atomic(
        self,
        target_profile_id: str,
        *,
        target_revision: int = 1,
        probe_candidate: Callable[[AiProfileRecord], tuple[bool, str]] | None = None,
        correlation_id: str,
        actor: str = "local_owner",
    ) -> ProfileSwitchOutcome:
        """Atomic profile switch with probe & automatic rollback to prior healthy profile (BR-AI-03)."""
        current = self.get_active_profile()
        with self._db.core_read() as conn:
            cand_row = conn.execute(
                "SELECT * FROM ai_profile WHERE id = ? AND revision = ?",
                (target_profile_id, target_revision),
            ).fetchone()
        if cand_row is None:
            raise AiRegistryError(
                ErrorCode.NOT_FOUND, f"Profile '{target_profile_id}' rev {target_revision} not found."
            )

        candidate = AiProfileRecord(
            id=str(cand_row["id"]),
            revision=int(cand_row["revision"]),
            mode=AiProfileMode(str(cand_row["mode"])),
            role_bindings=json.loads(str(cand_row["role_bindings_json"])),
            runtime_knobs=json.loads(str(cand_row["runtime_knobs_json"])),
            resource_limits=json.loads(str(cand_row["resource_limits_json"])),
            fallback_allowlist=tuple(json.loads(str(cand_row["fallback_allowlist_json"]))),
        )

        self._bus.publish(
            event_type="profile.switch.started",
            correlation_id=correlation_id,
            payload={"from": current.profile.id, "to": candidate.id},
        )

        if probe_candidate is not None:
            ok, probe_msg = probe_candidate(candidate)
            if not ok:
                # Roll back cleanly (keep previous healthy active; do not corrupt pointer)
                self._bus.publish(
                    event_type="profile.switch.failed",
                    correlation_id=correlation_id,
                    payload={"target": candidate.id, "restored": current.profile.id, "reason": probe_msg},
                )
                return ProfileSwitchOutcome(
                    committed=False,
                    rolled_back=True,
                    active_profile=current.profile,
                    reason=f"Candidate probe failed ({probe_msg}); retained healthy profile '{current.profile.id}'.",
                )

        now_iso = self._clock.now_utc().isoformat()
        with self._db.core_tx() as conn:
            conn.execute(
                """
                UPDATE active_ai_profile
                SET previous_healthy_profile_id = profile_id,
                    previous_healthy_revision = profile_revision,
                    profile_id = ?,
                    profile_revision = ?,
                    updated_at = ?
                WHERE singleton_id = 1
                """,
                (candidate.id, candidate.revision, now_iso),
            )
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'profile.switched', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"from": current.profile.id, "to": candidate.id}),
                    now_iso,
                ),
            )

        self._bus.publish(
            event_type="profile.switch.committed",
            correlation_id=correlation_id,
            payload={"profile_id": candidate.id, "revision": candidate.revision},
        )
        return ProfileSwitchOutcome(
            committed=True,
            rolled_back=False,
            active_profile=candidate,
            reason=f"Switched atomically to profile '{candidate.id}'.",
        )

    def rollback_profile(self, *, correlation_id: str, actor: str = "local_owner") -> ActiveProfileState:
        current = self.get_active_profile()
        prev_id = current.previous_healthy_profile_id or "direct"
        prev_rev = current.previous_healthy_revision or 1
        outcome = self.switch_profile_atomic(
            prev_id, target_revision=prev_rev, correlation_id=correlation_id, actor=actor
        )
        if not outcome.committed:
            raise AiRegistryError(ErrorCode.INTERNAL, "Failed to roll back AI profile.")
        return self.get_active_profile()
