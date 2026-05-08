"""Pydantic DTOs for ``/settings/*`` routes (slice R6).

``feature_flags`` is the v1 surface; future slices may add other
settings (notification preferences, locale, etc.) under the same
``/settings`` prefix.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureFlagsOut(BaseModel):
    """Read shape for ``GET /settings/feature-flags`` (slice R6)."""

    model_config = ConfigDict(extra="forbid")

    hindsight_recall_enabled: bool = Field(
        default=False,
        examples=[False],
        description=(
            "FR81 - togglable narrative recall. Default OFF; recommended "
            "ON after >=12 months of operation per ADR-016."
        ),
    )


class FeatureFlagsIn(BaseModel):
    """Write shape for ``PUT /settings/feature-flags`` (slice R6).

    Whitelist: only known keys accepted. Unknown keys -> 400 via
    Pydantic's ``extra='forbid'``.
    """

    model_config = ConfigDict(extra="forbid")

    hindsight_recall_enabled: bool = Field(examples=[True])


__all__ = ["FeatureFlagsIn", "FeatureFlagsOut"]
