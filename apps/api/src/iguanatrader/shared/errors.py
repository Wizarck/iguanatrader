"""Error hierarchy + RFC 7807 Problem Details serialisation.

Per design decision D4 (slice 2 ``shared-primitives``): one root
:class:`IguanaError` with attributes mirroring RFC 7807 fields
(``type``, ``title``, ``status``, ``detail``, ``instance``). Eight
subclasses cover the HTTP semantic codes the API surfaces today:

============== ====== =================
Subclass       Status Use case
============== ====== =================
``ValidationError``     400  Input failed validation (field, format, type).
``AuthError``           401  Caller not authenticated.
``ForbiddenError``      403  Authenticated but not authorised.
``NotFoundError``       404  Resource does not exist.
``ConflictError``       409  Concurrent update / resource state conflict.
``RateLimitError``      429  Caller exceeded rate quota.
``IntegrationError``    502  Downstream dependency (IBKR, Telegram, …) failed.
``InternalError``       500  Unexpected server-side error.
============== ====== =================

The ``CurrencyMismatchError`` is a thin :class:`ValidationError` subclass
raised by :class:`iguanatrader.shared.types.Money` when arithmetic mixes
currencies; cross-currency math is always a caller bug, hence 400.

The :meth:`IguanaError.to_problem_dict` method returns a dict matching the
RFC 7807 keys exactly (no extras), so the FastAPI exception handler in
slice 5 (``api-foundation-rfc7807``) can serialise directly without
remapping.

Type URIs follow the convention ``urn:iguanatrader:error:<kebab-name>``.
They are stable across refactors of the Python class names — clients
should pattern-match on ``type`` (or ``status``), never on class name.
"""

from __future__ import annotations

from typing import Any, ClassVar


class IguanaError(Exception):
    """Root of the error hierarchy. Maps 1:1 to RFC 7807 Problem Details.

    Subclasses set :attr:`type_uri`, :attr:`default_title`, and
    :attr:`default_status` as class-level constants. Instances may
    override ``title`` (rarely useful), ``detail`` (recommended — the
    human-readable specifics), and ``instance`` (optional — a URI
    identifying the specific occurrence).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:internal"
    default_title: ClassVar[str] = "Internal Error"
    default_status: ClassVar[int] = 500

    def __init__(
        self,
        detail: str | None = None,
        *,
        title: str | None = None,
        status: int | None = None,
        instance: str | None = None,
    ) -> None:
        self.type: str = self.type_uri
        self.title: str = title if title is not None else self.default_title
        self.status: int = status if status is not None else self.default_status
        self.detail: str | None = detail
        self.instance: str | None = instance
        super().__init__(detail or self.title)

    def to_problem_dict(self) -> dict[str, Any]:
        """Return a dict matching the RFC 7807 Problem Details schema.

        Only the canonical keys are emitted. ``detail`` and ``instance``
        are omitted when unset (per RFC 7807 they are optional).
        """
        out: dict[str, Any] = {
            "type": self.type,
            "title": self.title,
            "status": self.status,
        }
        if self.detail is not None:
            out["detail"] = self.detail
        if self.instance is not None:
            out["instance"] = self.instance
        return out


class ValidationError(IguanaError):
    """Input failed validation (HTTP 400)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:validation"
    default_title: ClassVar[str] = "Validation Error"
    default_status: ClassVar[int] = 400


class AuthError(IguanaError):
    """Caller is not authenticated (HTTP 401)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:auth"
    default_title: ClassVar[str] = "Authentication Required"
    default_status: ClassVar[int] = 401


class ForbiddenError(IguanaError):
    """Authenticated but not authorised (HTTP 403)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:forbidden"
    default_title: ClassVar[str] = "Forbidden"
    default_status: ClassVar[int] = 403


class NotFoundError(IguanaError):
    """Resource does not exist (HTTP 404)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:not-found"
    default_title: ClassVar[str] = "Not Found"
    default_status: ClassVar[int] = 404


class ConflictError(IguanaError):
    """Concurrent update or resource-state conflict (HTTP 409)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:conflict"
    default_title: ClassVar[str] = "Conflict"
    default_status: ClassVar[int] = 409


class RateLimitError(IguanaError):
    """Caller exceeded a rate quota (HTTP 429)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:rate-limit"
    default_title: ClassVar[str] = "Too Many Requests"
    default_status: ClassVar[int] = 429


class IntegrationError(IguanaError):
    """Downstream dependency failed (HTTP 502).

    Raised by adapters (IBKR, Telegram, OpenBB sidecar, scrapers, etc.)
    when an external system returns an unexpected error or times out.
    Live-resilience adapters wrap their failures in this class so the
    API layer can surface a uniform 502 response.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:integration"
    default_title: ClassVar[str] = "Bad Gateway"
    default_status: ClassVar[int] = 502


class InternalError(IguanaError):
    """Unexpected server-side error (HTTP 500)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:internal"
    default_title: ClassVar[str] = "Internal Error"
    default_status: ClassVar[int] = 500


class CurrencyMismatchError(ValidationError):
    """Arithmetic on :class:`Money` mixed two different currencies.

    Subclasses :class:`ValidationError` because cross-currency arithmetic
    is always a programmer bug at the call site (HTTP 400).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:currency-mismatch"
    default_title: ClassVar[str] = "Currency Mismatch"
    default_status: ClassVar[int] = 400


__all__ = [
    "AuthError",
    "ConflictError",
    "CurrencyMismatchError",
    "ForbiddenError",
    "IguanaError",
    "IntegrationError",
    "InternalError",
    "NotFoundError",
    "RateLimitError",
    "ValidationError",
]
