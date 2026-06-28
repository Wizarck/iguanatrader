"""Read-only LIVE-readiness / config doctor — ``iguanatrader trading doctor``.

Gate B of the recurring-problem prevention system (see the analysis in
``.claude`` + auto-memory). The root cause of nearly every iguanatrader incident
is ONE shape: a gap between "looks done / up / configured" and "verified working
end-to-end against reality", closed manually + reactively at the worst moment.
This command turns that manual diagnosis into ONE automated, READ-ONLY pass run
before every deploy / cutover / live-enable (and usable as a CI / scripting gate
— it exits non-zero if any check FAILs).

It checks the things that have historically failed SILENTLY, against the REAL
database (and, with ``--connect``, the REAL gateway):

* env / config drift from reality (watchlist source, live account code);
* ephemeral-live consistency — the daemon's hard boot guards, surfaced BEFORE
  boot (native brackets ON, coordinator creds present);
* watchlist ↔ ``strategy_configs`` consistency (the "propose iterates the
  watchlist ENV, not strategy_configs" gotcha → orphans both ways);
* per-symbol contract routing (the CRUD-on-LSE / currency-guess class: a non-US
  symbol silently resolving to the SMART/USD default with no conId override);
* paper-trading history before live (#15 gate);
* kill-switch state (a wedged kill-switch silently blocks execution);
* pending-approval backlog (the "173 proposals stuck pending_approval" class);
* broker connectivity + account equity (``--connect`` only).

The check FUNCTIONS are pure (dependencies injected) so they unit-test without a
live gateway; the command (``cli/trading.py::doctor``) wires the real session /
repos / broker and prints the report.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from iguanatrader.contexts.trading.brokers.symbol_contract import (
    DEFAULT_CURRENCY,
    DEFAULT_EXCHANGE,
    ContractParams,
    resolve_contract_params,
)


class CheckStatus(enum.StrEnum):
    """Outcome of one doctor check (ordered worst-last for aggregation)."""

    OK = "ok"
    SKIP = "skip"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class CheckResult:
    """One named check outcome + optional per-item detail lines."""

    name: str
    status: CheckStatus
    detail: str
    items: tuple[str, ...] = field(default_factory=tuple)


def worst_status(results: list[CheckResult]) -> CheckStatus:
    """The most-severe status across ``results`` (FAIL > WARN > SKIP > OK)."""
    order = {CheckStatus.OK: 0, CheckStatus.SKIP: 1, CheckStatus.WARN: 2, CheckStatus.FAIL: 3}
    worst = CheckStatus.OK
    for r in results:
        if order[r.status] > order[worst]:
            worst = r.status
    return worst


# ----------------------------------------------------------------------
# Pure checks (no I/O) — env / config / contract routing
# ----------------------------------------------------------------------


def check_env_presence(*, mode: str, env: dict[str, str]) -> CheckResult:
    """Required env / config for ``mode`` (catches config drift from reality)."""
    problems: list[str] = []
    if not (env.get("IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS") or "").strip():
        problems.append(
            "IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS unset → propose falls back to the "
            "AAPL,MSFT,GOOGL default (propose iterates the watchlist ENV, not strategy_configs)"
        )
    if mode == "live" and not (env.get("IGUANATRADER_IBKR_ACCOUNT_CODE") or "").strip():
        # IBKRBrokerageModel.from_env("live") raises without it → the live daemon
        # cannot even build the broker.
        return CheckResult(
            name="env",
            status=CheckStatus.FAIL,
            detail="live mode requires IGUANATRADER_IBKR_ACCOUNT_CODE (broker build fails without it)",
        )
    if problems:
        return CheckResult(name="env", status=CheckStatus.WARN, detail="; ".join(problems))
    return CheckResult(name="env", status=CheckStatus.OK, detail="required env present")


#: IBKR paper-trading account codes are prefixed ``DU`` (paper individual) /
#: ``DF`` (paper advisor); live accounts are ``U…`` / ``F…``. A live daemon
#: pointed at a ``DU…`` account is the silent paper-creds-on-live hazard — the
#: compose live-gateway env historically fell back to the PAPER credentials when
#: the ``*_LIVE`` vars were unset, so a live cutover could quietly run on paper.
_PAPER_ACCOUNT_PREFIXES = ("DU", "DF")


def check_live_account_not_paper(*, mode: str, env: dict[str, str]) -> CheckResult:
    """Fail-closed: a LIVE daemon must NOT be pointed at a paper account code.

    Makes the paper-creds-on-live mismatch a hard FAIL before arming live,
    rather than relying on a login to (maybe) reject the wrong account. Unset
    account code is left to :func:`check_env_presence` (which already FAILs) so
    we do not emit a duplicate failure line.
    """
    if mode != "live":
        return CheckResult(name="live-account", status=CheckStatus.SKIP, detail="paper mode (skip)")
    code = (env.get("IGUANATRADER_IBKR_ACCOUNT_CODE") or "").strip().upper()
    if not code:
        return CheckResult(
            name="live-account",
            status=CheckStatus.SKIP,
            detail="account code unset (reported by the env check)",
        )
    if code.startswith(_PAPER_ACCOUNT_PREFIXES):
        return CheckResult(
            name="live-account",
            status=CheckStatus.FAIL,
            detail=(
                f"live mode pointed at PAPER account {code} (DU/DF prefix) — set "
                "IGUANATRADER_IBKR_ACCOUNT_CODE + TWS_USERID_LIVE/TWS_PASSWORD_LIVE to the "
                "real live account; refusing to arm live on paper credentials"
            ),
        )
    return CheckResult(
        name="live-account",
        status=CheckStatus.OK,
        detail=f"live account code {code} is not a paper (DU/DF) account",
    )


def check_ephemeral_live_consistency(*, mode: str, env: dict[str, str]) -> CheckResult:
    """Mirror the daemon's ephemeral-live HARD boot guards, BEFORE boot.

    When ``IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED`` is on for live, the daemon
    refuses to start unless native brackets are on (protective stop must rest
    server-side at IBKR) AND the coordinator creds are present. Surfacing it here
    means the operator learns BEFORE the cutover, not from a crash-loop.
    """

    def truthy(name: str) -> bool:
        return (env.get(name) or "").strip().lower() in ("1", "true", "yes", "on")

    if mode != "live" or not truthy("IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED"):
        return CheckResult(
            name="ephemeral-live",
            status=CheckStatus.SKIP,
            detail="ephemeral live gateway not enabled (skip)",
        )
    problems: list[str] = []
    if not truthy("IGUANATRADER_NATIVE_BRACKET"):
        problems.append(
            "IGUANATRADER_NATIVE_BRACKET must be on — the protective stop MUST rest "
            "server-side at IBKR (a down ephemeral gateway must never leave a position unprotected)"
        )
    if not (env.get("ELIGIA_GATEWAY_WEBHOOK_URL") or "").strip():
        problems.append(
            "ELIGIA_GATEWAY_WEBHOOK_URL unset → no coordinator → daemon refuses to boot"
        )
    if not (env.get("ELIGIA_GATEWAY_HMAC_SECRET") or "").strip():
        problems.append(
            "ELIGIA_GATEWAY_HMAC_SECRET unset → no coordinator → daemon refuses to boot"
        )
    if problems:
        return CheckResult(
            name="ephemeral-live", status=CheckStatus.FAIL, detail="; ".join(problems)
        )
    return CheckResult(
        name="ephemeral-live",
        status=CheckStatus.OK,
        detail="ephemeral live consistent (native brackets on, coordinator creds present)",
    )


def check_watchlist_config_consistency(*, watchlist: list[str], configs: list[Any]) -> CheckResult:
    """Every watchlist symbol has ≥1 ENABLED strategy config, and vice versa.

    Both orphan directions are real bugs: a watchlist symbol with no config never
    produces a proposal (silent no-op); an enabled config for a symbol absent
    from the watchlist never gets ticked (propose iterates the watchlist ENV).
    """
    wl = {s.upper() for s in watchlist}
    enabled_cfg_symbols = {c.symbol.upper() for c in configs if getattr(c, "enabled", False)}
    watchlist_without_config = sorted(wl - enabled_cfg_symbols)
    config_without_watchlist = sorted(enabled_cfg_symbols - wl)
    items: list[str] = []
    if watchlist_without_config:
        items.append(
            f"watchlist symbols with NO enabled config: {', '.join(watchlist_without_config)}"
        )
    if config_without_watchlist:
        items.append(
            f"enabled configs NOT in the watchlist (never ticked): {', '.join(config_without_watchlist)}"
        )
    if items:
        return CheckResult(
            name="watchlist↔configs",
            status=CheckStatus.WARN,
            detail=(
                f"{len(wl)} watchlist / {len(enabled_cfg_symbols)} enabled-config symbols; "
                f"{len(watchlist_without_config)}+{len(config_without_watchlist)} orphans"
            ),
            items=tuple(items),
        )
    return CheckResult(
        name="watchlist↔configs",
        status=CheckStatus.OK,
        detail=f"{len(wl)} symbols, watchlist and enabled configs match",
    )


def check_contract_routing(
    *,
    symbols: list[str],
    resolve: Callable[[str], ContractParams] = resolve_contract_params,
) -> CheckResult:
    """Report per-symbol IBKR routing; surface the CRUD-on-LSE / currency-guess class.

    A symbol that resolves to the SMART/USD default with NO conId is fine for a
    US listing but is exactly how a non-US (e.g. UCITS) symbol silently routes to
    the wrong contract. The check lists every OVERRIDDEN symbol explicitly so the
    operator can confirm the conId overrides are present + correct, and counts
    the defaulted ones so a hidden non-US symbol stands out.
    """
    overridden: list[str] = []
    defaulted: list[str] = []
    for sym in symbols:
        p = resolve(sym)
        is_default = (
            p.exchange == DEFAULT_EXCHANGE and p.currency == DEFAULT_CURRENCY and p.con_id is None
        )
        if is_default:
            defaulted.append(sym.upper())
        else:
            conid = f" conId={p.con_id}" if p.con_id is not None else " (no conId!)"
            overridden.append(f"{sym.upper()}→{p.exchange}/{p.currency}{conid}")
    items = [f"explicit routing ({len(overridden)}): {', '.join(overridden)}"] if overridden else []
    items.append(f"SMART/USD default ({len(defaulted)}): {', '.join(defaulted) or '—'}")
    # An override WITHOUT a conId is the currency-guess landmine the conId work
    # exists to remove — flag it.
    no_conid = [o for o in overridden if "(no conId!)" in o]
    status = CheckStatus.WARN if no_conid else CheckStatus.OK
    detail = f"{len(overridden)} explicit / {len(defaulted)} default of {len(symbols)} symbols" + (
        f"; {len(no_conid)} override(s) MISSING a conId (currency guess risk)" if no_conid else ""
    )
    return CheckResult(name="contract-routing", status=status, detail=detail, items=tuple(items))


# ----------------------------------------------------------------------
# DB-backed checks (repos resolve the ambient session via contextvar)
# ----------------------------------------------------------------------


async def check_paper_history(*, mode: str, audit_repo: Any) -> CheckResult:
    """#15 gate: a LIVE tenant should have prior paper-trading history."""
    if mode != "live":
        return CheckResult(
            name="paper-history", status=CheckStatus.SKIP, detail="paper mode (skip)"
        )
    from iguanatrader.cli.trading import _PAPER_SESSION_EVENT

    has_history = await audit_repo.event_exists(_PAPER_SESSION_EVENT)
    if has_history:
        return CheckResult(
            name="paper-history", status=CheckStatus.OK, detail="prior paper-trading history found"
        )
    return CheckResult(
        name="paper-history",
        status=CheckStatus.WARN,
        detail=(
            "NO recorded paper-trading history — live start needs "
            "--i-understand-the-risks (paper-before-live is the hard rule)"
        ),
    )


