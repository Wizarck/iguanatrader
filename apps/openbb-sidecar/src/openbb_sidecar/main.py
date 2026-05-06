"""Sidecar FastAPI app factory + module-level ``app`` for uvicorn import."""

from __future__ import annotations

import logging

import structlog
from fastapi import FastAPI

from openbb_sidecar import __version__
from openbb_sidecar.config import get_settings
from openbb_sidecar.routes import register_routers


def _configure_logging(level: str) -> None:
    """Wire structlog to render JSON-ish key/value logs."""
    logging.basicConfig(
        level=level.upper(),
        format="%(message)s",
    )
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def create_app() -> FastAPI:
    """FastAPI app factory; mounts all auto-discovered routers."""
    settings = get_settings()
    _configure_logging(settings.log_level)

    app = FastAPI(
        title="openbb-sidecar",
        version=__version__,
        description=(
            "AGPL-isolated OpenBB Platform sidecar for iguanatrader. "
            "Communicates with the monolith over HTTP loopback per ADR-015."
        ),
    )
    register_routers(app)
    return app


# Module-level instance so uvicorn can import it as `openbb_sidecar.main:app`.
app = create_app()
