"""Global RFC 7807 exception handlers + structured-log breadcrumbs.

Slice 5 (``api-foundation-rfc7807``) per design D3 collapses slice 4's
hand-built ``_problem_response(...)`` helper in :mod:`routes.auth` into
a single FastAPI exception handler chain. Routes raise
:class:`iguanatrader.shared.errors.IguanaError` subclasses; this module
intercepts and renders.

Two layers handle exceptions:

1. :class:`IguanaError` (and subclasses) → :func:`_render_problem`, run
   inside Starlette's :class:`ExceptionMiddleware`. Body is
   ``application/problem+json`` via :meth:`IguanaError.to_problem_dict`;
   status from :attr:`status` (overridable per-instance, defaults to
   the subclass' :attr:`default_status`).
2. :class:`InternalErrorMiddleware` — an outer ASGI wrapper installed
   as the OUTERMOST user middleware (closest to
   :class:`ServerErrorMiddleware`). Catches any :class:`Exception` that
   escaped :class:`ExceptionMiddleware` (i.e. anything not matched by a
   specific handler) and renders the generic 500 RFC 7807 Problem.

   Why a wrapping middleware instead of ``app.add_exception_handler(Exception, ...)``:
   FastAPI's :meth:`build_middleware_stack` extracts handlers keyed on
   ``Exception`` (or status 500) out of :class:`ExceptionMiddleware`
   and onto :class:`ServerErrorMiddleware.handler`.
   ``ServerErrorMiddleware`` *always re-raises* after sending the
   response (intentional, so ASGI servers can log the underlying
   cause). That re-raise is propagated by ``httpx.ASGITransport`` to
   the test client, which surfaces the raw :class:`ValueError` instead
   of the rendered 500 — exactly the failure mode of
   ``test_error_rendering.py::test_unhandled_exception_wrapped_as_internal_500``
   before this fix. Registering against :class:`BaseException` looks
   like a one-line workaround but Starlette's
   ``ExceptionMiddleware.add_exception_handler`` asserts
   ``issubclass(cls, Exception)`` and rejects it. A wrapping middleware
   sidesteps both the bypass logic and the re-raise.

Per AGENTS.md §4 / NFR-O8: every exception path emits a structured-log
breadcrumb so observability stores capture the original cause even when
the response body is the generic 500 form.
"""

from __future__ import annotations

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

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


class InternalErrorMiddleware:
    """Pure-ASGI wrapper that renders any unhandled exception as 500 Problem.

    Catches what Starlette's :class:`ExceptionMiddleware` re-raises when
    no specific handler matches (i.e. anything that isn't
    :class:`IguanaError`, :class:`HTTPException`,
    :class:`RequestValidationError`, or another type with a registered
    handler) and renders the generic 500 RFC 7807 Problem.

    Installed via :func:`register_error_handlers` as the OUTERMOST user
    middleware so it sits just inside
    :class:`starlette.middleware.errors.ServerErrorMiddleware` — the
    exception is intercepted BEFORE ``ServerErrorMiddleware``'s
    intentional re-raise can clobber the response. Non-HTTP scopes
    pass through unchanged.

    Single-exception :class:`ExceptionGroup` wrappers are unwrapped for
    logging so the structured log carries the original exception class
    instead of the group wrapper (Python 3.13 ``BaseHTTPMiddleware``
    can produce these via ``anyio.create_task_group``).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def _send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            if response_started:
                # Already past the status line — can't replace the
                # response. Let the exception propagate so the ASGI
                # server (or test client) can log the partial-response
                # failure. Production never hits this branch because
                # IguanaError + ExceptionMiddleware handle every
                # path-handler error before any bytes go out.
                raise

            unwrapped: BaseException = exc
            while isinstance(unwrapped, ExceptionGroup) and len(unwrapped.exceptions) == 1:
                unwrapped = unwrapped.exceptions[0]

            log.error(
                "api.unhandled_exception",
                exc_info=(type(unwrapped), unwrapped, unwrapped.__traceback__),
                path=scope.get("path", ""),
                method=scope.get("method", "").upper(),
            )
            wrapped = InternalError(detail=_INTERNAL_DETAIL)
            response = JSONResponse(
                status_code=wrapped.status,
                content=wrapped.to_problem_dict(),
                media_type="application/problem+json",
            )
            await response(scope, receive, send)


def register_error_handlers(app: FastAPI) -> None:
    """Register the RFC 7807 + fallback handler chain on ``app``.

    Two-layer setup:

    * ``IguanaError`` handler is registered with FastAPI so
      ``ExceptionMiddleware`` renders subclasses as Problem responses.
    * :class:`InternalErrorMiddleware` is installed via
      ``app.add_middleware`` so the OUTERMOST user middleware catches
      anything else. We deliberately do NOT register an
      ``Exception``-keyed handler — FastAPI would move it onto
      :class:`ServerErrorMiddleware.handler`, which always re-raises
      after sending (clobbering the rendered 500 for test clients and
      ASGI servers alike). See the module docstring for the full
      rationale.

    ``add_middleware`` must run before the first request — FastAPI
    finalises the middleware stack lazily on the first request and
    further ``add_middleware`` calls would raise after that.
    """
    app.add_exception_handler(IguanaError, _render_problem)
    app.add_middleware(InternalErrorMiddleware)


__all__ = [
    "InternalErrorMiddleware",
    "register_error_handlers",
]
