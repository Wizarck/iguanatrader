"""Inter-context event contract for the trading bounded context.

This module is the wire-format contract between the trading bounded
context and risk (K1) / approval (P1) / observability (O1). Subscribers
in those contexts MUST treat field types as frozen; additions go in
``metadata: dict``. Genuine structural changes require a deliberate
cross-context PR.

Per design D3: each event class:

* Subclasses :class:`iguanatrader.shared.messagebus.Event`.
* Declares a :attr:`event_name` :class:`ClassVar` matching the structlog
  ``<context>.<entity>.<action>`` convention (NFR-O8).
* Carries ``tenant_id: UUID`` explicitly (do NOT rely on
  ``tenant_id_var`` propagating across worker boundaries).
* Carries the entity primary key — used as ``idempotency_key`` via
  :meth:`__post_init__`.
* Has a ``metadata: dict[str, Any]`` extension slot.

Dataclass kwarg-only declaration: every subclass uses ``kw_only=True``
so non-default fields can follow the parent's already-defaulted
``idempotency_key`` without tripping the field-ordering rule. Callers
construct events as ``ProposalCreated(tenant_id=..., proposal_id=...)``.

The :class:`KillSwitchTripped` event is OWNED by the risk bounded
context (slice K1 ``risk-engine-protections``) and not redeclared
here — :class:`TradingService` subscribes by importing the class from
``iguanatrader.contexts.risk.events`` once K1 lands.

Cross-context import boundary: the ruff ``no-cross-context-deep-imports``
rule (slice-2 contract) excludes ``events.py`` paths from the ban —
events are the documented inter-context wire format per
``docs/data-model.md §6``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar
from uuid import UUID

from iguanatrader.shared.messagebus import Event


@dataclass(kw_only=True)
class ProposalCreated(Event):
    """Emitted by ``TradingService.propose`` when a strategy returns a
    non-``None`` proposal that has been persisted.

    Subscribers: K1 ``RiskService`` (runs the risk engine), O1 cost
    meter / structlog narrator.
    """

    event_name: ClassVar[str] = "trading.proposal.created"

    tenant_id: UUID
    proposal_id: UUID
    symbol: str
    strategy_kind: str
    strategy_version: int
    correlation_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class ProposalRiskEvaluated(Event):
    """Emitted by K1 ``RiskService`` after evaluating a proposal.

    Subscribers: T1 ``TradingService.enqueue_approval_handler``, O1.
    """

    event_name: ClassVar[str] = "trading.proposal.risk_evaluated"

    tenant_id: UUID
    proposal_id: UUID
    outcome: str
    cap_type_breached: str | None = None
    clip_quantity: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class ApprovalRequested(Event):
    """Emitted by T1 ``TradingService`` after a permissive risk evaluation.

    Subscribers: P1 ``ApprovalService`` (dispatches Telegram/Hermes
    request), O1.
    """

    event_name: ClassVar[str] = "trading.approval.requested"

    tenant_id: UUID
    proposal_id: UUID
    decision: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class ProposalApproved(Event):
    """Emitted by P1 ``ApprovalService`` when the human approves.

    Subscribers: T1 ``TradingService.execute_on_approval_handler``, O1.
    """

    event_name: ClassVar[str] = "trading.proposal.approved"

    tenant_id: UUID
    proposal_id: UUID
    approved_by_user_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class ProposalRejected(Event):
    """Emitted by P1 ``ApprovalService`` when the human rejects (or times out).

    Subscribers: T1, O1.
    """

    event_name: ClassVar[str] = "trading.proposal.rejected"

    tenant_id: UUID
    proposal_id: UUID
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class OrderPlaced(Event):
    """Emitted by T1 ``TradingService`` after ``BrokerPort.place_order``.

    Subscribers: T2 reconciliation worker, O1.
    """

    event_name: ClassVar[str] = "trading.order.placed"

    tenant_id: UUID
    order_id: UUID
    broker_order_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.order_id)


@dataclass(kw_only=True)
class OrderRejected(Event):
    """Emitted by T1 ``TradingService.execute_on_approval_handler`` on broker
    rejection (auth error, budget exceeded, generic broker NACK).

    Slice T4 additive extension per the canonical extension pattern in
    [.ai-playbook/specs/protocol-fake-deferred-install.md](../../../../.ai-playbook/specs/protocol-fake-deferred-install.md).
    Subscribers: O1 cost meter, future P1 audit channels.
    """

    event_name: ClassVar[str] = "trading.order.rejected"

    tenant_id: UUID
    proposal_id: UUID
    reason: str  # "broker_auth" | "budget" | "broker_other"
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.proposal_id)


@dataclass(kw_only=True)
class OrderFilled(Event):
    """Emitted by T1 ``TradingService`` after recording a broker fill.

    Subscribers: T1 ``TradingService.update_equity`` (T4 wires), O1.
    """

    event_name: ClassVar[str] = "trading.order.filled"

    tenant_id: UUID
    order_id: UUID
    fill_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.fill_id)


@dataclass(kw_only=True)
class EquityUpdated(Event):
    """Emitted by T1 ``TradingService.update_equity`` after persisting a snapshot.

    Subscribers: slice W1's ``/sse/equity`` SSE consumer, O1.
    """

    event_name: ClassVar[str] = "trading.equity.updated"

    tenant_id: UUID
    equity_snapshot_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.equity_snapshot_id)


@dataclass(kw_only=True)
class CloseTradeRequested(Event):
    """Emitted by the manual-close API route + the trailing-stops sweep
    + the take-profit handler to request an exit-order for ``trade_id``.

    Slice ``trade-close-flow-exit-pathway``. Subscriber:
    :meth:`TradingService.close_trade_handler` calls
    :meth:`TradingService.close_trade` which submits the exit order
    + transitions the trade to ``state="closing"``.

    ``reason`` must be one of the four canonical exit categories
    (``stop`` / ``target`` / ``manual`` / ``expiry``) — mirrors the
    ``ck_trades_exit_reason_allowed`` DB constraint. The trade-close
    service writes this onto the Trade row at close-submit time so the
    terminal fill reconciliation does not need to know the original
    trigger.
    """

    event_name: ClassVar[str] = "trading.trade.close_requested"

    tenant_id: UUID
    trade_id: UUID
    reason: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            # One close request per trade — re-requests against an
            # already-closing trade are rejected at the handler.
            self.idempotency_key = str(self.trade_id)


@dataclass(kw_only=True)
class ExitApprovalRequested(Event):
    """Emitted by the WS-5 urgent-exit advisor to ask the operator, via the
    HITL approval machinery, to CLOSE an open position now.

    Subscriber: P1 ``ApprovalService._exit_approval_requested_handler`` →
    creates an ``action_type='exit'`` approval request + fans it out to
    Telegram. On a granted decision the action-aware bridge publishes
    :class:`CloseTradeRequested` (reason ``'manual'`` — a human-approved
    close); on reject/timeout nothing is closed (the advisor re-raises on a
    later tick if the urgent condition persists). NEVER auto-closes — this
    event only raises an approval.

    Dedup is PENDING-AWARE at the source: the urgent-exit sweep calls
    ``ApprovalRepository.has_pending_exit_for_trade(trade_id)`` and only raises
    when no card is currently open for that trade — so a card still pending is
    not duplicated, yet a re-raise flows the moment the previous card expires.
    The approval subscription is deliberately NON-idempotent (the bus dedup
    cache would otherwise suppress that legitimate re-raise for the whole
    process life). ``idempotency_key`` = ``trade_id`` is retained as documentary
    metadata + a guard for any future idempotent consumer.
    """

    event_name: ClassVar[str] = "trading.exit_approval.requested"

    tenant_id: UUID
    trade_id: UUID
    symbol: str
    side: str
    quantity: Decimal
    reason: str = "urgent"
    llm_rationale: str | None = None
    confidence: Decimal | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = str(self.trade_id)


@dataclass(kw_only=True)
class DaemonDrainRequested(Event):
    """Emitted by ``POST /api/v1/daemons/{mode}/toggle`` on a true→false toggle.

    Slice ``dual-daemon-mode-toggle-and-reconcile``. Subscriber:
    daemon-side lifecycle handler that bulk-rejects pending_approval
    proposals for the matching ``mode`` with
    ``rejection_reason='daemon_drained'``. IBKR-side orders are NOT
    cancelled — IBKR is the authoritative book; we only refuse to
    create new orders going forward.

    Each daemon process subscribes but filters by its own ``mode`` —
    the paper daemon ignores ``DaemonDrainRequested(mode='live')`` and
    vice versa. The bus subscription is registered with
    ``idempotent=True`` so duplicate emissions (toggle bounce) collapse
    to a single drain pass.
    """

    event_name: ClassVar[str] = "trading.daemon.drain_requested"

    tenant_id: UUID
    mode: str  # 'paper' | 'live'
    reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = f"drain:{self.tenant_id}:{self.mode}"


@dataclass(kw_only=True)
class DaemonReconcileRequested(Event):
    """Emitted by ``POST /api/v1/daemons/{mode}/reconcile`` + by ``POST
    /api/v1/daemons/{mode}/toggle`` on a false→true toggle.

    Slice ``dual-daemon-mode-toggle-and-reconcile``. Subscriber: daemon-
    side lifecycle handler that runs reconcile against IBKR (fills +
    equity snapshot first cut; positions/open-orders deferred to the
    Phase-2.5 follow-up).

    ``idempotency_key`` is NOT keyed by tenant + mode alone — operators
    may legitimately trigger several reconciles in a row (e.g. after a
    manual TWS-side action followed by a few-second observation
    window). A monotonic correlation_id keeps each request independent.
    """

    event_name: ClassVar[str] = "trading.daemon.reconcile_requested"

    tenant_id: UUID
    mode: str  # 'paper' | 'live'
    correlation_id: UUID
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            self.idempotency_key = f"reconcile:{self.correlation_id}"


@dataclass(kw_only=True)
class TradeClosed(Event):
    """Emitted post-fill reconciliation when a trade transitions from
    ``state="closing"`` to ``state="closed"`` (slice A3).

    Subscribers include :class:`AutoJournalOnCloseHandler` which
    triggers the LLM-generated post-mortem journal narrative. The
    event is fire-and-forget — handler failures (LLM timeout, budget
    exceeded, Hindsight retain network error) MUST NOT roll back the
    close. Best-effort semantics are documented per-handler.

    ``realised_pnl`` is denormalised onto the event so subscribers that
    feed dashboards / Hindsight metadata don't need a round-trip to
    the trade row.
    """

    event_name: ClassVar[str] = "trading.trade.closed"

    tenant_id: UUID
    trade_id: UUID
    symbol: str
    side: str  # 'buy' | 'sell' (entry side; long vs short)
    quantity: Decimal
    realised_pnl: Decimal
    exit_reason: str  # 'stop' | 'target' | 'manual' | 'expiry'
    closed_at: datetime

    def __post_init__(self) -> None:
        if self.idempotency_key is None:
            # One TradeClosed event per trade — re-deliveries against
            # the same trade_id should be deduped at the bus layer.
            self.idempotency_key = f"trade-closed:{self.trade_id}"


__all__ = [
    "ApprovalRequested",
    "CloseTradeRequested",
    "DaemonDrainRequested",
    "DaemonReconcileRequested",
    "EquityUpdated",
    "ExitApprovalRequested",
    "OrderFilled",
    "OrderPlaced",
    "OrderRejected",
    "ProposalApproved",
    "ProposalCreated",
    "ProposalRejected",
    "ProposalRiskEvaluated",
    "TradeClosed",
]
