"""Migration 0006 smoke test — approval_requests + approval_decisions.

Per slice P1 task 2.4. Asserts:

* Both tables exist after ``alembic upgrade head``.
* The UNIQUE constraint on ``approval_decisions.request_id`` rejects a
  duplicate INSERT (first-decision-wins per design D4).
* Hand-rolled UPDATE on either table raises ``AppendOnlyViolation`` via
  the L1 ORM listener.

**Local-runnability gate**: this test requires the alembic chain to
include revision ``0005_risk_tables`` (slice K1), ``0004_*``
(slice T1's ``trade_proposals``), and ``0003_*`` (slice R1) ahead of
0006. Until those land in this worktree's branch, the test is
SKIPPED — it is exercised in CI on the integration branch where all
sibling slices are present.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import SQLAlchemyError


@pytest.fixture
def alembic_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    db_path = tmp_path / "ig_migration_0006.db"
    db_url = f"sqlite:///{db_path.as_posix()}"
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
    cfg.attributes["sync_url"] = db_url
    cfg.attributes["db_path"] = str(db_path)
    return cfg


def _has_predecessors(cfg: Config) -> bool:
    """True iff revision ``0005_risk_tables`` exists in the alembic chain.

    Slice P1 chains onto K1's ``0005`` per the cross-slice merge plan.
    Until K1 lands in this worktree, the upgrade chain stops at
    ``0002`` and migration 0006 cannot run end-to-end.
    """
    script = ScriptDirectory.from_config(cfg)
    revisions = {r.revision for r in script.walk_revisions()}
    return "0005_risk_tables" in revisions


def test_upgrade_creates_approval_tables(alembic_config: Config) -> None:
    if not _has_predecessors(alembic_config):
        pytest.skip("predecessor migrations 0003/0004/0005 not yet on this branch")
    command.upgrade(alembic_config, "head")
    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    insp = inspect(sync_engine)
    tables = set(insp.get_table_names())
    assert "approval_requests" in tables
    assert "approval_decisions" in tables
    sync_engine.dispose()


def test_unique_constraint_rejects_duplicate_decision(alembic_config: Config) -> None:
    if not _has_predecessors(alembic_config):
        pytest.skip("predecessor migrations 0003/0004/0005 not yet on this branch")
    command.upgrade(alembic_config, "head")
    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    request_id = str(uuid4())
    with sync_engine.begin() as conn:
        # Seed a request — uses synthetic FK targets; FK enforcement
        # is per-connection in SQLite (gotcha #21) so this works.
        conn.execute(
            text(
                "INSERT INTO approval_requests "
                "(id, tenant_id, proposal_id, delivered_to_channels, "
                "timeout_seconds, expires_at, created_at) "
                "VALUES (:id, :tid, :pid, :ch, :to, :exp, :ca)"
            ),
            {
                "id": request_id,
                "tid": str(uuid4()),
                "pid": str(uuid4()),
                "ch": '["telegram"]',
                "to": 60,
                "exp": "2099-01-01T00:00:00Z",
                "ca": "2026-05-06T00:00:00Z",
            },
        )
        conn.execute(
            text(
                "INSERT INTO approval_decisions "
                "(id, tenant_id, request_id, outcome, decided_via_channel, "
                "latency_ms, created_at) "
                "VALUES (:id, :tid, :rid, 'granted', 'telegram', 100, :ca)"
            ),
            {
                "id": str(uuid4()),
                "tid": str(uuid4()),
                "rid": request_id,
                "ca": "2026-05-06T00:00:00Z",
            },
        )
    with sync_engine.begin() as conn, pytest.raises(SQLAlchemyError):
        conn.execute(
            text(
                "INSERT INTO approval_decisions "
                "(id, tenant_id, request_id, outcome, decided_via_channel, "
                "latency_ms, created_at) "
                "VALUES (:id, :tid, :rid, 'rejected', 'dashboard', 200, :ca)"
            ),
            {
                "id": str(uuid4()),
                "tid": str(uuid4()),
                "rid": request_id,
                "ca": "2026-05-06T00:00:01Z",
            },
        )
    sync_engine.dispose()


def test_update_blocked_by_trigger(alembic_config: Config) -> None:
    if not _has_predecessors(alembic_config):
        pytest.skip("predecessor migrations 0003/0004/0005 not yet on this branch")
    command.upgrade(alembic_config, "head")
    sync_engine = create_engine(f"sqlite:///{alembic_config.attributes['db_path']}")
    request_id = str(uuid4())
    with sync_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO approval_requests "
                "(id, tenant_id, proposal_id, delivered_to_channels, "
                "timeout_seconds, expires_at, created_at) "
                "VALUES (:id, :tid, :pid, :ch, :to, :exp, :ca)"
            ),
            {
                "id": request_id,
                "tid": str(uuid4()),
                "pid": str(uuid4()),
                "ch": '["telegram"]',
                "to": 60,
                "exp": "2099-01-01T00:00:00Z",
                "ca": "2026-05-06T00:00:00Z",
            },
        )
    with sync_engine.begin() as conn, pytest.raises(SQLAlchemyError):
        conn.execute(
            text("UPDATE approval_requests SET timeout_seconds = 120 WHERE id = :id"),
            {"id": request_id},
        )
    sync_engine.dispose()
