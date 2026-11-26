"""Fail-fast startup configuration validated once at boot before binding any socket."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from platformdirs import user_cache_dir, user_data_dir
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class CoreStartupSettings(BaseSettings):
    """Fail-fast validated startup config (zero lazy os.environ lookups inside route handlers)."""

    model_config = SettingsConfigDict(env_prefix="JARVIS_", extra="ignore")

    env: Literal["development", "test", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    bind_host: Literal["127.0.0.1", "::1"] = "127.0.0.1"
    bind_port: int = Field(default=0, ge=0, le=65535)
    release_sha: str = Field(default="dev-local", min_length=1, max_length=64)
    base_data_dir: Path | None = None
    base_cache_dir: Path | None = None
    auth_token: str = Field(default_factory=lambda: secrets.token_hex(32))

    @field_validator("auth_token")
    @classmethod
    def validate_token_strength(cls, value: str) -> str:
        if len(value) < 32:
            raise ValueError("JARVIS_AUTH_TOKEN must be at least 32 characters (>= 256-bit).")
        return value

    def resolved_data_dir(self) -> Path:
        if self.base_data_dir is not None:
            return self.base_data_dir.resolve()
        return Path(user_data_dir("Jarvis", "JarvisOS"))

    def resolved_cache_dir(self) -> Path:
        if self.base_cache_dir is not None:
            return self.base_cache_dir.resolve()
        return Path(user_cache_dir("Jarvis", "JarvisOS"))
