"""rename users.role CHECK to single-seat MVP RBAC

Slice 4 (``auth-jwt-cookie``) refines RBAC to the 2-level model
documented in ``docs/personas-jtbd.md`` §RBAC Matrix (refined 2026-05-05):

* ``tenant_user`` — single seat per tenant; replaces the legacy ``admin``.
* ``god_admin`` — platform-level cross-tenant; replaces the legacy ``user``
  (read-only secondary, "not used in MVP"). god_admin is reserved for
  forward-compat — no User row carries ``role = god_admin`` in MVP/v2
  (god-admin auth is via separate path).

Slice 3's migration ``0001`` shipped CHECK ``role IN ('admin','user')``;
this migration renames to ``role IN ('tenant_user','god_admin')`` and
migrates any existing rows.

SQLite cannot ``ALTER`` a CHECK constraint in place — Alembic's
``batch_alter_table`` transparently rewrites the table, copying rows
through. Per slice 3 design D6 (``render_as_batch=True`` in env.py),
this is the standard pattern for SQLite schema changes.

Revision ID: 0002
Revises: 0001
Created at: 2026-05-05T00:00:00Z
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Migrate existing rows first. Most envs at slice-4-time will have 0
    # rows (slice 3 just landed; no production users yet) but be defensive
    # against any test fixtures that seeded the old names.
    op.execute("UPDATE users SET role = 'tenant_user' WHERE role = 'admin'")
    op.execute("UPDATE users SET role = 'god_admin' WHERE role = 'user'")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role_allowed", type_="check")
        batch_op.create_check_constraint(
            "role_allowed",
            "role IN ('tenant_user','god_admin')",
        )


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'tenant_user'")
    op.execute("UPDATE users SET role = 'user' WHERE role = 'god_admin'")

    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_role_allowed", type_="check")
        batch_op.create_check_constraint(
            "role_allowed",
            "role IN ('admin','user')",
        )
