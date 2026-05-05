"""Typed cross-context events for the ``risk`` bounded context.

Per slice K1 design D6: bounded contexts publish typed events on
:class:`iguanatrader.shared.messagebus.MessageBus`. Approval (P1) and
observability (O1) subscribe via the constants below — they NEVER
``from iguanatrader.contexts.risk import ...`` directly.

Channel-name constants follow the project-wide
``<context>.<entity>.<action>`` convention. Event payload classes are
:class:`dataclass` (so they extend
:class:`iguanatrader.shared.messagebus.Event`), strict on construction,
and carry only the fields downstream consumers need.

Idempotency: every event carries an optional ``idempotency_key``
inherited from :class:`Event`; the kill-switch publishers in
:mod:`iguanatrader.contexts.risk.service` set this to the
``kill_switch_events.id`` so duplicate publishes (e.g. multi-source
activation per design D6 + spec scenario "Multi-source activation
idempotent") collapse on idempotent subscribers.

The ``kw_only=True`` flag on each subclass is required because the
parent :class:`Event` already declares a default for
``idempotency_key`` — without ``kw_only=True``, dataclass would refuse
non-default fields after a defaulted parent field.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import ClassVar
from uuid import UUID

from iguanatrader.contexts.risk.models import (
    CapType,
    KillSwitchSource,
)
from iguanatrader.shared.messagebus import Event

#: MessageBus channel names. Subscribers should import these constants
#: rather than hard-coding strings — keeps the contract searchable.
RISK_PROPOSAL_ACCEPTED: str = "risk.proposal.accepted"
RISK_PROPOSAL_REJECTED: str = "risk.proposal.rejected"
RISK_PROPOSAL_OVERRIDE_REQUIRED: str = "risk.proposal.override_required"
RISK_KILL_SWITCH_ACTIVATED: str = "risk.kill_switch.activated"
RISK_KILL_SWITCH_DEACTIVATED: str = "risk.kill_switch.deactivated"


@dataclass(kw_only=True)
class RiskProposalAccepted(Event):
    """Published when the engine returns ``Decision(outcome="allow")``."""

    channel: ClassVar[str] = RISK_PROPOSAL_ACCEPTED

    proposal_id: UUID
    tenant_id: UUID
    evaluation_id: UUID
    occurred_at: datetime


@dataclass(kw_only=True)
class RiskProposalRejected(Event):
    """Published when the engine returns ``Decision(outcome="reject"|"clip")``."""

    channel: ClassVar[str] = RISK_PROPOSAL_REJECTED

    proposal_id: UUID
    tenant_id: UUID
    evaluation_id: UUID
    cap_type_breached: CapType | None
    current_pct: Decimal | None
    occurred_at: datetime


@dataclass(kw_only=True)
class RiskProposalOverrideRequired(Event):
    """Published when the service-layer recorded an override row."""

    channel: ClassVar[str] = RISK_PROPOSAL_OVERRIDE_REQUIRED

    proposal_id: UUID
    tenant_id: UUID
    override_id: UUID
    authorised_by_user_id: UUID
    occurred_at: datetime


@dataclass(kw_only=True)
class RiskKillSwitchActivated(Event):
    """Published when ``RiskService.activate_kill_switch`` flips ``is_active=True``.

    De-duplicated at the service layer per design D6 + spec scenario
    "Multi-source activation idempotent" — re-publish only on the
    transition False→True, never on the no-op True→True.
    """

    channel: ClassVar[str] = RISK_KILL_SWITCH_ACTIVATED

    tenant_id: UUID
    event_id: UUID
    source: KillSwitchSource
    actor_user_id: UUID | None
    reason: str | None
    occurred_at: datetime


@dataclass(kw_only=True)
class RiskKillSwitchDeactivated(Event):
    """Counterpart of :class:`RiskKillSwitchActivated`."""

    channel: ClassVar[str] = RISK_KILL_SWITCH_DEACTIVATED

    tenant_id: UUID
    event_id: UUID
    source: KillSwitchSource
    actor_user_id: UUID | None
    reason: str | None
    occurred_at: datetime


__all__ = [
    "RISK_KILL_SWITCH_ACTIVATED",
    "RISK_KILL_SWITCH_DEACTIVATED",
    "RISK_PROPOSAL_ACCEPTED",
    "RISK_PROPOSAL_OVERRIDE_REQUIRED",
    "RISK_PROPOSAL_REJECTED",
    "RiskKillSwitchActivated",
    "RiskKillSwitchDeactivated",
    "RiskProposalAccepted",
    "RiskProposalOverrideRequired",
    "RiskProposalRejected",
]
