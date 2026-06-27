"""WS-4 ephemeral live-gateway lease client + coordinator.

Locks: the coordinator reuses one lease across a batch (one webhook per window),
re-leases on cache expiry, FAILS CLOSED when the gateway is not ready, the HMAC
client signs the exact body + degrades to not-ready on transport error, and the
env factory is OFF unless flag + creds are set.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from iguanatrader.contexts.trading.brokers.ephemeral_gateway import (
    EligiaSidecarGatewayClient,
    EphemeralGatewayCoordinator,
    LeaseResult,
    build_ephemeral_gateway_coordinator_from_env,
)
from iguanatrader.shared.channel_dispatch.sign import hmac_sha256_hex


class _StubClient:
    def __init__(self, results: list[LeaseResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

    async def request_lease(self, *, reason: str, ttl_seconds: int) -> LeaseResult:
        self.calls.append({"reason": reason, "ttl_seconds": ttl_seconds})
        return self._results.pop(0) if self._results else LeaseResult(ready=True)


class _Clock:
    def __init__(self, start: datetime) -> None:
        self.now = start

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now += timedelta(seconds=seconds)


@pytest.mark.asyncio
async def test_ready_lease_returns_true() -> None:
    client = _StubClient([LeaseResult(ready=True, detail="up")])
    coord = EphemeralGatewayCoordinator(client, ttl_seconds=300)
    assert await coord.ensure_up(reason="order:1") is True
    assert client.calls[0]["ttl_seconds"] == 300


@pytest.mark.asyncio
async def test_not_ready_fails_closed() -> None:
    client = _StubClient([LeaseResult(ready=False, detail="spinning up")])
    coord = EphemeralGatewayCoordinator(client, ttl_seconds=300)
    assert await coord.ensure_up(reason="order:1") is False


@pytest.mark.asyncio
async def test_batch_reuses_one_lease_within_window() -> None:
    clock = _Clock(datetime(2026, 6, 27, 12, 0, tzinfo=UTC))
    client = _StubClient([LeaseResult(ready=True)])
    coord = EphemeralGatewayCoordinator(client, ttl_seconds=300, clock=clock)

    assert await coord.ensure_up(reason="order:1") is True
    clock.advance(120)  # still inside the (300-60) window
    assert await coord.ensure_up(reason="order:2") is True
    # Only ONE webhook for the whole batch.
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_release_after_window_expires() -> None:
    clock = _Clock(datetime(2026, 6, 27, 12, 0, tzinfo=UTC))
    client = _StubClient([LeaseResult(ready=True), LeaseResult(ready=True)])
    coord = EphemeralGatewayCoordinator(client, ttl_seconds=300, clock=clock)

    assert await coord.ensure_up(reason="order:1") is True
    clock.advance(250)  # past the 300-60=240s refresh margin
    assert await coord.ensure_up(reason="order:2") is True
    assert len(client.calls) == 2  # re-leased


@pytest.mark.asyncio
async def test_not_ready_does_not_cache() -> None:
    client = _StubClient([LeaseResult(ready=False), LeaseResult(ready=True)])
    coord = EphemeralGatewayCoordinator(client, ttl_seconds=300)
    assert await coord.ensure_up(reason="order:1") is False
    # Next call re-attempts (no cached ready window from the failure).
    assert await coord.ensure_up(reason="order:1") is True
    assert len(client.calls) == 2


# ----------------------------------------------------------------------
# HMAC client
# ----------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpx:
    def __init__(self, response: Any = None, raise_exc: Exception | None = None) -> None:
        self._response = response
        self._raise = raise_exc
        self.posted: list[dict[str, Any]] = []

    async def post(self, url: str, *, content: bytes, headers: dict[str, str]) -> Any:
        self.posted.append({"url": url, "content": content, "headers": headers})
        if self._raise is not None:
            raise self._raise
        return self._response


@pytest.mark.asyncio
async def test_client_signs_exact_body_and_parses_ready() -> None:
    secret = b"s3cr3t"
    http = _FakeHttpx(response=_FakeResponse({"ready": True, "detail": "up"}))
    client = EligiaSidecarGatewayClient(
        webhook_url="https://sidecar.example/gateway", hmac_secret=secret, client=http
    )
    result = await client.request_lease(reason="order:abc", ttl_seconds=300)

    assert result.ready is True
    sent = http.posted[0]
    expected_body = json.dumps(
        {"action": "lease", "reason": "order:abc", "ttl_seconds": 300}, separators=(",", ":")
    ).encode("utf-8")
    assert sent["content"] == expected_body
    assert sent["headers"]["X-Signature"] == f"sha256={hmac_sha256_hex(secret, expected_body)}"


@pytest.mark.asyncio
async def test_client_transport_error_is_not_ready() -> None:
    http = _FakeHttpx(raise_exc=RuntimeError("connection refused"))
    client = EligiaSidecarGatewayClient(
        webhook_url="https://sidecar.example/gateway", hmac_secret=b"x", client=http
    )
    result = await client.request_lease(reason="order:1", ttl_seconds=300)
    assert result.ready is False
    assert "RuntimeError" in result.detail


# ----------------------------------------------------------------------
# Env factory
# ----------------------------------------------------------------------


def test_factory_off_without_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED", raising=False)
    monkeypatch.setenv("ELIGIA_GATEWAY_WEBHOOK_URL", "https://x")
    monkeypatch.setenv("ELIGIA_GATEWAY_HMAC_SECRET", "s")
    assert build_ephemeral_gateway_coordinator_from_env() is None


def test_factory_off_when_enabled_but_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED", "true")
    monkeypatch.delenv("ELIGIA_GATEWAY_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ELIGIA_GATEWAY_HMAC_SECRET", raising=False)
    assert build_ephemeral_gateway_coordinator_from_env() is None


def test_factory_builds_when_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED", "1")
    monkeypatch.setenv("ELIGIA_GATEWAY_WEBHOOK_URL", "https://sidecar/gateway")
    monkeypatch.setenv("ELIGIA_GATEWAY_HMAC_SECRET", "shh")
    coord = build_ephemeral_gateway_coordinator_from_env()
    assert coord is not None
