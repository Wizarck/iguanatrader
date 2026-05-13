"""User-record → :class:`Recipient` projection.

Slice ``auth-forgot-password-flow`` extracts this helper so flows that
dispatch to a single user (forgot-password today; future password-reset
notifications, security alerts, etc.) do not have to re-walk the
``email + telegram_chat_id + whatsapp_phone`` triple.

The :class:`UserRecipientFields` Protocol keeps this module decoupled
from the ORM ``User`` class — any object that exposes the three fields
plus a non-empty ``email`` is acceptable. That lets callers pass:

* The full ORM :class:`iguanatrader.persistence.User`.
* A simple namespace / dataclass in tests.
* A future read-model projection.

Without coupling. The helper lives under ``shared.channel_dispatch``
because it is the dual of the existing ``shared.channel_dispatch``
adapters — they consume :class:`Recipient`, this produces it.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from iguanatrader.shared.channel_dispatch.adapters.email_smtp import EMAIL_CHANNEL
from iguanatrader.shared.channel_dispatch.adapters.hermes import WHATSAPP_CHANNEL
from iguanatrader.shared.channel_dispatch.adapters.telegram import TELEGRAM_CHANNEL
from iguanatrader.shared.channel_dispatch.types import Recipient


@runtime_checkable
class UserRecipientFields(Protocol):
    """Structural type describing the fields :func:`resolve_recipients_for_user` reads.

    Both the SQLAlchemy ORM :class:`iguanatrader.persistence.User` model
    and lightweight test doubles (a :class:`types.SimpleNamespace`, a
    frozen dataclass, etc.) satisfy this Protocol — it is intentionally
    structural so this helper does not import the ORM model and stays
    upstream-extractable per the
    :mod:`iguanatrader.shared.channel_dispatch` "no ``iguanatrader.contexts.*``"
    constraint.
    """

    email: str
    telegram_chat_id: str | None
    whatsapp_phone: str | None


def resolve_recipients_for_user(user: UserRecipientFields) -> list[Recipient]:
    """Project a user record to one :class:`Recipient` per wired channel.

    Returns a list in canonical order (email → telegram → whatsapp) so
    callers + tests see a deterministic shape. Empty / whitespace-only
    addresses are filtered out — an operator who set
    ``telegram_chat_id = ""`` (instead of NULL) does not accidentally
    spawn a Telegram recipient with an empty ``chat_id``.

    The ``email`` field is treated as always-on: a user without an email
    has no other identity in the system today, so an empty / blank value
    produces zero email recipients but does NOT raise (callers may want
    to handle the "no channels at all" case themselves).
    """
    recipients: list[Recipient] = []
    email = (user.email or "").strip()
    if email:
        recipients.append(Recipient(channel=EMAIL_CHANNEL, address=email))
    telegram = (user.telegram_chat_id or "").strip() if user.telegram_chat_id else ""
    if telegram:
        recipients.append(Recipient(channel=TELEGRAM_CHANNEL, address=telegram))
    whatsapp = (user.whatsapp_phone or "").strip() if user.whatsapp_phone else ""
    if whatsapp:
        recipients.append(Recipient(channel=WHATSAPP_CHANNEL, address=whatsapp))
    return recipients


__all__ = [
    "UserRecipientFields",
    "resolve_recipients_for_user",
]
