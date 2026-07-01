"""Ephemeral live-gateway lease client (WS-4 / WS-F, iguanatrader side).

The live IBKR gateway logs the owner out of the IBKR mobile app (IBKR allows one
live session), so it must NOT run continuously — it is spun up on demand only to
drain approved live orders and torn down right after. The container lifecycle —
spin-up, the hard ~5-minute TTL teardown, and the "gateway down" Telegram notice
— runs in **eligia-core's AIOps sidecar** (``OrchestratorBackend`` /
``DockerBackend`` behind the ``eligia-sidecar-webhook``), cross-repo, with no
``docker.sock`` in the trading container.

The iguanatrader side's only job, therefore, is to request a short **lease**
before each live order so the sidecar keeps the gateway up just long enough, and
to **refuse to place the order if the gateway is not ready** — a live real-money
order must never be sent at a gateway we cannot confirm is up (FAIL-CLOSED).
Teardown is the sidecar's responsibility via the lease TTL, so there is no
teardown choreography here; a lease simply extends the window.

Wire contract (the eligia-core sidecar implements the other half):

    POST {webhook_url}
    header  X-Signature: sha256=<hex HMAC-SHA256 of the exact body, shared secret>
    body    {"action": "lease", "reason": "<str>", "ttl_seconds": <int>}
    → 200   {"ready": true|false, "detail": "<str>"}

    POST {webhook_url}
    header  X-Signature: sha256=<hex HMAC-SHA256 of the exact body, shared secret>
    body    {"action": "release", "reason": "<str>"}
    → 200   {"stopped": true|false, "detail": "<str>"}

Built only when ``ELIGIA_GATEWAY_WEBHOOK_URL`` + ``ELIGIA_GATEWAY_HMAC_SECRET``
are set AND ``IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED`` is truthy; otherwise the
factory returns ``None`` and the live execute path is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from iguanatrader.shared.channel_dispatch.sign import hmac_sha256_hex
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)

#: A broker-connect hook the coordinator invokes after a lease is confirmed
#: ready, to (re)establish + verify the live broker connection on demand right
#: before the order (the ephemeral adapter holds no persistent connection).
#: Returns True only when the broker is connected; the coordinator FAILS CLOSED
#: (``ensure_up`` → False, no order) on a False return OR any raised exception.
OnReadyHook = Callable[[], Awaitable[bool]]

#: Default lease TTL — matches the sidecar's hard teardown cap (5 minutes).
DEFAULT_LEASE_TTL_SECONDS = 300

#: How long before lease expiry to stop trusting the cache + re-lease, so a
#: batch of orders reuses one gateway without a webhook per order, yet never
#: rides a lease into its teardown window.
_LEASE_REFRESH_MARGIN_SECONDS = 60

#: Default quiet-window after the last live order before actively releasing
#: the gateway (rather than waiting out the full lease TTL) — see
#: :meth:`EphemeralGatewayCoordinator.schedule_release`.
DEFAULT_RELEASE_DELAY_SECONDS = 30.0


@dataclass(frozen=True, slots=True)
class LeaseResult:
    """Outcome of a lease request."""

    ready: bool
    detail: str = ""


@dataclass(frozen=True, slots=True)
class ReleaseResult:
    """Outcome of a release request."""

    stopped: bool
    detail: str = ""


class EphemeralGatewayPort(Protocol):
    """The sidecar lease call (concrete: :class:`EligiaSidecarGatewayClient`)."""

    async def request_lease(self, *, reason: str, ttl_seconds: int) -> LeaseResult: ...

    async def request_release(self, *, reason: str) -> ReleaseResult: ...


class EligiaSidecarGatewayClient:
    """HMAC-signed lease request to the eligia-core sidecar webhook.

    Fail-safe: any transport / HTTP / decode error resolves to
    ``LeaseResult(ready=False)`` (never raises into the caller) so the execute
    path can fail-closed deterministically rather than crash.
    """

    def __init__(
        self,
        *,
        webhook_url: str,
        hmac_secret: bytes,
        client: Any | None = None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._url = webhook_url
        self._secret = hmac_secret
        self._client = client
        self._timeout = timeout_seconds

    async def request_lease(self, *, reason: str, ttl_seconds: int) -> LeaseResult:
        payload = {"action": "lease", "reason": reason, "ttl_seconds": ttl_seconds}
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac_sha256_hex(self._secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": f"sha256={signature}",
        }
        try:
            client = self._client or self._new_client()
            resp = await client.post(self._url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(
                "trading.ephemeral_gateway.lease_request_failed",
                extra={"error": str(exc), "type": type(exc).__name__},
            )
            return LeaseResult(ready=False, detail=f"{type(exc).__name__}: {exc}")
        ready = bool(data.get("ready", False)) if isinstance(data, dict) else False
        detail = str(data.get("detail", "")) if isinstance(data, dict) else ""
        return LeaseResult(ready=ready, detail=detail)

    async def request_release(self, *, reason: str) -> ReleaseResult:
        payload = {"action": "release", "reason": reason}
        body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        signature = hmac_sha256_hex(self._secret, body)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": f"sha256={signature}",
        }
        try:
            client = self._client or self._new_client()
            resp = await client.post(self._url, content=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            logger.warning(
                "trading.ephemeral_gateway.release_request_failed",
                extra={"error": str(exc), "type": type(exc).__name__},
            )
            return ReleaseResult(stopped=False, detail=f"{type(exc).__name__}: {exc}")
        stopped = bool(data.get("stopped", False)) if isinstance(data, dict) else False
        detail = str(data.get("detail", "")) if isinstance(data, dict) else ""
        return ReleaseResult(stopped=stopped, detail=detail)

    def _new_client(self) -> Any:
        import httpx

        return httpx.AsyncClient(timeout=self._timeout)


class EphemeralGatewayCoordinator:
    """Ensures the ephemeral live gateway is leased-up before a live order.

    Holds an in-memory lease watermark so a *batch* of live orders reuses one
    gateway (one webhook per lease window, not per order); on a cache miss it
    re-leases (extending the sidecar's window). ``ensure_up`` returns ``True``
    only when the gateway is confirmed ready — the caller fails closed on
    ``False`` (no live order placed).
    """

    def __init__(
        self,
        client: EphemeralGatewayPort,
        *,
        ttl_seconds: int = DEFAULT_LEASE_TTL_SECONDS,
        clock: Any = utc_now,
        on_ready: OnReadyHook | None = None,
        sleep: Any = asyncio.sleep,
    ) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._clock = clock
        self._ready_until: datetime | None = None
        # Optional broker-connect hook (the ephemeral adapter's
        # ``ensure_connected``). The daemon attaches it after construction via
        # :meth:`attach_on_ready` because the coordinator is built from env
        # while the broker is built separately. ``None`` → the gateway lease is
        # the only readiness gate (back-compat: paper/tests/unwired).
        self._on_ready = on_ready
        # Injectable async sleep (tests substitute a no-op) for the release
        # debounce timer below.
        self._sleep = sleep
        self._release_task: asyncio.Task[None] | None = None

    def attach_on_ready(self, on_ready: OnReadyHook) -> None:
        """Wire the broker-connect hook after construction (daemon wiring)."""
        self._on_ready = on_ready

    async def ensure_up(self, *, reason: str) -> bool:
        now = self._clock()
        if self._ready_until is not None and now < self._ready_until:
            # Still inside a confirmed lease window — reuse it (batch path), but
            # still confirm the broker connection is live before the order.
            return await self._invoke_on_ready(reason)
        result = await self._client.request_lease(reason=reason, ttl_seconds=self._ttl)
        if result.ready:
            margin = min(_LEASE_REFRESH_MARGIN_SECONDS, self._ttl // 2)
            self._ready_until = now + timedelta(seconds=self._ttl - margin)
            logger.info("trading.ephemeral_gateway.leased", extra={"reason": reason})
            return await self._invoke_on_ready(reason)
        # Fail-closed: drop the cached window so the next order re-attempts.
        self._ready_until = None
        logger.warning(
            "trading.ephemeral_gateway.not_ready",
            extra={"reason": reason, "detail": result.detail},
        )
        return False

    async def _invoke_on_ready(self, reason: str) -> bool:
        """Run the broker-connect hook, FAILING CLOSED on False / any error.

        The gateway being leased-up is necessary but not sufficient: the broker
        must also be connected to it. On a False return or any exception the
        cached lease window is dropped so the next order re-leases (which may
        re-up a torn-down gateway) and retries the connection.
        """
        if self._on_ready is None:
            return True
        try:
            ready = await self._on_ready()
        except Exception as exc:
            self._ready_until = None
            logger.warning(
                "trading.ephemeral_gateway.on_ready_failed",
                extra={"reason": reason, "error": str(exc), "type": type(exc).__name__},
            )
            return False
        if not ready:
            self._ready_until = None
            logger.warning("trading.ephemeral_gateway.on_ready_not_ready", extra={"reason": reason})
            return False
        return True

    def schedule_release(
        self, *, reason: str, delay_seconds: float = DEFAULT_RELEASE_DELAY_SECONDS
    ) -> None:
        """Debounce an early gateway teardown ``delay_seconds`` after the LAST call.

        The lease TTL floor is 60s server-side, which would otherwise keep the
        owner locked out of his own IBKR mobile app (IBKR allows one live
        session) for at least that long after every order. Call this once a
        live order has been placed; a fresh call — from a follow-up order
        approved moments later — cancels the pending release and restarts the
        countdown, so a batch of quick approvals only tears down once it goes
        quiet. Fire-and-forget: never awaited by the caller, and any sidecar
        failure is logged, not raised — the TTL timer is still the backstop.
        """
        if self._release_task is not None and not self._release_task.done():
            self._release_task.cancel()
        self._release_task = asyncio.create_task(self._delayed_release(reason, delay_seconds))

    async def _delayed_release(self, reason: str, delay_seconds: float) -> None:
        await self._sleep(delay_seconds)
        # A superseding schedule_release() would have cancelled this task
        # before this point ran, so reaching here means the batch went quiet.
        self._ready_until = None
        try:
            result = await self._client.request_release(reason=reason)
        except Exception as exc:
            logger.warning(
                "trading.ephemeral_gateway.release_failed",
                extra={"reason": reason, "error": str(exc), "type": type(exc).__name__},
            )
            return
        logger.info(
            "trading.ephemeral_gateway.released",
            extra={"reason": reason, "stopped": result.stopped, "detail": result.detail},
        )


def build_ephemeral_gateway_coordinator_from_env() -> EphemeralGatewayCoordinator | None:
    """Construct the coordinator from env, or ``None`` when not enabled.

    Requires the feature flag ``IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED`` truthy
    AND both ``ELIGIA_GATEWAY_WEBHOOK_URL`` + ``ELIGIA_GATEWAY_HMAC_SECRET``. Any
    missing piece → ``None`` (the live execute path stays unchanged).
    """
    flag = os.environ.get("IGUANATRADER_EPHEMERAL_GATEWAY_ENABLED", "").strip().lower()
    if flag not in ("1", "true", "yes", "on"):
        return None
    url = os.environ.get("ELIGIA_GATEWAY_WEBHOOK_URL", "").strip()
    secret = os.environ.get("ELIGIA_GATEWAY_HMAC_SECRET", "").strip()
    if not url or not secret:
        logger.warning("trading.ephemeral_gateway.enabled_but_unconfigured")
        return None
    ttl_raw = os.environ.get("IGUANATRADER_EPHEMERAL_GATEWAY_TTL_SECONDS", "").strip()
    try:
        ttl = int(ttl_raw) if ttl_raw else DEFAULT_LEASE_TTL_SECONDS
    except ValueError:
        ttl = DEFAULT_LEASE_TTL_SECONDS
    client = EligiaSidecarGatewayClient(webhook_url=url, hmac_secret=secret.encode("utf-8"))
    return EphemeralGatewayCoordinator(client, ttl_seconds=ttl)


__all__ = [
    "DEFAULT_LEASE_TTL_SECONDS",
    "DEFAULT_RELEASE_DELAY_SECONDS",
    "EligiaSidecarGatewayClient",
    "EphemeralGatewayCoordinator",
    "EphemeralGatewayPort",
    "LeaseResult",
    "OnReadyHook",
    "ReleaseResult",
    "build_ephemeral_gateway_coordinator_from_env",
]
