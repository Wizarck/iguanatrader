"""Pydantic v2 DTOs for the approval surface.

Per slice P1 design + slice 5 typegen pipeline: every model declared
here lands in OpenAPI's ``components/schemas`` and is regenerated as a
TypeScript interface in ``packages/shared-types/src/index.ts`` on the
next CI push (no manual coordination needed).

All datetimes serialise as ISO 8601 UTC (Pydantic v2 default for
:class:`datetime`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApprovalRequest(BaseModel):
    """A pending approval-fan-out row (read-only projection)."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    # NULL for exit-approval rows (WS-5 PR-B) — those carry ``trade_id``.
    proposal_id: UUID | None = None
    delivered_to_channels: list[str]
    timeout_seconds: int = Field(gt=0)
    expires_at: datetime
    created_at: datetime
    delivery_failures: list[dict[str, Any]] | None = None
    # WS-5 PR-B: 'entry' (open a position) or 'exit' (close ``trade_id``).
    action_type: str = "entry"
    trade_id: UUID | None = None


class ApprovalDecision(BaseModel):
    """An outcome row in the append-only audit table."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tenant_id: UUID
    request_id: UUID
    outcome: Literal["granted", "rejected", "timeout"]
    decided_via_channel: Literal[
        "telegram",
        "whatsapp",
        "dashboard",
        "timeout",
        "system",
    ]
    decided_by_user_id: UUID | None = None
    decided_by_sender_id: UUID | None = None
    latency_ms: int = Field(ge=0)
    created_at: datetime


class ApprovalCommandResult(BaseModel):
    """Generic command-handler result for cross-transport responses."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "denied", "unknown_command", "error"]
    message: str
    extra: dict[str, Any] | None = None


class IncomingCommandDto(BaseModel):
    """Dashboard's POST shape — normalised inbound command from a UI form.

    The dashboard builds this DTO from a form submission and sends to
    ``POST /api/v1/approvals/{id}/{approve|reject}``; the route handler
    constructs an :class:`IncomingCommand` and calls ``dispatch``.
    """

    model_config = ConfigDict(extra="forbid")

    command_name: Literal[
        "/approve",
        "/reject",
        "/halt",
        "/resume",
        "/status",
        "/positions",
        "/equity",
        "/strategies",
        "/risk",
        "/override",
        "/cost",
        "/budget",
        "/help",
        "/whoami",
        "/lock",
        "/unlock",
        "/logout",
    ]
    raw_args: str = ""
    request_id: UUID | None = None
    idempotency_key: str | None = None


class RejectionRequest(BaseModel):
    """Body for ``POST /approvals/{id}/reject`` — optional reason text."""

    model_config = ConfigDict(extra="forbid")

    reason: str | None = None


__all__ = [
    "ApprovalCommandResult",
    "ApprovalDecision",
    "ApprovalRequest",
    "IncomingCommandDto",
    "RejectionRequest",
]
