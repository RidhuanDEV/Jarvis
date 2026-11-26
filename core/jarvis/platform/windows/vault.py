"""Windows SecretVaultAndCryptoPort using OS Credential Manager (keyring) + DPAPI DEK fallback."""

from __future__ import annotations

import base64
import os

import keyring

SERVICE_NAME = "jarvis.personal.os.v1"


class WindowsVaultAndCryptoAdapter:
    """Stores credentials and per-machine DEKs in Windows Credential Manager (never in config JSON)."""

    def __init__(self, service_name: str = SERVICE_NAME) -> None:
        self._service_name = service_name

    def get_secret(self, key_ref: str) -> str | None:
        return keyring.get_password(self._service_name, key_ref)

    def set_secret(self, key_ref: str, value: str) -> None:
        keyring.set_password(self._service_name, key_ref, value)

    def delete_secret(self, key_ref: str) -> bool:
        try:
            keyring.delete_password(self._service_name, key_ref)
            return True
        except keyring.errors.PasswordDeleteError:
            return False

    def get_or_create_master_dek(self, key_ref: str) -> bytes:
        existing = self.get_secret(key_ref)
        if existing is not None:
            decoded = base64.b64decode(existing)
            if len(decoded) == 32:
                return decoded
        new_key = os.urandom(32)
        self.set_secret(key_ref, base64.b64encode(new_key).decode("ascii"))
        return new_key
