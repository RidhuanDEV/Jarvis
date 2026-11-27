"""Versioned Configuration & Profile Management Service (DEC-017, FR-SYS-02)."""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from jarvis.domain.models import (
    AiConfig,
    AudioConfig,
    ConfigDocument,
    ErrorCode,
    LocaleConfig,
    OnboardingConfig,
    PermissionsConfig,
    PersonaConfig,
    StorageConfig,
    StorageRootsConfig,
    VisualConfig,
)
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager

_DEFAULT_CONTRACTS_DIR = Path(__file__).resolve().parents[3] / "contracts"
CONTRACTS_DIR = (
    Path(os.environ["JARVIS_CONTRACTS_DIR"])
    if os.environ.get("JARVIS_CONTRACTS_DIR", "").strip()
    else _DEFAULT_CONTRACTS_DIR
)
SECRET_PATTERN_RE = re.compile(
    r"(?:Bearer\s+[A-Za-z0-9._\-~+/]{12,}|sk-[A-Za-z0-9]{16,}|ghp_[A-Za-z0-9]{20,}|"
    r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})"
)


class ConfigServiceError(ValueError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class StoredConfigRevision:
    revision: int
    schema_version: int
    source: str
    is_active: bool
    previous_healthy_revision: int | None
    created_at: str
    document: ConfigDocument


def build_default_storage_roots(base_data_dir: Path, base_cache_dir: Path) -> StorageRootsConfig:
    """Build portable OS-standard 11 storage roots without hardcoded drives or usernames."""
    return StorageRootsConfig(
        app_data=str(base_data_dir),
        models=str(base_data_dir / "models"),
        runtimes=str(base_data_dir / "runtimes"),
        core_db=str(base_data_dir / "db" / "core"),
        knowledge_db=str(base_data_dir / "db" / "knowledge"),
        logs=str(base_data_dir / "logs"),
        temp=str(base_cache_dir / "temp"),
        cache=str(base_cache_dir / "cache"),
        backups=str(base_data_dir / "backups"),
        imported_docs=str(base_data_dir / "imported_docs"),
        extensions=str(base_data_dir / "extensions"),
    )


def build_default_config(
    roots: StorageRootsConfig,
    *,
    timezone_iana: str = "UTC",
    primary_language: str = "id-ID",
) -> ConfigDocument:
    """Create initial deny-by-default, offline-first, Bahasa Indonesia default configuration."""
    return ConfigDocument(
        schema_version=1,
        profile_name="default",
        locale=LocaleConfig(
            primary_language=primary_language,
            multilingual_enabled=True,
            fallback_languages=("en-US",),
            timezone_iana=timezone_iana,
        ),
        persona=PersonaConfig(),
        storage=StorageConfig(roots=roots),
        ai=AiConfig(),
        visual=VisualConfig(),
        audio=AudioConfig(),
        permissions=PermissionsConfig(),
        onboarding=OnboardingConfig(),
    )


class ConfigService:
    """Manages versioned config revisions, secret-free export/import, and rollback."""

    def __init__(self, db: DualSqliteManager, clock: ClockPort) -> None:
        self._db = db
        self._clock = clock
        schema_path = CONTRACTS_DIR / "config.schema.v1.json"
        self._json_schema: dict[str, Any] = json.loads(schema_path.read_text(encoding="utf-8"))

    def ensure_initialized(self, default_doc: ConfigDocument) -> StoredConfigRevision:
        existing = self.get_active_or_none()
        if existing is not None:
            return existing
        return self.save_revision(default_doc, source="onboarding", correlation_id="bootstrap-init")

    def get_active_or_none(self) -> StoredConfigRevision | None:
        with self._db.core_read() as conn:
            row = conn.execute(
                """
                SELECT revision, schema_version, config_json, source, is_active,
                       previous_healthy_revision, created_at
                FROM config_revision
                WHERE is_active = 1
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        doc = ConfigDocument.model_validate_json(str(row["config_json"]))
        return StoredConfigRevision(
            revision=int(row["revision"]),
            schema_version=int(row["schema_version"]),
            source=str(row["source"]),
            is_active=bool(row["is_active"]),
            previous_healthy_revision=(
                int(row["previous_healthy_revision"]) if row["previous_healthy_revision"] is not None else None
            ),
            created_at=str(row["created_at"]),
            document=doc,
        )

    def get_active(self) -> StoredConfigRevision:
        active = self.get_active_or_none()
        if active is None:
            raise ConfigServiceError(ErrorCode.NOT_FOUND, "No active configuration revision found.")
        return active

    def validate_payload(self, payload: dict[str, Any]) -> ConfigDocument:
        """Fail-closed validation against both JSON Schema v1 and Pydantic strict models."""
        serialized = json.dumps(payload, ensure_ascii=False)
        if SECRET_PATTERN_RE.search(serialized):
            raise ConfigServiceError(
                ErrorCode.INVALID_ARGS,
                "Configuration payload appears to contain raw secret/token material (T18).",
            )
        try:
            jsonschema.validate(instance=payload, schema=self._json_schema)
            return ConfigDocument.model_validate(payload)
        except Exception as exc:
            raise ConfigServiceError(ErrorCode.INVALID_ARGS, f"Invalid configuration: {exc}") from exc

    def save_revision(
        self,
        doc: ConfigDocument,
        *,
        source: str = "user",
        correlation_id: str,
        actor: str = "local_owner",
    ) -> StoredConfigRevision:
        if source not in ("onboarding", "user", "rollback"):
            raise ConfigServiceError(ErrorCode.INVALID_ARGS, f"Unsupported config source '{source}'.")
        payload_dict = doc.model_dump(mode="json")
        self.validate_payload(payload_dict)
        now_iso = self._clock.now_utc().isoformat()
        config_json = json.dumps(payload_dict, sort_keys=True, separators=(",", ":"))

        with self._db.core_tx() as conn:
            prev_row = conn.execute("SELECT revision FROM config_revision WHERE is_active = 1 LIMIT 1").fetchone()
            prev_rev = int(prev_row["revision"]) if prev_row is not None else None
            if prev_rev is not None:
                conn.execute("UPDATE config_revision SET is_active = 0 WHERE revision = ?", (prev_rev,))
            cur = conn.execute(
                """
                INSERT INTO config_revision(
                    schema_version, config_json, source, is_active, previous_healthy_revision, created_at
                ) VALUES (?, ?, ?, 1, ?, ?)
                """,
                (doc.schema_version, config_json, source, prev_rev, now_iso),
            )
            new_rev = int(cur.lastrowid or 1)
            conn.execute(
                """
                INSERT INTO audit_event(
                    id, correlation_id, action_run_id, actor, event_type, outcome, redacted_meta_json, timestamp
                ) VALUES (?, ?, NULL, ?, 'config.revision_saved', 'completed', ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    correlation_id,
                    actor,
                    json.dumps({"revision": new_rev, "source": source, "previous": prev_rev}),
                    now_iso,
                ),
            )
        return StoredConfigRevision(
            revision=new_rev,
            schema_version=doc.schema_version,
            source=source,
            is_active=True,
            previous_healthy_revision=prev_rev,
            created_at=now_iso,
            document=doc,
        )

    def rollback(self, *, correlation_id: str, actor: str = "local_owner") -> StoredConfigRevision:
        """Roll back to previous_healthy_revision atomically (DEC-017)."""
        current = self.get_active()
        target_rev = current.previous_healthy_revision
        if target_rev is None:
            raise ConfigServiceError(
                ErrorCode.NOT_FOUND, "No previous healthy configuration revision available for rollback."
            )
        with self._db.core_read() as conn:
            row = conn.execute("SELECT config_json FROM config_revision WHERE revision = ?", (target_rev,)).fetchone()
        if row is None:
            raise ConfigServiceError(ErrorCode.NOT_FOUND, f"Revision {target_rev} not found.")
        prior_doc = ConfigDocument.model_validate_json(str(row["config_json"]))
        return self.save_revision(prior_doc, source="rollback", correlation_id=correlation_id, actor=actor)

    def export_secret_free_profile(self) -> dict[str, Any]:
        """Export active profile JSON guaranteed free of raw secrets (DEC-017, T18)."""
        active = self.get_active()
        exported = active.document.model_dump(mode="json")
        # Double-check via regex guard
        if SECRET_PATTERN_RE.search(json.dumps(exported)):
            raise ConfigServiceError(ErrorCode.INTERNAL, "Secret leak detected during export.")
        return {
            "exported_at": self._clock.now_utc().isoformat(),
            "revision": active.revision,
            "config": exported,
        }

    def import_profile(
        self, raw_payload: dict[str, Any], *, correlation_id: str, actor: str = "local_owner"
    ) -> StoredConfigRevision:
        config_obj = raw_payload.get("config", raw_payload)
        if not isinstance(config_obj, dict):
            raise ConfigServiceError(ErrorCode.INVALID_ARGS, "Import payload must be a JSON object.")
        validated = self.validate_payload(config_obj)
        return self.save_revision(validated, source="user", correlation_id=correlation_id, actor=actor)

    def complete_onboarding_step(
        self, step: int, *, mark_completed: bool = False, correlation_id: str
    ) -> StoredConfigRevision:
        if step < 1 or step > 10:
            raise ConfigServiceError(ErrorCode.INVALID_ARGS, "Onboarding step must be 1..10.")
        active = self.get_active()
        steps = tuple(sorted({*active.document.onboarding.completed_steps, step}))
        updated_onboarding = active.document.onboarding.model_copy(
            update={"completed_steps": steps, "completed": active.document.onboarding.completed or mark_completed}
        )
        updated_doc = active.document.model_copy(update={"onboarding": updated_onboarding})
        return self.save_revision(updated_doc, source="onboarding", correlation_id=correlation_id)


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()
