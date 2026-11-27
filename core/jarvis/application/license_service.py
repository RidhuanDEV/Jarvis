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
        LicenseArtifact(
            id="native-pypdfium2",
            category=LicenseArtifactCategory.NATIVE_LIBRARY,
            name="pypdfium2 / PDFium",
            version_or_rev="5.15.2",
            license_spdx="Apache-2.0",
            source_url="https://github.com/pypdfium2-team/pypdfium2",
            notice_text="pypdfium2 & PDFium licensed under Apache-2.0 / BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-pypdf",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="pypdf",
            version_or_rev="7.1.1",
            license_spdx="BSD-3-Clause",
            source_url="https://github.com/py-pdf/pypdf",
            notice_text="Copyright (c) pypdf contributors. Licensed under BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-python-docx",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="python-docx",
            version_or_rev="1.2.0",
            license_spdx="MIT",
            source_url="https://github.com/python-openxml/python-docx",
            notice_text="Copyright (c) Steve Canny. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="voice-faster-whisper",
            category=LicenseArtifactCategory.VOICE_ASSET,
            name="faster-whisper (Optional Offline Multilingual STT)",
            version_or_rev="1.1.x",
            license_spdx="MIT",
            source_url="https://github.com/SYSTRAN/faster-whisper",
            notice_text="Copyright (c) SYSTRAN. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="voice-openwakeword",
            category=LicenseArtifactCategory.VOICE_ASSET,
            name="openWakeWord + hey_jarvis ONNX (Optional Offline Wake Word)",
            version_or_rev="0.6.0",
            license_spdx="Apache-2.0",
            source_url="https://github.com/dscripka/openWakeWord",
            notice_text="Copyright (c) David Scripka. Licensed under Apache-2.0.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-sounddevice",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="python-sounddevice (Optional Live Microphone/Speaker I/O)",
            version_or_rev="0.5.x",
            license_spdx="MIT",
            source_url="https://github.com/spatialaudio/python-sounddevice",
            notice_text="Copyright (c) Matthias Geier. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-uvicorn",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="Uvicorn",
            version_or_rev="0.54.0",
            license_spdx="BSD-3-Clause",
            source_url="https://github.com/encode/uvicorn",
            notice_text="Copyright (c) Encode OSS Ltd. Licensed under BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-httpx",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="HTTPX",
            version_or_rev="0.28.1",
            license_spdx="BSD-3-Clause",
            source_url="https://github.com/encode/httpx",
            notice_text="Copyright (c) Encode OSS Ltd. Licensed under BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-argon2-cffi",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="argon2-cffi",
            version_or_rev="25.1.0",
            license_spdx="MIT",
            source_url="https://github.com/hynek/argon2-cffi",
            notice_text="Copyright (c) Hynek Schlawack. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-keyring",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="keyring",
            version_or_rev="25.7.0",
            license_spdx="MIT",
            source_url="https://github.com/jaraco/keyring",
            notice_text="Copyright (c) Jason R. Coombs. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-psutil",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="psutil",
            version_or_rev="7.2.2",
            license_spdx="BSD-3-Clause",
            source_url="https://github.com/giampaolo/psutil",
            notice_text="Copyright (c) Giampaolo Rodola. Licensed under BSD-3-Clause.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-structlog",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="structlog",
            version_or_rev="26.1.0",
            license_spdx="Apache-2.0",
            source_url="https://github.com/hynek/structlog",
            notice_text="Dual-licensed under Apache-2.0 or MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="native-onnxruntime",
            category=LicenseArtifactCategory.NATIVE_LIBRARY,
            name="ONNX Runtime (Optional Local Wake/VAD Inference)",
            version_or_rev="1.32.0",
            license_spdx="MIT",
            source_url="https://github.com/microsoft/onnxruntime",
            notice_text="Copyright (c) Microsoft Corporation. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="native-ctranslate2",
            category=LicenseArtifactCategory.NATIVE_LIBRARY,
            name="CTranslate2 (Optional Offline Whisper Backend)",
            version_or_rev="4.9.1",
            license_spdx="MIT",
            source_url="https://github.com/OpenNMT/CTranslate2",
            notice_text="Copyright (c) OpenNMT. Licensed under MIT.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="native-pyav-ffmpeg",
            category=LicenseArtifactCategory.NATIVE_LIBRARY,
            name="PyAV (av) + Bundled FFmpeg (Optional [voice] Transitive Dependency)",
            version_or_rev="18.1.1",
            license_spdx="GPL-3.0-or-later",
            source_url="https://github.com/PyAV-Org/PyAV",
            notice_text="PyAV Python bindings are BSD-3-Clause; binary wheels bundle FFmpeg libraries subject to LGPL/GPL-3.0-or-later distribution obligations. Kept isolated in optional [voice] extra and omitted from core base build.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="voice-windows-onecore-os",
            category=LicenseArtifactCategory.VOICE_ASSET,
            name="Windows OneCore OS Speech Voices (Host OS Component)",
            version_or_rev="host-os",
            license_spdx="Proprietary-Windows-OS",
            source_url="https://learn.microsoft.com/en-us/windows/uwp/design/input/speech-interactions",
            notice_text="Provided exclusively by the host Windows OS installation; NOT bundled or redistributed by J.A.R.V.I.S.",
            verified_at=verified_at,
        ),
        LicenseArtifact(
            id="pkg-numpy",
            category=LicenseArtifactCategory.APP_PACKAGE,
            name="NumPy (Optional Audio Buffer Processing)",
            version_or_rev="2.2.6",
            license_spdx="BSD-3-Clause",
            source_url="https://github.com/numpy/numpy",
            notice_text="Copyright (c) NumPy Developers. Licensed under BSD-3-Clause.",
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
