"""Alembic upgrade/downgrade smoke for the trading-context migration.

Per design D5: ``0003_trading_tables`` requires R1's
``0002_research_tables`` migration to be present in the ``versions/``
directory; absence raises ``RevisionError`` (or similar) at
``alembic upgrade head``. The CI gate fails the slice-T1 PR until R1
is rebased in.

Slice T1 acceptance: this test runs locally only when R1's migration
is on the branch. CI handles the cross-slice integration; the test is
skipped here when the parent revision is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


def _versions_dir() -> Path:
    repo_root = Path(__file__).resolve().parents[5]
    return repo_root / "apps" / "api" / "src" / "iguanatrader" / "migrations" / "versions"


def _r1_migration_present() -> bool:
    """Detect R1's ``0002_research_tables`` migration in ``versions/``."""
    versions = _versions_dir()
    if not versions.exists():
        return False
    return any(p.name.startswith("0002_research_tables") for p in versions.iterdir())


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "ig_trading_migration.db"
    monkeypatch.setenv("IGUANA_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    repo_root = Path(__file__).resolve().parents[5]
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


def test_r1_migration_required_for_upgrade(alembic_config: Config) -> None:
    """Without R1's migration in ``versions/``, ``upgrade head`` fails.

    Per design D5 the ``down_revision='0002_research_tables'`` is the
    explicit merge-order anchor; alembic refuses to walk past a missing
    parent revision.
    """
    if _r1_migration_present():
        pytest.skip(
            "R1 migration present locally — merge-order gate cannot be exercised "
            "without temporarily removing 0002_research_tables.py from versions/"
        )

    with pytest.raises(Exception):  # noqa: B017 — alembic raises one of several internal types
        # Loading the script directory walks the chain and surfaces the
        # missing-revision error (alembic.util.exc.CommandError or similar).
        ScriptDirectory.from_config(alembic_config).walk_revisions()


def test_upgrade_head_creates_trading_tables_when_chain_is_complete(
    alembic_config: Config,
) -> None:
    """When R1 is on the branch, ``upgrade head`` creates the 6 tables."""
    if not _r1_migration_present():
        pytest.skip(
            "R1 migration not yet on branch; merge order requires R1 first "
            "(documented in design D5)."
        )

    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    table_names = set(insp.get_table_names())

    expected = {
        "strategy_configs",
        "trade_proposals",
        "trades",
        "orders",
        "fills",
        "equity_snapshots",
    }
    assert expected.issubset(table_names), f"missing trading tables: {expected - table_names}"

    fks = insp.get_foreign_keys("trade_proposals")
    fk_names = {fk["name"] for fk in fks}
    assert "fk_trade_proposals_research_brief_id_research_briefs" in fk_names

    sync_engine.dispose()


def test_downgrade_one_drops_trading_tables(alembic_config: Config) -> None:
    """``alembic downgrade -1`` removes the 6 trading tables."""
    if not _r1_migration_present():
        pytest.skip("R1 migration not yet on branch")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "-1")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    table_names = set(insp.get_table_names())
    trading_tables = {
        "strategy_configs",
        "trade_proposals",
        "trades",
        "orders",
        "fills",
        "equity_snapshots",
    }
    assert table_names.isdisjoint(trading_tables), "trading tables not dropped on downgrade"
    sync_engine.dispose()


def test_upgrade_head_idempotent_after_downgrade_upgrade_cycle(
    alembic_config: Config,
) -> None:
    """upgrade head → downgrade -1 → upgrade head produces the same schema."""
    if not _r1_migration_present():
        pytest.skip("R1 migration not yet on branch")

    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "-1")
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    table_names = set(insp.get_table_names())
    expected = {
        "strategy_configs",
        "trade_proposals",
        "trades",
        "orders",
        "fills",
        "equity_snapshots",
    }
    assert expected.issubset(table_names)
    sync_engine.dispose()
