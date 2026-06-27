"""ApprovalRepository — INSERT-only access to the approval audit trail.

Per slice P1 design + slice 2 :class:`BaseRepository` convention: the
repository reads its session lazily from
:data:`iguanatrader.shared.contextvars.session_var`. Tenant scoping is
automatic via the slice-3 ``tenant_listener`` (writes are stamped with
``tenant_id_var``; reads are filtered by it).

Append-only paths (FR48 + design D5):

* :meth:`create_request` INSERTs an :class:`ApprovalRequest` row.
* :meth:`record_decision` INSERTs an :class:`ApprovalDecision` row.
  Catches :class:`IntegrityError` from the UNIQUE-on-request_id
  constraint and re-raises as :class:`ApprovalAlreadyDecidedError`.
* :meth:`is_sender_authorized` SELECTs from ``authorized_senders`` and
  also returns the matching row's id (so callers can stamp it onto
  decisions).
* :meth:`list_pending` returns all :class:`ApprovalRequest` rows for
  the current tenant that have no matching decision and have not yet
  expired.
* :meth:`sweep_expired` returns expired requests with no decision; the
  service writes a timeout decision row + emits the event.

Hard rule: this slice never UPDATEs or DELETEs against approval tables.
Both tables are append-only; the slice-3 listener will raise
:class:`AppendOnlyViolation` on accidental ORM-driven mutation.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, cast
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from iguanatrader.contexts.approval.channels.types import (
    ApprovalDecisionRow,
    ApprovalRequestRow,
    ChannelKind,
)
from iguanatrader.contexts.approval.errors import ApprovalAlreadyDecidedError
from iguanatrader.contexts.approval.models import (
    ApprovalDecision,
    ApprovalRequest,
)
from iguanatrader.persistence.models import AuthorizedSender
from iguanatrader.shared.contextvars import tenant_id_var
from iguanatrader.shared.kernel import BaseRepository
from iguanatrader.shared.time import now as utc_now


@dataclass(frozen=True, slots=True)
class EnabledSenderRow:
    """In-memory projection of an enabled :class:`AuthorizedSender` row.

    Used by the channel-dispatch binding layer (slice
    ``p1-channel-fanout-production``) to resolve recipients without leaking
    ORM types across the boundary.
    """

    channel: str
    external_id: str
    display_name: str | None


@dataclass(frozen=True, slots=True)
class ResolvedSender:
    """Identity + privilege of an enabled :class:`AuthorizedSender` row.

    Used by the MCP HITL adapter (slice ``mcp-hitl-approvals``) to revalidate
    the operator's ``channel``+``external_id`` and resolve the privilege
    ``role`` from the database — never the request payload.
    """

    id: UUID
    role: str


class ApprovalRepository(BaseRepository):
    """Concrete repository for the approval bounded context."""

    async def create_request(
        self,
        *,
        proposal_id: UUID | None = None,
        delivered_to_channels: list[str],
        timeout_seconds: int,
        action_type: str = "entry",
        trade_id: UUID | None = None,
    ) -> ApprovalRequestRow:
        """INSERT a new :class:`ApprovalRequest` row.

        The slice-3 tenant listener stamps ``tenant_id`` from
        ``tenant_id_var`` automatically; callers MUST run inside a
        ``with_tenant_context(...)`` (or equivalent request scope).

        WS-5 PR-B: ``action_type='exit'`` rows carry ``trade_id`` (the open
        trade to close) and leave ``proposal_id`` NULL; entry rows are the
        existing path (``proposal_id`` set, ``trade_id`` NULL).
        """
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError("tenant_id_var not set; cannot create approval request")
        created_at = utc_now()
        # ``expires_at`` is computed in pure Python so the value is
        # available immediately for fan-out + audit. Database also
        # carries it for the sweeper query.
        from datetime import timedelta

        expires_at = created_at + timedelta(seconds=timeout_seconds)
        row_id = uuid4()
        instance = ApprovalRequest(
            id=row_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            delivered_to_channels=list(delivered_to_channels),
            timeout_seconds=timeout_seconds,
            expires_at=expires_at,
            created_at=created_at,
            action_type=action_type,
            trade_id=trade_id,
        )
        self.session.add(instance)
        await self.session.flush()
        return ApprovalRequestRow(
            id=row_id,
            tenant_id=tenant_id,
            proposal_id=proposal_id,
            delivered_to_channels=list(delivered_to_channels),
            timeout_seconds=timeout_seconds,
            expires_at=expires_at,
            created_at=created_at,
            action_type=action_type,
            trade_id=trade_id,
        )

    async def get_request(self, request_id: UUID) -> ApprovalRequestRow | None:
        """SELECT one ``approval_requests`` row by id."""
        stmt = select(ApprovalRequest).where(ApprovalRequest.id == request_id)
        result = await self.session.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance is None:
            return None
        return self._to_request_row(instance)

    async def record_decision(
        self,
        *,
        request_id: UUID,
        outcome: Literal["granted", "rejected", "timeout"],
        decided_via_channel: ChannelKind,
        decided_by_user_id: UUID | None = None,
        decided_by_sender_id: UUID | None = None,
        latency_ms: int,
    ) -> ApprovalDecisionRow:
        """INSERT one ``approval_decisions`` row.

        Idempotent at the DB layer via ``uq_approval_decisions_request_id``.
        On UNIQUE-constraint violation, raises
        :class:`ApprovalAlreadyDecidedError` (HTTP 409 + RFC 7807) per
        design D4 first-decision-wins.
        """
        tenant_id = tenant_id_var.get()
        if tenant_id is None:
            raise LookupError("tenant_id_var not set; cannot record approval decision")
        created_at = utc_now()
        row_id = uuid4()
        instance = ApprovalDecision(
            id=row_id,
            tenant_id=tenant_id,
            request_id=request_id,
            outcome=outcome,
            decided_via_channel=decided_via_channel,
            decided_by_user_id=decided_by_user_id,
            decided_by_sender_id=decided_by_sender_id,
            latency_ms=latency_ms,
            created_at=created_at,
        )
        self.session.add(instance)
        try:
            await self.session.flush()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ApprovalAlreadyDecidedError(
                detail=(
                    f"Decision already recorded for request {request_id}; " "first-decision-wins."
                ),
            ) from exc
        return ApprovalDecisionRow(
            id=row_id,
            tenant_id=tenant_id,
            request_id=request_id,
            outcome=outcome,
            decided_via_channel=decided_via_channel,
            decided_by_user_id=decided_by_user_id,
            decided_by_sender_id=decided_by_sender_id,
            latency_ms=latency_ms,
            created_at=created_at,
        )

    async def get_decision(self, request_id: UUID) -> ApprovalDecisionRow | None:
        """Return the canonical decision row for a request, or None."""
        stmt = select(ApprovalDecision).where(ApprovalDecision.request_id == request_id)
        result = await self.session.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance is None:
            return None
        return self._to_decision_row(instance)

    async def is_sender_authorized(
        self,
        *,
        tenant_id: UUID,
        channel: Literal["telegram", "whatsapp"],
        external_id: str,
    ) -> tuple[bool, UUID | None]:
        """Return ``(authorized, sender_db_id)`` for the given external id.

        Per design D6: a missing row, a row with ``enabled=False``, or
        a tenant mismatch all return ``(False, None)``. The caller MUST
        silent-drop on ``False`` — no echo, no exception.
        """
        # Cross-tenant lookup at the channel boundary — the bot token
        # already implies a tenant_id; we set it on the contextvar so
        # the slice-3 listener filters correctly.
        stmt = (
            select(AuthorizedSender)
            .where(AuthorizedSender.tenant_id == tenant_id)
            .where(AuthorizedSender.channel == channel)
            .where(AuthorizedSender.external_id == external_id)
            .where(AuthorizedSender.enabled.is_(True))
        )
        result = await self.session.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance is None:
            return (False, None)
        return (True, instance.id)

    async def resolve_enabled_sender(
        self,
        *,
        tenant_id: UUID,
        channel: Literal["telegram", "whatsapp"],
        external_id: str,
    ) -> ResolvedSender | None:
        """Return the enabled sender's ``(id, role)`` or ``None``.

        Role-aware sibling of :meth:`is_sender_authorized` used by the MCP
        HITL adapter (slice ``mcp-hitl-approvals``). A missing row, a
        ``enabled=False`` row, or a tenant mismatch all return ``None`` —
        the caller MUST deny without echoing proposal details. The ``role``
        is read from the DB so the privilege can never be asserted by the
        request payload.
        """
        stmt = (
            select(AuthorizedSender)
            .where(AuthorizedSender.tenant_id == tenant_id)
            .where(AuthorizedSender.channel == channel)
            .where(AuthorizedSender.external_id == external_id)
            .where(AuthorizedSender.enabled.is_(True))
        )
        result = await self.session.execute(stmt)
        instance = result.scalar_one_or_none()
        if instance is None:
            return None
        return ResolvedSender(id=instance.id, role=instance.role)

    async def list_pending(self) -> list[ApprovalRequestRow]:
        """All non-expired requests with no decision for the current tenant."""
        now_dt = utc_now()
        stmt = (
            select(ApprovalRequest)
            .outerjoin(
                ApprovalDecision,
                ApprovalDecision.request_id == ApprovalRequest.id,
            )
            .where(ApprovalDecision.id.is_(None))
            .where(ApprovalRequest.expires_at > now_dt)
            .order_by(ApprovalRequest.created_at.desc())
        )
        result = await self.session.execute(stmt)
        instances = result.scalars().all()
        return [self._to_request_row(i) for i in instances]

    async def has_pending_exit_for_trade(self, trade_id: UUID) -> bool:
        """Return True iff an undecided, unexpired ``action_type='exit'``
        approval request already exists for ``trade_id`` (WS-5 PR-C dedup).

        The urgent-exit sweep calls this before raising a fresh
        :class:`ExitApprovalRequested` so a still-open card is not duplicated
        every 15-minute tick. It is PENDING-AWARE (filters on ``expires_at`` +
        absent decision) rather than relying on the bus idempotency cache,
        which would suppress a legitimate re-raise after a card EXPIRED for the
        whole daemon-process lifetime. Tenant scoping is automatic via the
        slice-3 ``tenant_listener`` reading ``tenant_id_var``.
        """
        now_dt = utc_now()
        stmt = (
            select(ApprovalRequest.id)
            .outerjoin(
                ApprovalDecision,
                ApprovalDecision.request_id == ApprovalRequest.id,
            )
            .where(ApprovalRequest.trade_id == trade_id)
            .where(ApprovalRequest.action_type == "exit")
            .where(ApprovalDecision.id.is_(None))
            .where(ApprovalRequest.expires_at > now_dt)
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.first() is not None

    async def list_enabled_senders(
        self,
        *,
        tenant_id: UUID,
        channels: Sequence[str],
    ) -> list[EnabledSenderRow]:
        """Return enabled ``authorized_senders`` rows for ``tenant_id`` in ``channels``.

        Used by the channel-dispatch binding layer to resolve recipients per
        approval request without coupling to the generic dispatch core.
        Returns the empty list if ``channels`` is empty.
        """
        if not channels:
            return []
        stmt = (
            select(AuthorizedSender)
            .where(AuthorizedSender.tenant_id == tenant_id)
            .where(AuthorizedSender.channel.in_(list(channels)))
            .where(AuthorizedSender.enabled.is_(True))
        )
        result = await self.session.execute(stmt)
        instances = result.scalars().all()
        return [
            EnabledSenderRow(
                channel=row.channel,
                external_id=row.external_id,
                display_name=row.display_name,
            )
            for row in instances
        ]

    async def sweep_expired(self, now: datetime) -> list[ApprovalRequestRow]:
        """All expired requests with no decision (timeout-sweep candidates)."""
        stmt = (
            select(ApprovalRequest)
            .outerjoin(
                ApprovalDecision,
                ApprovalDecision.request_id == ApprovalRequest.id,
            )
            .where(ApprovalDecision.id.is_(None))
            .where(ApprovalRequest.expires_at <= now)
        )
        result = await self.session.execute(stmt)
        instances = result.scalars().all()
        return [self._to_request_row(i) for i in instances]

    @staticmethod
    def _to_request_row(instance: ApprovalRequest) -> ApprovalRequestRow:
        return ApprovalRequestRow(
            id=instance.id,
            tenant_id=instance.tenant_id,
            proposal_id=instance.proposal_id,
            delivered_to_channels=list(instance.delivered_to_channels),
            timeout_seconds=instance.timeout_seconds,
            expires_at=instance.expires_at,
            created_at=instance.created_at,
            delivery_failures=instance.delivery_failures,
            action_type=instance.action_type,
            trade_id=instance.trade_id,
        )

    @staticmethod
    def _to_decision_row(instance: ApprovalDecision) -> ApprovalDecisionRow:
        return ApprovalDecisionRow(
            id=instance.id,
            tenant_id=instance.tenant_id,
            request_id=instance.request_id,
            outcome=cast(
                Literal["granted", "rejected", "timeout"],
                instance.outcome,
            ),
            decided_via_channel=cast(ChannelKind, instance.decided_via_channel),
            decided_by_user_id=instance.decided_by_user_id,
            decided_by_sender_id=instance.decided_by_sender_id,
            latency_ms=instance.latency_ms,
            created_at=instance.created_at,
        )


__all__ = ["ApprovalRepository", "EnabledSenderRow", "ResolvedSender"]
