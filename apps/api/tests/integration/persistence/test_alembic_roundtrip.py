"""Alembic upgrade/downgrade round-trip — proves the first migration is reversible."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "ig_alembic_roundtrip.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("IGUANA_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    repo_root = Path(__file__).resolve().parents[5]
    api_dir = repo_root / "apps" / "api"
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "src" / "iguanatrader" / "migrations"))
    cfg.set_main_option(
        "sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}"
    )
    cfg.attributes["sync_url"] = db_url
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def test_upgrade_head_creates_three_tables(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    user_tables = set(insp.get_table_names()) - {"alembic_version"}
    assert user_tables == {"tenants", "users", "authorized_senders"}
    sync_engine.dispose()


def test_constraint_naming_convention_applied(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)

    # Primary keys.
    for table in ("tenants", "users", "authorized_senders"):
        pk = insp.get_pk_constraint(table)
        assert pk["name"] == f"pk_{table}", f"PK name mismatch for {table}: {pk['name']!r}"

    # Foreign keys.
    user_fks = insp.get_foreign_keys("users")
    assert len(user_fks) == 1
    assert user_fks[0]["name"] == "fk_users_tenant_id_tenants"

    sender_fks = insp.get_foreign_keys("authorized_senders")
    assert len(sender_fks) == 1
    assert sender_fks[0]["name"] == "fk_authorized_senders_tenant_id_tenants"

    # Unique constraints.
    user_uqs = insp.get_unique_constraints("users")
    assert any(uq["name"] == "uq_users_tenant_id" for uq in user_uqs)

    sender_uqs = insp.get_unique_constraints("authorized_senders")
    assert any(uq["name"] == "uq_authorized_senders_tenant_id" for uq in sender_uqs)

    # Index on users.tenant_id.
    user_ix = insp.get_indexes("users")
    assert any(ix["name"] == "ix_users_tenant_id" for ix in user_ix)

    sync_engine.dispose()


def test_downgrade_base_round_trips_to_empty(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, "base")

    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    user_tables = set(insp.get_table_names()) - {"alembic_version"}
    assert user_tables == set()

    # Re-upgrade produces identical schema.
    command.upgrade(alembic_config, "head")
    insp = inspect(sync_engine)
    user_tables_after = set(insp.get_table_names()) - {"alembic_version"}
    assert user_tables_after == {"tenants", "users", "authorized_senders"}

    sync_engine.dispose()
