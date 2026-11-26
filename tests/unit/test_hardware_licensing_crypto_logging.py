"""Unit tests for Hardware Recommendation matrix, 11-Category Licensing, Crypto, and PII Log Redaction."""

from __future__ import annotations

import io
import json
import os
from datetime import UTC, datetime

import pytest

from jarvis.domain.licensing import (
    LicenseValidationError,
    derive_license_obligations,
    generate_cyclonedx_sbom,
    generate_third_party_notices,
    validate_license_artifact,
)
from jarvis.domain.models import (
    AiProfileMode,
    BackendPreference,
    CpuInfo,
    DisplayInfo,
    FpsTarget,
    GpuInfo,
    HardwareSnapshot,
    LicenseArtifact,
    LicenseArtifactCategory,
    OsInfo,
    PowerState,
    SupportTier,
    VisualQualityTier,
)
from jarvis.domain.recommendations import recommend_configuration
from jarvis.infrastructure.crypto import (
    Argon2Params,
    CryptoIntegrityError,
    decrypt_field,
    decrypt_portable_backup,
    encrypt_field,
    encrypt_portable_backup,
)
from jarvis.infrastructure.logging_setup import configure_logging, get_logger

GIB = 1024 * 1024 * 1024
FAST_TEST_ARGON2 = Argon2Params(time_cost=1, memory_cost_kib=16384, parallelism=1)


def _snapshot(
    *,
    ram_gib: float,
    gpus: tuple[GpuInfo, ...] = (),
    refresh_hz: float = 60.0,
    power: PowerState = PowerState.AC,
) -> HardwareSnapshot:
    return HardwareSnapshot(
        id="hw-fixture",
        os_info=OsInfo(system="Windows", release="11", version="10.0", arch="AMD64"),
        cpu=CpuInfo(model_name="Generic x64 CPU", physical_cores=6, logical_cores=12),
        ram_total_bytes=int(ram_gib * GIB),
        ram_available_bytes=int(ram_gib * 0.6 * GIB),
        gpus=gpus,
        displays=(
            DisplayInfo(
                name="DISPLAY1",
                width_px=1920,
                height_px=1080,
                refresh_hz=refresh_hz,
                is_primary=True,
            ),
        ),
        power_state=power,
        captured_at=datetime(2026, 11, 26, 12, 0, tzinfo=UTC),
    )


def test_hardware_recommendation_matrix_across_all_tiers() -> None:
    # 1. < 6 GB RAM -> Unsupported for local LLM, Direct Mode + Lite
    low_ram = recommend_configuration(_snapshot(ram_gib=4))
    assert low_ram.support_tier == SupportTier.UNSUPPORTED
    assert low_ram.recommended_ai_mode == AiProfileMode.DIRECT
    assert low_ram.recommended_visual_tier == VisualQualityTier.LITE

    # 2. 8 GB CPU-only -> Supported Eco + Lite
    cpu8 = recommend_configuration(_snapshot(ram_gib=8))
    assert cpu8.support_tier == SupportTier.SUPPORTED
    assert cpu8.recommended_ai_mode == AiProfileMode.ECO
    assert cpu8.recommended_backend == BackendPreference.CPU
    assert cpu8.recommended_visual_tier == VisualQualityTier.LITE

    # 3. 16 GB CPU-only -> Supported Balanced CPU
    cpu16 = recommend_configuration(_snapshot(ram_gib=16, refresh_hz=144.0))
    assert cpu16.support_tier == SupportTier.SUPPORTED
    assert cpu16.recommended_ai_mode == AiProfileMode.BALANCED
    assert cpu16.recommended_fps_target == FpsTarget.AUTO

    # 4. 4 GB NVIDIA GPU -> Supported Balanced CUDA, VRAM cap <= 80%
    nv4 = recommend_configuration(
        _snapshot(
            ram_gib=24,
            gpus=(
                GpuInfo(
                    index=0,
                    vendor="nvidia",
                    name="Entry Discrete GPU 4GB",
                    vram_total_mib=4096,
                    vram_free_mib=3800,
                    supports_cuda=True,
                    supports_vulkan=True,
                ),
            ),
            refresh_hz=200.0,
        )
    )
    assert nv4.support_tier == SupportTier.SUPPORTED
    assert nv4.recommended_ai_mode == AiProfileMode.BALANCED
    assert nv4.recommended_backend == BackendPreference.CUDA
    assert nv4.recommended_max_vram_mib <= int(4096 * 0.80)

    # 5. 12 GB NVIDIA GPU -> Supported Quality + Cinematic
    nv12 = recommend_configuration(
        _snapshot(
            ram_gib=32,
            gpus=(
                GpuInfo(
                    index=0,
                    vendor="nvidia",
                    name="Mid Discrete GPU 12GB",
                    vram_total_mib=12288,
                    vram_free_mib=11800,
                    supports_cuda=True,
                ),
            ),
        )
    )
    assert nv12.support_tier == SupportTier.SUPPORTED
    assert nv12.recommended_ai_mode == AiProfileMode.QUALITY
    assert nv12.recommended_visual_tier == VisualQualityTier.CINEMATIC

    # 6. AMD GPU -> Experimental Adaptive Vulkan/ROCm
    amd = recommend_configuration(
        _snapshot(
            ram_gib=16,
            gpus=(
                GpuInfo(
                    index=0,
                    vendor="amd",
                    name="AMD Radeon RX",
                    vram_total_mib=8192,
                    vram_free_mib=7800,
                    supports_vulkan=True,
                    supports_rocm=False,
                ),
            ),
        )
    )
    assert amd.support_tier == SupportTier.EXPERIMENTAL
    assert amd.recommended_backend == BackendPreference.VULKAN

    # 7. Unknown GPU -> Unverified + safe CPU fallback
    unk = recommend_configuration(
        _snapshot(
            ram_gib=16,
            gpus=(
                GpuInfo(
                    index=0,
                    vendor="unknown",
                    name="Mystery Accelerator",
                    vram_total_mib=6144,
                    vram_free_mib=6144,
                ),
            ),
        )
    )
    assert unk.support_tier == SupportTier.UNVERIFIED
    assert unk.recommended_backend == BackendPreference.CPU


