"""Read-only LIVE-readiness doctor checks (prevention gate B).

Each pure check is exercised across OK / WARN / FAIL / SKIP, plus the severity
aggregation. The check functions take their dependencies as args, so no live
gateway or database is needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

import pytest
from iguanatrader.cli.doctor import (
    CheckResult as _CheckResult,
)
from iguanatrader.cli.doctor import (
    CheckStatus,
    check_contract_routing,
    check_env_presence,
    check_ephemeral_live_consistency,
    check_kill_switch,
    check_live_account_not_paper,
    check_paper_history,
    check_pending_backlog,
    check_watchlist_config_consistency,
    worst_status,
)
from iguanatrader.cli.trading import app
from iguanatrader.contexts.trading.brokers.symbol_contract import ContractParams
from iguanatrader.shared.time import now as utc_now
from typer.testing import CliRunner


@dataclass
class _Cfg:
    symbol: str
    enabled: bool = True


# ----------------------------------------------------------------------
# env / ephemeral-live consistency
# ----------------------------------------------------------------------


def test_env_live_without_account_code_fails() -> None:
    r = check_env_presence(mode="live", env={"IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS": "AAPL"})
    assert r.status is CheckStatus.FAIL
    assert "ACCOUNT_CODE" in r.detail


def test_env_missing_watchlist_warns() -> None:
    r = check_env_presence(mode="paper", env={})
    assert r.status is CheckStatus.WARN
    assert "WATCHLIST" in r.detail


def test_env_all_present_ok() -> None:
    r = check_env_presence(
        mode="live",
        env={
            "IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS": "AAPL,MSFT",
            "IGUANATRADER_IBKR_ACCOUNT_CODE": "U123",
        },
    )
    assert r.status is CheckStatus.OK


def test_ephemeral_disabled_skips() -> None:
    assert check_ephemeral_live_consistency(mode="live", env={}).status is CheckStatus.SKIP
    assert (
        check_ephemeral_live_consistency(
            mode="paper", env={"IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED": "on"}
        ).status
        is CheckStatus.SKIP
    )


def test_ephemeral_enabled_without_native_bracket_fails() -> None:
    r = check_ephemeral_live_consistency(
        mode="live",
        env={
            "IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED": "on",
            "ELIGIA_GATEWAY_WEBHOOK_URL": "https://x",
            "ELIGIA_GATEWAY_HMAC_SECRET": "s",
        },
    )
    assert r.status is CheckStatus.FAIL
    assert "NATIVE_BRACKET" in r.detail


def test_ephemeral_enabled_missing_creds_fails() -> None:
    r = check_ephemeral_live_consistency(
        mode="live",
        env={
            "IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED": "on",
            "IGUANATRADER_NATIVE_BRACKET": "on",
        },
    )
    assert r.status is CheckStatus.FAIL
    assert "WEBHOOK_URL" in r.detail or "HMAC_SECRET" in r.detail


def test_ephemeral_fully_consistent_ok() -> None:
    r = check_ephemeral_live_consistency(
        mode="live",
        env={
            "IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED": "on",
            "IGUANATRADER_NATIVE_BRACKET": "on",
            "ELIGIA_GATEWAY_WEBHOOK_URL": "https://x",
            "ELIGIA_GATEWAY_HMAC_SECRET": "s",
        },
    )
    assert r.status is CheckStatus.OK


# ----------------------------------------------------------------------
# live account is not a paper (DU/DF) account
# ----------------------------------------------------------------------


def test_live_account_paper_code_fails() -> None:
    # DUR071858 is the paper account the live daemon must never be armed against.
    r = check_live_account_not_paper(
        mode="live", env={"IGUANATRADER_IBKR_ACCOUNT_CODE": "DUR071858"}
    )
    assert r.status is CheckStatus.FAIL
    assert "PAPER" in r.detail


def test_live_account_live_code_ok() -> None:
    r = check_live_account_not_paper(
        mode="live", env={"IGUANATRADER_IBKR_ACCOUNT_CODE": "U1234567"}
    )
    assert r.status is CheckStatus.OK


def test_live_account_paper_mode_skips() -> None:
    r = check_live_account_not_paper(mode="paper", env={"IGUANATRADER_IBKR_ACCOUNT_CODE": "DU1"})
    assert r.status is CheckStatus.SKIP


def test_live_account_unset_defers_to_env_check() -> None:
    # Unset code is FAILed by check_env_presence; this check SKIPs to avoid a
    # duplicate failure line.
    r = check_live_account_not_paper(mode="live", env={})
    assert r.status is CheckStatus.SKIP


# ----------------------------------------------------------------------
# watchlist ↔ configs
# ----------------------------------------------------------------------


def test_watchlist_config_match_ok() -> None:
    r = check_watchlist_config_consistency(
        watchlist=["AAPL", "MSFT"], configs=[_Cfg("AAPL"), _Cfg("MSFT")]
    )
    assert r.status is CheckStatus.OK


def test_watchlist_orphans_both_directions_warn() -> None:
    r = check_watchlist_config_consistency(
        watchlist=["AAPL", "TSLA"],  # TSLA has no config
        configs=[_Cfg("AAPL"), _Cfg("NVDA"), _Cfg("DISABLED", enabled=False)],
    )
    assert r.status is CheckStatus.WARN
    joined = " ".join(r.items)
    assert "TSLA" in joined  # watchlist symbol w/o config
    assert "NVDA" in joined  # enabled config not in watchlist
    assert "DISABLED" not in joined  # disabled configs don't count


# ----------------------------------------------------------------------
# contract routing (CRUD-on-LSE / currency-guess class)
# ----------------------------------------------------------------------


def test_contract_routing_all_default_ok() -> None:
    r = check_contract_routing(
        symbols=["AAPL", "MSFT"],
        resolve=lambda s: ContractParams(exchange="SMART", currency="USD", con_id=None),
    )
    assert r.status is CheckStatus.OK
    assert "2 default" in r.detail or "default (2)" in " ".join(r.items)


def test_contract_routing_override_with_conid_ok() -> None:
    table = {
        "SGLN": ContractParams(exchange="LSEETF", currency="GBP", con_id=123456),
        "AAPL": ContractParams(exchange="SMART", currency="USD", con_id=None),
    }
    r = check_contract_routing(symbols=["SGLN", "AAPL"], resolve=lambda s: table[s.upper()])
    assert r.status is CheckStatus.OK
    assert "conId=123456" in " ".join(r.items)


def test_contract_routing_override_without_conid_warns() -> None:
    # An explicit non-US routing WITHOUT a conId is the currency-guess landmine.
    r = check_contract_routing(
        symbols=["SGLN"],
        resolve=lambda s: ContractParams(exchange="LSEETF", currency="GBP", con_id=None),
    )
    assert r.status is CheckStatus.WARN
    assert "conId" in r.detail


# ----------------------------------------------------------------------
# DB-backed checks (fake repos)
# ----------------------------------------------------------------------


class _AuditRepo:
    def __init__(self, *, exists: bool) -> None:
        self._exists = exists

    async def event_exists(self, event: str) -> bool:
        return self._exists


class _RiskRepo:
    def __init__(self, *, active: bool) -> None:
        self._active = active

    async def load_kill_switch_state(self, tenant_id: object) -> bool:
        return self._active


@dataclass
class _PendingRow:
    expires_at: object


class _ApprovalRepo:
    def __init__(self, rows: list[_PendingRow]) -> None:
        self._rows = rows

    async def list_pending(self) -> list[_PendingRow]:
        return list(self._rows)


@pytest.mark.asyncio
async def test_paper_history_skip_for_paper() -> None:
    r = await check_paper_history(mode="paper", audit_repo=_AuditRepo(exists=False))
    assert r.status is CheckStatus.SKIP


@pytest.mark.asyncio
async def test_paper_history_live_with_history_ok() -> None:
    r = await check_paper_history(mode="live", audit_repo=_AuditRepo(exists=True))
    assert r.status is CheckStatus.OK


@pytest.mark.asyncio
async def test_paper_history_live_without_history_warns() -> None:
    r = await check_paper_history(mode="live", audit_repo=_AuditRepo(exists=False))
    assert r.status is CheckStatus.WARN


@pytest.mark.asyncio
async def test_kill_switch_active_fails() -> None:
    r = await check_kill_switch(tenant_id=uuid4(), risk_repo=_RiskRepo(active=True))
    assert r.status is CheckStatus.FAIL


@pytest.mark.asyncio
async def test_kill_switch_inactive_ok() -> None:
    r = await check_kill_switch(tenant_id=uuid4(), risk_repo=_RiskRepo(active=False))
    assert r.status is CheckStatus.OK


@pytest.mark.asyncio
async def test_pending_backlog_empty_ok() -> None:
    r = await check_pending_backlog(approval_repo=_ApprovalRepo([]), now=utc_now())
    assert r.status is CheckStatus.OK


@pytest.mark.asyncio
async def test_pending_backlog_expired_warns() -> None:
    now = utc_now()
    rows = [
        _PendingRow(expires_at=now - timedelta(hours=1)),
        _PendingRow(expires_at=now + timedelta(hours=1)),
    ]
    r = await check_pending_backlog(approval_repo=_ApprovalRepo(rows), now=now)
    assert r.status is CheckStatus.WARN
    assert "PAST expiry" in r.detail


# ----------------------------------------------------------------------
# aggregation
# ----------------------------------------------------------------------


def test_worst_status_orders_fail_over_warn_over_ok() -> None:
    def mk(status: CheckStatus) -> _CheckResult:
        return _CheckResult(name="x", status=status, detail="")

    assert worst_status([mk(CheckStatus.OK), mk(CheckStatus.WARN)]) is CheckStatus.WARN
    assert worst_status([mk(CheckStatus.WARN), mk(CheckStatus.FAIL)]) is CheckStatus.FAIL
    assert worst_status([mk(CheckStatus.OK), mk(CheckStatus.SKIP)]) is CheckStatus.SKIP
    assert worst_status([mk(CheckStatus.OK)]) is CheckStatus.OK


# ----------------------------------------------------------------------
# command wiring (typer)
# ----------------------------------------------------------------------


def test_doctor_command_is_registered_and_help_works() -> None:
    result = CliRunner().invoke(app, ["doctor", "--help"])
    assert result.exit_code == 0
    assert "--connect" in result.output
    assert "--mode" in result.output
