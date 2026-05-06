"""Pydantic v2 DTOs for the ``/api/v1/risk/*`` route family + SSE feed.

Per slice K1 design + tasks 5.1: the wire shapes for ``GET /risk/state``,
``POST /risk/override``, and ``/stream/risk/events``. Validation lives at
the DTO level (Pydantic v2 ``Field`` constraints + per-field validators);
service-layer + DB CHECK are the second + third defence layers.

All datetimes serialise as ISO 8601 UTC (Pydantic v2 default for
:class:`datetime`). All monetary values + caps are :class:`Decimal`
(per the project's "Decimal everywhere for money" gotcha).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from iguanatrader.contexts.risk.models import (
    CapType,
    Confirmation,
    ConfirmationChain,
    Outcome,
)


class CapsDTO(BaseModel):
    """Wire shape mirroring :class:`iguanatrader.contexts.risk.models.RiskCaps`.

    Re-declared as a non-frozen DTO so OpenAPI sees it under the
    ``api.dtos.risk`` namespace (Pydantic v2 puts the schema name from
    the *defining* class). The fields match
    :class:`RiskCaps` 1-for-1.
    """

    model_config = ConfigDict(extra="forbid")

    per_trade_pct: Decimal
    daily_loss_pct: Decimal
    weekly_loss_pct: Decimal
    max_open_positions: int
    max_drawdown_pct: Decimal


class StateDTO(BaseModel):
    """Wire shape mirroring :class:`iguanatrader.contexts.risk.models.RiskState`."""

    model_config = ConfigDict(extra="forbid")

    capital: Decimal
    day_to_date_loss_pct: Decimal
    week_to_date_loss_pct: Decimal
    open_positions_count: int
    peak_to_trough_drawdown_pct: Decimal


class RiskStateResponse(BaseModel):
    """``GET /api/v1/risk/state`` response body.

    Returns the active caps + the last-loaded state + the cached
    kill-switch flag. The ``utilisation`` map is a derived view —
    each cap type's current observed utilisation as a Decimal in [0, 1+).
    """

    model_config = ConfigDict(extra="forbid")

    caps: CapsDTO
    state: StateDTO
    utilisation: dict[str, Decimal]
    kill_switch_active: bool
    fetched_at: datetime


class OverrideRequest(BaseModel):
    """``POST /api/v1/risk/override`` request body.

    Per design D5 + spec scenario "Override with 19-char reason rejected
    at service layer": the 20-char floor is enforced at the DTO level
    via ``Field(min_length=20)`` (Pydantic raises 422 with native
    error shape; the service-layer `OverrideAuditMissingError` is the
    fallback for non-DTO entry points like CLI ops).
    """

    model_config = ConfigDict(extra="forbid")

    proposal_id: UUID
    risk_evaluation_id: UUID
    authorised_by_user_id: UUID
    reason_text: str = Field(min_length=20)
    confirmation_chain: ConfirmationChain
    state_snapshot_at_override: dict[str, Any] = Field(default_factory=dict)


class OverrideResponse(BaseModel):
    """``POST /api/v1/risk/override`` 201 response body."""

    model_config = ConfigDict(extra="forbid")

    override_id: UUID
    proposal_id: UUID
    risk_evaluation_id: UUID
    authorised_by_user_id: UUID
    reason_text: str
    confirmation_chain: ConfirmationChain
    created_at: datetime


class RiskEventPayload(BaseModel):
    """Envelope for SSE-streamed ``risk.*`` events.

    The dashboard subscribes to ``GET /api/v1/stream/risk/events`` and
    reads JSON-encoded payloads of this shape. The ``kind`` discriminator
    matches the MessageBus channel name.
    """

    model_config = ConfigDict(extra="allow")

    kind: Literal[
        "risk.proposal.accepted",
        "risk.proposal.rejected",
        "risk.proposal.override_required",
        "risk.kill_switch.activated",
        "risk.kill_switch.deactivated",
    ]
    occurred_at: datetime
    tenant_id: UUID
    # Free-form payload — exact fields depend on ``kind``. Frontend
    # discriminates by ``kind`` and reads the relevant fields.
    proposal_id: UUID | None = None
    evaluation_id: UUID | None = None
    override_id: UUID | None = None
    cap_type_breached: CapType | None = None
    current_pct: Decimal | None = None
    outcome: Outcome | None = None
    source: str | None = None
    actor_user_id: UUID | None = None
    reason: str | None = None


__all__ = [
    "CapsDTO",
    "Confirmation",
    "ConfirmationChain",
    "OverrideRequest",
    "OverrideResponse",
    "RiskEventPayload",
    "RiskStateResponse",
    "StateDTO",
]
