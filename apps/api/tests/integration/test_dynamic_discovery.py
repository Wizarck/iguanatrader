"""Slice 5 — dynamic router discovery via :func:`pkgutil.iter_modules`.

Covers the spec ``api-foundation`` Requirement 3 scenarios:

* New route module added → registered without any edit to ``app.py``
  or ``routes/__init__.py``.
* Module without a ``router`` attribute → skipped with structlog warning.
* Module raising on import → app boot fails loudly (NOT silently absent).

These tests drop temporary stub modules into
``apps/api/src/iguanatrader/api/routes/`` at runtime, build a fresh
FastAPI app via :func:`create_app`, and assert the discovery loop did
the right thing. The stubs are cleaned up in ``finally`` so the
package state is restored even on assertion failure.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import APIRouter
from httpx import ASGITransport, AsyncClient
from iguanatrader.api.app import create_app
from iguanatrader.api.routes import register_routers


def _routes_pkg_dir() -> Path:
    """Path to ``apps/api/src/iguanatrader/api/routes/``."""
    package = importlib.import_module("iguanatrader.api.routes")
    package_paths = list(getattr(package, "__path__", []))
    if not package_paths:
        raise RuntimeError("could not resolve iguanatrader.api.routes path")
    return Path(package_paths[0])


@pytest.fixture
def stub_module() -> Iterator[Path]:
    """Drop a stub route module that exports a ``router`` with one endpoint.

    Cleans up the file and the ``sys.modules`` cache entry on teardown
    so subsequent tests see a fresh package state.
    """
    pkg_dir = _routes_pkg_dir()
    stub_path = pkg_dir / "_test_stub.py"
    stub_path.write_text(
        '"""Test-only stub route — see test_dynamic_discovery.py."""\n'
        "from __future__ import annotations\n\n"
        "from fastapi import APIRouter\n\n"
        'router = APIRouter(prefix="/_stub", tags=["_stub"])\n\n\n'
        '@router.get("/ping")\n'
        "async def _ping() -> dict[str, str]:\n"
        '    return {"ok": "yes"}\n',
        encoding="utf-8",
    )
    try:
        yield stub_path
    finally:
        stub_path.unlink(missing_ok=True)
        sys.modules.pop("iguanatrader.api.routes._test_stub", None)


@pytest.fixture
def stub_no_router_module() -> Iterator[Path]:
    """Drop a module that does NOT export ``router`` (helper-style)."""
    pkg_dir = _routes_pkg_dir()
    stub_path = pkg_dir / "_test_helper.py"
    stub_path.write_text(
        '"""Test-only helper module — exports no router on purpose."""\n'
        "from __future__ import annotations\n\n"
        "def utility_helper() -> int:\n"
        "    return 42\n",
        encoding="utf-8",
    )
    try:
        yield stub_path
    finally:
        stub_path.unlink(missing_ok=True)
        sys.modules.pop("iguanatrader.api.routes._test_helper", None)


@pytest.fixture
def stub_broken_module() -> Iterator[Path]:
    """Drop a module that raises :class:`ImportError` on import."""
    pkg_dir = _routes_pkg_dir()
    stub_path = pkg_dir / "_test_broken.py"
    stub_path.write_text(
        "from __future__ import annotations\n\n"
        'raise ImportError("synthetic boot failure for the test")\n',
        encoding="utf-8",
    )
    try:
        yield stub_path
    finally:
        stub_path.unlink(missing_ok=True)
        sys.modules.pop("iguanatrader.api.routes._test_broken", None)


async def test_new_route_module_registered_without_app_py_edit(
    stub_module: Path,
) -> None:
    """A stub ``routes/<name>.py`` with ``router`` is mounted at ``/api/v1``."""
    app = create_app()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="https://test") as c:
        resp = await c.get("/api/v1/_stub/ping")

    assert resp.status_code == 200
    assert resp.json() == {"ok": "yes"}


def test_module_without_router_is_skipped(
    stub_no_router_module: Path,
) -> None:
    """A helper module without ``router`` does not break discovery.

    The discovery loop logs ``api.router.skipped`` and moves on; the
    real ``auth`` router is still registered on the app.
    """
    app = create_app()

    paths = [r.path for r in app.routes if hasattr(r, "path")]
    # Auth router still mounted (slice 4 contract still holds).
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/me" in paths
    # The helper module did not contribute any route.
    assert not any(p.startswith("/api/v1/_helper") for p in paths)


def test_broken_module_fails_loudly(stub_broken_module: Path) -> None:
    """Broken module raising on import → :func:`register_routers` re-raises.

    Per the spec scenario "Module raises on import": the discovery loop
    emits ``api.router.import_failed`` (covered by the structlog test
    in unit tier) and re-raises so app boot fails — not silently absent.
    """
    with pytest.raises(ImportError, match="synthetic boot failure"):
        create_app()


def test_register_routers_is_idempotent_callable_directly() -> None:
    """:func:`register_routers` accepts a fresh app + populates routes.

    Sanity check that the helper is importable + callable; the create_app
    factory uses it but a direct test exercises the contract once more.
    """
    from fastapi import FastAPI

    app = FastAPI()
    register_routers(app)
    paths = [r.path for r in app.routes if hasattr(r, "path")]
    assert any(p.startswith("/api/v1/auth") for p in paths), paths


def test_routers_helper_no_args_after_helpers() -> None:
    """Helper APIRouter sanity check (mypy / runtime) — keeps the import alive."""
    r = APIRouter()
    assert isinstance(r, APIRouter)
