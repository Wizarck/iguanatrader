# ruff: noqa: RUF001
"""Strategies catalogue route — slice U7.

Auto-discovered. Exposes the per-strategy parameter catalogue
(display name, description, parameter list with type/default/help)
as ``GET /api/v1/strategies/catalogue`` so the frontend can stop
maintaining a parallel copy in ``apps/web/src/lib/strategies/types.ts``.

Phase 1 (this slice): the catalogue is a Python literal living inside
this route module — already an improvement over the prior state since
**any** Python-side change forces a coordinated DTO/route update, not
a silent TS drift.

Phase 2 (follow-up): each ``Strategy`` subclass under
``apps/api/src/iguanatrader/contexts/trading/strategies/`` exposes a
``describe()`` classmethod returning its own descriptor; this route
calls ``StrategyManager.registry()`` to assemble the catalogue
dynamically. Defer because that requires touching every strategy
class — not the keystone for closing the drift problem.

Frontend cutover happens in the same follow-up that ships phase 2 —
swap the TS ``STRATEGY_CATALOGUE`` constant for an async server-load
fetch with the TS literal as a fallback for SSR + offline scenarios.
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from iguanatrader.api.deps import get_current_user
from iguanatrader.persistence import User

log = structlog.get_logger("iguanatrader.api.routes.strategies_catalogue")

router = APIRouter(prefix="/strategies", tags=["strategies"])


class ParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str
    type: str  # 'integer' | 'decimal' | 'percent' | 'optional-decimal' | 'optional-string'
    default: int | float | str | None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    help: str


class StrategyDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str
    display_name: str
    description: str
    params: list[ParamSpec]


# Shared parameter blocks reused across strategies. Mirrors
# `apps/web/src/lib/strategies/types.ts` ATR_PARAMS + RISK_PARAM.

_ATR_PARAMS: list[dict[str, object]] = [
    {
        "name": "atr_period",
        "label": "ATR period (bars)",
        "type": "integer",
        "default": 14,
        "min": 2,
        "max": 200,
        "step": 1,
        "help": (
            "Bars used by the ATR (mean true range). 14 is the textbook default; "
            "lower = tighter, jumpier stops."
        ),
    },
    {
        "name": "atr_mult",
        "label": "ATR stop multiplier",
        "type": "decimal",
        "default": 2.0,
        "min": 0.5,
        "max": 10,
        "step": 0.1,
        "help": (
            "Stop loss is placed at entry − atr_mult × ATR. 2.0 is a common "
            "middle ground; 1.0 is tight, 3.0 wide."
        ),
    },
]

_RISK_PARAM: dict[str, object] = {
    "name": "risk_pct",
    "label": "Risk per trade (%)",
    "type": "percent",
    "default": 0.01,
    "min": 0.001,
    "max": 0.1,
    "step": 0.001,
    "help": (
        "Fraction of account equity to put at risk per trade. 1% is a common "
        "cap; NFR-R6 enforces a hard ceiling."
    ),
}

# Position-sizing mode shared across every strategy. "risk" (default) sizes by
# risk_pct of equity; "cash" buys a fixed dollar amount (target_cash / price),
# the way orders are often placed by hand at IB. Both floor to whole shares.
_SIZING_PARAMS: list[dict[str, object]] = [
    {
        "name": "sizing_mode",
        "label": "Position sizing mode",
        "type": "optional-string",
        "default": None,
        "help": (
            'How the share quantity is sized. Leave empty (or "risk") to size by '
            'risk-per-trade (risk_pct of equity); set to "cash" to buy a fixed '
            "dollar amount (target_cash ÷ price). Always floored to whole shares."
        ),
    },
    {
        "name": "target_cash",
        "label": "Target cash per trade ($)",
        "type": "optional-decimal",
        "default": None,
        "min": 0,
        "step": 50,
        "help": (
            'Dollar amount to deploy per trade when sizing mode is "cash". '
            "Ignored in risk mode. Floored to whole shares at the entry price."
        ),
    },
]


def _build_catalogue() -> list[StrategyDescriptor]:
    """Build the canonical catalogue. Idempotent + side-effect free."""
    return [
        StrategyDescriptor(
            kind="donchian_atr",
            display_name="Donchian breakout + ATR stop",
            description=(
                "Long-only trend follower. Buys when price closes above the highest "
                "high of the prior N bars. Stop placed below entry at a multiple of "
                "Average True Range. Position sized to risk a fixed % of equity. "
                "Originated with the Turtle Traders."
            ),
            params=[
                ParamSpec(
                    name="lookback",
                    label="Donchian channel lookback (bars)",
                    type="integer",
                    default=20,
                    min=5,
                    max=200,
                    step=1,
                    help=(
                        "How many bars define the breakout high. 20 (Turtle S1) is "
                        "reactive; 55 (Turtle S2) is slower but cleaner."
                    ),
                ),
                *[ParamSpec(**p) for p in _ATR_PARAMS],  # type: ignore[arg-type]
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
        StrategyDescriptor(
            kind="sma_cross",
            display_name="Golden-cross SMA",
            description=(
                "Long-only momentum strategy. Enters when the fast SMA crosses up "
                "through the slow SMA. Volatility-aware position sizing using a "
                'rolling stdev of returns. Classic 50/200 day combo is the "golden cross".'
            ),
            params=[
                ParamSpec(
                    name="fast",
                    label="Fast SMA period (bars)",
                    type="integer",
                    default=50,
                    min=2,
                    max=200,
                    step=1,
                    help="Short moving-average window. Smaller = more sensitive, more whipsaws.",
                ),
                ParamSpec(
                    name="slow",
                    label="Slow SMA period (bars)",
                    type="integer",
                    default=200,
                    min=10,
                    max=500,
                    step=1,
                    help="Long moving-average window. Must be greater than fast.",
                ),
                ParamSpec(
                    name="vol_window",
                    label="Volatility window (bars)",
                    type="integer",
                    default=20,
                    min=5,
                    max=100,
                    step=1,
                    help="Bars used to estimate return stdev for sizing.",
                ),
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
        StrategyDescriptor(
            kind="bollinger_breakout",
            display_name="Bollinger upper-band breakout",
            description=(
                "Long-only volatility-adaptive trend follower. Buys when price "
                "closes above the upper Bollinger band (SMA + N stdev). Optional "
                "squeeze gate requires the bands to have been narrow before the "
                "break, which filters chop. ATR-based stop and risk-% sizing."
            ),
            params=[
                ParamSpec(
                    name="period",
                    label="Bollinger period (bars)",
                    type="integer",
                    default=20,
                    min=5,
                    max=200,
                    step=1,
                    help=(
                        "Bars used for the SMA + stdev. 20 is the canonical " "Bollinger setting."
                    ),
                ),
                ParamSpec(
                    name="num_std",
                    label="Band width (× stdev)",
                    type="decimal",
                    default=2.0,
                    min=0.5,
                    max=5,
                    step=0.1,
                    help=(
                        "How many standard deviations away the band sits. 2.0 is "
                        "the classic default; higher = harder to trigger."
                    ),
                ),
                ParamSpec(
                    name="squeeze_threshold",
                    label="Squeeze threshold (band width %)",
                    type="optional-decimal",
                    default=None,
                    min=0.001,
                    max=0.5,
                    step=0.001,
                    help=(
                        "Optional. When set, the break only counts if the prior "
                        "squeeze-lookback bars had band width below this %. Leave "
                        "empty to disable the gate."
                    ),
                ),
                ParamSpec(
                    name="squeeze_lookback",
                    label="Squeeze lookback (bars)",
                    type="integer",
                    default=6,
                    min=2,
                    max=50,
                    step=1,
                    help=(
                        "Bars over which the squeeze condition must hold. "
                        "Ignored when squeeze threshold is empty."
                    ),
                ),
                *[ParamSpec(**p) for p in _ATR_PARAMS],  # type: ignore[arg-type]
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
        StrategyDescriptor(
            kind="rsi_mean_reversion",
            display_name="RSI oversold mean-reversion",
            description=(
                "Long-only counter-trend. Buys when Wilder RSI(14) crosses up from "
                "below the oversold threshold — i.e. the dip is starting to "
                "reverse. ATR stop and risk-% sizing keep losses bounded on the "
                "(frequent) failed reversals."
            ),
            params=[
                ParamSpec(
                    name="rsi_period",
                    label="RSI period (bars)",
                    type="integer",
                    default=14,
                    min=2,
                    max=100,
                    step=1,
                    help="Wilder smoothing period. 14 is the textbook default.",
                ),
                ParamSpec(
                    name="oversold",
                    label="Oversold threshold (0-100)",
                    type="decimal",
                    default=30,
                    min=5,
                    max=50,
                    step=1,
                    help=(
                        "RSI level below which the strategy waits for a cross-up. "
                        "30 is conventional; 20 is more aggressive."
                    ),
                ),
                ParamSpec(
                    name="overbought",
                    label="Overbought threshold (0-100)",
                    type="decimal",
                    default=70,
                    min=50,
                    max=95,
                    step=1,
                    help=(
                        "Symmetric counterpart to oversold. Exposed for symmetry "
                        "— long-only entries do not consume it directly."
                    ),
                ),
                *[ParamSpec(**p) for p in _ATR_PARAMS],  # type: ignore[arg-type]
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
        StrategyDescriptor(
            kind="macd_cross",
            display_name="MACD signal-line cross",
            description=(
                "Long-only momentum strategy. Buys when the MACD line crosses up "
                "through its signal line (Appel canonical 12/26/9). Optional bias "
                "filter — pass an SMA period in bias_filter to require price above "
                "SMA(period) before entry, filtering counter-trend signals."
            ),
            params=[
                ParamSpec(
                    name="fast",
                    label="MACD fast EMA (bars)",
                    type="integer",
                    default=12,
                    min=2,
                    max=100,
                    step=1,
                    help="Short EMA in the MACD formula. 12 is the Appel default.",
                ),
                ParamSpec(
                    name="slow",
                    label="MACD slow EMA (bars)",
                    type="integer",
                    default=26,
                    min=5,
                    max=200,
                    step=1,
                    help="Long EMA. Must be greater than fast.",
                ),
                ParamSpec(
                    name="signal",
                    label="MACD signal EMA (bars)",
                    type="integer",
                    default=9,
                    min=2,
                    max=50,
                    step=1,
                    help="Smoothing EMA applied to the MACD line. 9 is the Appel default.",
                ),
                ParamSpec(
                    name="bias_filter",
                    label="Bias filter (SMA period, optional)",
                    type="optional-string",
                    default=None,
                    help=(
                        'Optional trend filter — type an SMA period like "200" '
                        "to require price above SMA(period). Leave empty to disable."
                    ),
                ),
                *[ParamSpec(**p) for p in _ATR_PARAMS],  # type: ignore[arg-type]
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
        StrategyDescriptor(
            kind="volume_donchian",
            display_name="Donchian breakout + volume confirmation",
            description=(
                "Long-only conviction-filtered Donchian variant. Same N-bar high "
                "breakout as the vanilla Donchian, but the breakout bar must also "
                "see volume above a multiple of the rolling average volume. "
                "Filters low-conviction breaks at the cost of fewer entries."
            ),
            params=[
                ParamSpec(
                    name="period",
                    label="Donchian period (bars)",
                    type="integer",
                    default=20,
                    min=5,
                    max=200,
                    step=1,
                    help=(
                        "Channel lookback. Same role as `lookback` in the vanilla "
                        "Donchian strategy."
                    ),
                ),
                ParamSpec(
                    name="vol_window",
                    label="Volume average window (bars)",
                    type="integer",
                    default=20,
                    min=5,
                    max=200,
                    step=1,
                    help="Bars used for the rolling average volume baseline.",
                ),
                ParamSpec(
                    name="volume_threshold",
                    label="Volume multiple required",
                    type="decimal",
                    default=1.5,
                    min=1.0,
                    max=10,
                    step=0.1,
                    help=(
                        "Breakout volume must be ≥ this multiple of the rolling "
                        "avg. 1.5× is a moderate filter; 2.0× is strict."
                    ),
                ),
                *[ParamSpec(**p) for p in _ATR_PARAMS],  # type: ignore[arg-type]
                ParamSpec(**_RISK_PARAM),  # type: ignore[arg-type]
                *[ParamSpec(**p) for p in _SIZING_PARAMS],  # type: ignore[arg-type]
            ],
        ),
    ]


@router.get("/catalogue", response_model=list[StrategyDescriptor])
async def get_catalogue(
    user: User = Depends(get_current_user),
) -> list[StrategyDescriptor]:
    """Return the canonical strategies catalogue.

    Cross-tenant — every tenant queries the same catalogue (the
    strategy IMPLEMENTATIONS are global; tenants choose which to
    enable via their per-strategy config rows).
    """
    log.info("api.strategies.catalogue.get")
    return _build_catalogue()


__all__ = ["router"]
