"""Replay orchestrator.

Pipes :class:`TradeProposal` rows → :func:`simulate_pnl` per policy →
aggregates → :class:`ReplayResult`. The market-data port is injected
so tests can pass an in-memory adapter without spinning up a real
``DBMarketDataAdapter`` + ingestor.

Tenant scoping: relies on the slice-3 ``tenant_listener`` reading
``tenant_id_var``. The caller is expected to wrap the invocation in
``with_tenant_context(tenant_id)``; without that the proposal query
falls through with no rows.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import select

from iguanatrader.contexts.replay.models import (
    ExitPolicy,
    GateCalibration,
    PolicyAggregate,
    ProposalReplayRow,
    ReplayResult,
    SimulatedOutcome,
)
from iguanatrader.contexts.replay.pnl_simulator import simulate_pnl
from iguanatrader.contexts.trading.models import Trade, TradeProposal
from iguanatrader.contexts.trading.ports import Bar, MarketDataPort

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ReplayService:
    """Orchestrate a counterfactual replay over a time window.

    Stateless beyond injected deps; one instance per CLI invocation.
    """

    def __init__(
        self,
        *,
        session: AsyncSession,
        market_data_port: MarketDataPort,
        lookback_bars: int = 400,
        pre_entry_bars_count: int = 30,
    ) -> None:
        self._session = session
        self._market_data_port = market_data_port
        self._lookback_bars = lookback_bars
        self._pre_entry_bars_count = pre_entry_bars_count

    async def replay_window(
        self,
        *,
        window_start: datetime,
        window_end: datetime,
        policies: Sequence[ExitPolicy],
        gate_calibration_policy: str | None = None,
    ) -> ReplayResult:
        """Replay every proposal opened between ``window_start`` and ``window_end``.

        ``gate_calibration_policy`` selects which policy's simulated
        outcomes feed the gate-precision / gate-recall metric. Defaults
        to the first policy in the input tuple.
        """
        proposals = await self._list_proposals(window_start, window_end)
        trades_by_proposal = await self._index_trades_by_proposal()

        rows: list[ProposalReplayRow] = []
        skipped_no_bars = 0

        for proposal in proposals:
            bars = await self._fetch_bars_around(proposal)
            if bars is None:
                skipped_no_bars += 1
                continue

            opened_at = self._coerce_utc(proposal.created_at)
            pre_entry, post_entry = self._split_bars(bars, opened_at)

            sim_outcomes: dict[str, SimulatedOutcome] = {}
            for policy in policies:
                outcome = simulate_pnl(
                    proposal_id=proposal.id,
                    side=proposal.side,
                    entry_price=Decimal(str(proposal.entry_price_indicative)),
                    initial_stop=Decimal(str(proposal.stop_price)),
                    quantity=Decimal(str(proposal.quantity)),
                    opened_at=opened_at,
                    pre_entry_bars=pre_entry,
                    post_entry_bars=post_entry,
                    policy=policy,
                )
                sim_outcomes[policy.name] = outcome

            trade_row = trades_by_proposal.get(proposal.id)
            historical_decision = self._classify_historical_decision(trade_row)
            actual_pnl = (
                Decimal(str(trade_row.realised_pnl))
                if trade_row is not None and trade_row.realised_pnl is not None
                else None
            )

            rows.append(
                ProposalReplayRow(
                    proposal_id=proposal.id,
                    symbol=proposal.symbol,
                    side=proposal.side,
                    opened_at=opened_at,
                    historical_decision=historical_decision,
                    would_pass_gate_now=None,  # carry-forward — needs risk-engine re-eval
                    actual_pnl=actual_pnl,
                    sim_outcomes=sim_outcomes,
                )
            )

        aggregates = tuple(self._aggregate_for_policy(rows, policy=p) for p in policies)
        chosen_policy = gate_calibration_policy or (policies[0].name if policies else "")
        gate_calibrations = tuple(
            self._compute_gate_calibration(rows, policy_name=p.name)
            for p in policies
            if p.name == chosen_policy or gate_calibration_policy is None
        )
        # When the operator did not pin a single policy, emit calibration
        # blocks for every policy so the report shows the full matrix.
        if gate_calibration_policy is None:
            gate_calibrations = tuple(
                self._compute_gate_calibration(rows, policy_name=p.name) for p in policies
            )

        logger.info(
            "replay.window.completed",
            extra={
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "proposals_evaluated": len(rows),
                "proposals_skipped_no_bars": skipped_no_bars,
                "policies": [p.name for p in policies],
            },
        )

        return ReplayResult(
            window_start=window_start,
            window_end=window_end,
            policies=tuple(policies),
            rows=tuple(rows),
            aggregates=aggregates,
            gate_calibrations=gate_calibrations,
            proposals_skipped_no_bars=skipped_no_bars,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _list_proposals(self, start: datetime, end: datetime) -> list[TradeProposal]:
        stmt = (
            select(TradeProposal)
            .where(TradeProposal.created_at >= start)
            .where(TradeProposal.created_at < end)
            .order_by(TradeProposal.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _index_trades_by_proposal(self) -> dict[UUID, Trade]:
        stmt = select(Trade)
        result = await self._session.execute(stmt)
        return {t.proposal_id: t for t in result.scalars().all()}

    async def _fetch_bars_around(self, proposal: TradeProposal) -> Sequence[Bar] | None:
        """Pull bars from the market-data port spanning pre- + post-entry."""
        try:
            history = await self._market_data_port.get_bars(
                symbol=proposal.symbol,
                timeframe="1d",
                lookback_bars=self._lookback_bars,
                as_of=None,
            )
        except Exception as exc:
            logger.warning(
                "replay.fetch_bars.failed",
                extra={
                    "symbol": proposal.symbol,
                    "proposal_id": str(proposal.id),
                    "error": str(exc),
                },
            )
            return None
        if not history.bars:
            return None
        return history.bars

    @staticmethod
    def _coerce_utc(dt: datetime) -> datetime:
        """SQLite strips tz on round-trip; assume UTC for naive datetimes."""
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)

    def _split_bars(
        self, bars: Sequence[Bar], opened_at: datetime
    ) -> tuple[Sequence[Bar], Sequence[Bar]]:
        """Split into (pre-entry, post-entry) at ``opened_at``.

        Pre-entry uses bars with ``timestamp <= opened_at`` (the
        contemporary view used for ATR computation). Post-entry uses
        bars with ``timestamp > opened_at`` (strict — the entry-bar's
        own close already informed the entry decision).
        """
        pre: list[Bar] = []
        post: list[Bar] = []
        # opened_at is already UTC-aware (caller passes through _coerce_utc).
        # Normalize bars to UTC-aware too so downstream simulate_pnl can
        # compare bar.timestamp against horizon_end without raising.
        for bar in bars:
            if bar.timestamp.tzinfo is None:
                bar_aware = Bar(
                    timestamp=bar.timestamp.replace(tzinfo=UTC),
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            else:
                bar_aware = bar
            if bar_aware.timestamp <= opened_at:
                pre.append(bar_aware)
            else:
                post.append(bar_aware)
        # Limit pre-entry context for ATR — older bars don't help.
        if len(pre) > self._pre_entry_bars_count:
            pre = pre[-self._pre_entry_bars_count :]
        return pre, post

    @staticmethod
    def _classify_historical_decision(trade: Trade | None) -> str:
        """Map the trade row's state to a one-word historical decision.

        ``approved`` covers any state where the trade was actually
        submitted (open / closing / closed). ``rejected`` covers the
        proposal having no trade row at all (gate stopped it, or the
        operator rejected). The replay doesn't currently inspect the
        approval_decisions / approval_requests timeline; that's a
        follow-up if we want to distinguish "operator rejected" from
        "risk-gate rejected".
        """
        if trade is None:
            return "rejected"
        if trade.state in {"open", "closing", "closed"}:
            return "approved"
        return "unknown"

    @staticmethod
    def _aggregate_for_policy(
        rows: Sequence[ProposalReplayRow], *, policy: ExitPolicy
    ) -> PolicyAggregate:
        outcomes = [
            row.sim_outcomes[policy.name] for row in rows if policy.name in row.sim_outcomes
        ]
        exited = [o for o in outcomes if o.exited]
        if not exited:
            return PolicyAggregate(
                policy_name=policy.name,
                proposals_evaluated=len(outcomes),
                proposals_exited=0,
                total_pnl=Decimal("0"),
                mean_pnl_pct=Decimal("0"),
                win_rate=Decimal("0"),
                stop_rate=Decimal("0"),
                target_rate=Decimal("0"),
                horizon_rate=Decimal("0"),
            )
        total_pnl = sum((o.pnl_absolute for o in exited), Decimal("0"))
        mean_pct = sum((o.pnl_pct for o in exited), Decimal("0")) / Decimal(len(exited))
        wins = sum(1 for o in exited if o.pnl_absolute > 0)
        stops = sum(1 for o in exited if o.exit_reason == "stop")
        targets = sum(1 for o in exited if o.exit_reason == "target")
        horizons = sum(1 for o in exited if o.exit_reason == "horizon")
        return PolicyAggregate(
            policy_name=policy.name,
            proposals_evaluated=len(outcomes),
            proposals_exited=len(exited),
            total_pnl=total_pnl,
            mean_pnl_pct=mean_pct,
            win_rate=Decimal(wins) / Decimal(len(exited)),
            stop_rate=Decimal(stops) / Decimal(len(exited)),
            target_rate=Decimal(targets) / Decimal(len(exited)),
            horizon_rate=Decimal(horizons) / Decimal(len(exited)),
        )

    @staticmethod
    def _compute_gate_calibration(
        rows: Sequence[ProposalReplayRow], *, policy_name: str
    ) -> GateCalibration:
        approved_outcomes = [
            row.sim_outcomes[policy_name]
            for row in rows
            if row.historical_decision == "approved" and policy_name in row.sim_outcomes
        ]
        rejected_outcomes = [
            row.sim_outcomes[policy_name]
            for row in rows
            if row.historical_decision == "rejected" and policy_name in row.sim_outcomes
        ]
        approved_profitable = sum(1 for o in approved_outcomes if o.exited and o.pnl_absolute > 0)
        rejected_would_profit = sum(1 for o in rejected_outcomes if o.exited and o.pnl_absolute > 0)
        gate_precision: Decimal | None = (
            Decimal(approved_profitable) / Decimal(len(approved_outcomes))
            if approved_outcomes
            else None
        )
        denom_recall = approved_profitable + rejected_would_profit
        gate_recall: Decimal | None = (
            Decimal(approved_profitable) / Decimal(denom_recall) if denom_recall > 0 else None
        )
        return GateCalibration(
            policy_name=policy_name,
            historical_approved_count=len(approved_outcomes),
            historical_approved_profitable_count=approved_profitable,
            historical_rejected_count=len(rejected_outcomes),
            historical_rejected_would_have_profited_count=rejected_would_profit,
            gate_precision=gate_precision,
            gate_recall=gate_recall,
        )


__all__ = ["ReplayService"]
