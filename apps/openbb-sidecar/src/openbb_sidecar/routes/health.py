"""Health route.

Per task 2.6 + design D8: ``/health`` NEVER returns 5xx. A sidecar that
cannot import openbb returns 200 with ``openbb_loadable: false`` so the
docker healthcheck still treats the container as alive while operators
see the readiness flag is false. Five-xx would trigger restart loops
on AGPL packaging issues that need manual intervention, not retry.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from openbb_sidecar import __version__
from openbb_sidecar.adapters.openbb_facade import OpenBBFacade

router = APIRouter(tags=["health"])

_facade = OpenBBFacade()


class HealthResponse(BaseModel):
    status: str
    openbb_loadable: bool
    version: str
    error: str | None = None


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness + readiness."""
    loadable = _facade.is_ready()
    return HealthResponse(
        status="ok",
        openbb_loadable=loadable,
        version=__version__,
        error=None if loadable else _facade.import_error,
    )
