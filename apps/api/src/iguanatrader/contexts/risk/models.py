"""Frozen Pydantic v2 value objects for the ``risk`` bounded context.

Per slice K1 design D1+D3+D5:

* :class:`RiskCaps` — env-overridable :class:`Decimal` constants (the
  "policy"). Defaults: 2% / 5% / 15% / 10 / 15%.
* :class:`RiskState` — point-in-time read of capital + utilisation
  numbers; the engine's only read of "what's happening" comes through
  this immutable struct.
* :class:`Decision` — the engine's output. Carries ``outcome``,
  ``cap_type_breached``, ``current_pct``, optional ``clip_quantity``,
  and a ``state_snapshot`` mirror so audit consumers see what the
  engine saw.
* :class:`TradeProposalInput` — the engine's input shape, decoupled
  from T1's ORM row. Slice T1 (when merged) will surface a
  ``TradeProposal`` SQLAlchemy model; the engine consumes only the
  fields it needs (notional, side, mode, id, tenant, …) via this DTO
  so it never imports from the trading bounded context.
* :class:`Confirmation` + :class:`ConfirmationChain` — typed payloads
  for the override audit JSON (per design D5 open-question
  "ConfirmationChain typed Pydantic model").

All classes are frozen + ``model_config = ConfigDict(extra="forbid",
frozen=True)``. Decimals are exact; ``mode='strict'`` rejects floats.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

#: Outcome enum (string Literal — Pydantic + mypy both narrow on these).
Outcome = Literal["allow", "reject", "clip"]

#: Cap type enum. Aligned with ``docs/data-model.md §3.3`` which uses
#: ``daily_loss`` / ``weekly_loss`` (NOT ``daily`` / ``weekly``); the
#: openspec spec.md uses the short forms in prose but the migration +
#: ORM CHECK constraint match the data-model wire form.
CapType = Literal[
    "per_trade",
    "daily_loss",
    "weekly_loss",
    "max_open",
    "max_drawdown",
    "stoploss_guard",
    "cooldown_period",
]

#: Activation source for ``kill_switch_events.source``. Includes the
#: ``cli`` value added by K1 (per design D7 open question + tasks.md 2.6).
KillSwitchSource = Literal[
    "file_flag",
    "env_var",
    "channel_command",
    "dashboard_button",
    "automatic_backoff",
    "automatic_cap_breach",
    "cli",
]

#: Transition enum for ``kill_switch_events.transition``.
KillSwitchTransition = Literal["activated", "deactivated"]


class RiskCaps(BaseModel):
    """Cap configuration — frozen, Decimal-only, env-overridable defaults.

    Defaults match the K1 MVP contract (per design D3 + slice row K1):

    ============================ =================== ==============
    Field                        Default             Env override
    ============================ =================== ==============
    ``per_trade_pct``            ``Decimal("0.02")`` ``IGUANATRADER_RISK_PER_TRADE_PCT``
    ``daily_loss_pct``           ``Decimal("0.05")`` ``IGUANATRADER_RISK_DAILY_LOSS_PCT``
    ``weekly_loss_pct``          ``Decimal("0.15")`` ``IGUANATRADER_RISK_WEEKLY_LOSS_PCT``
    ``max_open_positions``       ``10``              ``IGUANATRADER_RISK_MAX_OPEN_POSITIONS``
    ``max_drawdown_pct``         ``Decimal("0.15")`` ``IGUANATRADER_RISK_MAX_DRAWDOWN_PCT``
    ============================ =================== ==============

    Loaded by :func:`iguanatrader.contexts.risk.service.RiskService._load_caps`.
    Per-tenant overrides via a future ``risk_caps`` config row are out
    of scope for K1.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    per_trade_pct: Decimal = Field(default=Decimal("0.02"))
    daily_loss_pct: Decimal = Field(default=Decimal("0.05"))
    weekly_loss_pct: Decimal = Field(default=Decimal("0.15"))
    max_open_positions: int = Field(default=10, ge=0)
    max_drawdown_pct: Decimal = Field(default=Decimal("0.15"))
    #: v1.5 ``stoploss_guard`` cap — N consecutive stoploss-triggered
    #: exits in the trailing M closed trades that trip the guard.
    #: ``None`` means the protection is disabled (the default — so
    #: existing tenants see no behavioural change until they opt in).
    stoploss_guard_threshold: int | None = Field(default=None, ge=1)
    #: Lookback window M — how many of the most-recent closed trades
    #: the service-layer state builder scans when computing
    #: :attr:`RiskState.recent_stoploss_count_trailing`. Five is the
    #: Freqtrade default; the engine itself does not read this field,
    #: it is supplied only for ``current_pct`` denominator computation
    #: when the guard trips.
    stoploss_guard_lookback: int = Field(default=5, ge=1)
    #: v1.5 ``cooldown_period`` cap — minimum wait, in seconds, after
    #: a closed trade on a given symbol before a new proposal on the
    #: same symbol is allowed. ``None`` means the protection is
    #: disabled (the default — so existing tenants see no behavioural
    #: change until they opt in). Per-symbol scoping prevents
    #: revenge-trading after a stopout without blocking unrelated
    #: signals on other symbols.
    cooldown_seconds: int | None = Field(default=None, ge=1)
    #: v1.5 trailing-stops trigger — favorable-move fraction (e.g.
    #: ``Decimal("0.03")`` = 3%) that arms the trailing logic. ``None``
    #: means trailing is disabled (the default — opt-in semantics
    #: matching ``stoploss_guard_threshold`` + ``cooldown_seconds``).
    #: Unlike the seven pre-trade protections this field is NOT read
    #: by ``engine.evaluate``; it is consumed by
    #: ``contexts.risk.stop_management.compute_trailing_stop`` from a
    #: future cron sweep slice. Stored on :class:`RiskCaps` so the
    #: single tenant-level policy object owns every knob the risk
    #: layer reads, even when the consumer is the stop-management
    #: service rather than the pre-trade engine.
    trail_trigger_pct: Decimal | None = Field(default=None)
    #: Multiplier on Wilder ATR for the trailing-stop distance below
    #: the highest post-entry close. ``1.5`` is the Freqtrade default;
    #: lower = tighter trail (faster stop-out on pullbacks), higher =
    #: looser. Read only when :attr:`trail_trigger_pct` is set.
    trail_atr_mult: Decimal = Field(default=Decimal("1.5"))
    #: ATR period passed into the trailing-stop helper. ``14`` matches
    #: the period used by every strategy's entry-time ATR stop sizing
    #: (``donchian_atr``, ``volume_donchian``, ``rsi_mean_reversion``,
    #: ``macd_cross``, ``bollinger_breakout``) so the trail distance
    #: and the initial stop distance move on the same indicator.
    trail_atr_period: int = Field(default=14, ge=2)


