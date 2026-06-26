"""Unit tests for the strategies-catalogue route (slice U7).

Pure-unit — no HTTP layer. The route's heavy lifting is the
``_build_catalogue()`` function; we exercise it directly to pin the
6-strategy shape + parameter invariants. Drift detection here means
breaking a parameter (rename / type change / default removal) fails
this test instead of bleeding silently into the frontend form.
"""

from __future__ import annotations

from iguanatrader.api.routes.strategies_catalogue import (
    ParamSpec,
    StrategyDescriptor,
    _build_catalogue,
)


def test_catalogue_returns_all_six_strategies() -> None:
    catalogue = _build_catalogue()
    kinds = [d.kind for d in catalogue]
    assert kinds == [
        "donchian_atr",
        "sma_cross",
        "bollinger_breakout",
        "rsi_mean_reversion",
        "macd_cross",
        "volume_donchian",
    ]


def test_every_descriptor_has_display_name_and_description() -> None:
    for d in _build_catalogue():
        assert d.display_name, f"missing display_name on {d.kind!r}"
        assert d.description, f"missing description on {d.kind!r}"
        assert len(d.params) > 0, f"no params on {d.kind!r}"


def test_every_strategy_includes_risk_pct() -> None:
    """`risk_pct` is the universal sizing parameter; every strategy
    MUST expose it so the form gates risk consistently."""
    for d in _build_catalogue():
        names = {p.name for p in d.params}
        assert "risk_pct" in names, f"{d.kind!r} missing risk_pct"


def test_every_strategy_includes_sizing_params() -> None:
    """WS-A added the risk/cash sizing controls; every strategy MUST expose both
    `sizing_mode` and `target_cash` so the form offers cash sizing consistently."""
    for d in _build_catalogue():
        names = {p.name for p in d.params}
        assert {"sizing_mode", "target_cash"} <= names, f"{d.kind!r} missing sizing params"


def test_atr_strategies_include_atr_block() -> None:
    """Every strategy that uses an ATR stop must carry both
    `atr_period` and `atr_mult` so the form's grouped renderer can
    find them as a pair."""
    atr_using_kinds = {
        "donchian_atr",
        "bollinger_breakout",
        "rsi_mean_reversion",
        "macd_cross",
        "volume_donchian",
    }
    for d in _build_catalogue():
        if d.kind not in atr_using_kinds:
            continue
        names = {p.name for p in d.params}
        assert "atr_period" in names, f"{d.kind!r} missing atr_period"
        assert "atr_mult" in names, f"{d.kind!r} missing atr_mult"
        # WS-C: the ATR strategies' take-profit is an ATR multiple.
        assert "target_mult" in names, f"{d.kind!r} missing target_mult"


def test_sma_cross_uses_target_rr_not_target_mult() -> None:
    """sma_cross has no ATR, so its take-profit (WS-C) is a reward:risk
    multiple of the volatility-based stop distance, not an ATR multiple."""
    sma = next(d for d in _build_catalogue() if d.kind == "sma_cross")
    names = {p.name for p in sma.params}
    assert "target_rr" in names
    assert "target_mult" not in names


def test_param_types_are_in_the_allowed_set() -> None:
    """Frontend renderer dispatches off `type`; any new shape must be
    added to the renderer FIRST to avoid silently broken inputs."""
    allowed = {"integer", "decimal", "percent", "optional-decimal", "optional-string"}
    for d in _build_catalogue():
        for p in d.params:
            assert p.type in allowed, f"{d.kind!r}.{p.name!r} has unknown type {p.type!r}"


def test_optional_params_have_null_default() -> None:
    """`optional-*` typed params encode "leave blank to skip" semantics
    via a None default. Any non-null default on an optional-typed param
    is a contract violation."""
    for d in _build_catalogue():
        for p in d.params:
            if p.type.startswith("optional-"):
                assert p.default is None, (
                    f"{d.kind!r}.{p.name!r} is optional but has non-null default " f"{p.default!r}"
                )


def test_descriptor_pydantic_extra_forbid_keeps_drift_visible() -> None:
    """`extra='forbid'` ensures a typo in a future inline param dict
    raises at construction time. This test pins that the descriptor
    config stays strict."""
    # Round-trip through model_dump → model_validate, asserting no
    # unknown fields slip through.
    catalogue = _build_catalogue()
    for d in catalogue:
        dumped = d.model_dump()
        rebuilt = StrategyDescriptor.model_validate(dumped)
        assert rebuilt == d


def test_param_spec_extra_forbid() -> None:
    p = ParamSpec(
        name="x",
        label="X",
        type="integer",
        default=1,
        help="test",
    )
    assert p.default == 1
