"""user password metadata — must_change_password + password_changed_at

Slice ``auth-change-password`` task 1. Adds two columns to ``users``:

* ``must_change_password`` BOOLEAN NOT NULL DEFAULT FALSE — admin/operator
  hands out provisional credentials; the gate middleware blocks all routes
  except change-password/logout/me until the user rotates the password.
* ``password_changed_at`` TIMESTAMP NULL — set to ``func.now()`` on every
  successful hash write (bootstrap, change, future force-reset / forgot).
  Useful for audit + future "password too old" policies.

SQLite can ``ALTER TABLE ADD COLUMN`` directly; we still use
``batch_alter_table`` to match the project's slice-3 convention
(``render_as_batch=True`` in env.py).

Revision ID: 0013_user_password_metadata
Revises: 0012_market_data_tables
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_user_password_metadata"
down_revision: str | None = "0012_market_data_tables"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "must_change_password",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "password_changed_at",
                sa.DateTime(timezone=True),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("password_changed_at")
        batch_op.drop_column("must_change_password")
