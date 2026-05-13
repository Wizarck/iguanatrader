"""Generic outbound message dispatch — upstream-extractable channel core.

This package has zero ``iguanatrader.contexts.*`` imports by design (slice
``p1-channel-fanout-production`` D1). It can be lifted to a standalone PyPI
package via a mechanical ``git mv`` without code changes.

Public surface:

* :class:`OutboundMessage` / :class:`Recipient` / :class:`DispatchResult` —
  generic value types.
* :class:`MessageDispatcher` / :class:`OutboundTransport` — Protocols.
* :class:`LogOnlyMessageDispatcher` — in-tree fake (no real send).
* :class:`MultiChannelMessageDispatcher` — per-channel routing with FR-isolation.
* :class:`AsyncTokenBucket` — rate-limit helper.
* :func:`hmac_sha256_hex` — HMAC payload-signing helper.
* Adapters (under :mod:`.adapters`) — concrete Telegram + Hermes/WhatsApp +
  Email SMTP dispatchers wrapping injectable transports.
* :func:`render_email_template` — branded email rendering helper.
"""

from iguanatrader.shared.channel_dispatch.adapters.email_smtp import (
    EMAIL_CHANNEL,
    EMAIL_DEFAULT_RATE_PER_SECOND,
    EmailSMTPDispatcher,
)
from iguanatrader.shared.channel_dispatch.log_only import LogOnlyMessageDispatcher
from iguanatrader.shared.channel_dispatch.multi import MultiChannelMessageDispatcher
from iguanatrader.shared.channel_dispatch.protocol import (
    MessageDispatcher,
    OutboundTransport,
    RateLimiter,
)
from iguanatrader.shared.channel_dispatch.rate_limit import AsyncTokenBucket
from iguanatrader.shared.channel_dispatch.sign import hmac_sha256_hex
from iguanatrader.shared.channel_dispatch.templates import render_email_template
from iguanatrader.shared.channel_dispatch.types import (
    DispatchResult,
    OutboundMessage,
    Recipient,
)

__all__ = [
    "EMAIL_CHANNEL",
    "EMAIL_DEFAULT_RATE_PER_SECOND",
    "AsyncTokenBucket",
    "DispatchResult",
    "EmailSMTPDispatcher",
    "LogOnlyMessageDispatcher",
    "MessageDispatcher",
    "MultiChannelMessageDispatcher",
    "OutboundMessage",
    "OutboundTransport",
    "RateLimiter",
    "Recipient",
    "hmac_sha256_hex",
    "render_email_template",
]
