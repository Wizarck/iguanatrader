"""Unit tests for the A0 budget-cap surface on /settings/feature-flags.

The :class:`BudgetGuard` itself ships from R6; this slice exposes the
per-tenant `llm_budget_usd` flag through the existing settings DTO so
the operator can edit it via the UI / API rather than having to drop
into the DB.

Pure-unit — test the DTO parse + the route's flag-merge logic with a
fake `db.get(Tenant, id)` so we don't depend on a live AsyncSession.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from iguanatrader.api.dtos.settings import FeatureFlagsIn, FeatureFlagsOut


def test_feature_flags_in_accepts_only_budget_cap_field() -> None:
    """A partial PUT that only updates the cap leaves the recall toggle alone."""
    payload = FeatureFlagsIn(llm_budget_usd="75.50")
    assert payload.hindsight_recall_enabled is None
    assert payload.llm_budget_usd == "75.50"


def test_feature_flags_in_accepts_partial_recall_toggle_only() -> None:
    payload = FeatureFlagsIn(hindsight_recall_enabled=True)
    assert payload.hindsight_recall_enabled is True
    assert payload.llm_budget_usd is None


def test_feature_flags_in_forbids_unknown_keys() -> None:
    """Schema is whitelisted — typos / future flags must be rejected
    rather than silently persisted."""
    with pytest.raises(ValueError):
        FeatureFlagsIn.model_validate({"bogus_flag": True})


def test_feature_flags_out_serialises_empty_cap_as_null() -> None:
    out = FeatureFlagsOut()
    assert out.llm_budget_usd is None
    assert out.hindsight_recall_enabled is False


def test_feature_flags_out_round_trips_decimal_string() -> None:
    out = FeatureFlagsOut(llm_budget_usd="125.75")
    assert out.llm_budget_usd == "125.75"
    # Decimal parses cleanly — the route's `BudgetGuard` consumer needs
    # this guarantee to keep float-drift out of the comparison.
    assert Decimal(out.llm_budget_usd) == Decimal("125.75")


# ---------------------------------------------------------------------------
# Route-level flag-merge semantics (validated against a hand-rolled tenant)
# ---------------------------------------------------------------------------


class _FakeTenant:
    """Stands in for the SQLAlchemy ``Tenant`` row in unit tests."""

    def __init__(self, feature_flags: dict[str, Any] | None = None) -> None:
        self.feature_flags: dict[str, Any] | None = dict(feature_flags) if feature_flags else None


def _merge(tenant: _FakeTenant, payload: FeatureFlagsIn) -> dict[str, Any]:
    """Replica of the route's flag-merge step, isolated from FastAPI.

    Used to exercise the partial-update + parse / clear semantics
    without spinning up an AsyncSession + listener stack.
    """
    from decimal import Decimal as _D
    from decimal import InvalidOperation as _IO

    current = dict(tenant.feature_flags or {})
    if payload.hindsight_recall_enabled is not None:
        current["hindsight_recall_enabled"] = bool(payload.hindsight_recall_enabled)
    if payload.llm_budget_usd is not None:
        raw = payload.llm_budget_usd.strip()
        if raw == "":
            current.pop("llm_budget_usd", None)
        else:
            try:
                value = _D(raw)
            except (_IO, ValueError) as exc:
                raise ValueError(str(exc)) from exc
            if value < _D("0"):
                raise ValueError("cannot be negative")
            current["llm_budget_usd"] = str(value)
    return current


def test_merge_sets_cap_from_clean_state() -> None:
    tenant = _FakeTenant()
    out = _merge(tenant, FeatureFlagsIn(llm_budget_usd="100.00"))
    assert out["llm_budget_usd"] == "100.00"


def test_merge_clears_cap_with_empty_string() -> None:
    tenant = _FakeTenant({"llm_budget_usd": "100.00"})
    out = _merge(tenant, FeatureFlagsIn(llm_budget_usd=""))
    assert "llm_budget_usd" not in out


def test_merge_preserves_recall_flag_when_only_cap_changes() -> None:
    """Critical partial-update invariant — a cap edit must not silently
    flip the recall toggle back to False."""
    tenant = _FakeTenant({"hindsight_recall_enabled": True})
    out = _merge(tenant, FeatureFlagsIn(llm_budget_usd="50.00"))
    assert out["hindsight_recall_enabled"] is True
    assert out["llm_budget_usd"] == "50.00"


def test_merge_rejects_negative_cap() -> None:
    tenant = _FakeTenant()
    with pytest.raises(ValueError, match="negative"):
        _merge(tenant, FeatureFlagsIn(llm_budget_usd="-5.00"))


def test_merge_rejects_non_decimal_cap() -> None:
    tenant = _FakeTenant()
    with pytest.raises(ValueError):
        _merge(tenant, FeatureFlagsIn(llm_budget_usd="not a number"))
