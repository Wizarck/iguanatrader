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


# Added 2026-05-05 by slice 5 (api-foundation-rfc7807) per design D9 to
# canonicalise the slice-4 inline 503 zero-tenant Problem (which used a
# URL-form ``type`` URI ``https://iguanatrader.local/problems/...``) onto
# the project-wide ``urn:iguanatrader:error:*`` scheme. Semantically
# equivalent to slice-4's inline 503 — same wire status + body shape;
# only the ``type`` URI changes form.
class BootstrapNotReadyError(IguanaError):
    """API booted but the ``tenants`` table is empty (HTTP 503).

    Raised by ``POST /api/v1/auth/login`` (and any future endpoint that
    requires an authenticated tenant) when the operator has not yet run
    ``iguanatrader admin bootstrap-tenant <slug>`` to create the first
    tenant + admin user. The handler renders RFC 7807 with the canonical
    urn-form ``type`` URI; the ``detail`` carries the operator-facing
    CLI hint.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:not-bootstrapped"
    default_title: ClassVar[str] = "Service Not Bootstrapped"
    default_status: ClassVar[int] = 503


# Added 2026-05-05 by slice T1 (trading-models-interfaces) per design D6
# to express stub-only routes that are part of the public OpenAPI
# surface but whose bodies are scheduled for a later slice (T4 owns the
# trading routes' real bodies). Mirrors the slice-5 D9 precedent of
# rectifying a status-code-canonicalisation gap with one new IguanaError
# subclass; will no longer be raised once T4 ships the real route
# bodies.
class NotImplementedFeatureError(IguanaError):
    """Endpoint or feature is intentionally unimplemented (HTTP 501).

    Raised by the trading route stubs in
    :mod:`iguanatrader.api.routes.trades` (and siblings) so consumers
    see a uniform RFC 7807 Problem with type
    ``urn:iguanatrader:error:not-implemented`` until slice T4 lands the
    real bodies. The handler attaches the canonical urn-form ``type``
    URI; the ``detail`` field SHOULD name the slice that will land the
    implementation, e.g. ``"... will be wired in slice T4
    (trading-routes-and-daemon)."``
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:not-implemented"
    default_title: ClassVar[str] = "Feature Not Implemented"
    default_status: ClassVar[int] = 501


# Added 2026-05-05 by slice K1 (risk-engine-protections) per tasks.md 1.4.
# These three subclasses extend the project-wide ``IguanaError`` hierarchy
# so the slice-5 global handler renders them as RFC 7807 ``application/
# problem+json`` automatically — no per-route try/except wiring needed.
class RiskCapBreachedError(IguanaError):
    """Risk evaluation produced a non-allow Decision (HTTP 400).

    Raised by service-layer / route helpers when a synchronous caller
    asks "did this proposal pass?" and the engine returned reject /
    clip. The ``detail`` carries the breached cap name + observed
    utilisation. Auto-activation of the kill-switch (per design D6)
    lives in ``RiskService``; this error class is only the wire shape.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:risk-cap-breached"
    default_title: ClassVar[str] = "Risk Cap Breached"
    default_status: ClassVar[int] = 400


class KillSwitchActiveError(IguanaError):
    """Caller attempted a trade-evaluation while kill-switch is active (HTTP 409).

    Raised by ``RiskService.evaluate_proposal`` BEFORE the engine is
    called, by reading the cached ``kill_switch_state.is_active`` flag.
    The caller (TradingService / CLI / channel handler) surfaces this
    as a uniform 409 + Problem body with the activation reason in
    ``detail`` (when the operator supplied one).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:risk-kill-switch-active"
    default_title: ClassVar[str] = "Kill Switch Active"
    default_status: ClassVar[int] = 409


class OverrideAuditMissingError(ValidationError):
    """Override audit fields missing or below NFR-S5 floor (HTTP 400).

    Subclasses :class:`ValidationError` (per design D5 contract — the
    20-char floor + mandatory recorded_by + mandatory confirmation_chain
    are validation invariants) so existing 400-handlers continue to work.
    The ``type_uri`` differentiates this from a generic field validation
    failure so dashboards can surface a specific "audit fields missing"
    UX hint without parsing ``detail``.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:risk-override-audit-missing"
    default_title: ClassVar[str] = "Override Audit Missing"
    default_status: ClassVar[int] = 400


# Added 2026-05-13 by slice ``auth-change-password`` per proposal §Errors.
# Two new URN types:
#
# * ``AuthMismatchError`` — raised by ``POST /api/v1/auth/change-password``
#   when ``old_password`` does not match the stored hash. Distinct from the
#   generic :class:`AuthError` so the change-password UI can render a
#   specific "wrong current password" message without parsing ``detail``.
# * ``PasswordChangeRequiredError`` — raised by the
#   :mod:`must_change_password` middleware when an authenticated user with
#   ``must_change_password=True`` hits any non-allow-listed route. 403,
#   not 401: the user IS authenticated; they're just gated.
class AuthMismatchError(IguanaError):
    """Submitted credentials did not match stored hash (HTTP 401).

    Distinguished from the generic :class:`AuthError` so the
    change-password UI can render a route-specific "current password is
    wrong" message instead of the generic "Authentication Required"
    copy. The wire status is still 401 — same handler chain renders the
    Problem body via :meth:`IguanaError.to_problem_dict`.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:auth-mismatch"
    default_title: ClassVar[str] = "Authentication Mismatch"
    default_status: ClassVar[int] = 401


class PasswordChangeRequiredError(IguanaError):
    """Authenticated user has ``must_change_password=True`` (HTTP 403).

    Raised by :class:`MustChangePasswordMiddleware` when the user has
    not yet rotated their provisional credential. The handler chain
    renders the Problem body with the canonical URN type so frontends
    can recognise the gate and redirect to ``/account/change-password``
    without parsing ``detail`` (the SvelteKit ``hooks.server.ts`` reads
    ``must_change_password`` directly off ``/auth/me`` for the same
    purpose; this error class exists for API-only consumers).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:password-change-required"
    default_title: ClassVar[str] = "Password Change Required"
    default_status: ClassVar[int] = 403


__all__ = [
    "AuthError",
    "AuthMismatchError",
    "BootstrapNotReadyError",
    "ConflictError",
    "CurrencyMismatchError",
    "ForbiddenError",
    "IguanaError",
    "IntegrationError",
    "InternalError",
    "KillSwitchActiveError",
    "NotFoundError",
    "NotImplementedFeatureError",
    "OverrideAuditMissingError",
    "PasswordChangeRequiredError",
    "RateLimitError",
    "RiskCapBreachedError",
    "ValidationError",
]
