"""TelegramBotMessageDispatcher — Telegram bot ``sendMessage`` adapter.

Wraps an injectable :class:`OutboundTransport` (default: httpx-backed POST to
``https://api.telegram.org/bot<token>/sendMessage``). Honours the canonical
30-msg/s bot-API limit via :class:`AsyncTokenBucket`.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import httpx
import structlog

from iguanatrader.shared.channel_dispatch.protocol import OutboundTransport, RateLimiter
from iguanatrader.shared.channel_dispatch.rate_limit import AsyncTokenBucket
from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

log = structlog.get_logger("iguanatrader.shared.channel_dispatch.adapters.telegram")

#: Telegram bot API limit per https://core.telegram.org/bots/faq.
TELEGRAM_DEFAULT_RATE_PER_SECOND: float = 30.0
TELEGRAM_CHANNEL: str = "telegram"


class _HttpxTelegramTransport:
    """Default transport: POST to Telegram bot API ``sendMessage`` via httpx."""

    def __init__(self, *, bot_token: str, client: httpx.AsyncClient | None = None) -> None:
        self._bot_token = bot_token
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def send(self, *, address: str, body: str) -> str:
        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        resp = await self._client.post(url, json={"chat_id": address, "text": body})
        resp.raise_for_status()
        payload = cast(dict[str, Any], resp.json())
        if not payload.get("ok"):
            raise RuntimeError(f"telegram send failed: {payload}")
        result = cast(dict[str, Any], payload.get("result", {}))
        return str(result.get("message_id", ""))

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()


class TelegramBotMessageDispatcher:
    """Concrete dispatcher for ``channel == 'telegram'`` recipients."""

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        transport: OutboundTransport | None = None,
        rate_limit: RateLimiter | None = None,
    ) -> None:
        if transport is None:
            if bot_token is None:
                raise ValueError("either transport or bot_token must be provided")
            transport = _HttpxTelegramTransport(bot_token=bot_token)
        self._transport = transport
        self._rate_limit: RateLimiter = rate_limit or AsyncTokenBucket(
            rate_per_second=TELEGRAM_DEFAULT_RATE_PER_SECOND
        )

    async def dispatch(
        self,
        *,
        message: OutboundMessage,
        recipients: Sequence[Recipient],
    ) -> list[DispatchResult]:
        results: list[DispatchResult] = []
        for r in recipients:
            if r.channel != TELEGRAM_CHANNEL:
                results.append(
                    DispatchResult(
                        channel=r.channel,
                        address=r.address,
                        status="skipped",
                        wire_message_id=None,
                        error=f"telegram dispatcher cannot handle channel={r.channel!r}",
                    )
                )
                continue
            await self._rate_limit.acquire()
            try:
                wire_id = await self._transport.send(address=r.address, body=message.body)
            except Exception as exc:
                log.warning(
                    "channel_dispatch.telegram.send_failed",
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
    "TELEGRAM_CHANNEL",
    "TELEGRAM_DEFAULT_RATE_PER_SECOND",
    "TelegramBotMessageDispatcher",
]
