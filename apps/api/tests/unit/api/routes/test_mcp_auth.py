"""Unit tests for the MCP server auth/config gates (slice B).

Tests the bearer-token check + env-var configuration paths in
isolation from FastAPI's routing. The full route integration (with
real DB session + tenant context) belongs in an integration test
suite — this slice ships the protocol scaffolding only.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from iguanatrader.api.routes.mcp import (
    MCPNotConfiguredError,
    MCPUnauthorizedError,
    _bearer_auth,
    _read_configured_tenant_slug,
    _read_configured_token,
)


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Configuration gates
# ---------------------------------------------------------------------------


def test_token_unset_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IGUANATRADER_MCP_TOKEN", raising=False)
    with pytest.raises(MCPNotConfiguredError, match="IGUANATRADER_MCP_TOKEN"):
        _read_configured_token()


def test_token_blank_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "   ")
    with pytest.raises(MCPNotConfiguredError):
        _read_configured_token()


def test_token_present_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "ok-val")
    assert _read_configured_token() == "ok-val"


def test_tenant_slug_unset_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IGUANATRADER_MCP_TENANT_SLUG", raising=False)
    with pytest.raises(MCPNotConfiguredError, match="IGUANATRADER_MCP_TENANT_SLUG"):
        _read_configured_tenant_slug()


def test_tenant_slug_returns_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TENANT_SLUG", "default")
    assert _read_configured_tenant_slug() == "default"


# ---------------------------------------------------------------------------
# Bearer auth dependency
# ---------------------------------------------------------------------------


def test_bearer_auth_missing_header_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "good")
    with pytest.raises(MCPUnauthorizedError, match="missing"):
        _run(_bearer_auth(authorization=None))


def test_bearer_auth_wrong_scheme_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "good")
    with pytest.raises(MCPUnauthorizedError, match="Bearer"):
        _run(_bearer_auth(authorization="Basic some-base64=="))


def test_bearer_auth_wrong_token_unauthorized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "good")
    with pytest.raises(MCPUnauthorizedError, match="mismatch"):
        _run(_bearer_auth(authorization="Bearer wrong-token"))


def test_bearer_auth_correct_token_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful auth returns None and doesn't raise — the
    dependency is purely a gate."""
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "good")
    # Should NOT raise.
    _run(_bearer_auth(authorization="Bearer good"))


def test_bearer_auth_with_token_unset_raises_config_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even a syntactically correct request fails when the token env
    is unset — the server is not configured for MCP exposure yet."""
    monkeypatch.delenv("IGUANATRADER_MCP_TOKEN", raising=False)
    with pytest.raises(MCPNotConfiguredError):
        _run(_bearer_auth(authorization="Bearer anything"))


# ---------------------------------------------------------------------------
# Constant-time compare invariant
# ---------------------------------------------------------------------------


def test_bearer_auth_token_compare_is_length_insensitive_in_outcome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A near-match (off-by-one) and a totally-wrong token must both
    raise the same exception type. Constant-time compare via hmac
    prevents the route from leaking timing differences."""
    monkeypatch.setenv("IGUANATRADER_MCP_TOKEN", "ok-val-12345")

    with pytest.raises(MCPUnauthorizedError):
        _run(_bearer_auth(authorization="Bearer ok-val-12346"))  # one char off
    with pytest.raises(MCPUnauthorizedError):
        _run(_bearer_auth(authorization="Bearer x"))  # totally wrong
