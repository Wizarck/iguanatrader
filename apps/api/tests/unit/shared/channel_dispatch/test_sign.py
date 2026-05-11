"""Unit test for :func:`hmac_sha256_hex` — known-vector."""

from __future__ import annotations

import hashlib
import hmac

from iguanatrader.shared.channel_dispatch import hmac_sha256_hex


def test_hmac_matches_stdlib() -> None:
    secret = b"shh"
    payload = b'{"a":1}'
    expected = hmac.new(secret, payload, hashlib.sha256).hexdigest()
    assert hmac_sha256_hex(secret, payload) == expected


def test_hmac_changes_with_payload() -> None:
    secret = b"shh"
    assert hmac_sha256_hex(secret, b"a") != hmac_sha256_hex(secret, b"b")


def test_hmac_changes_with_secret() -> None:
    payload = b"same"
    assert hmac_sha256_hex(b"k1", payload) != hmac_sha256_hex(b"k2", payload)
