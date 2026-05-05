"""Event-name + idempotency-key conventions for trading-context events.

Per design D3 each event class declares ``event_name`` matching the
``<context>.<entity>.<action>`` structlog convention, carries
``tenant_id`` explicitly, and sets ``idempotency_key`` from the entity
PK in :meth:`__post_init__`.
"""

from __future__ import annotations

from uuid import uuid4

from iguanatrader.contexts.trading.events import (
    ApprovalRequested,
    EquityUpdated,
    OrderFilled,
    OrderPlaced,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalRiskEvaluated,
)

CANONICAL_NAMES: dict[type, str] = {
    ProposalCreated: "trading.proposal.created",
    ProposalRiskEvaluated: "trading.proposal.risk_evaluated",
    ApprovalRequested: "trading.approval.requested",
    ProposalApproved: "trading.proposal.approved",
    ProposalRejected: "trading.proposal.rejected",
    OrderPlaced: "trading.order.placed",
    OrderFilled: "trading.order.filled",
    EquityUpdated: "trading.equity.updated",
}


def test_event_names_match_convention() -> None:
    for cls, expected in CANONICAL_NAMES.items():
        # `event_name` is declared `ClassVar[str]` on each Event subclass.
        # The dict's value type is `type` (parent of all subclasses);
        # mypy can't statically prove `event_name` is on every entry.
        # `getattr` keeps the runtime check intact + silences mypy.
        actual = getattr(cls, "event_name", None)
        assert actual == expected, f"{cls.__name__}.event_name != {expected!r}"


def test_proposal_created_idempotency_key_is_proposal_id() -> None:
    pid = uuid4()
    ev = ProposalCreated(
        tenant_id=uuid4(),
        proposal_id=pid,
        symbol="SPY",
        strategy_kind="donchian_atr",
        strategy_version=1,
        correlation_id=uuid4(),
    )
    assert ev.idempotency_key == str(pid)


def test_order_placed_idempotency_key_is_order_id() -> None:
    oid = uuid4()
    ev = OrderPlaced(
        tenant_id=uuid4(),
        order_id=oid,
    )
    assert ev.idempotency_key == str(oid)


def test_order_filled_idempotency_key_is_fill_id() -> None:
    fid = uuid4()
    ev = OrderFilled(
        tenant_id=uuid4(),
        order_id=uuid4(),
        fill_id=fid,
    )
    assert ev.idempotency_key == str(fid)


def test_metadata_defaults_to_empty_dict() -> None:
    ev = ProposalCreated(
        tenant_id=uuid4(),
        proposal_id=uuid4(),
        symbol="SPY",
        strategy_kind="donchian_atr",
        strategy_version=1,
        correlation_id=uuid4(),
    )
    assert ev.metadata == {}
    assert (
        ev.metadata
        is not ProposalCreated(
            tenant_id=uuid4(),
            proposal_id=uuid4(),
            symbol="SPY",
            strategy_kind="donchian_atr",
            strategy_version=1,
            correlation_id=uuid4(),
        ).metadata
    )


def test_tenant_id_is_required_field() -> None:
    """Constructing without ``tenant_id`` should raise (kw_only dataclass)."""
    import pytest

    with pytest.raises(TypeError):
        # Missing required tenant_id keyword.
        ProposalApproved(proposal_id=uuid4())  # type: ignore[call-arg]


def test_equity_updated_idempotency_from_snapshot_id() -> None:
    sid = uuid4()
    ev = EquityUpdated(tenant_id=uuid4(), equity_snapshot_id=sid)
    assert ev.idempotency_key == str(sid)


def test_proposal_rejected_carries_reason() -> None:
    ev = ProposalRejected(
        tenant_id=uuid4(),
        proposal_id=uuid4(),
        reason="risk_cap_breached",
    )
    assert ev.reason == "risk_cap_breached"
    assert ev.idempotency_key is not None
