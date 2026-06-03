"""authorized_senders — add the bot-channel privilege ``role`` column

Slice ``mcp-hitl-approvals`` (the deferred "slice O1 follow-up" noted on
:class:`IncomingCommand`). Adds ``authorized_senders.role`` so the MCP
HITL adapter can resolve the operator's privilege **from the database**
(never the request payload):

* ``NOT NULL DEFAULT 'user'`` — existing rows backfill to ``'user'``
  (deny-by-default for privileged actions).
* ``CHECK (role IN ('user','owner'))`` — ``'owner'`` is the tenant
  operator; the adapter maps ``owner -> IncomingCommand.role='admin'`` so
  the existing per-command ``required_role`` gate enforces owner-only.

SQLite cannot ``ALTER`` to add a CHECK in place — Alembic's
``batch_alter_table`` (``render_as_batch=True`` in env.py) rewrites the
table, copying rows through. The bare constraint name re-resolves via the
project naming convention to ``ck_authorized_senders_role_allowed``
(mirrors 0034).

Revision ID: 0036_authorized_senders_role
Revises: 0035_trading_whitelist_l2_triggers
Created at: 2026-06-03T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0036_authorized_senders_role"
down_revision: str | None = "0035_trading_whitelist_l2_triggers"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLE_CHECK = "role IN ('user','owner')"


def upgrade() -> None:
    with op.batch_alter_table("authorized_senders") as batch_op:
        batch_op.add_column(
            sa.Column(
                "role",
                sa.Text(),
                nullable=False,
                server_default="user",
            )
        )
        batch_op.create_check_constraint("role_allowed", _ROLE_CHECK)


def downgrade() -> None:
    with op.batch_alter_table("authorized_senders") as batch_op:
        batch_op.drop_constraint("role_allowed", type_="check")
        batch_op.drop_column("role")
