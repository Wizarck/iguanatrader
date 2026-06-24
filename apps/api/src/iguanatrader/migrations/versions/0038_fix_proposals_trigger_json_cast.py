"""Postgres-only: fix the trade_proposals append-only trigger's json comparison.

The L2 whitelist trigger installed by 0035 guards immutability with
``OLD.col IS DISTINCT FROM NEW.col`` over every non-whitelisted column. One of
those columns, ``reasoning``, is type ``json`` — and Postgres defines no ``=``
operator for ``json`` (only ``jsonb``). So the predicate raised
``UndefinedFunctionError: operator does not exist: json = json`` on EVERY
legitimate whitelisted UPDATE (e.g. the risk engine moving a proposal
pending_approval → rejected, or → approved), silently failing the
``proposal_rejected_handler`` and stranding proposals at their default state.

(0035 itself noted the Postgres branch was "Unvalidated against a real
Postgres in this MVP". This is the validation.)

Fix: CREATE OR REPLACE the function so the ``reasoning`` comparison casts to
``::text`` (``OLD.reasoning::text IS DISTINCT FROM NEW.reasoning::text``) —
still null-safe, still trips on any real change, but operator-valid on json.
The trigger itself is unchanged (it references the function by name), so only
the function body is replaced. Postgres-only; SQLite stores JSON as TEXT and
its ``IS NOT`` branch never had the problem. Downgrade is a no-op (the prior
body is broken).

Revision ID: 0038_fix_proposals_trigger_json_cast
Revises: 0037_postgres_native_types
"""

from __future__ import annotations

from alembic import op

revision: str = "0038_fix_proposals_trigger_json_cast"
down_revision: str | None = "0037_postgres_native_types"
branch_labels: str | None = None
depends_on: str | None = None


# Non-whitelisted columns for trade_proposals (static snapshot, lockstep with
# ``_trading_whitelist_trigger_helpers.NON_WHITELISTED_COLUMNS``); ``reasoning``
# is the only json column and is compared via ``::text``.
_CHANGED = (
    "OLD.id IS DISTINCT FROM NEW.id "
    "OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id "
    "OR OLD.strategy_config_id IS DISTINCT FROM NEW.strategy_config_id "
    "OR OLD.symbol IS DISTINCT FROM NEW.symbol "
    "OR OLD.side IS DISTINCT FROM NEW.side "
    "OR OLD.quantity IS DISTINCT FROM NEW.quantity "
    "OR OLD.entry_price_indicative IS DISTINCT FROM NEW.entry_price_indicative "
    "OR OLD.stop_price IS DISTINCT FROM NEW.stop_price "
    "OR OLD.target_price IS DISTINCT FROM NEW.target_price "
    "OR OLD.confidence_score IS DISTINCT FROM NEW.confidence_score "
    "OR OLD.reasoning::text IS DISTINCT FROM NEW.reasoning::text "
    "OR OLD.research_brief_id IS DISTINCT FROM NEW.research_brief_id "
    "OR OLD.mode IS DISTINCT FROM NEW.mode "
    "OR OLD.correlation_id IS DISTINCT FROM NEW.correlation_id "
    "OR OLD.created_at IS DISTINCT FROM NEW.created_at"
)

_ALLOWED = (
    "state,rejection_reason,rejected_at,risk_score,risk_flags,"
    "risk_rationale,risk_generated_at,risk_model"
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(f"""
        CREATE OR REPLACE FUNCTION trg_trade_proposals_block_nonwhitelisted_update()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF {_CHANGED} THEN
                RAISE EXCEPTION
                    'append-only: only [{_ALLOWED}] are mutable on trade_proposals';
            END IF;
            RETURN NEW;
        END;
        $$;
        """)


def downgrade() -> None:
    # The prior function body is the broken (json =) one; intentionally a no-op.
    pass
