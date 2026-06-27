"""Cross-channel value types — :class:`IncomingCommand`, :class:`CommandSpec`,
:class:`CommandContext`, :class:`CommandResult`.

These types are the canonical wire-format-independent shapes used by
the dispatcher (:mod:`command_handler`) and every command handler
(:mod:`commands.<name>`). Transport adapters normalise their native
inbound payloads (Telegram update JSON, Meta Cloud API webhook JSON,
dashboard REST body) into :class:`IncomingCommand` and forward to
:func:`dispatch`.

All datetimes are ISO 8601 UTC per project convention
(:func:`iguanatrader.shared.time.now`).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

#: Discriminated channel identifier — also the value stored in
#: ``approval_decisions.decided_via_channel``. ``"system"`` is reserved
#: for non-user-driven decisions (e.g. operator CLI overrides) and is
#: not a transport adapter.
ChannelKind = Literal["telegram", "whatsapp", "dashboard", "timeout", "system"]

#: Required-role discriminator for command authorization.
RequiredRole = Literal["admin", "user"]

#: Where the dispatcher derives the idempotency key from. ``"request_id"``
#: keys off the per-approval-request UUID (used by /approve, /reject —
#: enforced by the DB UNIQUE constraint per design D4). ``"payload"``
#: builds a tuple key from command-specific fields (admin commands like
#: /halt use ``(command, sender_id, minute_bucket)``). ``"none"`` means
#: read-only — no idempotency check.
IdempotencyKeySource = Literal["payload", "request_id", "none"]


@dataclass(frozen=True)
class IncomingCommand:
    """Normalised inbound command — transport-independent.

    Attributes:

    * ``command_name``: includes the leading slash (e.g. ``"/approve"``)
      to keep parity with the user-facing surface.
    * ``raw_args``: the literal argument string after the command name;
      may be empty.
    * ``sender_external_id``: native channel identifier (Telegram user
      ID, WhatsApp phone number, dashboard JWT subject UUID).
    * ``channel``: which adapter received the command — values from
      :data:`ChannelKind` excluding ``"timeout"``/``"system"``.
    * ``tenant_id``: tenant resolved from the bot token (telegram /
      whatsapp) or from the JWT (dashboard).
    * ``idempotency_key``: native at-most-once token from the wire
      (Telegram callback_query_id, WhatsApp interactive_id) — used by
      the dispatcher to dedupe at the application layer in addition to
      the DB UNIQUE constraint.
    * ``request_id``: target ``approval_requests.id`` when applicable
      (only for /approve, /reject, /override).
    """

    command_name: str
    raw_args: str
    sender_external_id: str
    channel: Literal["telegram", "whatsapp", "dashboard"]
    tenant_id: UUID
    idempotency_key: str | None = None
    request_id: UUID | None = None
    sender_db_id: UUID | None = None
    user_db_id: UUID | None = None
    #: Caller's role, resolved by the channel adapter from the
    #: ``users.role`` column (dashboard) or the ``authorized_senders``
    #: row's role facet (bot channels — slice O1 follow-up adds the
    #: column; until then, bot senders default to ``"user"``).
    role: RequiredRole = "user"


@dataclass(frozen=True)
class CommandResult:
    """Output of every command handler. Renderable to any wire format.

    ``status`` discriminator:

    * ``"ok"`` — handler succeeded; ``message`` carries human-readable
      output for the channel to render.
    * ``"denied"`` — required role mismatch.
    * ``"unknown_command"`` — dispatcher received a command not in the
      registry.
    * ``"error"`` — handler raised; ``message`` carries the error
      detail. The transport adapter decides whether to echo to the
      user or to silent-drop (e.g. structured 5xx is silent-drop on
      Telegram so we don't spam the user with stack traces).
    """

    status: Literal["ok", "denied", "unknown_command", "error"]
    message: str
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandContext:
    """Bag of dependencies passed to every command handler.

    The handler reads what it needs and ignores the rest. Adding a new
    dependency is a single edit (here + in the dispatcher's
    construction site) — handlers don't need to update.
    """

    incoming: IncomingCommand
    #: Optional service handle — concrete handlers may need the
    #: :class:`ApprovalService` to record decisions, sweep expired
    #: requests, etc. Typed :class:`Any` here to break what would
    #: otherwise be a circular import (service → command_handler →
    #: types → service).
    service: Any
    #: The slice-2 :class:`MessageBus` for cross-context events.
    message_bus: Any
    #: Optional repository handle for read-only commands.
    repository: Any | None = None


@dataclass(frozen=True)
class CommandSpec:
    """Metadata + handler reference for one of the 17 canonical commands.

    Per design D2 + spec ``approval`` Requirement 1. Each command lives
    in its own module under :mod:`commands.<name>`; the
    :func:`pkgutil.iter_modules` registry discovery in
    :mod:`commands.__init__` reads ``SPEC`` from each module and folds
    into the canonical ``COMMANDS`` mapping.
    """

    name: str
    handler: Callable[[CommandContext], Awaitable[CommandResult]]
    required_role: RequiredRole
    idempotency_key_source: IdempotencyKeySource
    description_md: str
    #: #31: when True, the dispatcher denies this command while the
    #: tenant's ``approvals_paused`` feature flag is set (operator
    #: ``/lock``). Set on the trade-actuating commands (/approve,
    #: /override) only — resolving commands like /reject still flow so a
    #: paused operator can clear the backlog. Defaults False so every
    #: existing spec is unaffected.
    blocked_when_paused: bool = False


@dataclass
class ApprovalRequestRow:
    """In-memory projection of an :class:`ApprovalRequest` row.

    The service path returns this DTO rather than the SQLAlchemy
    instance to keep the surface purely read-only and decoupled from
    session lifetime.
    """

    id: UUID
    tenant_id: UUID
    proposal_id: UUID | None
    delivered_to_channels: list[str]
    timeout_seconds: int
    expires_at: datetime
    created_at: datetime
    delivery_failures: list[dict[str, Any]] | None = None
    # WS-5 PR-B: 'entry' (open a position) or 'exit' (close trade_id). The
    # granted bridge is fail-closed on action_type.
    action_type: str = "entry"
    trade_id: UUID | None = None


@dataclass
class ApprovalDecisionRow:
    """In-memory projection of an :class:`ApprovalDecision` row."""

    id: UUID
    tenant_id: UUID
    request_id: UUID
    outcome: Literal["granted", "rejected", "timeout"]
    decided_via_channel: ChannelKind
    decided_by_user_id: UUID | None
    decided_by_sender_id: UUID | None
    latency_ms: int
    created_at: datetime


__all__ = [
    "ApprovalDecisionRow",
    "ApprovalRequestRow",
    "ChannelKind",
    "CommandContext",
    "CommandResult",
    "CommandSpec",
    "IdempotencyKeySource",
    "IncomingCommand",
    "RequiredRole",
]
