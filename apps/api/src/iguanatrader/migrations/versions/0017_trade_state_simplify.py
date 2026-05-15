"""trades.state — simplify enum + add `closing` transitional state.

Slice ``trade-state-machine-redesign``. Pre-slice the
``ck_trades_state_allowed`` CHECK constraint accepted four values::

    'open', 'closed_filled', 'closed_force_exit', 'closed_canceled'

This was redundant with the ``exit_reason`` column (added in slice
``trades-add-exit-and-realised-pnl-columns``, migration 0015) which
already captures *why* a trade closed (``stop`` / ``target`` /
``manual`` / ``expiry``). The three ``closed_*`` variants encoded the
same dimension at the state-machine level.

Post-slice the allowed values are::

    'open', 'closing', 'closed'

Semantics:

* ``open`` — trade is active. Covers BOTH the pre-fill window (entry
  order submitted, not yet filled) AND the live-position window
  (entry filled, no exit ordered yet). The risk engine counts these
  as live positions; the small pre-fill window is acceptable as a
  conservative overcount.
* ``closing`` — an exit order has been submitted but not yet fully
  filled. The trailing-stops sweep + close-flow service will use
  this state to mark trades that are mid-transition; risk continues
  to count them as live positions for cap purposes.
* ``closed`` — the trade has terminated. ``exit_reason`` records the
  category; ``realised_pnl`` records the P&L. The risk engine's
  realised-loss aggregations match this state exclusively.

**Migration behaviour**: rewrites any pre-existing row whose state is
one of the three legacy ``closed_*`` variants to ``'closed'`` (the
``exit_reason`` is unchanged — if it's NULL on a legacy row it stays
NULL, which is the documented "unknown" sentinel from slice 0015).
``'open'`` rows are untouched.

**No data loss**: the legacy state variants are still discoverable
via the ``exit_reason`` column (``'manual'`` ≈ legacy
``'closed_force_exit'`` semantically, ``NULL`` ≈ unknown reason).

Revision ID: 0017_trade_state_simplify
Revises: 0016_trailing_stop_audit
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0017_trade_state_simplify"
down_revision: str | None = "0016_trailing_stop_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1. Migrate existing closed_* variants to the unified `closed` state.
    op.execute(
        "UPDATE trades SET state = 'closed' "
        "WHERE state IN ('closed_filled', 'closed_force_exit', 'closed_canceled')"
    )

    # 2. Swap the CHECK constraint. SQLite cannot ALTER a CHECK in place;
    # batch_alter_table rewrites the table with the new constraint. The
    # constraint name uses ``op.f()`` to opt out of the project's naming
    # convention (``ck_%(table_name)s_%(constraint_name)s``) — without it
    # Alembic would prefix again and look up the wrong identifier.
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_constraint(op.f("ck_trades_state_allowed"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_trades_state_allowed"),
            "state IN ('open', 'closing', 'closed')",
        )


def downgrade() -> None:
    # Recreate the legacy 4-variant constraint. Data going back to
    # ``closed_filled`` is the safe default (most legacy rows would have
    # been "filled normally"); operators with `closed_force_exit` /
    # `closed_canceled` semantics they want to preserve must restore
    # from a pre-upgrade backup. Documented in the upgrade note.
    with op.batch_alter_table("trades") as batch_op:
        batch_op.drop_constraint(op.f("ck_trades_state_allowed"), type_="check")
        batch_op.create_check_constraint(
            op.f("ck_trades_state_allowed"),
            "state IN ('open', 'closed_filled', 'closed_force_exit', 'closed_canceled')",
        )
    op.execute("UPDATE trades SET state = 'closed_filled' WHERE state = 'closed'")
    # `closing` has no legacy equivalent; coerce to `open` so the new
    # CHECK accepts it (those positions were mid-exit; reverting the
    # state machine loses that information).
    op.execute("UPDATE trades SET state = 'open' WHERE state = 'closing'")
