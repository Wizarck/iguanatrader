"""Cross-context events emitted by the approval bounded context.

Per slice P1 design D7 + slice 2 :class:`MessageBus` convention
``<context>.<entity>.<action>``. Three events, one per outcome:

* :class:`ApprovalProposalApproved` — outcome=granted; trading T2/T4
  subscribes; this is the trigger to call
  :func:`BrokerPort.place_order`.
* :class:`ApprovalProposalRejected` — outcome=rejected; trading marks
  the proposal terminal.
* :class:`ApprovalProposalTimedOut` — outcome=timeout; trading marks
  proposal auto-discarded (FR13).

The slice-2 MessageBus guarantees per-subscriber FIFO ordering;
idempotency is the consumer's responsibility (T2/T4 will use
``proposal_id`` as the dedup key).

Three string constants (``APPROVAL_PROPOSAL_*``) are also exported as
the canonical event names — used by structlog log lines that mirror
the bus event vocabulary so log/event correlation is byte-grep-able.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID

from iguanatrader.shared.messagebus import Event

#: Canonical event-name strings (mirrored in structlog event names so
#: ``approval.proposal.approved`` finds both the bus emission and the
#: logged confirmation in a single grep).
APPROVAL_PROPOSAL_APPROVED: Final[str] = "approval.proposal.approved"
APPROVAL_PROPOSAL_REJECTED: Final[str] = "approval.proposal.rejected"
APPROVAL_PROPOSAL_TIMED_OUT: Final[str] = "approval.proposal.timed_out"


@dataclass
class ApprovalProposalApproved(Event):
    """Outcome=granted. Trading service kicks off broker order placement.

    ``decided_by_user_id`` is populated for dashboard channel; NULL for
    telegram/whatsapp (where ``decided_by_sender_id`` is populated
    instead — the bus event keeps user_id only for forensics, channel
    is the canonical actor field).
    """

    proposal_id: UUID | None = None
    decision_id: UUID | None = None
    decided_at: datetime | None = None
    decided_by_user_id: UUID | None = None
    decided_via_channel: str | None = None


@dataclass
class ApprovalProposalRejected(Event):
    """Outcome=rejected. Trading marks proposal terminal."""

    proposal_id: UUID | None = None
    decision_id: UUID | None = None
    decided_at: datetime | None = None
    reason: str | None = None
    decided_via_channel: str | None = None


@dataclass
class ApprovalProposalTimedOut(Event):
    """Outcome=timeout. Trading auto-discards (FR13)."""

    proposal_id: UUID | None = None
    request_id: UUID | None = None
    expired_at: datetime | None = None


__all__ = [
    "APPROVAL_PROPOSAL_APPROVED",
    "APPROVAL_PROPOSAL_REJECTED",
    "APPROVAL_PROPOSAL_TIMED_OUT",
    "ApprovalProposalApproved",
    "ApprovalProposalRejected",
    "ApprovalProposalTimedOut",
]
