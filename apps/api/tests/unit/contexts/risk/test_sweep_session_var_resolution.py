"""#29: the cron-sweep services + the trailing-stop audit repo resolve their
session lazily from ``session_var`` when constructed without an explicit one.

This is what lets a single service instance ride a FRESH per-tick session
bound by the daemon's sweep unit-of-work wrapper, rather than capturing the
long-lived ambient daemon session at construction time. Explicit callers
(the existing unit / integration tests) keep passing ``session=...`` and are
unaffected — covered here by the explicit-session branch.
"""

from __future__ import annotations

import pytest
from iguanatrader.contexts.risk.stop_hit_sweep import StopHitSweepService
from iguanatrader.contexts.risk.trailing_stop_repository import (
    TrailingStopAuditRepository,
)
from iguanatrader.contexts.risk.trailing_stop_sweep import TrailingStopSweepService
from iguanatrader.shared.contextvars import session_var


def _stop_hit() -> StopHitSweepService:
    return StopHitSweepService(market_data_port=object(), bus=object())  # type: ignore[arg-type]


def _trailing() -> TrailingStopSweepService:
    return TrailingStopSweepService(
        audit_repo=object(),  # type: ignore[arg-type]
        risk_caps_provider=lambda: object(),  # type: ignore[arg-type,return-value]
        market_data_port=object(),  # type: ignore[arg-type]
    )


def _builders() -> list[object]:
    return [_stop_hit(), _trailing(), TrailingStopAuditRepository()]


def test_resolves_session_from_session_var_when_no_explicit_session() -> None:
    sentinel = object()
    token = session_var.set(sentinel)
    try:
        for svc in _builders():
            assert svc._session is sentinel  # type: ignore[attr-defined]
    finally:
        session_var.reset(token)


def test_raises_lookup_error_when_no_session_anywhere() -> None:
    token = session_var.set(None)
    try:
        for svc in _builders():
            with pytest.raises(LookupError):
                _ = svc._session  # type: ignore[attr-defined]
    finally:
        session_var.reset(token)


def test_explicit_session_wins_over_session_var() -> None:
    explicit = object()
    ambient = object()
    services = [
        StopHitSweepService(session=explicit, market_data_port=object(), bus=object()),  # type: ignore[arg-type]
        TrailingStopSweepService(
            session=explicit,  # type: ignore[arg-type]
            audit_repo=object(),  # type: ignore[arg-type]
            risk_caps_provider=lambda: object(),  # type: ignore[arg-type,return-value]
            market_data_port=object(),  # type: ignore[arg-type]
        ),
        TrailingStopAuditRepository(explicit),  # type: ignore[arg-type]
    ]
    token = session_var.set(ambient)
    try:
        for svc in services:
            assert svc._session is explicit  # type: ignore[attr-defined]
    finally:
        session_var.reset(token)
