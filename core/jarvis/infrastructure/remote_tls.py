"""Local Private-LAN/VPN TLS Certificate Provisioning & SHA-256 Pin Verifier for Remote Gateway (Stage G7, B26, FR-REM-01)."""

from __future__ import annotations

import contextlib
import ipaddress
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from jarvis.domain.iot_and_remote import validate_private_gateway_bind_address


@dataclass(frozen=True)
class ProvisionedTlsMaterial:
    cert_path: Path
    key_path: Path
    bind_address: str
    fingerprint_sha256: str
    not_before_utc: datetime
    not_after_utc: datetime


def compute_cert_fingerprint_sha256(cert_pem_bytes: bytes) -> str:
    """Parse an X.509 PEM certificate and return its lowercase 64-hex SHA-256 DER fingerprint."""
    cert = x509.load_pem_x509_certificate(cert_pem_bytes)
    return cert.fingerprint(hashes.SHA256()).hex().lower()


def provision_local_remote_tls_cert(
    tls_dir: Path,
    *,
    bind_address: str,
    now_utc: datetime | None = None,
    validity_days: int = 365,
) -> ProvisionedTlsMaterial:
    """Generate a local self-signed ECDSA P-256 TLS certificate pinned strictly to a private/VPN bind IP."""
    verdict = validate_private_gateway_bind_address(bind_address)
    if not verdict.allowed:
        raise ValueError(verdict.reason)

    ip_obj = ipaddress.ip_address(bind_address.strip().strip("[]"))
    now = now_utc or datetime.now(UTC)
    not_before = now - timedelta(minutes=5)
    not_after = now + timedelta(days=max(1, min(validity_days, 825)))

    private_key = ec.generate_private_key(ec.SECP256R1())
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "J.A.R.V.I.S. Local Personal Intelligence"),
            x509.NameAttribute(NameOID.COMMON_NAME, f"jarvis-remote-{ip_obj}"),
        ]
    )
    san = x509.SubjectAlternativeName([x509.IPAddress(ip_obj)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(san, critical=False)
        .sign(private_key, hashes.SHA256())
    )

    tls_dir.mkdir(parents=True, exist_ok=True)
    cert_path = tls_dir / "remote_gateway_cert.pem"
    key_path = tls_dir / "remote_gateway_key.pem"

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    cert_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    with contextlib.suppress(OSError):
        os.chmod(key_path, 0o600)

    fingerprint = cert.fingerprint(hashes.SHA256()).hex().lower()
    return ProvisionedTlsMaterial(
        cert_path=cert_path,
        key_path=key_path,
        bind_address=str(ip_obj),
        fingerprint_sha256=fingerprint,
        not_before_utc=not_before,
        not_after_utc=not_after,
    )


def verify_provisioned_tls_material(
    tls_dir: Path, *, expected_fingerprint_sha256: str, now_utc: datetime | None = None
) -> tuple[bool, str]:
    """Verify local TLS cert + key exist, certificate is unexpired, and DER SHA-256 matches expected pin."""
    cert_path = tls_dir / "remote_gateway_cert.pem"
    key_path = tls_dir / "remote_gateway_key.pem"
    if not cert_path.is_file() or not key_path.is_file():
        return (False, "Local TLS certificate/key pair has not been provisioned yet (/v1/remote/tls/provision).")

    try:
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        _ = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except Exception as exc:
        return (False, f"Provisioned TLS certificate or private key is invalid: {exc}")

    now = now_utc or datetime.now(UTC)
    if now < cert.not_valid_before_utc or now >= cert.not_valid_after_utc:
        return (False, "Provisioned TLS certificate is expired or not yet valid.")

    actual_fp = cert.fingerprint(hashes.SHA256()).hex().lower()
    if actual_fp != expected_fingerprint_sha256.strip().lower():
        return (False, "TLS certificate fingerprint does not match the provisioned local certificate.")
    return (True, "Provisioned local TLS certificate and private key verified.")
