"""Admin operator commands — ``iguanatrader admin <subcommand>``.

Subcommands:

* ``bootstrap-tenant`` — create the first tenant + admin user on a
  fresh database. Idempotent on the tenant slug + user email pair
  (re-running with the same slug fails unless ``--force-reset`` is
  passed, which deletes the row first).
* ``register-symbol`` — register a ticker in the tenant's
  ``symbol_universe`` + ``watchlist_configs`` tables so research-brief
  refresh can resolve its FKs. Without this, ``POST
  /api/v1/research/briefs/{symbol}/refresh`` raises ``LookupError``
  (surfaced as 404 by the route).

The auth route :mod:`iguanatrader.api.routes.auth` raises
:class:`BootstrapNotReadyError` when the database has zero tenants and
the error message explicitly points operators at this command.
"""

from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import typer

app: typer.Typer = typer.Typer(
    name="admin",
    help="Admin commands (tenant bootstrap, etc.).",
    no_args_is_help=True,
)

_DEFAULT_DB_URL = "sqlite+aiosqlite:///./data/iguanatrader.db"


def _db_url() -> str:
    return os.getenv("IGUANA_DATABASE_URL") or _DEFAULT_DB_URL


@app.command("bootstrap-tenant")
def bootstrap_tenant(
    slug: str = typer.Argument(
        ...,
        help="Tenant slug (also stored as Tenant.name). Lowercase + hyphens.",
    ),
    email: str = typer.Option(
        ...,
        "--email",
        "-e",
        help="Admin user email address.",
    ),
    password: str = typer.Option(
        ...,
        "--password",
        "-p",
        prompt=True,
        hide_input=True,
        confirmation_prompt=False,
        help=(
            "Admin user plaintext password. Hashed with Argon2id before "
            "insert. Prompted (no echo) if not passed via flag."
        ),
    ),
    force_reset: bool = typer.Option(
        False,
        "--force-reset",
        help=(
            "If the tenant slug exists, delete it (and its users) before "
            "re-creating. Destroys data; only use on a brand-new DB."
        ),
    ),
) -> None:
    """Create the first tenant + admin user on a fresh database.

    Usage:

        iguanatrader admin bootstrap-tenant arturo-trading \\
            --email arturo@example.com --password 'changeme-2026'

    Exits with code 0 on success, non-zero on validation failure or
    duplicate-slug-without-force-reset.
    """
    asyncio.run(_bootstrap_tenant_async(slug, email, password, force_reset))


async def _bootstrap_tenant_async(
    slug: str,
    email: str,
    password: str,
    force_reset: bool,
) -> None:
    """Async body of the ``bootstrap-tenant`` command."""
    # Local imports keep ``--help`` fast (gotcha #29).
    from sqlalchemy import delete, select

    from iguanatrader.api.auth import hash_password
    from iguanatrader.persistence import (
        Tenant,
        User,
        engine_factory,
        session_factory,
    )
    from iguanatrader.shared.contextvars import with_tenant_context

    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)

        async with sessionmaker() as session:
            existing = await session.execute(select(Tenant).where(Tenant.name == slug))
            existing_tenant = existing.scalars().first()
            if existing_tenant is not None:
                if not force_reset:
                    typer.echo(
                        f"ERROR: tenant {slug!r} already exists (id={existing_tenant.id}). "
                        "Pass --force-reset to delete + re-create."
                    )
                    raise typer.Exit(code=1)
                # --force-reset: drop the existing tenant's users + the
                # tenant itself. We do this with raw deletes inside a
                # with_tenant_context to satisfy the slice-3 listener.
                async with with_tenant_context(existing_tenant.id):
                    await session.execute(delete(User).where(User.tenant_id == existing_tenant.id))
                    await session.execute(delete(Tenant).where(Tenant.id == existing_tenant.id))
                    await session.commit()
                typer.echo(
                    f"--force-reset: deleted tenant {slug!r} (id={existing_tenant.id}) + its users."
                )

        tenant_id = uuid4()
        user_id = uuid4()
        hashed = hash_password(password)

        # #16: create the Tenant AND its admin User in ONE transaction. The
        # previous two-commit version could crash after committing the
        # tenant but before the user, leaving an orphaned tenant with no
        # admin — a permanent lockout (login impossible, and a re-run of
        # bootstrap refuses because the tenant already exists). SQLAlchemy
        # orders the inserts by the User→Tenant FK, so a single commit is
        # safe; a failure rolls back both.
        async with with_tenant_context(tenant_id), sessionmaker() as session:
            session.add(Tenant(id=tenant_id, name=slug, feature_flags={}))
            session.add(
                User(
                    id=user_id,
                    tenant_id=tenant_id,
                    email=email,
                    password_hash=hashed,
                    role="tenant_user",
                )
            )
            await session.commit()
    finally:
        await engine.dispose()

    typer.echo(f"OK — tenant_id={tenant_id} user_id={user_id} email={email} slug={slug}")


