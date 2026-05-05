"""HTTP route modules + dynamic discovery (slice 5 ``api-foundation-rfc7807``).

Each route module under this package SHOULD export a top-level
``router: APIRouter`` attribute. :func:`register_routers` iterates
:func:`pkgutil.iter_modules`, imports each module, and
``app.include_router(module.router, prefix="/api/v1")`` for every module
that conforms.

Modules without a ``router`` attribute are skipped with a structlog
``api.router.skipped`` warning (so a typo doesn't silently disable a
route family). Modules that raise on import emit
``api.router.import_failed`` and the original exception is re-raised so
the FastAPI app fails to boot loudly (per design D1 risk mitigation).

Adding a new route family is a one-file change: drop
``apps/api/src/iguanatrader/api/routes/<name>.py`` exporting
``router: APIRouter`` — no edit to ``app.py`` or this ``__init__``.
"""

from __future__ import annotations

import importlib
import pkgutil

import structlog
from fastapi import APIRouter, FastAPI

log = structlog.get_logger("iguanatrader.api.routes")


def register_routers(app: FastAPI) -> None:
    """Discover and mount every ``routes/<name>.py`` exporting ``router``.

    All routers are registered under the ``/api/v1`` prefix. Discovery
    is alphabetical-by-module-name (``pkgutil.iter_modules`` ordering)
    so registration order is deterministic across runs.
    """
    package = importlib.import_module(__name__)
    package_path: list[str] = list(getattr(package, "__path__", []))

    for _finder, module_name, _is_pkg in pkgutil.iter_modules(package_path):
        full_name = f"{__name__}.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception:
            log.error("api.router.import_failed", module=full_name, exc_info=True)
            raise

        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            log.warning(
                "api.router.skipped",
                module=full_name,
                reason="no_router_attribute",
            )
            continue

        app.include_router(router, prefix="/api/v1")
        log.info("api.router.registered", module=full_name)


__all__ = [
    "register_routers",
]
