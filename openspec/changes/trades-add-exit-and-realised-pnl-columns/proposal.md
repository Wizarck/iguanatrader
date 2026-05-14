# Proposal: trades-add-exit-and-realised-pnl-columns

> **Add `Trade.exit_reason` + `Trade.realised_pnl` columns** (with Alembic migration `0015`) — prerequisite for the v1.5 risk-state-wiring slice that populates `RiskState.recent_stoploss_count_trailing` (needs `exit_reason`) and `day_to_date_loss_pct` / `week_to_date_loss_pct` (need `realised_pnl`). Columns + migration + ORM update + whitelist edit; NO write-side wiring (close-flow updates are a separate slice).

## Why

The v1.5 risk-extension wave (PRs #161, #162, #163) added new fields to `RiskCaps` + `RiskState` but the data sources don't exist on `trades`:

- `stoploss_guard` reads `Trade.exit_reason == "stop"` to count consecutive stoplosses → column doesn't exist.
- `cooldown_period` reads `Trade.closed_at` per symbol → column exists.
- `daily_loss` / `weekly_loss` caps need P&L aggregation → no `Trade.realised_pnl` column exists.

Until these columns land, `wire-risk-state-real-data` (the follow-up slice) cannot populate the state correctly. Tracking the dependency cleanly as a 1-PR prerequisite avoids bundling schema migrations with state-population logic in one over-large PR.

## What

### Migration `0015_trade_exit_columns.py`

```python
"""Add Trade.exit_reason + Trade.realised_pnl columns.

Both nullable — legacy rows (pre-2026-05-15) have these as NULL.
exit_reason populated forward by the trade-close service when state
transitions to "closed". realised_pnl populated at the same moment.

Backfill: NONE. Legacy NULL semantics mean "unknown" — risk
protections treat NULL as "no contribution" (stoploss_guard counts
NULL as not-a-stop; daily/weekly P&L sums skip NULL rows).
"""

def upgrade() -> None:
    op.add_column(
        "trades",
        sa.Column("exit_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "trades",
        sa.Column("realised_pnl", sa.Numeric(18, 8), nullable=True),
    )
    # Optional: CHECK constraint on exit_reason values (SQLite + Postgres compatible)
    op.create_check_constraint(
        "ck_trades_exit_reason_allowed",
        "trades",
        "exit_reason IS NULL OR exit_reason IN ('stop', 'target', 'manual', 'expiry')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_trades_exit_reason_allowed", "trades", type_="check")
    op.drop_column("trades", "realised_pnl")
    op.drop_column("trades", "exit_reason")
```

### ORM update

`apps/api/src/iguanatrader/contexts/trading/models.py::Trade`:

```python
class Trade(Base):
    __tablename__ = "trades"
    __tablename_is_append_only__ = True
    __append_only_mutable_columns__: ClassVar[frozenset[str]] = frozenset(
        {"state", "closed_at", "exit_reason", "realised_pnl"}  # add 2
    )
    ...
    exit_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    realised_pnl: Mapped[Any | None] = mapped_column(Numeric(18, 8), nullable=True)
```

The whitelist edit is essential — without adding the new columns to `__append_only_mutable_columns__`, the global append-only listener will reject the UPDATE when the close-flow tries to populate them (in the follow-up slice).

### Tests

`apps/api/tests/integration/persistence/test_trades_append_only.py` (or extend existing): add 1 test verifying the mutability whitelist allows updating `exit_reason` + `realised_pnl` after INSERT on a state-transition path.

`apps/api/tests/integration/test_migrations.py` (or wherever migration smoke tests live): verify `0015` applies + the constraint rejects bogus values.

## Out of scope

- **Wiring the close-flow to populate exit_reason + realised_pnl** — separate slice (`trades-close-flow-exit-classification`). Service layer that closes a trade today only sets `state="closed"` + `closed_at`; this prerequisite slice does NOT touch that flow.
- **Backfilling existing trade rows** — they stay NULL. The risk protections are NULL-tolerant by default.
- **Per-symbol or per-strategy exit_reason classification beyond the 4 canonical values** — `stop`/`target`/`manual`/`expiry` cover the v1.5 surface. Extended classifications (`expiry_target`, `stop_atr_trail`, etc.) deferred.
- **`wire-risk-state-real-data`** — depends on this slice but is the next slice in the chain, not bundled here.

## Acceptance

- `0015_trade_exit_columns.py` migration applies cleanly (upgrade + downgrade).
- `Trade` ORM has `exit_reason` + `realised_pnl` fields.
- Whitelist includes the 4 columns (2 new + 2 existing).
- Constraint rejects `exit_reason` outside the allowed set.
- mypy --strict + ruff + black clean.
- Existing trades-related tests pass unchanged (no logic touched besides ORM column declarations).
