"""Global RFC 7807 exception handlers + structured-log breadcrumbs.

Slice 5 (``api-foundation-rfc7807``) per design D3 collapses slice 4's
hand-built ``_problem_response(...)`` helper in :mod:`routes.auth` into
a single FastAPI exception handler chain. Routes raise
:class:`iguanatrader.shared.errors.IguanaError` subclasses; this module
intercepts and renders.

Two handlers are registered, MRO-first per FastAPI / Starlette:

1. :class:`IguanaError` (and subclasses) → :func:`_render_problem`,
   ``application/problem+json`` body via
   :meth:`IguanaError.to_problem_dict`, status from
   :attr:`default_status`.
2. :class:`Exception` fallback → :func:`_render_internal`. Re-raises
   FastAPI's own :class:`HTTPException` and :class:`RequestValidationError`
   so the framework's native 404/422 responses survive (per gotcha #30);
   wraps anything else as :class:`InternalError` (status 500), emits
   structlog ``api.unhandled_exception`` with ``exc_info=True``.

Per AGENTS.md §4 / NFR-O8: every exception path emits a structured-log
breadcrumb so observability stores capture the original cause even when
the response body is the generic 500 form.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from iguanatrader.shared.errors import IguanaError, InternalError

log = structlog.get_logger("iguanatrader.api.errors")

#: Generic ``detail`` for the 500 fallback — never leaks the raw
#: third-party exception message (which could carry stack-trace
#: fragments, file paths, or PII). Operators use the structured log
#: ``api.unhandled_exception`` event to recover the underlying cause.
_INTERNAL_DETAIL = "Unexpected server error."


def _render_problem(request: Request, exc: Exception) -> JSONResponse:
    """Render any :class:`IguanaError` as RFC 7807 Problem Details.

    Per design D3 + spec scenario "Route raises AuthError": serialises
    via :meth:`IguanaError.to_problem_dict`; HTTP status from
    :attr:`status` (overridable per-instance, defaults to the subclass'
    :attr:`default_status`); media type
    ``application/problem+json``.
    """
    if not isinstance(exc, IguanaError):  # pragma: no cover — handler signature guard
        raise TypeError(f"_render_problem received non-IguanaError: {type(exc)!r}")

    return JSONResponse(
        status_code=exc.status,
        content=exc.to_problem_dict(),
        media_type="application/problem+json",
    )


def _render_internal(request: Request, exc: Exception) -> JSONResponse:
    """Fallback for unhandled exceptions — wraps as :class:`InternalError`.

    Per gotcha #30: FastAPI's own :class:`HTTPException` and
    :class:`RequestValidationError` are re-raised so the framework's
    default handlers render their canonical responses (404 for missing
    routes, 422 for Pydantic body-validation failures). Only "true"
    unhandled exceptions (third-party library errors, AssertionErrors
    leaking from routes, etc.) get the 500 + Problem treatment.
    """
    if isinstance(exc, HTTPException | RequestValidationError):
        # Let FastAPI's native handler chain render this. We re-raise so
        # Starlette's exception middleware picks it up; this matches the
        # intent of the spec scenario "FastAPI's own HTTPException passes
        # through" — and avoids clobbering 404/422 into 500 (gotcha #30).
        raise exc

    log.error(
        "api.unhandled_exception",
        exc_info=True,
        path=request.url.path,
        method=request.method,
    )
    wrapped = InternalError(detail=_INTERNAL_DETAIL)
    return JSONResponse(
        status_code=wrapped.status,
        content=wrapped.to_problem_dict(),
        media_type="application/problem+json",
    )


def register_error_handlers(app: FastAPI) -> None:
    """Register the RFC 7807 + fallback handler chain on ``app``.

    Order matters (per design D10): ``IguanaError`` first so subclasses
    are intercepted by the specific Problem renderer; ``Exception``
    fallback second so the breadcrumb-emitting wrapper catches
    everything else.
    """
    app.add_exception_handler(IguanaError, _render_problem)
    app.add_exception_handler(Exception, _render_internal)


__all__ = [
    "register_error_handlers",
]
