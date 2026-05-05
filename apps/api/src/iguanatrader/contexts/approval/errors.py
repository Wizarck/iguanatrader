"""Slice-local IguanaError subclasses for the approval bounded context.

Per cross-slice coordination (slice P1 anti-collision contract): these
errors live HERE — not in ``shared/errors.py`` — so multiple Wave 2
slices can land in parallel without merge conflicts on the shared
errors module. The slice-5 global RFC 7807 handler walks the
:class:`IguanaError` hierarchy and renders any subclass automatically;
location of the subclass declaration is irrelevant for HTTP response
shape.

Type URIs follow the project convention
``urn:iguanatrader:error:<kebab-name>``. Stable across refactors —
clients pattern-match on the URI, never on the Python class name.

Slice-P1-owned errors:

* :class:`ApprovalNotFoundError` (404) — request_id does not exist.
* :class:`ApprovalAlreadyDecidedError` (409) — first-decision-wins;
  raised when ``approval_decisions.request_id`` UNIQUE constraint
  rejects a duplicate INSERT (per design D4).
* :class:`ApprovalExpiredError` (410) — request crossed ``expires_at``
  before any decision was recorded.
* :class:`UnauthorizedSenderError` (403) — channel boundary already
  drops silently (design D6); this class exists for the rare case
  where the dashboard route receives a request whose user has no
  matching ``authorized_senders`` entry.
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import (
    ConflictError,
    ForbiddenError,
    IguanaError,
    NotFoundError,
)


class ApprovalNotFoundError(NotFoundError):
    """No ``approval_requests`` row matches the given id (HTTP 404)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:approval-not-found"
    default_title: ClassVar[str] = "Approval Request Not Found"
    default_status: ClassVar[int] = 404


class ApprovalAlreadyDecidedError(ConflictError):
    """A decision is already recorded for this request (HTTP 409).

    Per design D4: first-decision-wins. The DB UNIQUE constraint on
    ``approval_decisions.request_id`` is the source of truth; the
    service catches :class:`IntegrityError` and raises this. Idempotent
    response — clients SHOULD treat as success and re-read the
    canonical decision row.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:approval-already-decided"
    default_title: ClassVar[str] = "Approval Already Decided"
    default_status: ClassVar[int] = 409


class ApprovalExpiredError(IguanaError):
    """Request's ``expires_at`` has passed without a decision (HTTP 410)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:approval-expired"
    default_title: ClassVar[str] = "Approval Request Expired"
    default_status: ClassVar[int] = 410


class UnauthorizedSenderError(ForbiddenError):
    """Caller is not in ``authorized_senders`` for this tenant + channel.

    Per design D6, the channel boundary drops silently for inbound
    messages from non-whitelisted senders (no echo — anti-enumeration).
    This class is raised only when the dashboard REST surface receives
    a request whose JWT-authenticated user has no matching
    ``authorized_senders`` row (rare — usually :class:`AuthError`
    triggers first).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:unauthorized-sender"
    default_title: ClassVar[str] = "Unauthorized Sender"
    default_status: ClassVar[int] = 403


__all__ = [
    "ApprovalAlreadyDecidedError",
    "ApprovalExpiredError",
    "ApprovalNotFoundError",
    "UnauthorizedSenderError",
]
