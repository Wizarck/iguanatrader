"""Migration 0036 — ``authorized_senders.role`` (slice ``mcp-hitl-approvals``).

Proves the column is added ``NOT NULL DEFAULT 'user'`` with a
``CHECK (role IN ('user','owner'))``, that pre-existing rows backfill to
``'user'`` (deny-by-default), and that the migration round-trips.

Raw ``sqlite3`` inserts run with foreign-key enforcement off (SQLite's
default for a bare connection), so a sender row needs no parent tenant —
the CHECK constraint is still enforced regardless.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

_PREV = "0035_trading_whitelist_l2_triggers"
_THIS = "0036_authorized_senders_role"


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "ig_migration_0036.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
    monkeypatch.setenv("IGUANA_DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    repo_root = Path(__file__).resolve().parents[5]
    api_dir = repo_root / "apps" / "api"
    cfg = Config(str(api_dir / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_dir / "src" / "iguanatrader" / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{db_path.as_posix()}")
    cfg.attributes["sync_url"] = db_url
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def _insert_sender(db_path: str, *, external_id: str, role: str | None = None) -> None:
    conn = sqlite3.connect(db_path)
    try:
        cols = ["id", "tenant_id", "channel", "external_id"]
        vals: list[str] = [str(uuid4()), str(uuid4()), "telegram", external_id]
        if role is not None:
            cols.append("role")
            vals.append(role)
        placeholders = ",".join("?" for _ in vals)
        conn.execute(
            f"INSERT INTO authorized_senders ({','.join(cols)}) VALUES ({placeholders})",
            vals,
        )
        conn.commit()
    finally:
        conn.close()


def _role_of(db_path: str, external_id: str) -> str | None:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT role FROM authorized_senders WHERE external_id = ?",
            (external_id,),
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else str(row[0])


def test_upgrade_adds_role_column_not_null(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    eng = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(eng)
    cols = {c["name"]: c for c in insp.get_columns("authorized_senders")}
    assert "role" in cols
    assert cols["role"]["nullable"] is False
    eng.dispose()


def test_existing_row_backfills_to_user(alembic_config: Config) -> None:
    command.upgrade(alembic_config, _PREV)
    db_path = alembic_config.attributes["db_path"]
    _insert_sender(db_path, external_id="pre-existing")  # no role column yet
    command.upgrade(alembic_config, _THIS)
    assert _role_of(db_path, "pre-existing") == "user"


def test_default_is_user_when_role_omitted(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    db_path = alembic_config.attributes["db_path"]
    _insert_sender(db_path, external_id="defaulted")
    assert _role_of(db_path, "defaulted") == "user"


def test_check_accepts_owner_and_rejects_unknown(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    db_path = alembic_config.attributes["db_path"]
    _insert_sender(db_path, external_id="the-owner", role="owner")  # accepted
    assert _role_of(db_path, "the-owner") == "owner"
    with pytest.raises(sqlite3.IntegrityError):
        _insert_sender(db_path, external_id="bad-role", role="bogus")


def test_downgrade_removes_then_reupgrade_restores(alembic_config: Config) -> None:
    command.upgrade(alembic_config, "head")
    command.downgrade(alembic_config, _PREV)
    eng = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    cols = {c["name"] for c in inspect(eng).get_columns("authorized_senders")}
    eng.dispose()
    assert "role" not in cols

    command.upgrade(alembic_config, "head")
    eng2 = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    cols2 = {c["name"] for c in inspect(eng2).get_columns("authorized_senders")}
    eng2.dispose()
    assert "role" in cols2
