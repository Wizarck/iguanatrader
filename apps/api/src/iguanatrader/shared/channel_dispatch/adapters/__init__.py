"""Concrete channel adapters wrapping injectable HTTP / SMTP transports."""

from iguanatrader.shared.channel_dispatch.adapters.email_smtp import (
    EmailSMTPDispatcher,
)
from iguanatrader.shared.channel_dispatch.adapters.hermes import (
    HermesWhatsAppMessageDispatcher,
)
from iguanatrader.shared.channel_dispatch.adapters.telegram import (
    TelegramBotMessageDispatcher,
)

__all__ = [
    "EmailSMTPDispatcher",
    "HermesWhatsAppMessageDispatcher",
    "TelegramBotMessageDispatcher",
]
