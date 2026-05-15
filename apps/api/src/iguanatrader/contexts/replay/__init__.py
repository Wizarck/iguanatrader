"""Replay context — decision-quality counterfactual analysis (slice ``replay-engine-decision-quality``).

Lite alternative to a full backtest engine (ADR-016 deliberately
dropped that). Instead of simulating strategy signals from scratch
against historical bars, this context:

1. Loads :class:`TradeProposal` rows that the live system already
   generated (the proposals carry entry + stop + side + quantity).
2. For each proposal, simulates the post-entry PnL using the bars
   that followed (already in ``market_data_bars`` via the ingestor).
3. Applies a configurable :class:`ExitPolicy` matrix so the operator
   can compare "what would each exit policy have yielded" without
   reintroducing the backtest bounded context.
4. Produces an HTML report aggregating per-proposal outcomes +
   gate-precision / gate-recall metrics.

The slice is read-only against the existing schema (no migrations).
"""

from __future__ import annotations
