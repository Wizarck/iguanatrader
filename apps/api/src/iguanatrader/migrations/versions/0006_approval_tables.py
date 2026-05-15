"""approval tables — approval_requests + approval_decisions

Slice P1 (``approval-channels-multichannel``) — Wave 2.

Per cross-slice merge plan (R1 → 0003, T1 → 0004 rebase, K1 → 0005 rebase,
**P1 → 0006**, O1 → 0007), this migration's ``down_revision`` chains onto
K1's ``0005_risk_tables``. Wave 2 merge order is K1 → P1; the rebase
already accounts for predecessors landing first.

**Local-runnability gate**: this migration cannot be applied locally
until **all** of slices R1 (``0003``), T1 (``0004``), K1 (``0005``) have
landed because:

* ``approval_requests.proposal_id`` references ``trade_proposals(id)``
  which is owned by T1's migration ``0004``.
* ``decided_by_sender_id`` references ``authorized_senders(id)``
  (already present from slice 3's ``0001``).
* ``decided_by_user_id`` references ``users(id)`` (already present from
  slice 3's ``0001``).

The integration test ``test_migration_0006`` skips when revision
``0005_risk_tables`` (or its predecessors) is not on the alembic chain.
CI runs the full chain because all sibling slices land before merge.

Tables created (per ``docs/data-model.md`` §3.4 verbatim, both
append-only — registered with the slice-3 ``append_only_listener`` via
``__tablename_is_append_only__ = True`` on the ORM models):

* ``approval_requests`` — fan-out targets + expiry; one row per fan-out.
* ``approval_decisions`` — outcome audit (granted/rejected/timeout) with
  channel + latency. UNIQUE on ``request_id`` enforces FR48
  first-decision-wins idempotency (D4).

Indexes:
* ``ix_approval_requests_tenant_id_created_at``
* ``ix_approval_requests_proposal_id``
* ``uq_approval_decisions_request_id`` (UNIQUE — first-decision-wins)
* ``ix_approval_decisions_tenant_id_outcome_created_at``

Revision ID: 0006
Revises: 0005_risk_tables
Created at: 2026-05-06T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006_approval_tables"
down_revision: str | None = "0005_risk_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_requests",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("proposal_id", sa.CHAR(36), nullable=False),
        sa.Column("delivered_to_channels", sa.JSON(), nullable=False),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.Column("delivery_failures", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_requests")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_approval_requests_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposal_id"],
            ["trade_proposals.id"],
            name=op.f("fk_approval_requests_proposal_id_trade_proposals"),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "timeout_seconds > 0",
            name=op.f("ck_approval_requests_timeout_positive"),
        ),
    )
    op.create_index(
        op.f("ix_approval_requests_tenant_id_created_at"),
        "approval_requests",
        ["tenant_id", "created_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_approval_requests_proposal_id"),
        "approval_requests",
        ["proposal_id"],
        unique=False,
    )

    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.CHAR(36), nullable=False),
        sa.Column("tenant_id", sa.CHAR(36), nullable=False),
        sa.Column("request_id", sa.CHAR(36), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("decided_via_channel", sa.Text(), nullable=False),
        sa.Column("decided_by_user_id", sa.CHAR(36), nullable=True),
        sa.Column("decided_by_sender_id", sa.CHAR(36), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_approval_decisions")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_approval_decisions_tenant_id_tenants"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["approval_requests.id"],
            name=op.f("fk_approval_decisions_request_id_approval_requests"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_user_id"],
            ["users.id"],
            name=op.f("fk_approval_decisions_decided_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_sender_id"],
            ["authorized_senders.id"],
            name=op.f("fk_approval_decisions_decided_by_sender_id_authorized_senders"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "request_id",
            name=op.f("uq_approval_decisions_request_id"),
        ),
        sa.CheckConstraint(
            "outcome IN ('granted','rejected','timeout')",
            name=op.f("ck_approval_decisions_outcome_allowed"),
        ),
        sa.CheckConstraint(
            "decided_via_channel IN ('telegram','whatsapp','dashboard','timeout','system')",
            name=op.f("ck_approval_decisions_channel_allowed"),
        ),
        sa.CheckConstraint(
            "latency_ms >= 0",
            name=op.f("ck_approval_decisions_latency_nonneg"),
        ),
    )
    op.create_index(
        op.f("ix_approval_decisions_tenant_id_outcome_created_at"),
        "approval_decisions",
        ["tenant_id", "outcome", "created_at"],
        unique=False,
    )

    # L2 append-only triggers — catch raw-SQL bypasses that skip the
    # ORM ``before_flush`` listener (gotcha #23). Dialect-aware: SQLite
    # uses RAISE(FAIL,...), Postgres uses plpgsql functions per the
    # pattern in 0003 / 0007 / 0009.
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute(
            "CREATE TRIGGER trg_approval_requests_no_update "
            "BEFORE UPDATE ON approval_requests "
            "BEGIN SELECT RAISE(FAIL, 'append-only: approval_requests'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_approval_requests_no_delete "
            "BEFORE DELETE ON approval_requests "
            "BEGIN SELECT RAISE(FAIL, 'append-only: approval_requests'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_approval_decisions_no_update "
            "BEFORE UPDATE ON approval_decisions "
            "BEGIN SELECT RAISE(FAIL, 'append-only: approval_decisions'); END"
        )
        op.execute(
            "CREATE TRIGGER trg_approval_decisions_no_delete "
            "BEFORE DELETE ON approval_decisions "
            "BEGIN SELECT RAISE(FAIL, 'append-only: approval_decisions'); END"
        )
    elif dialect == "postgresql":
        for table in ("approval_requests", "approval_decisions"):
            op.execute(f"""
                CREATE OR REPLACE FUNCTION raise_{table}_append_only()
                RETURNS trigger AS $$
                BEGIN
                    RAISE EXCEPTION 'append-only: {table}';
                END;
                $$ LANGUAGE plpgsql;
                """)
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_update
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION raise_{table}_append_only();
                """)
            op.execute(f"""
                CREATE TRIGGER trg_{table}_no_delete
                BEFORE DELETE ON {table}
                FOR EACH ROW EXECUTE FUNCTION raise_{table}_append_only();
                """)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    if dialect == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS trg_approval_decisions_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_approval_decisions_no_update")
        op.execute("DROP TRIGGER IF EXISTS trg_approval_requests_no_delete")
        op.execute("DROP TRIGGER IF EXISTS trg_approval_requests_no_update")
    elif dialect == "postgresql":
        for table in ("approval_decisions", "approval_requests"):
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_delete ON {table}")
            op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_no_update ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS raise_{table}_append_only()")

    op.drop_index(
        op.f("ix_approval_decisions_tenant_id_outcome_created_at"),
        table_name="approval_decisions",
    )
    op.drop_table("approval_decisions")
    op.drop_index(
        op.f("ix_approval_requests_proposal_id"),
        table_name="approval_requests",
    )
    op.drop_index(
        op.f("ix_approval_requests_tenant_id_created_at"),
        table_name="approval_requests",
    )
    op.drop_table("approval_requests")
