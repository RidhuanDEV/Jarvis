"""11-Category License Artifact Inventory Service (DEC-022, FR-SYS-05, BR-SYS-03)."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from jarvis.domain.licensing import (
    generate_cyclonedx_sbom,
    generate_third_party_notices,
    validate_license_artifact,
)
from jarvis.domain.models import LicenseArtifact, LicenseArtifactCategory
from jarvis.domain.ports import ClockPort
from jarvis.infrastructure.dual_db import DualSqliteManager


def baseline_license_artifacts(verified_at: datetime) -> tuple[LicenseArtifact, ...]:
    """Seed initial verified Phase 2 baseline entries across core/UI/runtime categories."""
    entries = (
        LicenseArtifact(
            id="pkg-fastapi",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="FastAPI",
            version_or_rev="0.165.0",
            license_spdx="MIT",
            source_url="https://github.com/fastapi/fastapi",
            notice_text="Copyright (c) Sebastián Ramírez. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-pydantic",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="Pydantic",
            version_or_rev="2.14.4",
            license_spdx="MIT",
            source_url="https://github.com/pydantic/pydantic",
            notice_text="Copyright (c) Pydantic Services Inc. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-cryptography",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="pyca/cryptography",
            version_or_rev="50.0.2",
            license_spdx="Apache-2.0",
            source_url="https://github.com/pyca/cryptography",
            notice_text="Dual-licensed under Apache-2.0 or BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-tauri",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="Tauri",
            version_or_rev="2.x",
            license_spdx="Apache-2.0",
            source_url="https://github.com/tauri-apps/tauri",
            notice_text="Copyright (c) Tauri Programme within The Commons Conservancy. Apache-2.0 / MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-react",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="React",
            version_or_rev="19.x",
            license_spdx="MIT",
            source_url="https://github.com/facebook/react",
            notice_text="Copyright (c) Meta Platforms, Inc. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="native-sqlite-vec",
            category=LicenseArtifactCategory.NATIVE_LIBRARY,
            name="sqlite-vec",
            version_or_rev="0.1.9",
            license_spdx="Apache-2.0",
            source_url="https://github.com/asg017/sqlite-vec",
            notice_text="Copyright (c) Alex Garcia. Dual-licensed Apache-2.0 / MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="runtime-llama-cpp",
            category=LicenseArtifactCategory.AI_RUNTIME,
            name="llama.cpp (Optional Managed/External Reference Adapter)",
            version_or_rev="b12774",
            license_spdx="MIT",
            source_url="https://github.com/ggml-org/llama.cpp",
            notice_text="Copyright (c) Georgi Gerganov and contributors. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="voice-piper-tts-gpl",
            category=LicenseArtifactCategory.VOICE_ASSET,
            name="OHF-Voice piper1-gpl (Optional Offline TTS Engine)",
            version_or_rev="1.8.0",
            license_spdx="GPL-3.0-or-later",
            source_url="https://github.com/OHF-Voice/piper1-gpl",
            notice_text="Licensed under GPL-3.0-or-later (bundles espeak-ng). Source offer and full GPLv3 text required upon distribution; voice weights require upstream MODEL_CARD review.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="font-system-orbital-stack",
            category=LicenseArtifactCategory.FONT,
            name="JetBrains Mono & Inter (Local Bundled / OS Fallback)",
            version_or_rev="2.304",
            license_spdx="OFL-1.1",
            source_url="https://www.jetbrains.com/lp/mono/",
            notice_text="SIL Open Font License 1.1.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="icons-lucide",
            category=LicenseArtifactCategory.ICON_SET,
            name="Lucide Icons",
            version_or_rev="0.460+",
            license_spdx="ISC",
            source_url="https://github.com/lucide-icons/lucide",
            notice_text="Copyright (c) Lucide Contributors. Licensed under ISC.",
            verified_at=verified_at,
        ),
    )
    return tuple(validate_license_artifact(item) for item in entries)


class LicenseInventoryService:
    """Persists validated 11-category license artifacts and generates SBOM/NOTICE exports."""

    def __init__(self, db: DualSqliteManager, clock: ClockPort) -> None:
        self._db = db
        self._clock = clock

    def seed_baseline_if_empty(self) -> int:
        with self._db.core_read() as conn:
            count = int(conn.execute("SELECT COUNT(*) FROM license_artifact").fetchone()[0])
        if count > 0:
            return 0
        seeded = baseline_license_artifacts(self._clock.now_utc())
        for artifact in seeded:
            self.register_artifact(artifact)
        return len(seeded)

    def register_artifact(self, artifact: LicenseArtifact) -> LicenseArtifact:
        validated = validate_license_artifact(artifact)
        with self._db.core_tx() as conn:
            conn.execute(
                """
                INSERT INTO license_artifact(
                    id, category, name, version_or_rev, license_spdx, obligations_json,
                    source_url, notice_text, verified_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    category = excluded.category,
                    name = excluded.name,
                    version_or_rev = excluded.version_or_rev,
                    license_spdx = excluded.license_spdx,
                    obligations_json = excluded.obligations_json,
                    source_url = excluded.source_url,
                    notice_text = excluded.notice_text,
                    verified_at = excluded.verified_at
                """,
                (
                    validated.id,
                    validated.category.value,
                    validated.name,
                    validated.version_or_rev,
                    validated.license_spdx,
                    json.dumps(list(validated.obligations)),
                    validated.source_url,
                    validated.notice_text,
                    validated.verified_at.isoformat(),
                ),
            )
        return validated

    def list_artifacts(self) -> tuple[LicenseArtifact, ...]:
        with self._db.core_read() as conn:
            rows = conn.execute(
                """
                SELECT id, category, name, version_or_rev, license_spdx, obligations_json,
                       source_url, notice_text, verified_at
                FROM license_artifact
                ORDER BY category ASC, id ASC
                """
            ).fetchall()
        return tuple(
            LicenseArtifact(
                id=str(r["id"]),
                category=LicenseArtifactCategory(str(r["category"])),
                name=str(r["name"]),
                version_or_rev=str(r["version_or_rev"]),
                license_spdx=str(r["license_spdx"]),
                obligations=tuple(json.loads(str(r["obligations_json"]))),
                source_url=str(r["source_url"]),
                notice_text=str(r["notice_text"]),
                verified_at=datetime.fromisoformat(str(r["verified_at"])),
            )
            for r in rows
        )

    def export_sbom(self) -> dict[str, Any]:
        return generate_cyclonedx_sbom(self.list_artifacts(), generated_at=self._clock.now_utc())

    def export_notices(self) -> str:
        return generate_third_party_notices(self.list_artifacts())
