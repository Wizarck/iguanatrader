"""HMAC payload-signing helper.

A single function so the surface stays tiny and testable. Adapters that need
to sign request bodies (e.g. Hermes WhatsApp HTTP) call this directly.
"""

from __future__ import annotations

import hashlib
import hmac


def hmac_sha256_hex(secret: bytes, payload: bytes) -> str:
    """Return the hex-encoded HMAC-SHA256 of ``payload`` keyed by ``secret``."""
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


__all__ = ["hmac_sha256_hex"]
