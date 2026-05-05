"""Slice 5 — global RFC 7807 + ``Exception`` fallback handler tests.

Covers the spec ``api-foundation`` requirements:

* ``IguanaError`` subclass raised inside a route → RFC 7807 body shape
  + ``application/problem+json`` content type + status from
  :attr:`default_status`.
* Unhandled :class:`ValueError` (or any non-IguanaError, non-FastAPI
  exception) → 500 + Problem; structlog ``api.unhandled_exception`` event.
* FastAPI's :class:`HTTPException` passes through unchanged (native body
  shape, not Problem).
* :class:`RequestValidationError` (Pydantic 422) passes through unchanged.
* :class:`BootstrapNotReadyError` renders with the canonical
  ``urn:iguanatrader:error:not-bootstrapped`` type URI (slice 5 D9).

The tests build a fresh FastAPI app via :func:`create_app` and mount
test-only stub routes that raise on demand. They do NOT need the
slice-4 auth surface — only the global handler chain registered by
:func:`register_error_handlers`.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from iguanatrader.api.app import create_app
from iguanatrader.shared.errors import (
    AuthError,
    BootstrapNotReadyError,
    ValidationError,
)
from pydantic import BaseModel


@pytest.fixture
def app_with_test_routes() -> FastAPI:
    """FastAPI app with stub routes that raise on demand."""
    app = create_app()

    @app.get("/_test/raise-auth")
    async def _raise_auth() -> None:
        raise AuthError(detail="Not authenticated")

    @app.get("/_test/raise-validation")
    async def _raise_validation() -> None:
        raise ValidationError(detail="email is required")

    @app.get("/_test/raise-bootstrap")
    async def _raise_bootstrap() -> None:
        raise BootstrapNotReadyError(detail="Run iguanatrader admin bootstrap-tenant <slug>")

    @app.get("/_test/raise-value-error")
    async def _raise_value_error() -> None:
        # Unhandled non-IguanaError → wrapped as InternalError 500.
        int("not-a-number")

    @app.get("/_test/raise-http-exception")
    async def _raise_http_exception() -> None:
        # FastAPI's own exception. Our Exception fallback re-raises so
        # FastAPI's native handler renders it.
        raise HTTPException(status_code=418, detail="I'm a teapot")

    class _Body(BaseModel):
        email: str

    @app.post("/_test/validate-body")
    async def _validate_body(body: _Body) -> dict[str, str]:
        return {"email": body.email}

    return app


@pytest.fixture
async def client(app_with_test_routes: FastAPI):
    transport = ASGITransport(app=app_with_test_routes)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        yield c


async def test_iguana_error_subclass_renders_as_rfc7807(client: AsyncClient) -> None:
    """``raise AuthError(...)`` → 401 + Problem body."""
    resp = await client.get("/_test/raise-auth")

    assert resp.status_code == 401
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body == {
        "type": "urn:iguanatrader:error:auth",
        "title": "Authentication Required",
        "status": 401,
        "detail": "Not authenticated",
    }


async def test_validation_error_renders_with_400(client: AsyncClient) -> None:
    """``raise ValidationError(...)`` → 400 + Problem body."""
    resp = await client.get("/_test/raise-validation")

    assert resp.status_code == 400
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:validation"
    assert body["status"] == 400


async def test_bootstrap_not_ready_renders_canonical_urn_type(client: AsyncClient) -> None:
    """Slice 5 D9 — type URI scheme is ``urn:iguanatrader:error:not-bootstrapped``."""
    resp = await client.get("/_test/raise-bootstrap")

    assert resp.status_code == 503
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:not-bootstrapped"
    assert body["title"] == "Service Not Bootstrapped"
    assert body["status"] == 503
    assert "iguanatrader admin bootstrap-tenant" in body["detail"]


async def test_unhandled_exception_wrapped_as_internal_500(client: AsyncClient) -> None:
    """Unhandled :class:`ValueError` → 500 + Problem; raw text NOT leaked."""
    resp = await client.get("/_test/raise-value-error")

    assert resp.status_code == 500
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["type"] == "urn:iguanatrader:error:internal"
    assert body["title"] == "Internal Error"
    assert body["status"] == 500
    # Generic detail — never leaks the raw ValueError message.
    assert body["detail"] == "Unexpected server error."
    assert "not-a-number" not in body.get("detail", "")


async def test_fastapi_http_exception_passes_through(client: AsyncClient) -> None:
    """FastAPI's :class:`HTTPException` renders via the framework's handler.

    Body is the native ``{"detail": "..."}`` shape, not the Problem
    schema. The fallback ``Exception`` handler re-raises so Starlette's
    exception middleware picks it up (per gotcha #30).
    """
    resp = await client.get("/_test/raise-http-exception")

    assert resp.status_code == 418
    body = resp.json()
    assert body == {"detail": "I'm a teapot"}
    # NOT a Problem body.
    assert "type" not in body
    assert "title" not in body


async def test_request_validation_error_uses_fastapi_native_shape(client: AsyncClient) -> None:
    """Pydantic body validation failure → 422 with FastAPI's native shape.

    The handler chain re-raises :class:`RequestValidationError` so the
    framework's default handler runs. Body shape: ``{"detail": [...]}``.
    """
    resp = await client.post("/_test/validate-body", json={"not_email": "x"})

    assert resp.status_code == 422
    body = resp.json()
    # FastAPI native: detail is a list of field-level error dicts.
    assert isinstance(body["detail"], list)
    assert all(isinstance(item, dict) for item in body["detail"])
    # NOT the Problem shape.
    assert "type" not in body
    assert "title" not in body
