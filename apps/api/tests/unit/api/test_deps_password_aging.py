"""Unit tests for :func:`iguanatrader.api.deps._classify_password_aging`.

Five cases (proposal §Backend tests for slice ``auth-password-aging-warning``):

1. ``test_password_aging_state_fresh_when_null`` —
   ``password_changed_at is None`` → ``(None, "fresh")`` (grandfather
   rule for legacy users planted before migration 0013).
2. ``test_password_aging_state_fresh_when_recent`` — 30 days old
   classifies as ``"fresh"``.
3. ``test_password_aging_state_ageing_at_threshold`` — 60 days old
   classifies as ``"ageing"`` (boundary case at the default ``ageing``
   threshold).
4. ``test_password_aging_state_stale_at_threshold`` — 90 days old
   classifies as ``"stale"`` (boundary case at the default ``stale``
   threshold).
5. ``test_password_aging_state_respects_env_overrides`` — set
   ``IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS=30`` and
   ``IGUANATRADER_AUTH_PASSWORD_STALE_DAYS=60``; verify the boundaries
   shift accordingly.

The helper is exercised directly (no FastAPI, no DB) so each test is a
single function call + assertion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from iguanatrader.api.deps import _classify_password_aging

#: Anchor "now" so the tests are deterministic across runs / time zones.
_NOW: datetime = datetime(2026, 5, 14, 12, 0, 0, tzinfo=UTC)


def test_password_aging_state_fresh_when_null() -> None:
    """``password_changed_at is None`` → ``(None, "fresh")``.

    Legacy users (planted before migration 0013) have NULL in the column.
    Per proposal §Backend, we grandfather them: no signal, no banner.
    """
    age_days, state = _classify_password_aging(None, now=_NOW)
    assert age_days is None
    assert state == "fresh"


def test_password_aging_state_fresh_when_recent() -> None:
    """30 days old → ``"fresh"`` with the default 60-day ageing threshold."""
    pwd_changed_at = _NOW - timedelta(days=30)
    age_days, state = _classify_password_aging(pwd_changed_at, now=_NOW)
    assert age_days == 30
    assert state == "fresh"


def test_password_aging_state_ageing_at_threshold() -> None:
    """60 days old → ``"ageing"`` (boundary inclusive at the default threshold)."""
    pwd_changed_at = _NOW - timedelta(days=60)
    age_days, state = _classify_password_aging(pwd_changed_at, now=_NOW)
    assert age_days == 60
    assert state == "ageing"


def test_password_aging_state_stale_at_threshold() -> None:
    """90 days old → ``"stale"`` (boundary inclusive at the default threshold)."""
    pwd_changed_at = _NOW - timedelta(days=90)
    age_days, state = _classify_password_aging(pwd_changed_at, now=_NOW)
    assert age_days == 90
    assert state == "stale"


def test_password_aging_state_respects_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env overrides shift the ageing/stale boundaries.

    Set the ageing threshold to 30 and the stale threshold to 60; assert
    a 45-day-old password becomes ``"ageing"`` (instead of ``"fresh"``
    under the defaults) and a 70-day-old becomes ``"stale"`` (instead of
    ``"ageing"`` under the defaults).
    """
    monkeypatch.setenv("IGUANATRADER_AUTH_PASSWORD_AGEING_DAYS", "30")
    monkeypatch.setenv("IGUANATRADER_AUTH_PASSWORD_STALE_DAYS", "60")

    # 45 days is in [30, 60) — ageing under the override.
    age_days, state = _classify_password_aging(_NOW - timedelta(days=45), now=_NOW)
    assert age_days == 45
    assert state == "ageing"

    # 70 days is >= 60 — stale under the override.
    age_days, state = _classify_password_aging(_NOW - timedelta(days=70), now=_NOW)
    assert age_days == 70
    assert state == "stale"

    # And the lower band: 10 days is < 30 — fresh.
    age_days, state = _classify_password_aging(_NOW - timedelta(days=10), now=_NOW)
    assert age_days == 10
    assert state == "fresh"