_METHODOLOGY_CHOICES = ("three_pillar", "canslim", "magic_formula", "qarp", "multi_factor")
_TIER_CHOICES = ("primary", "secondary")
_SCHEDULE_CHOICES = ("daily", "weekly", "manual")


@app.command("register-symbol")
def register_symbol(
    symbol: str = typer.Argument(
        ...,
        help="Ticker symbol (e.g. NVDA). Stored verbatim — uppercase recommended.",
    ),
    tenant: str = typer.Option(
        ...,
        "--tenant",
        "-t",
        help="Tenant slug (matches Tenant.name from bootstrap-tenant).",
    ),
    exchange: str = typer.Option(
        "NASDAQ",
        "--exchange",
        "-x",
        help="Exchange code. Free-form text; default NASDAQ.",
    ),
    tier: str = typer.Option(
        "primary",
        "--tier",
        help=f"Watchlist tier. One of: {', '.join(_TIER_CHOICES)}.",
    ),
    methodology: str = typer.Option(
        "three_pillar",
        "--methodology",
        "-m",
        help=f"Default brief methodology. One of: {', '.join(_METHODOLOGY_CHOICES)}.",
    ),
    schedule: str = typer.Option(
        "manual",
        "--schedule",
        "-s",
        help=f"Refresh schedule. One of: {', '.join(_SCHEDULE_CHOICES)}.",
    ),
) -> None:
    """Register ``symbol`` for ``tenant`` so research-brief refresh works.

    Inserts one row in ``symbol_universe`` + one in ``watchlist_configs``.
    Both tables enforce ``(tenant_id, symbol, exchange)`` /
    ``(tenant_id, symbol_universe_id)`` uniqueness, so re-running for a
    symbol that's already registered exits non-zero.

    Usage::

        iguanatrader admin register-symbol NVDA --tenant arturo-trading

    The route ``POST /api/v1/research/briefs/{symbol}/refresh`` needs
    these rows to resolve the FK pair on the new brief; without them it
    returns HTTP 404 with the message from this command.
    """
    if tier not in _TIER_CHOICES:
        typer.echo(f"ERROR: tier must be one of {_TIER_CHOICES}, got {tier!r}.")
        raise typer.Exit(code=2)
    if methodology not in _METHODOLOGY_CHOICES:
        typer.echo(
            f"ERROR: methodology must be one of {_METHODOLOGY_CHOICES}, got {methodology!r}."
        )
        raise typer.Exit(code=2)
    if schedule not in _SCHEDULE_CHOICES:
        typer.echo(f"ERROR: schedule must be one of {_SCHEDULE_CHOICES}, got {schedule!r}.")
        raise typer.Exit(code=2)

    asyncio.run(
        _register_symbol_async(
            symbol=symbol,
            tenant_slug=tenant,
            exchange=exchange,
            tier=tier,
            methodology=methodology,
            schedule=schedule,
        )
    )


