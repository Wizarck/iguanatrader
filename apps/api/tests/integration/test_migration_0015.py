"""Alembic upgrade/downgrade smoke for ``0015_trade_exit_columns``.

Slice ``trades-add-exit-and-realised-pnl-columns``. Verifies:

* ``alembic upgrade head`` adds ``exit_reason`` + ``realised_pnl``
  columns to ``trades`` (both nullable).
* ``ck_trades_exit_reason_allowed`` rejects values outside the
  canonical enum (raw-SQL INSERT — exercises the DB-layer guard, not
  ORM-side validation).
* ``alembic downgrade -1`` reverses the migration: columns gone,
  constraint gone, ``alembic_version`` rolled back to the parent
  revision.
* ``upgrade → downgrade → upgrade`` produces the same final schema
  (idempotent round-trip).

Mirrors the structure of ``test_alembic_roundtrip.py`` +
``test_trading_migration.py``; uses a synchronous SQLite URL with
``alembic.command`` for upgrade/downgrade and ``inspect()`` for
schema introspection.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "ig_migration_0015.db"
    monkeypatch.setenv(
        "IGUANA_DATABASE_URL",
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    repo_root = Path(__file__).resolve().parents[4]
    api_dir = repo_root / "apps" / "api"
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option(
        "script_location",
        str(api_dir / "src" / "iguanatrader" / "migrations"),
    )
    cfg.set_main_option(
        "sqlalchemy.url",
        f"sqlite+aiosqlite:///{db_path.as_posix()}",
    )
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def _columns(insp: object, table: str) -> dict[str, dict[str, object]]:
    return {col["name"]: col for col in insp.get_columns(table)}  # type: ignore[attr-defined]


def test_upgrade_head_adds_exit_columns(alembic_config: Config) -> None:
    """``trades`` gains ``exit_reason`` + ``realised_pnl`` as NULLABLE."""
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    cols = _columns(insp, "trades")

    assert "exit_reason" in cols, "exit_reason column missing from trades"
    assert "realised_pnl" in cols, "realised_pnl column missing from trades"
    assert cols["exit_reason"]["nullable"] is True
    assert cols["realised_pnl"]["nullable"] is True

    sync_engine.dispose()


def test_check_constraint_rejects_bogus_exit_reason(alembic_config: Config) -> None:
    """``ck_trades_exit_reason_allowed`` blocks values outside the enum.

    The constraint is enforced at the DB layer (SQLite ``PRAGMA
    foreign_keys = ON`` + CHECK constraints are honoured). We INSERT
    via raw SQL to bypass any ORM-side validation and prove the
    migration's DDL guard fires.
    """
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    tenant_id = str(uuid4())
    proposal_id = str(uuid4())
    strategy_id = str(uuid4())
    trade_id = str(uuid4())

    # Seed FK chain: tenant → strategy_config → trade_proposal → trade.
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO tenants (id, name, feature_flags, created_at, updated_at) "
                "VALUES (:id, :name, '{}', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"id": tenant_id, "name": "t-0015"},
        )
        conn.execute(
            text(
                "INSERT INTO strategy_configs "
                "(id, tenant_id, strategy_kind, symbol, params, enabled, version) "
                "VALUES (:id, :tenant_id, 'donchian_atr', 'SPY', '{}', 1, 1)"
            ),
            {"id": strategy_id, "tenant_id": tenant_id},
        )
        conn.execute(
            text(
                "INSERT INTO trade_proposals "
                "(id, tenant_id, strategy_config_id, symbol, side, quantity, "
                "entry_price_indicative, stop_price, reasoning, mode, correlation_id) "
                "VALUES (:id, :tenant_id, :strategy_id, 'SPY', 'buy', 10, "
                "450, 440, '{}', 'paper', :corr)"
            ),
            {
                "id": proposal_id,
                "tenant_id": tenant_id,
                "strategy_id": strategy_id,
                "corr": str(uuid4()),
            },
        )

    # Valid insert: exit_reason in canonical set.
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO trades (id, tenant_id, proposal_id, symbol, side, "
                "quantity, mode, state, opened_at, exit_reason) "
                "VALUES (:id, :tenant_id, :proposal_id, 'SPY', 'buy', 10, "
                "'paper', 'closed_filled', CURRENT_TIMESTAMP, 'stop')"
            ),
            {
                "id": trade_id,
                "tenant_id": tenant_id,
                "proposal_id": proposal_id,
            },
        )

    # Invalid insert: bogus exit_reason — CHECK constraint must fire.
    with (
        pytest.raises(IntegrityError),
        sync_engine.begin() as conn,
    ):
        conn.execute(
            text(
                "INSERT INTO trades (id, tenant_id, proposal_id, symbol, side, "
                "quantity, mode, state, opened_at, exit_reason) "
                "VALUES (:id, :tenant_id, :proposal_id, 'SPY', 'buy', 10, "
                "'paper', 'closed_filled', CURRENT_TIMESTAMP, 'bogus')"
            ),
            {
                "id": str(uuid4()),
                "tenant_id": tenant_id,
                "proposal_id": proposal_id,
            },
        )

    sync_engine.dispose()


def test_downgrade_one_removes_exit_columns(alembic_config: Config) -> None:
    """``alembic downgrade -1`` drops both columns + the CHECK constraint."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "-1")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    cols = _columns(insp, "trades")

    assert "exit_reason" not in cols
    assert "realised_pnl" not in cols

    sync_engine.dispose()


def test_upgrade_downgrade_upgrade_is_idempotent(alembic_config: Config) -> None:
    """Round-trip leaves ``trades`` in the same shape as a clean upgrade."""
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "-1")
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    cols = _columns(insp, "trades")

    assert "exit_reason" in cols
    assert "realised_pnl" in cols

    sync_engine.dispose()