class RiskState(BaseModel):
    """Point-in-time risk state — the engine's only "world read".

    All :class:`Decimal` fields are non-negative fractions in [0, 1)
    except ``capital`` which is an absolute :class:`Decimal` amount in
    the tenant's settlement currency. ``open_positions_count`` is a
    non-negative integer.

    Per design D1: this struct is constructed by ``RiskService`` from
    repository reads (equity snapshot, open positions, day P&L) and
    passed *by value* to the pure-functional engine. The engine never
    reaches back to the repository.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    capital: Decimal
    day_to_date_loss_pct: Decimal = Field(default=Decimal("0"))
    week_to_date_loss_pct: Decimal = Field(default=Decimal("0"))
    open_positions_count: int = Field(default=0, ge=0)
    peak_to_trough_drawdown_pct: Decimal = Field(default=Decimal("0"))
    #: v1.5 ``stoploss_guard`` input — count of ``exit_reason == "stop"``
    #: rows among the trailing ``RiskCaps.stoploss_guard_lookback`` closed
    #: trades. Derived by the service-layer state builder; defaults to 0
    #: so the engine is inert when the upstream builder has not yet been
    #: wired (legacy seed rows + the pre-``chore-add-exit-reason-column``
    #: era both fall through to "guard never trips").
    recent_stoploss_count_trailing: int = Field(default=0, ge=0)
    #: Denominator the service builder used to compute the count above.
    #: Mirrors :attr:`RiskCaps.stoploss_guard_lookback` at the moment of
    #: state derivation; reported back through ``Decision.current_pct``
    #: when the guard rejects so observability consumers can chart
    #: "3 of 5 trailing trades stopped" uniformly.
    recent_trades_lookback: int = Field(default=0, ge=0)
    #: v1.5 ``cooldown_period`` input — for each symbol that has at
    #: least one closed trade, the integer number of seconds elapsed
    #: between the moment of state derivation and the most-recent
    #: close on that symbol. Populated by the service-layer state
    #: builder via a single ``datetime.now()`` read (the only clock
    #: read in the build; per design D5 the engine itself stays pure).
    #: Symbols with no prior close are absent from the dict — the
    #: protection treats absence as "no cooldown applies".
    seconds_since_last_close_by_symbol: dict[str, int] = Field(default_factory=dict)


class TradeProposalInput(BaseModel):
    """Subset of T1's ``trade_proposals`` row that the engine cares about.

    Decouples ``contexts/risk/engine.py`` from T1's ORM model — when T1
    is unmerged at K1 propose-time, the engine still types-checks. The
    service layer (which DOES depend on T1's ORM at runtime) is the
    single conversion point.

    Fields chosen per ``docs/data-model.md §3.2 trade_proposals`` —
    only the columns the cap evaluation reads:

    * ``id`` — for audit linkage (``risk_evaluations.proposal_id``).
    * ``tenant_id`` — defence-in-depth tenant assertion in the engine's
      caller (engine itself is tenant-agnostic — it just operates on the
      fields).
    * ``notional_value`` — ``quantity * entry_price_indicative``,
      computed by the service layer before calling the engine (the
      engine does not multiply, keeping the input contract minimal).
    * ``side`` — informational; not used by current protections (per
      design D2's "fixed-order composition") but available for future
      protections that distinguish long/short exposure.
    * ``symbol`` — the instrument the proposal targets (e.g. ``"SPY"``).
      Read by the v1.5 ``cooldown_period`` protection to look up the
      per-symbol seconds-since-last-close in
      :attr:`RiskState.seconds_since_last_close_by_symbol`. Other
      protections currently ignore it; future per-symbol caps would
      key off this field too.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    id: UUID
    tenant_id: UUID
    notional_value: Decimal
    side: Literal["buy", "sell"]
    symbol: str = Field(default="", min_length=0)


class Decision(BaseModel):
    """Risk-engine output. Single source of truth for "is this trade allowed?".

    Per design D1: the engine returns this (no exceptions for the
    common reject path — exceptions are reserved for kill-switch +
    audit failures upstream). ``state_snapshot`` is the engine's own
    record of the input ``RiskState`` it saw, so a future audit
    reconstruct can answer "what did the engine see?" without joining
    against the equity history.

    ``cap_type_breached`` is ``None`` iff ``outcome == "allow"``;
    enforced by the validator below.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    outcome: Outcome
    cap_type_breached: CapType | None = None
    current_pct: Decimal | None = None
    clip_quantity: Decimal | None = None
    state_snapshot: dict[str, str] = Field(default_factory=dict)
    """Mirror of the input ``RiskState`` rendered as ``str(value)`` per field.

    Stored as ``dict[str, str]`` rather than ``RiskState`` to make JSON
    serialisation trivial in the SQLAlchemy ``state_snapshot`` JSONB
    column without a custom encoder.
    """


class Confirmation(BaseModel):
    """Single confirmation entry inside :class:`ConfirmationChain`.

    Per FR25 ("double confirmation"), an override needs first + second
    confirmations. Each carries the channel the operator confirmed
    through (``"telegram"``, ``"whatsapp"``, ``"cli"``, ``"dashboard"``),
    a UTC timestamp, and the actor's user id (which MAY be the same
    user for both confirmations if the operator is acting alone — the
    audit captures the channel diversity, not the actor identity).
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    channel: Literal["telegram", "whatsapp", "cli", "dashboard"]
    at: datetime
    actor_user_id: UUID


class ConfirmationChain(BaseModel):
    """Typed wrapper around the ``risk_overrides.confirmation_chain`` JSONB.

    Stored as ``model.model_dump(mode="json")`` in the column; loaded
    via ``ConfirmationChain.model_validate(row.confirmation_chain)``.
    The DTO's ``frozen=True`` means existing rows can never be mutated
    via the ORM model — append-only at the row level (per the global
    ``__tablename_is_append_only__`` listener) AND immutable at the
    Python level.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    first_confirmation: Confirmation
    second_confirmation: Confirmation


__all__ = [
    "CapType",
    "Confirmation",
    "ConfirmationChain",
    "Decision",
    "KillSwitchSource",
    "KillSwitchTransition",
    "Outcome",
    "RiskCaps",
    "RiskState",
    "TradeProposalInput",
]