def test_license_inventory_blocks_unknown_and_tracks_copyleft_obligations() -> None:
    now = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)

    # Recall: Unknown / unreviewed licenses MUST be blocked (BR-SYS-03)
    for bad_spdx in ("Unknown", "UNKNOWN", "", "TBD", "Proprietary-Unknown"):
        with pytest.raises(LicenseValidationError):
            derive_license_obligations(bad_spdx, LicenseArtifactCategory.APP_PACKAGE)

    # Precision: MIT, GPL-3.0-or-later, AGPL-3.0-only, and voice_asset pass with exact obligations
    gpl_voice = validate_license_artifact(
        LicenseArtifact(
            id="voice-piper",
            category=LicenseArtifactCategory.VOICE_ASSET,
            name="Piper GPL",
            version_or_rev="1.8.0",
            license_spdx="GPL-3.0-or-later",
            source_url="https://github.com/OHF-Voice/piper1-gpl",
            notice_text="GPL-3.0-or-later",
            verified_at=now,
        )
    )
    assert "source_offer_or_distribution" in gpl_voice.obligations
    assert "model_card_notice" in gpl_voice.obligations
    assert "upstream_dataset_review" in gpl_voice.obligations

    agpl_obs = derive_license_obligations("AGPL-3.0-only", LicenseArtifactCategory.NATIVE_LIBRARY)
    assert "network_source_offer" in agpl_obs

    sbom = generate_cyclonedx_sbom((gpl_voice,), generated_at=now)
    assert sbom["bomFormat"] == "CycloneDX"
    assert sbom["specVersion"] == "1.5"
    assert len(sbom["components"]) == 1

    notices = generate_third_party_notices((gpl_voice,))
    assert "Piper GPL" in notices
    assert "GPL-3.0-or-later" in notices


def test_aes256_gcm_field_crypto_and_argon2id_portable_backup_tamper_detection() -> None:
    dek = os.urandom(32)
    aad = b"memory:mem-1:content"
    ct1 = encrypt_field(dek, "rahasia pemilik", aad)
    ct2 = encrypt_field(dek, "rahasia pemilik", aad)
    assert ct1 != ct2  # Fresh 96-bit nonce per encryption
    assert decrypt_field(dek, ct1, aad) == "rahasia pemilik"

    # Wrong AAD or wrong DEK fails authentication
    with pytest.raises(CryptoIntegrityError):
        decrypt_field(dek, ct1, b"memory:mem-2:content")
    with pytest.raises(CryptoIntegrityError):
        decrypt_field(os.urandom(32), ct1, aad)

    # Portable backup Argon2id + AES-256-GCM
    payload = b"SQLITE-SNAPSHOT-BYTES-123456"
    archive = encrypt_portable_backup(payload, "correct-horse-battery", params=FAST_TEST_ARGON2)
    assert decrypt_portable_backup(archive, "correct-horse-battery") == payload

    # Wrong recovery passphrase fails
    with pytest.raises(CryptoIntegrityError):
        decrypt_portable_backup(archive, "wrong-passphrase-123")

    # Flipped ciphertext byte fails GCM authentication
    tampered = bytearray(archive)
    tampered[-1] ^= 0xFF
    with pytest.raises(CryptoIntegrityError):
        decrypt_portable_backup(bytes(tampered), "correct-horse-battery")


def test_structured_logging_pii_redaction_and_crlf_precision_recall_probes() -> None:
    buf = io.StringIO()
    configure_logging(level="INFO", stream=buf)
    logger = get_logger("jarvis.test")

    jwt_sample = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJvd25lciJ9.c2lnbmF0dXJlMTIz"
    logger.info(
        "probe.security.event",
        authorization="Bearer topsecret_token_99999",
        cookie="session=abc",
        password="my-password",
        token="raw-token-value",
        nonce="single-use-nonce-123",
        passphrase="recovery-phrase-secret",
        nik="3174012345678901",
        otp="482910",
        free_text=f"user input\n{{\"level\":\"info\",\"forged\":true}} Bearer raw_inline_secret {jwt_sample}",
        benign_route="/v1/system/capabilities",
        benign_status=200,
        benign_class="nvidia_entry_vram",
    )

    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    assert len(lines) == 1  # Anti-CRLF: forged newline MUST NOT split into 2 JSON lines!
    record = json.loads(lines[0])

    # Recall probes: sensitive fields MUST be redacted
    for secret_key in ("authorization", "cookie", "password", "token", "nonce", "passphrase", "nik", "otp"):
        assert record[secret_key] == "[REDACTED]", f"Key '{secret_key}' was not redacted"
    assert "topsecret_token_99999" not in lines[0]
    assert "raw_inline_secret" not in lines[0]
    assert jwt_sample not in lines[0]
    assert "[REDACTED_TOKEN]" in record["free_text"]
    assert "\n" not in record["free_text"]

    # Precision probes: benign operational fields MUST remain intact
    assert record["benign_route"] == "/v1/system/capabilities"
    assert record["benign_status"] == 200
    assert record["benign_class"] == "nvidia_entry_vram"
