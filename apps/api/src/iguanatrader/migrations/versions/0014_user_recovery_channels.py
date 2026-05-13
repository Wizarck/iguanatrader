"""user recovery channels — telegram_chat_id + whatsapp_phone

Slice ``auth-forgot-password-flow`` task 1. Adds two nullable columns to
``users`` so the forgot-password endpoint can fan a temporary credential
out to whichever recovery channels the operator opted into:

* ``telegram_chat_id`` VARCHAR(64) NULL — operator-set chat id for the
  ``Recipient(channel='telegram', address=<chat_id>)`` shape. The 64-char
  ceiling matches Telegram's bot API which uses int64 ids stringified.
* ``whatsapp_phone`` VARCHAR(32) NULL — operator-set E.164 phone number
  (``+<cc><subscriber>``). 32 chars covers the longest legal E.164 with
  room for future format drift.

Both are opt-in: NULL means "do not fan out to this channel for this
user". Email is the always-on channel (the existing ``users.email``
column is NOT NULL since the slice-3 schema).

There is no UI in this slice to manage these values — the operator sets
them via SQL or a future admin CLI. Surfacing a per-user settings page
is intentionally out of scope (see proposal §Out of scope).

SQLite can ``ALTER TABLE ADD COLUMN`` directly; we still use
``batch_alter_table`` to match the project's slice-3 convention
(``render_as_batch=True`` in env.py).

Revision ID: 0014_user_recovery_channels
Revises: 0013_user_password_metadata
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_user_recovery_channels"
down_revision: str | None = "0013_user_password_metadata"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "telegram_chat_id",
                sa.String(length=64),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "whatsapp_phone",
                sa.String(length=32),
                nullable=True,
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("whatsapp_phone")
        batch_op.drop_column("telegram_chat_id")
