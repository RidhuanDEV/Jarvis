"""Cryptographic primitives: AES-256-GCM field encryption & Argon2id portable backups (DEC-007, T07)."""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from argon2.low_level import Type as Argon2Type
from argon2.low_level import hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

AES_KEY_LEN = 32
GCM_NONCE_LEN = 12
ARGON2_SALT_LEN = 16
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST_KIB = 65536
ARGON2_PARALLELISM = 2

# DEF-24 / B05: strict KDF bounds against untrusted backup-header OOM / CPU DoS
ARGON2_MIN_TIME_COST = 1
ARGON2_MAX_TIME_COST = 10
ARGON2_MIN_MEMORY_COST_KIB = 8192       # 8 MiB floor
ARGON2_MAX_MEMORY_COST_KIB = 524288     # 512 MiB ceiling
ARGON2_MIN_PARALLELISM = 1
ARGON2_MAX_PARALLELISM = 8

FIELD_PREFIX = "v1:"
BACKUP_FORMAT_VERSION = 1


class CryptoIntegrityError(ValueError):
    """Raised when ciphertext authentication fails or payload is corrupted."""


def encrypt_field(dek: bytes, plaintext: str, aad: bytes) -> str:
    """Encrypt a sensitive database field using AES-256-GCM with a fresh 96-bit nonce."""
    if len(dek) != AES_KEY_LEN:
        raise ValueError("DEK must be exactly 32 bytes (256-bit).")
    nonce = os.urandom(GCM_NONCE_LEN)
    aes = AESGCM(dek)
    ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), aad)
    encoded = base64.b64encode(nonce + ciphertext).decode("ascii")
    return f"{FIELD_PREFIX}{encoded}"


def decrypt_field(dek: bytes, token: str, aad: bytes) -> str:
    """Decrypt and authenticate an AES-256-GCM field token."""
    if len(dek) != AES_KEY_LEN:
        raise ValueError("DEK must be exactly 32 bytes (256-bit).")
    if not token.startswith(FIELD_PREFIX):
        raise CryptoIntegrityError("Unsupported encrypted field prefix.")
    try:
        raw = base64.b64decode(token[len(FIELD_PREFIX) :], validate=True)
    except Exception as exc:
        raise CryptoIntegrityError("Malformed base64 field ciphertext.") from exc
    if len(raw) <= GCM_NONCE_LEN + 16:
        raise CryptoIntegrityError("Truncated field ciphertext.")
    nonce, ciphertext = raw[:GCM_NONCE_LEN], raw[GCM_NONCE_LEN:]
    aes = AESGCM(dek)
    try:
        plain = aes.decrypt(nonce, ciphertext, aad)
    except InvalidTag as exc:
        raise CryptoIntegrityError("Field authentication failed (wrong key, AAD, or tampered data).") from exc
    return plain.decode("utf-8")


@dataclass(frozen=True)
class Argon2Params:
    time_cost: int = ARGON2_TIME_COST
    memory_cost_kib: int = ARGON2_MEMORY_COST_KIB
    parallelism: int = ARGON2_PARALLELISM


def derive_backup_key_argon2id(
    passphrase: str,
    salt: bytes,
    params: Argon2Params = Argon2Params(),
) -> bytes:
    """Derive a portable 256-bit backup key from user recovery passphrase via Argon2id."""
    if len(passphrase) < 8:
        raise ValueError("Recovery passphrase must be at least 8 characters.")
    if len(salt) != ARGON2_SALT_LEN:
        raise ValueError("Salt must be exactly 16 bytes.")
    return hash_secret_raw(
        secret=passphrase.encode("utf-8"),
        salt=salt,
        time_cost=params.time_cost,
        memory_cost=params.memory_cost_kib,
        parallelism=params.parallelism,
        hash_len=AES_KEY_LEN,
        type=Argon2Type.ID,
    )


def encrypt_portable_backup(
    payload: bytes,
    passphrase: str,
    params: Argon2Params = Argon2Params(),
) -> bytes:
    """Encrypt a cross-machine backup archive with Argon2id + AES-256-GCM."""
    salt = os.urandom(ARGON2_SALT_LEN)
    nonce = os.urandom(GCM_NONCE_LEN)
    key = derive_backup_key_argon2id(passphrase, salt, params)
    header = {
        "v": BACKUP_FORMAT_VERSION,
        "kdf": "argon2id",
        "t": params.time_cost,
        "m": params.memory_cost_kib,
        "p": params.parallelism,
        "salt": base64.b64encode(salt).decode("ascii"),
        "nonce": base64.b64encode(nonce).decode("ascii"),
    }
    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = AESGCM(key).encrypt(nonce, payload, header_bytes)
    header_len = len(header_bytes).to_bytes(4, "big")
    return b"JRVB" + header_len + header_bytes + ciphertext


