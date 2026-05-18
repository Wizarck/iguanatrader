"""Pydantic DTOs for ``/settings/*`` routes (slice R6).

``feature_flags`` is the v1 surface; future slices may add other
settings (notification preferences, locale, etc.) under the same
``/settings`` prefix.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class FeatureFlagsOut(BaseModel):
    """Read shape for ``GET /settings/feature-flags`` (slice R6 + A0)."""

    model_config = ConfigDict(extra="forbid")

    hindsight_recall_enabled: bool = Field(
        default=False,
        examples=[False],
        description=(
            "FR81 - togglable narrative recall. Default OFF; recommended "
            "ON after >=12 months of operation per ADR-016."
        ),
    )

    # Slice A0 — surface the per-tenant monthly LLM budget cap that the
    # `BudgetGuard` consults. Read-only here is fine (the cap defaults
    # to $50 when unset); the PUT shape below exposes editing.
    llm_budget_usd: str | None = Field(
        default=None,
        examples=["50.00"],
        description=(
            "Monthly LLM-spend cap (USD, string-encoded Decimal to avoid "
            "float drift). NULL → use the canonical $50 default. "
            "BudgetGuard auto-downgrades sonnet→haiku at 80%, blocks at 100%."
        ),
    )

    risk_review_confidence_threshold: str | None = Field(
        default=None,
        examples=["0.80"],
        description=(
            "Confidence-score threshold above which "
            "``AutoRiskReviewOnCreateHandler`` runs a Sonnet risk assessment "
            "(slice A2). String-encoded Decimal in ``[0, 1]``. NULL → use "
            'the canonical 0.80 default. Setting it to ``"1.00"`` '
            "disables auto-risk-review without removing the subscriber."
        ),
    )


class FeatureFlagsIn(BaseModel):
    """Write shape for ``PUT /settings/feature-flags`` (slice R6 + A0).

    Whitelist: only known keys accepted. Unknown keys -> 400 via
    Pydantic's ``extra='forbid'``.

    All fields are Optional so a PUT can update a single flag without
    re-sending the whole payload — fields left ``None`` are not
    touched on the persisted ``feature_flags`` JSON.
    """

    model_config = ConfigDict(extra="forbid")

    hindsight_recall_enabled: bool | None = Field(default=None, examples=[True])

    # Slice A0 — admin surface for editing the LLM budget cap. Accepts
    # a string-encoded Decimal so the JSON payload doesn't lose
    # precision on round-trip. ``None`` = "don't change"; an explicit
    # empty string ``""`` clears the cap (returns to the $50 default).
    llm_budget_usd: str | None = Field(default=None, examples=["100.00", ""])

    # Slice A2 — admin surface for editing the confidence threshold that
    # gates auto-risk-review. ``None`` = "don't change"; ``""`` clears
    # the override and falls back to the canonical 0.80 default.
    # ``"1.00"`` effectively disables auto-risk-review (no proposal can
    # exceed the threshold).
    risk_review_confidence_threshold: str | None = Field(
        default=None,
        examples=["0.85", "1.00", ""],
    )


__all__ = ["FeatureFlagsIn", "FeatureFlagsOut"]
