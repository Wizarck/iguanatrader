"""Unit tests for :func:`iguanatrader.shared.channel_dispatch.recipients.resolve_recipients_for_user`.

Four cases (proposal §Tests):

1. Email only (telegram + whatsapp NULL) → 1 :class:`Recipient` (email).
2. Email + telegram → 2 :class:`Recipient` (email, telegram).
3. Email + whatsapp → 2 :class:`Recipient` (email, whatsapp).
4. All three → 3 :class:`Recipient` (email, telegram, whatsapp), in
   canonical order.

The helper consumes a structural :class:`UserRecipientFields`, so we
pass :class:`types.SimpleNamespace` doubles rather than the ORM
:class:`User` to keep these unit tests independent of the DB schema.
"""

from __future__ import annotations

from types import SimpleNamespace

from iguanatrader.shared.channel_dispatch.recipients import (
    resolve_recipients_for_user,
)


def test_email_only_returns_single_email_recipient() -> None:
    user = SimpleNamespace(
        email="alice@example.com",
        telegram_chat_id=None,
        whatsapp_phone=None,
    )
    out = resolve_recipients_for_user(user)
    assert len(out) == 1
    assert out[0].channel == "email"
    assert out[0].address == "alice@example.com"


def test_email_plus_telegram_returns_two_recipients_in_order() -> None:
    user = SimpleNamespace(
        email="alice@example.com",
        telegram_chat_id="123456789",
        whatsapp_phone=None,
    )
    out = resolve_recipients_for_user(user)
    assert [r.channel for r in out] == ["email", "telegram"]
    assert out[1].address == "123456789"


def test_email_plus_whatsapp_returns_two_recipients_in_order() -> None:
    user = SimpleNamespace(
        email="alice@example.com",
        telegram_chat_id=None,
        whatsapp_phone="+15551234567",
    )
    out = resolve_recipients_for_user(user)
    assert [r.channel for r in out] == ["email", "whatsapp"]
    assert out[1].address == "+15551234567"


def test_all_three_channels_returns_canonical_order() -> None:
    user = SimpleNamespace(
        email="alice@example.com",
        telegram_chat_id="123456789",
        whatsapp_phone="+15551234567",
    )
    out = resolve_recipients_for_user(user)
    assert [r.channel for r in out] == ["email", "telegram", "whatsapp"]
    assert [r.address for r in out] == [
        "alice@example.com",
        "123456789",
        "+15551234567",
    ]


def test_whitespace_only_addresses_are_filtered() -> None:
    """Operator-set blank strings (instead of NULL) MUST be ignored.

    Defensive: a future admin CLI that accepts user input could trim
    to ``""`` without realising NULL is the intended sentinel; the
    helper treats blank-after-strip as "no channel" so empty
    recipients never reach the dispatcher.
    """
    user = SimpleNamespace(
        email="alice@example.com",
        telegram_chat_id="   ",
        whatsapp_phone="",
    )
    out = resolve_recipients_for_user(user)
    assert [r.channel for r in out] == ["email"]
