"""Pydantic DTOs for the daemon status + toggle + reconcile endpoints.

Slice ``dual-daemon-mode-toggle-and-reconcile``. Mirrored on the
persistence side by :class:`iguanatrader.contexts.trading.repository.DaemonStatusRow`
(dataclass) which the route layer adapts into :class:`DaemonStatusOut`.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class DaemonStatusOut(BaseModel):
    """One row of the ``GET /api/v1/status`` payload (per daemon mode)."""

    mode: str = Field(description="'paper' or 'live'")
    enabled: bool = Field(description="Operator-toggle state for this daemon mode.")
    ib_connected: bool = Field(
        description=(
            "Effective broker-connection state — false if the last "
            "heartbeat is older than 30s OR the daemon reported "
            "ib_connected=false explicitly."
        )
    )
    last_heartbeat_at: datetime | None = Field(
        default=None,
        description="Wall-clock of the most recent daemon heartbeat write; null if the daemon has never written one.",
    )
    last_fill_at: datetime | None = Field(
        default=None,
        description="Wall-clock of the most recent broker fill recorded for this mode; null if no fills exist.",
    )
    pending_proposals_count: int = Field(
        description="Count of trade_proposals.state='pending_approval' for this mode.",
    )


class StatusResponse(BaseModel):
    """Envelope for ``GET /api/v1/status``."""

    daemons: list[DaemonStatusOut]
    fetched_at: datetime = Field(
        description="Server wall-clock at the moment the snapshot was assembled."
    )


class DaemonToggleIn(BaseModel):
    """Request payload for ``POST /api/v1/daemons/{mode}/toggle``."""

    enabled: bool = Field(description="Target enabled-state for this daemon mode.")
    reason: str | None = Field(
        default=None,
        description=(
            "Free-form operator reason for the toggle — recorded in "
            "the audit trail. Required (>=20 chars) for mode='live'; "
            "optional for mode='paper'."
        ),
    )
    password_reconfirm: str | None = Field(
        default=None,
        description=(
            "Operator password — required when toggling LIVE on or off "
            "(server re-verifies via the same Argon2id compare as "
            "login). Ignored for mode='paper'."
        ),
    )


class DaemonToggleOut(BaseModel):
    """Response payload for ``POST /api/v1/daemons/{mode}/toggle``."""

    mode: str
    enabled: bool
    last_toggled_at: datetime
    reason: str | None = None


class DaemonReconcileOut(BaseModel):
    """Response payload for ``POST /api/v1/daemons/{mode}/reconcile`` (202)."""

    mode: str
    correlation_id: str = Field(
        description=(
            "Operator-trace token — flows into the daemon-side reconcile "
            "structlog events. Use to correlate the API request with the "
            "ingestion logs in case of failure investigation."
        )
    )
    accepted_at: datetime


__all__ = [
    "DaemonReconcileOut",
    "DaemonStatusOut",
    "DaemonToggleIn",
    "DaemonToggleOut",
    "StatusResponse",
]
