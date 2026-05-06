"""Unit tests for OpenBBFacade.

Mocks the lazy openbb import so tests run without the SDK installed.
Asserts each facade method maps the openbb response shape to the
documented dict contract; asserts errors propagate as OpenBBFacadeError
rather than crashing the process.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import pytest

from openbb_sidecar.adapters.openbb_facade import OpenBBFacade, OpenBBFacadeError


@pytest.fixture(autouse=True)
def reset_facade_cache() -> None:
    """Reset the cached import result + remove any injected fake openbb module."""
    OpenBBFacade._import_result = None
    OpenBBFacade._import_error = None
    sys.modules.pop("openbb", None)


def _install_fake_openbb(obb_namespace: SimpleNamespace) -> ModuleType:
    """Install a fake ``openbb`` module exposing the given ``obb`` attribute."""
    fake = ModuleType("openbb")
    fake.obb = obb_namespace  # type: ignore[attr-defined]
    sys.modules["openbb"] = fake
    return fake


def test_is_ready_returns_true_when_openbb_imports() -> None:
    _install_fake_openbb(SimpleNamespace())
    facade = OpenBBFacade()
    assert facade.is_ready() is True
    assert facade.import_error is None


def test_is_ready_returns_false_when_openbb_import_fails() -> None:
    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openbb":
            raise ImportError("mocked: openbb not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with patch("builtins.__import__", side_effect=fake_import):
        facade = OpenBBFacade()
        assert facade.is_ready() is False
        assert facade.import_error is not None
        assert "openbb" in facade.import_error.lower()


def test_equity_fundamentals_maps_response_shape() -> None:
    fake_row = SimpleNamespace(
        pe_ratio=22.5,
        market_cap=3_500_000_000_000.0,
        dividend_yield=0.005,
        date="2026-04-30",
    )
    fake_obj = SimpleNamespace(results=[fake_row])
    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            fundamental=SimpleNamespace(metrics=lambda symbol: fake_obj),
            estimates=SimpleNamespace(consensus=lambda symbol: fake_obj),
        ),
        economy=SimpleNamespace(fred_series=lambda symbol: fake_obj),
    )
    _install_fake_openbb(fake_obb)

    facade = OpenBBFacade()
    result = facade.equity_fundamentals("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["pe_ratio"] == 22.5
    assert result["market_cap"] == 3_500_000_000_000.0
    assert result["dividend_yield"] == 0.005
    assert result["as_of_date"] == "2026-04-30"


def test_equity_fundamentals_raises_when_no_results() -> None:
    fake_obj = SimpleNamespace(results=[])
    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            fundamental=SimpleNamespace(metrics=lambda symbol: fake_obj),
        ),
    )
    _install_fake_openbb(fake_obb)

    facade = OpenBBFacade()
    with pytest.raises(OpenBBFacadeError) as exc:
        facade.equity_fundamentals("UNKNOWN")
    assert "no fundamentals" in str(exc.value).lower()


def test_equity_ratings_maps_response_shape() -> None:
    fake_row = SimpleNamespace(
        recommendation="Buy",
        target_high=250.0,
        number_of_analysts=42,
        date="2026-04-29",
    )
    fake_obj = SimpleNamespace(results=[fake_row])
    fake_obb = SimpleNamespace(
        equity=SimpleNamespace(
            estimates=SimpleNamespace(consensus=lambda symbol: fake_obj),
        ),
    )
    _install_fake_openbb(fake_obb)

    facade = OpenBBFacade()
    result = facade.equity_ratings("AAPL")

    assert result["symbol"] == "AAPL"
    assert result["consensus"] == "Buy"
    assert result["target_price"] == 250.0
    assert result["analyst_count"] == 42


def test_economy_macro_returns_series_and_metadata() -> None:
    fake_rows = [
        SimpleNamespace(date="2026-01-01", value=100.0),
        SimpleNamespace(date="2026-02-01", value=101.5),
    ]
    fake_obj = SimpleNamespace(
        results=fake_rows,
        extra={"unit": "Index 1982-1984=100", "frequency": "Monthly"},
    )
    fake_obb = SimpleNamespace(
        economy=SimpleNamespace(fred_series=lambda symbol: fake_obj),
    )
    _install_fake_openbb(fake_obb)

    facade = OpenBBFacade()
    result = facade.economy_macro("CPIAUCSL")

    assert result["indicator"] == "CPIAUCSL"
    assert len(result["series"]) == 2
    assert result["series"][0]["value"] == 100.0
    assert result["unit"] == "Index 1982-1984=100"
    assert result["frequency"] == "Monthly"


def test_facade_method_raises_when_openbb_unavailable() -> None:
    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "openbb":
            raise ImportError("mocked: openbb not installed")
        return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

    with patch("builtins.__import__", side_effect=fake_import):
        facade = OpenBBFacade()
        with pytest.raises(OpenBBFacadeError) as exc:
            facade.equity_fundamentals("AAPL")
        assert "not loadable" in str(exc.value).lower()
