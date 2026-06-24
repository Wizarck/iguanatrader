"""HermesWhatsAppMessageDispatcher — Hermes WhatsApp HTTP adapter.

Posts JSON ``{recipient, body, correlation_id}`` to Hermes with an
``X-Signature: sha256=<hex>`` HMAC header. Honours the conservative
80-msg/s default rate (Meta Cloud API tier varies; 80 is safe baseline).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, cast

import httpx
import structlog

from iguanatrader.shared.channel_dispatch.protocol import OutboundTransport, RateLimiter
from iguanatrader.shared.channel_dispatch.rate_limit import AsyncTokenBucket
from iguanatrader.shared.channel_dispatch.sign import hmac_sha256_hex
from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

log = structlog.get_logger("iguanatrader.shared.channel_dispatch.adapters.hermes")

#: Conservative baseline rate for Meta Cloud API across tiers.
HERMES_DEFAULT_RATE_PER_SECOND: float = 80.0
WHATSAPP_CHANNEL: str = "whatsapp"


class _HttpxHermesTransport:
    """Default transport: signed POST to Hermes WhatsApp endpoint via httpx."""

    def __init__(
        self,
        *,
        base_url: str,
        hmac_secret: bytes,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._hmac_secret = hmac_secret
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def send(
        self, *, address: str, body: str, actions: tuple[tuple[str, str], ...] = ()
    ) -> str:
        # Hermes/WhatsApp interactive buttons are a future slice; ignore ``actions``.
        url = f"{self._base_url}/messages"
        payload_obj: dict[str, str] = {"recipient": address, "body": body}
        payload_bytes = json.dumps(payload_obj, separators=(",", ":")).encode("utf-8")
        signature = hmac_sha256_hex(self._hmac_secret, payload_bytes)
        headers = {
            "Content-Type": "application/json",
            "X-Signature": f"sha256={signature}",
        }
        resp = await self._client.post(url, content=payload_bytes, headers=headers)
        resp.raise_for_status()
        body_json = cast(dict[str, Any], resp.json())
        wire_id = body_json.get("message_id") or body_json.get("id") or ""
        return str(wire_id)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class HermesWhatsAppMessageDispatcher:
    """Concrete dispatcher for ``channel == 'whatsapp'`` recipients."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        hmac_secret: bytes | None = None,
        transport: OutboundTransport | None = None,
        rate_limit: RateLimiter | None = None,
    ) -> None:
        if transport is None:
            if base_url is None or hmac_secret is None:
                raise ValueError("either transport or both base_url + hmac_secret must be provided")
            transport = _HttpxHermesTransport(base_url=base_url, hmac_secret=hmac_secret)
        self._transport = transport
        self._rate_limit: RateLimiter = rate_limit or AsyncTokenBucket(
            rate_per_second=HERMES_DEFAULT_RATE_PER_SECOND
        )

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for r in recipients:
            if r.channel != WHATSAPP_CHANNEL:
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="skipped",
                        wire_message_id=None,
                        error=f"hermes dispatcher cannot handle channel={r.channel!r}",
                    )
                )
                continue
            await self._rate_limit.acquire()
            try:
                wire_id = await self._transport.send(address=r.address, body=message.body)
            except Exception as exc:
                log.warning(
                    "channel_dispatch.hermes.send_failed",
                    address=r.address,
                    correlation_id=message.correlation_id,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="failed",
                        wire_message_id=None,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
                continue
            results.append(
                DispatchResult(
                    channel=r.channel,
                    address=r.address,
                    status="delivered",
                    wire_message_id=wire_id,
                    error=None,
                )
            )
        return results


__all__ = [
    "HERMES_DEFAULT_RATE_PER_SECOND",
    "WHATSAPP_CHANNEL",
    "HermesWhatsAppMessageDispatcher",
]
