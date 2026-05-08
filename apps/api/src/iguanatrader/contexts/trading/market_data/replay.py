"""MarketDataReplayService - re-evaluate strategies against historical bars.

Slice market-data-replay. Operator command surface:

    iguanatrader market-data replay
        --routine=<premarket|midday|postmarket|weekly_review>
        --date=<YYYY-MM-DD>
        [--symbols=AAPL,MSFT] [--timeframe=1d] [--lookback-bars=200]

Re-evaluates each (symbol, enabled-config) pair against bars
``ts <= as_of`` from ``market_data_bars`` (T4-followup-market-data).
NEVER calls ``TradingService.propose`` (no event emission, no
trade_proposals INSERT, no broker call). Read-only.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from iguanatrader.contexts.trading.market_data import MarketDataNotAvailableError
from iguanatrader.contexts.trading.ports import StrategyConfigSnapshot

if TYPE_CHECKING:
    from iguanatrader.contexts.trading.ports import MarketDataPort, StrategyPort
    from iguanatrader.contexts.trading.repository import StrategyConfigRepository


log = structlog.get_logger("iguanatrader.contexts.trading.market_data.replay")


_ALLOWED_ROUTINES: frozenset[str] = frozenset(
    {"premarket", "midday", "postmarket", "weekly_review"}
)


@dataclass(frozen=True, slots=True)
class ReplayRow:
    """One (symbol, strategy) result from a replay invocation."""

    symbol: str
    strategy_kind: str
    strategy_version: int
    would_propose: bool
    side: str | None = None
    quantity: Decimal | None = None
    entry_price: Decimal | None = None
    stop_price: Decimal | None = None
    rationale: str = ""


@dataclass(slots=True)
class ReplayResult:
    """Aggregate replay outcome for a single (routine, as_of) tick.

    Mutable (NOT frozen) because `bars_loaded` accumulates across the
    per-symbol loop in `MarketDataReplayService.replay`.
    """

    routine: str
    as_of: datetime
    rows: list[ReplayRow] = field(default_factory=list)
    bars_loaded: int = 0


class MarketDataReplayService:
    """Replay strategies against historical bars without side effects."""

    def __init__(
        self,
        *,
        market_data_port: MarketDataPort,
        strategy_config_repo: StrategyConfigRepository,
        strategy_resolver: Callable[[UUID], Awaitable[StrategyPort]],
    ) -> None:
        self._md = market_data_port
        self._configs = strategy_config_repo
        self._resolve = strategy_resolver

    async def replay(
        self,
        *,
        symbols: list[str],
        routine: str,
        as_of: datetime,
        timeframe: str = "1d",
        lookback_bars: int = 200,
    ) -> ReplayResult:
        """Re-evaluate each (symbol, enabled-config) pair at ``as_of``."""
        if routine not in _ALLOWED_ROUTINES:
            raise ValueError(
                f"Unknown routine {routine!r}; expected one of " f"{sorted(_ALLOWED_ROUTINES)}"
            )

        result = ReplayResult(routine=routine, as_of=as_of)
        for symbol in symbols:
            try:
                configs = await self._configs.list_enabled_for_symbol(symbol)
            except Exception as exc:
                log.warning(
                    "market_data.replay.config_load_failed",
                    symbol=symbol,
                    error=str(exc),
                )
                continue

            if not configs:
                result.rows.append(
                    ReplayRow(
                        symbol=symbol,
                        strategy_kind="<none>",
                        strategy_version=0,
                        would_propose=False,
                        rationale="<no enabled configs>",
                    )
                )
                continue

            try:
                bars = await self._md.get_bars(
                    symbol=symbol,
                    timeframe=timeframe,  # type: ignore[arg-type]
                    lookback_bars=lookback_bars,
                    as_of=as_of,
                )
            except MarketDataNotAvailableError as exc:
                for cfg in configs:
                    result.rows.append(
                        ReplayRow(
                            symbol=symbol,
                            strategy_kind=cfg.strategy_kind,
                            strategy_version=cfg.version,
                            would_propose=False,
                            rationale=f"<no bars: {exc.detail}>",
                        )
                    )
                continue

            result.bars_loaded += len(bars.bars)
            for cfg in configs:
                snapshot = StrategyConfigSnapshot(
                    id=cfg.id,
                    tenant_id=cfg.tenant_id,
                    strategy_kind=cfg.strategy_kind,
                    symbol=cfg.symbol,
                    params=dict(cfg.params),
                    enabled=cfg.enabled,
                    version=cfg.version,
                )
                try:
                    strategy = await self._resolve(cfg.id)
                except Exception as exc:
                    log.warning(
                        "market_data.replay.resolver_failed",
                        symbol=symbol,
                        config_id=str(cfg.id),
                        error=str(exc),
                    )
                    result.rows.append(
                        ReplayRow(
                            symbol=symbol,
                            strategy_kind=cfg.strategy_kind,
                            strategy_version=cfg.version,
                            would_propose=False,
                            rationale=f"<resolver failed: {exc}>",
                        )
                    )
                    continue

                try:
                    proposal = strategy.evaluate(symbol, bars, snapshot)
                except Exception as exc:
                    log.warning(
                        "market_data.replay.evaluate_failed",
                        symbol=symbol,
                        strategy_kind=cfg.strategy_kind,
                        error=str(exc),
                    )
                    result.rows.append(
                        ReplayRow(
                            symbol=symbol,
                            strategy_kind=cfg.strategy_kind,
                            strategy_version=cfg.version,
                            would_propose=False,
                            rationale=f"<evaluate raised: {exc}>",
                        )
                    )
                    continue

                if proposal is None:
                    result.rows.append(
                        ReplayRow(
                            symbol=symbol,
                            strategy_kind=cfg.strategy_kind,
                            strategy_version=cfg.version,
                            would_propose=False,
                            rationale="<no signal>",
                        )
                    )
                else:
                    result.rows.append(
                        ReplayRow(
                            symbol=symbol,
                            strategy_kind=cfg.strategy_kind,
                            strategy_version=cfg.version,
                            would_propose=True,
                            side=proposal.side,
                            quantity=proposal.quantity,
                            entry_price=proposal.entry_price_indicative,
                            stop_price=proposal.stop_price,
                            rationale=str(getattr(proposal, "reasoning", "") or ""),
                        )
                    )

        return result


__all__ = ["MarketDataReplayService", "ReplayResult", "ReplayRow"]