def decrypt_portable_backup(archive_bytes: bytes, passphrase: str) -> bytes:
    """Authenticate and decrypt a portable backup archive using user recovery passphrase."""
    if len(archive_bytes) < 12 or archive_bytes[:4] != b"JRVB":
        raise CryptoIntegrityError("Invalid JARVIS backup magic header.")
    header_len = int.from_bytes(archive_bytes[4:8], "big")
    if header_len <= 0 or header_len > 16384 or 8 + header_len >= len(archive_bytes):
        raise CryptoIntegrityError("Corrupt backup header length.")
    header_bytes = archive_bytes[8 : 8 + header_len]
    ciphertext = archive_bytes[8 + header_len :]
    try:
        header = json.loads(header_bytes.decode("utf-8"))
        if header.get("v") != BACKUP_FORMAT_VERSION or header.get("kdf") != "argon2id":
            raise CryptoIntegrityError("Unsupported backup format version or KDF.")
        salt = base64.b64decode(str(header["salt"]), validate=True)
        nonce = base64.b64decode(str(header["nonce"]), validate=True)
        if len(salt) != ARGON2_SALT_LEN or len(nonce) != GCM_NONCE_LEN:
            raise CryptoIntegrityError("Invalid backup salt or nonce length.")
        t_cost = int(header["t"])
        m_cost = int(header["m"])
        p_cost = int(header["p"])
        if not (ARGON2_MIN_TIME_COST <= t_cost <= ARGON2_MAX_TIME_COST):
            raise CryptoIntegrityError("Backup KDF time_cost outside safe bounds.")
        if not (ARGON2_MIN_MEMORY_COST_KIB <= m_cost <= ARGON2_MAX_MEMORY_COST_KIB):
            raise CryptoIntegrityError("Backup KDF memory_cost_kib outside safe bounds.")
        if not (ARGON2_MIN_PARALLELISM <= p_cost <= ARGON2_MAX_PARALLELISM):
            raise CryptoIntegrityError("Backup KDF parallelism outside safe bounds.")
        params = Argon2Params(
            time_cost=t_cost,
            memory_cost_kib=m_cost,
            parallelism=p_cost,
        )
    except CryptoIntegrityError:
        raise
    except Exception as exc:
        raise CryptoIntegrityError("Malformed backup header metadata.") from exc

    key = derive_backup_key_argon2id(passphrase, salt, params)
    try:
        return AESGCM(key).decrypt(nonce, ciphertext, header_bytes)
    except InvalidTag as exc:
        raise CryptoIntegrityError(
            "Backup authentication failed (incorrect recovery passphrase or tampered archive)."
        ) from exc


# --- Stage G7 (B26): Argon2id Pairing Code Hashing for Remote Mobile Gateway ---

PAIRING_ARGON2_TIME_COST = 2
PAIRING_ARGON2_MEMORY_COST_KIB = 16384  # 16 MiB — memory-hard protection for 6-digit pairing codes
PAIRING_ARGON2_PARALLELISM = 1
PAIRING_ARGON2_PREFIX = "argon2id$"


def hash_pairing_code_argon2id(pairing_code: str) -> str:
    """Hash a short-lived local pairing code with salted Argon2id (never bare fast SHA-256)."""
    clean = pairing_code.strip()
    if not clean:
        raise ValueError("Pairing code cannot be empty.")
    salt = os.urandom(ARGON2_SALT_LEN)
    digest = hash_secret_raw(
        secret=clean.encode("utf-8"),
        salt=salt,
        time_cost=PAIRING_ARGON2_TIME_COST,
        memory_cost=PAIRING_ARGON2_MEMORY_COST_KIB,
        parallelism=PAIRING_ARGON2_PARALLELISM,
        hash_len=AES_KEY_LEN,
        type=Argon2Type.ID,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(digest).decode("ascii")
    return (
        f"{PAIRING_ARGON2_PREFIX}t={PAIRING_ARGON2_TIME_COST}"
        f"$m={PAIRING_ARGON2_MEMORY_COST_KIB}$p={PAIRING_ARGON2_PARALLELISM}"
        f"${salt_b64}${hash_b64}"
    )


def verify_pairing_code_argon2id(stored_hash: str, candidate_code: str) -> bool:
    """Constant-time verification of a salted Argon2id pairing code hash with bounded KDF params."""
    import hmac

    if not stored_hash.startswith(PAIRING_ARGON2_PREFIX):
        return False
    parts = stored_hash.split("$")
    if len(parts) != 6:
        return False
    try:
        t_cost = int(parts[1].removeprefix("t="))
        m_cost = int(parts[2].removeprefix("m="))
        p_cost = int(parts[3].removeprefix("p="))
        if not (ARGON2_MIN_TIME_COST <= t_cost <= ARGON2_MAX_TIME_COST):
            return False
        if not (ARGON2_MIN_MEMORY_COST_KIB <= m_cost <= ARGON2_MAX_MEMORY_COST_KIB):
            return False
        if not (ARGON2_MIN_PARALLELISM <= p_cost <= ARGON2_MAX_PARALLELISM):
            return False
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
        if len(salt) != ARGON2_SALT_LEN or len(expected) != AES_KEY_LEN:
            return False
    except Exception:
        return False

    actual = hash_secret_raw(
        secret=candidate_code.strip().encode("utf-8"),
        salt=salt,
        time_cost=t_cost,
        memory_cost=m_cost,
        parallelism=p_cost,
        hash_len=AES_KEY_LEN,
        type=Argon2Type.ID,
    )
    return hmac.compare_digest(expected, actual)

