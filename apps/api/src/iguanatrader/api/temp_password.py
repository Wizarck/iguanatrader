"""Temporary password generator for the forgot-password flow.

Slice ``auth-forgot-password-flow``. The generator returns a 16-character
base32-no-confusables credential formatted as ``XXXX-XXXX-XXXX-XXXX`` so
operators can dictate it over a phone if a recovery channel is broken.

Alphabet: ``ABCDEFGHJKLMNPQRSTUVWXYZ23456789`` (32 chars; the
``A-HJ-NP-Z2-9`` shape from the proposal). Confusable glyphs ``0/O``
and ``1/I`` are excluded so the credential is unambiguous when read
aloud or pasted from a screenshot. Per-character entropy =
log2(32) = 5 bits; 16 characters = 80 bits — comfortably above the
NIST SP 800-63B 60-bit floor for ephemeral provisional credentials.

Uses :func:`secrets.choice` (CSPRNG) — never :mod:`random` (which is
seeded from the process clock and predictable). The function is pure
(no I/O, no side effects); call it once per recovery event and discard
the plaintext as soon as it has been hashed + dispatched.

NOT a sibling of :mod:`iguanatrader.api.auth` because that module is a
single-file ``auth.py`` (not a package); a flat sibling module keeps the
import surface obvious without renaming the existing file.
"""

from __future__ import annotations

import secrets

#: 32-char base32-no-confusables alphabet (proposal shape ``A-HJ-NP-Z2-9``).
#: Excludes the ``0/O`` and ``1/I`` confusable pairs while keeping ``L``
#: (visually distinct from ``1`` in a monospace font). 5 bits of entropy
#: per character.
TEMP_PASSWORD_ALPHABET: str = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

#: Per-group character count. 4 groups of 4 = 16 chars total.
TEMP_PASSWORD_GROUP_SIZE: int = 4

#: Number of groups in the formatted string.
TEMP_PASSWORD_GROUP_COUNT: int = 4

#: Total character count (excluding separators). 16 chars * 5 bits = 80
#: bits of entropy — above the NIST SP 800-63B 60-bit floor.
TEMP_PASSWORD_CHAR_COUNT: int = TEMP_PASSWORD_GROUP_SIZE * TEMP_PASSWORD_GROUP_COUNT


def generate_temp_password() -> str:
    """Return a fresh ``XXXX-XXXX-XXXX-XXXX`` temporary password.

    Each character is drawn independently from
    :data:`TEMP_PASSWORD_ALPHABET` via :func:`secrets.choice`. The string
    is suitable for handing out as a provisional credential — pair with
    :data:`users.must_change_password = TRUE` so the user must rotate on
    first login.
    """
    chars = [secrets.choice(TEMP_PASSWORD_ALPHABET) for _ in range(TEMP_PASSWORD_CHAR_COUNT)]
    groups = [
        "".join(chars[i : i + TEMP_PASSWORD_GROUP_SIZE])
        for i in range(0, TEMP_PASSWORD_CHAR_COUNT, TEMP_PASSWORD_GROUP_SIZE)
    ]
    return "-".join(groups)


__all__ = [
    "TEMP_PASSWORD_ALPHABET",
    "TEMP_PASSWORD_CHAR_COUNT",
    "TEMP_PASSWORD_GROUP_COUNT",
    "TEMP_PASSWORD_GROUP_SIZE",
    "generate_temp_password",
]
