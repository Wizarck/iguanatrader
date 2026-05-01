"""Alembic environment — async-aware + naming-convention propagation.

Per design D6 (slice 3): the env reads ``IGUANA_DATABASE_URL`` from the
environment, defaulting to a local SQLite file. ``target_metadata`` is set to
the project ``Base.metadata`` so autogenerate respects the naming convention
(D4) and produces stable, reviewable diffs across machines and engines.

Configuration:

- ``compare_type=True`` — catches type changes that Alembic 1.x defaults to
  ignoring.
- ``render_as_batch=True`` — works around SQLite's lack of full ``ALTER TABLE``
  by emitting copy-and-rename for column changes.
- ``transaction_per_migration=True`` — each migration runs in its own
  transaction so partial failures don't leave a half-applied schema.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from iguanatrader.persistence.base import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

_DEFAULT_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"


def _resolve_url() -> str:
    """Resolve the DB URL: env var wins, then alembic.ini, then default."""
    env_url = os.environ.get("IGUANA_DATABASE_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    return _DEFAULT_URL


def run_migrations_offline() -> None:
    """Render migrations as SQL without a live DB connection.

    Used by ``alembic upgrade head --sql`` to produce a SQL script for ops
    review, or for environments where the migrator cannot reach the DB.
    """
    url = _resolve_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        render_as_batch=url.startswith("sqlite"),
        transaction_per_migration=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=connection.engine.dialect.name == "sqlite",
        transaction_per_migration=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations with a live async DB connection."""
    url = _resolve_url()
    config.set_main_option("sqlalchemy.url", url)

    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
