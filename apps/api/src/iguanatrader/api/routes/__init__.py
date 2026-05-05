"""HTTP route modules.

Slice 4 (``auth-jwt-cookie``) seeds this package with the auth router
(``routes/auth.py``). Slice 5 (``api-foundation-rfc7807``) refactors
:mod:`iguanatrader.api.app` to discover routers dynamically via
:func:`pkgutil.iter_modules` over this package; slice 4 ships a manual
``app.include_router(auth_router)`` as a pre-pattern.

Each router module SHOULD export a top-level ``router: APIRouter``
attribute so the slice-5 dynamic loader can pick it up uniformly.
"""

from __future__ import annotations