async def _register_symbol_async(
    *,
    symbol: str,
    tenant_slug: str,
    exchange: str,
    tier: str,
    methodology: str,
    schedule: str,
) -> None:
    """Async body of the ``register-symbol`` command."""
    from sqlalchemy import select
    from sqlalchemy.exc import IntegrityError

    from iguanatrader.contexts.research.models import SymbolUniverse, WatchlistConfig
    from iguanatrader.persistence import Tenant, engine_factory, session_factory
    from iguanatrader.shared.contextvars import with_tenant_context

    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)

        async with sessionmaker() as session:
            tenant_row = (
                (await session.execute(select(Tenant).where(Tenant.name == tenant_slug)))
                .scalars()
                .first()
            )
            if tenant_row is None:
                typer.echo(
                    f"ERROR: tenant {tenant_slug!r} not found. Run "
                    f"`iguanatrader admin bootstrap-tenant {tenant_slug} ...` first."
                )
                raise typer.Exit(code=1)
            tenant_id = tenant_row.id

        async with with_tenant_context(tenant_id), sessionmaker() as session:
            symbol_universe_id = uuid4()
            watchlist_config_id = uuid4()
            session.add(
                SymbolUniverse(
                    id=symbol_universe_id,
                    tenant_id=tenant_id,
                    symbol=symbol,
                    exchange=exchange,
                )
            )
            session.add(
                WatchlistConfig(
                    id=watchlist_config_id,
                    tenant_id=tenant_id,
                    symbol_universe_id=symbol_universe_id,
                    tier=tier,
                    methodology=methodology,
                    brief_refresh_schedule=schedule,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                typer.echo(
                    f"ERROR: symbol {symbol!r}/{exchange!r} already registered for "
                    f"tenant {tenant_slug!r}: {exc.orig}"
                )
                raise typer.Exit(code=1) from exc
    finally:
        await engine.dispose()

    typer.echo(
        f"OK — symbol={symbol} exchange={exchange} tenant={tenant_slug} "
        f"symbol_universe_id={symbol_universe_id} watchlist_config_id={watchlist_config_id}"
    )


#: US-ETF → UCITS substitution map (WS-B2). Arturo's EU retail account
#: cannot trade US-listed ETFs (KID/PRIIPs block — IBKR Error 201,
#: confirmed on the LIVE account, not just paper), so a live watchlist
#: MUST swap these 11 tickers for their UCITS equivalents. Symbols not
#: in this map pass through unchanged. Exchange/currency resolution
#: (LSE/USD; VUSA AEB/EUR) happens at gateway contract-qualify time, not
#: here — this only rewrites the ticker the strategy config is keyed on.
_UCITS_SWAP_MAP: dict[str, str] = {
    "SPY": "VUSA",
    "QQQ": "EQQQ",
    "IWM": "R2US",
    "XLE": "IUES",
    "XLF": "IUFS",
    "XLK": "IUIT",
    "XLV": "IUHC",
    "GLD": "IGLN",
    "SLV": "ISLN",
    "USO": "CRUD",
    "TLT": "IDTL",
}


def _parse_symbols(raw: str) -> list[str]:
    """Split a comma-separated symbol list into deduped, uppercased tickers.

    Order is preserved (first occurrence wins) so the printed plan reads
    in the operator's input order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for tok in raw.split(","):
        sym = tok.strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            out.append(sym)
    return out


@app.command("seed-watchlist")
def seed_watchlist(
    symbols: str = typer.Option(
        ...,
        "--symbols",
        help=(
            "Comma-separated tickers to seed (e.g. 'AMD,NVDA,SPY'). The "
            "authoritative list — nothing is hard-coded. Pass the daemon's "
            "IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS to keep them in sync."
        ),
    ),
    tenant: str = typer.Option(
        ...,
        "--tenant",
        "-t",
        help="Tenant slug (matches Tenant.name from bootstrap-tenant).",
    ),
    strategies: str = typer.Option(
        "all",
        "--strategies",
        help=(
            "'all' (every registered strategy) or a comma-separated list of "
            "strategy kinds (e.g. 'donchian_atr,sma_cross')."
        ),
    ),
    ucits_swap: bool = typer.Option(
        False,
        "--ucits-swap/--no-ucits-swap",
        help=(
            "Rewrite the 11 US ETFs to their UCITS equivalents (SPY→VUSA, "
            "GLD→IGLN, …) — the paper→LIVE transform for an EU account that "
            "cannot trade US ETFs. Other symbols pass through unchanged."
        ),
    ),
    wipe: bool = typer.Option(
        True,
        "--wipe/--no-wipe",
        help=(
            "Soft-disable EVERY existing config for the tenant before "
            "reseeding (clean slate; audit history preserved, no DELETE). "
            "Configs not in the new grid stay disabled."
        ),
    ),
    refresh_briefs: bool = typer.Option(
        False,
        "--refresh-briefs/--no-refresh-briefs",
        help=(
            "WS-1b: after seeding, synthesise a fresh research brief for each "
            "seeded symbol immediately (the on-add-stock trigger) instead of "
            "waiting for the next daily 07:00 brief cron — so the LLM entry/exit "
            "gates read current fundamentals from the first tick. Spends one "
            "OpenBB fetch + one LLM synthesis per symbol; best-effort per symbol. "
            "Off by default."
        ),
    ),
    apply: bool = typer.Option(
        False,
        "--apply",
        help=(
            "Actually write the changes. Omit for a DRY RUN that prints the "
            "plan and touches nothing (the default — this command mutates "
            "real trading config)."
        ),
    ),
) -> None:
    """Wipe + reseed ``strategy_configs`` for ``tenant`` (WS-B1).

    Seeds the cartesian product ``strategies x symbols`` with each
    strategy's documented defaults (``params={}`` → risk-based 1%,
    whole-share sizing). The propose loop evaluates a symbol only when it
    is BOTH in the daemon's ``IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS`` env
    AND has an enabled config here, so keep the two in lockstep.

    ``strategy_configs`` are mode-agnostic (shared by the paper + live
    daemons); "for live" is expressed by the symbol set (``--ucits-swap``)
    plus which daemon runs — NOT a column on the row.

    Usage (dry run, then apply)::

        iguanatrader admin seed-watchlist --tenant arturo-trading \\
            --symbols "$IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS" --ucits-swap
        iguanatrader admin seed-watchlist --tenant arturo-trading \\
            --symbols "$IGUANATRADER_DEFAULT_WATCHLIST_SYMBOLS" --ucits-swap --apply
    """
    from iguanatrader.contexts.trading.strategies.manager import STRATEGY_REGISTRY

    if strategies.strip().lower() == "all":
        kinds = sorted(STRATEGY_REGISTRY)
    else:
        kinds = []
        seen_kinds: set[str] = set()
        for tok in strategies.split(","):
            kind = tok.strip()
            if kind and kind not in seen_kinds:
                seen_kinds.add(kind)
                kinds.append(kind)
        unknown = [k for k in kinds if k not in STRATEGY_REGISTRY]
        if unknown:
            typer.echo(
                f"ERROR: unknown strategy kind(s) {unknown}. "
                f"Valid: {sorted(STRATEGY_REGISTRY)}."
            )
            raise typer.Exit(code=2)

    parsed = _parse_symbols(symbols)
    if not parsed:
        typer.echo("ERROR: --symbols is empty after parsing.")
        raise typer.Exit(code=2)
    if ucits_swap:
        parsed = [_UCITS_SWAP_MAP.get(sym, sym) for sym in parsed]

    asyncio.run(
        _seed_watchlist_async(
            tenant_slug=tenant,
            symbols=parsed,
            kinds=kinds,
            wipe=wipe,
            apply=apply,
            refresh_briefs=refresh_briefs,
        )
    )


#: House research methodology for the on-add-stock brief refresh — matches the
#: daemon's daily brief cron (``OrchestrationService._DEFAULT_BRIEF_METHODOLOGY``)
#: + the REST route default, so a CLI-triggered brief is identical to a cron one.
_SEED_BRIEF_METHODOLOGY = "three_pillar"


async def _refresh_briefs_for_symbols(
    brief_service: object,
    *,
    symbols: list[str],
    methodology: str = _SEED_BRIEF_METHODOLOGY,
) -> int:
    """Synthesise a fresh brief per seeded symbol (WS-1b on-add-stock trigger).

    Best-effort + per-symbol fail-soft (mirrors the daemon brief cron): one bad
    symbol never aborts the batch. Returns the count refreshed. Must run inside
    a ``with_tenant_context`` + ``with_session_context`` scope so the brief
    service's repository resolves its session + tenant.
    """
    refreshed = 0
    for symbol in symbols:
        try:
            await brief_service.refresh(symbol=symbol, methodology=methodology)  # type: ignore[attr-defined]
            refreshed += 1
            typer.echo(f"  brief refreshed: {symbol}")
        except Exception as exc:  # fail-soft per symbol
            typer.echo(f"  brief refresh FAILED for {symbol}: {type(exc).__name__}: {exc}")
            continue
    return refreshed


async def _seed_watchlist_async(
    *,
    tenant_slug: str,
    symbols: list[str],
    kinds: list[str],
    wipe: bool,
    apply: bool,
    refresh_briefs: bool = False,
) -> None:
    """Async body of the ``seed-watchlist`` command.

    Dry-run path computes the plan with ZERO mutation (no upsert, no
    disable, no flush) so the ``before_update`` version-bump hook never
    fires. The apply path runs the disable + upserts inside one
    ``with_tenant_context`` session and commits once.
    """
    from sqlalchemy import select

    from iguanatrader.contexts.trading.repository import StrategyConfigRepository
    from iguanatrader.persistence import Tenant, engine_factory, session_factory
    from iguanatrader.shared.contextvars import with_session_context, with_tenant_context

    engine = engine_factory(_db_url())
    try:
        sessionmaker = session_factory(engine)

        async with sessionmaker() as session:
            tenant_row = (
                (await session.execute(select(Tenant).where(Tenant.name == tenant_slug)))
                .scalars()
                .first()
            )
            if tenant_row is None:
                typer.echo(
                    f"ERROR: tenant {tenant_slug!r} not found. Run "
                    f"`iguanatrader admin bootstrap-tenant {tenant_slug} ...` first."
                )
                raise typer.Exit(code=1)
            tenant_id = tenant_row.id

        grid = [(kind, sym) for sym in symbols for kind in kinds]

        async with (
            with_tenant_context(tenant_id),
            sessionmaker() as session,
            with_session_context(session),
        ):
            repo = StrategyConfigRepository()
            existing = await repo.list_for_tenant()
            existing_pairs = {(c.strategy_kind, c.symbol) for c in existing}
            enabled_before = sum(1 for c in existing if c.enabled)

            created = [pair for pair in grid if pair not in existing_pairs]
            updated = [pair for pair in grid if pair in existing_pairs]

            typer.echo(
                f"tenant={tenant_slug} (id={tenant_id})\n"
                f"strategies ({len(kinds)}): {', '.join(kinds)}\n"
                f"symbols ({len(symbols)}): {', '.join(symbols)}\n"
                f"grid: {len(kinds)} x {len(symbols)} = {len(grid)} configs "
                f"({len(created)} new, {len(updated)} updated)\n"
                f"wipe: {'soft-disable ' + str(enabled_before) + ' currently-enabled configs first' if wipe else 'no'}"
            )

            if not apply:
                typer.echo("\nDRY RUN — nothing written. Re-run with --apply to commit.")
                return

            if wipe:
                await repo.disable_all_for_tenant()
            for kind, sym in grid:
                await repo.upsert(symbol=sym, strategy_kind=kind, params={}, enabled=True)
            await session.commit()

        # WS-1b on-add-stock trigger: now that the configs are committed +
        # enabled, synthesise a fresh brief per seeded symbol so the LLM
        # entry/exit gates have current fundamentals immediately instead of
        # waiting for the next daily 07:00 brief cron. Best-effort, in its own
        # committed session scope; a brief failure never undoes the seed above.
        if refresh_briefs:
            from iguanatrader.contexts.research.factory import build_brief_service
            from iguanatrader.contexts.research.repository import ResearchRepository

            typer.echo(f"\nRefreshing briefs for {len(symbols)} seeded symbol(s)...")
            async with (
                with_tenant_context(tenant_id),
                sessionmaker() as brief_session,
                with_session_context(brief_session),
            ):
                brief_service = build_brief_service(ResearchRepository())
                refreshed = await _refresh_briefs_for_symbols(brief_service, symbols=symbols)
                await brief_session.commit()
            typer.echo(f"Briefs refreshed: {refreshed}/{len(symbols)}.")
    finally:
        await engine.dispose()

    typer.echo(
        f"\nOK — seeded {len(symbols) * len(kinds)} configs for tenant {tenant_slug} "
        f"({len(symbols)} symbols x {len(kinds)} strategies). "
        f"Active set now = exactly this grid."
    )


__all__ = ["app"]
