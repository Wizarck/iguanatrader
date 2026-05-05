"""Pydantic v2 DTOs for the auth surface.

Per design D8 (slice 4): the SvelteKit ``(auth)/login`` form action POSTs
``application/x-www-form-urlencoded`` to FastAPI ``/api/v1/auth/login``;
FastAPI accepts the body as JSON OR form because both shapes parse into
:class:`LoginRequest` (Pydantic accepts dicts from either parser when
:mod:`python-multipart` is installed).

The :class:`LoginResponse` exposes only :attr:`redirect_to` — the JWT
itself rides in the ``Set-Cookie`` header, never in the response body
(per NFR-S4: HttpOnly cookie). :class:`MeResponse` mirrors the User row
projection that is safe to return to the client (no ``password_hash``,
no internal flags).

Hard rules per AGENTS.md §4:

* :class:`SecretStr` for the password — its ``__repr__`` returns
  ``"**********"`` so accidentally logging the model never leaks the
  plaintext (NFR-S5).
* All datetimes are serialised as ISO 8601 UTC (Pydantic v2 default for
  :class:`datetime`).
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr

from iguanatrader.api.auth import Role


class LoginRequest(BaseModel):
    """Credentials submitted to ``POST /api/v1/auth/login``.

    Both JSON and form-urlencoded request bodies parse into this model.
    The :class:`SecretStr` wrapper prevents the plaintext password from
    leaking through accidental ``repr()`` / structlog field rendering;
    extracting the plaintext requires the explicit
    :meth:`SecretStr.get_secret_value` call inside the route handler.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    email: EmailStr
    password: SecretStr = Field(min_length=1)


class LoginResponse(BaseModel):
    """Body returned on a 200 OK login.

    The actual session token rides in the ``Set-Cookie`` header
    (``iguana_session``); the body only carries the post-auth redirect
    target so the SvelteKit form action knows where to ``redirect(302, ...)``
    the user-agent.
    """

    model_config = ConfigDict(extra="forbid")

    redirect_to: str


class MeResponse(BaseModel):
    """Safe projection of the authenticated :class:`User` row.

    NEVER includes ``password_hash``, internal flags, or any other field
    that could leak via the typed client (slice 5 generates a TS client
    from the OpenAPI schema — anything in this model is fair game for
    the browser).
    """

    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    tenant_id: UUID
    email: EmailStr
    role: Role
    created_at: datetime


__all__ = [
    "LoginRequest",
    "LoginResponse",
    "MeResponse",
]
