"""Concrete channel adapters wrapping injectable HTTP transports."""

from iguanatrader.shared.channel_dispatch.adapters.hermes import (
    HermesWhatsAppMessageDispatcher,
)
from iguanatrader.shared.channel_dispatch.adapters.telegram import (
    TelegramBotMessageDispatcher,
)

__all__ = [
    "HermesWhatsAppMessageDispatcher",
    "TelegramBotMessageDispatcher",
]
