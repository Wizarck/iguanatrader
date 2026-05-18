"""trades — extend ``ck_trades_exit_reason_allowed`` with ``'ibkr_reconcile'``

Slice ``dual-daemon-followups`` Phase-2.5. The position-side reconcile
path (:meth:`DaemonLifecycleService.reconcile_with_ibkr` step 3) closes
local trades that IBKR no longer holds — typically because the operator
flat-closed the position manually via TWS while the daemon was off, or
because a fill was missed during a long disconnect. Those closes need
their own ``exit_reason`` sentinel so the daily-loss / stoploss-guard
aggregations (which key off ``exit_reason``) can distinguish a normal
strategy-driven close from a reconcile fix-up.

Allowed values after this migration:

* ``'stop'`` — strategy stop-loss fired (pre-existing).
* ``'target'`` — strategy take-profit fired (pre-existing).
* ``'manual'`` — operator close via the API (pre-existing).
* ``'expiry'`` — time-based expiry (pre-existing).
* ``'ibkr_reconcile'`` — NEW. Trade closed because reconcile detected
  the broker no longer holds the position.

``stoploss_guard`` and the consecutive-stoploss tally still count only
``'stop'``; ``daily_loss`` / ``weekly_loss`` aggregate ``realised_pnl``
over all close categories so the new value contributes naturally.

SQLite cannot rewrite a CHECK constraint in place via ``ALTER TABLE``,
so ``batch_alter_table`` drops + recreates with the extended enum.

Revision ID: 0030_trades_exit_reason_ibkr_reconcile
Revises: 0029_tenant_trading_modes_reconcile_marker
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0030_trades_exit_reason_ibkr_reconcile"
down_revision: str | None = "0029_tenant_trading_modes_reconcile_marker"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ALLOWED_OLD = "exit_reason IS NULL OR exit_reason IN ('stop', 'target', 'manual', 'expiry')"
_ALLOWED_NEW = (
    "exit_reason IS NULL OR exit_reason IN "
    "('stop', 'target', 'manual', 'expiry', 'ibkr_reconcile')"
)


def upgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_constraint("ck_trades_exit_reason_allowed", type_="check")
        batch_op.create_check_constraint(
            "ck_trades_exit_reason_allowed",
            _ALLOWED_NEW,
        )


def downgrade() -> None:
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_constraint("ck_trades_exit_reason_allowed", type_="check")
        batch_op.create_check_constraint(
            "ck_trades_exit_reason_allowed",
            _ALLOWED_OLD,
        )
