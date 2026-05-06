"""Sidecar runtime config — env-only.

Per design D10 (config surface): no SOPS layer in MVP. The sidecar reads
plain env vars from docker-compose. Production hardening (rotated API keys
via SOPS-encrypted envs) is a v0.2 follow-up if/when OpenBB endpoints
require auth.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class SidecarSettings(BaseSettings):
    """Pydantic-settings model reading OPENBB_SIDECAR_* env vars."""

    model_config = SettingsConfigDict(
        env_prefix="OPENBB_SIDECAR_",
        env_file=None,
        case_sensitive=False,
    )

    host: str = "0.0.0.0"
    port: int = 8765
    log_level: str = "INFO"


def get_settings() -> SidecarSettings:
    """Lazy factory; pydantic-settings reads env at call time."""
    return SidecarSettings()
