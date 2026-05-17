"""Sidecar route auto-discovery.

Anti-collision pattern from slice 5 (api-foundation-rfc7807): each
route module exports a top-level ``router: APIRouter``; this package's
``register_routers(app)`` iterates ``pkgutil.iter_modules`` and mounts
every router that imports cleanly. New routes ship as new files;
nobody edits this ``__init__.py``.
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter, FastAPI

logger = logging.getLogger(__name__)


def register_routers(app: FastAPI) -> None:
    """Discover every ``routes/<name>.py`` exporting ``router`` and mount it."""
    package_name = __name__
    package_path = __path__  # type: ignore[name-defined]

    for module_info in pkgutil.iter_modules(package_path):
        module_name = f"{package_name}.{module_info.name}"
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 — boundary; log + skip
            logger.warning(
                "openbb_sidecar.router.import_failed",
                extra={"module_name": module_name, "error": str(exc)},
            )
            continue

        router: APIRouter | None = getattr(module, "router", None)
        if router is None:
            logger.info(
                "openbb_sidecar.router.skipped",
                extra={"module_name": module_name, "reason": "no_router_attribute"},
            )
            continue

        app.include_router(router)
        logger.info(
            "openbb_sidecar.router.registered",
            extra={"module_name": module_name},
        )
