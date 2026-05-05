"""Server-Sent Events (SSE) endpoints + dynamic discovery (slice 5).

Mirror of :mod:`iguanatrader.api.routes` per design D2 — same
:func:`pkgutil.iter_modules` discovery shape, different prefix.
SSE modules drop under this package (e.g. ``sse/research_stream.py``)
exporting ``router: APIRouter``; FastAPI's :class:`StreamingResponse`
+ async generators handle the underlying ASGI streaming.

Slice 5 ships zero SSE modules — the discovery scaffold lands now so
slice R5 (research streams), slice T4 (trading event feeds), slice P1
(approval channel) plug in without editing this ``__init__`` or
``app.py``.

Mounted prefix: ``/api/v1/stream``. Module emits structlog events
``api.sse.registered`` / ``api.sse.skipped`` / ``api.sse.import_failed``
mirroring the routes-loader convention.
"""

from __future__ import annotations

import importlib
import pkgutil

import structlog
from fastapi import APIRouter, FastAPI

log = structlog.get_logger("iguanatrader.api.sse")


def register_sse(app: FastAPI) -> None:
    """Discover and mount every ``sse/<name>.py`` exporting ``router``.

    Same contract as :func:`iguanatrader.api.routes.register_routers`;
    only the prefix differs (``/api/v1/stream``) and the structlog
    event names use ``api.sse.*``.
    """
    package = importlib.import_module(__name__)
    package_path: list[str] = list(getattr(package, "__path__", []))

    for _finder, module_name, _is_pkg in pkgutil.iter_modules(package_path):
        full_name = f"{__name__}.{module_name}"
        try:
            module = importlib.import_module(full_name)
        except Exception:
            log.error("api.sse.import_failed", module=full_name, exc_info=True)
            raise

        router = getattr(module, "router", None)
        if not isinstance(router, APIRouter):
            log.warning(
                "api.sse.skipped",
                module=full_name,
                reason="no_router_attribute",
            )
            continue

        app.include_router(router, prefix="/api/v1/stream")
        log.info("api.sse.registered", module=full_name)


__all__ = [
    "register_sse",
]
