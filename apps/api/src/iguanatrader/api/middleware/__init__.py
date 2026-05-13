"""ASGI / Starlette middleware for the iguanatrader API.

This package holds standalone middleware classes that are wired into
the FastAPI factory in :mod:`iguanatrader.api.app`. The
:class:`BufferLoginEmailMiddleware` (slice 4 ``auth-jwt-cookie``) lives
in :mod:`iguanatrader.api.limiting` for historical reasons; new
middleware lands here.

Each middleware module SHOULD export:

* The class itself, with a clear docstring describing the ASGI / HTTP
  contract it adds.
* Any allow-list / config constants it consumes (so tests can import
  them without monkey-patching internals).
"""

from __future__ import annotations

from iguanatrader.api.middleware.must_change_password import (
    MUST_CHANGE_PASSWORD_ALLOW_LIST,
    MUST_CHANGE_PASSWORD_ALLOW_PREFIXES,
    MustChangePasswordMiddleware,
    set_session_factory_override,
)

__all__ = [
    "MUST_CHANGE_PASSWORD_ALLOW_LIST",
    "MUST_CHANGE_PASSWORD_ALLOW_PREFIXES",
    "MustChangePasswordMiddleware",
    "set_session_factory_override",
]