async def check_kill_switch(*, tenant_id: UUID, risk_repo: Any) -> CheckResult:
    """A wedged active kill-switch silently blocks all execution."""
    active = await risk_repo.load_kill_switch_state(tenant_id)
    if active:
        return CheckResult(
            name="kill-switch",
            status=CheckStatus.FAIL,
            detail="kill-switch is ACTIVE — execution is halted until it is cleared",
        )
    return CheckResult(name="kill-switch", status=CheckStatus.OK, detail="kill-switch inactive")


async def check_pending_backlog(*, approval_repo: Any, now: datetime) -> CheckResult:
    """Pending-approval backlog, flagging expired-but-still-pending rows.

    A large pile of pending approvals (the "173 stuck pending_approval" incident)
    means the approve / timeout path is not draining — surface it.
    """
    pending = await approval_repo.list_pending()
    expired = [
        r for r in pending if getattr(r, "expires_at", None) is not None and r.expires_at < now
    ]
    if expired:
        return CheckResult(
            name="pending-backlog",
            status=CheckStatus.WARN,
            detail=(
                f"{len(pending)} pending approvals, {len(expired)} PAST expiry but still pending "
                "(approval-timeout→expired not draining)"
            ),
        )
    if len(pending) > 0:
        return CheckResult(
            name="pending-backlog",
            status=CheckStatus.OK,
            detail=f"{len(pending)} pending approvals (none past expiry)",
        )
    return CheckResult(name="pending-backlog", status=CheckStatus.OK, detail="no pending approvals")


__all__ = [
    "CheckResult",
    "CheckStatus",
    "check_contract_routing",
    "check_env_presence",
    "check_ephemeral_live_consistency",
    "check_kill_switch",
    "check_live_account_not_paper",
    "check_paper_history",
    "check_pending_backlog",
    "check_watchlist_config_consistency",
    "worst_status",
]
