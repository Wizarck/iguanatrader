"""Unit tests for :mod:`iguanatrader.api.temp_password`.

Three cases (proposal §Tests):

1. Format: every generated string matches ``XXXX-XXXX-XXXX-XXXX`` (4
   groups of 4 chars separated by ``-``).
2. Alphabet constraint: every character is in
   :data:`TEMP_PASSWORD_ALPHABET` (no confusable glyphs).
3. Entropy floor: across N samples the empirical Shannon entropy per
   character is close to the theoretical 5 bits — coarse but catches
   a constant-output bug.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from iguanatrader.api.temp_password import (
    TEMP_PASSWORD_ALPHABET,
    TEMP_PASSWORD_CHAR_COUNT,
    generate_temp_password,
)

#: Canonical regex for the formatted shape — anchored so any trailing
#: garbage (a stray newline, a copy-paste suffix) trips the assertion.
_TEMP_PASSWORD_RE = re.compile(
    r"^[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-"
    r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-"
    r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}-"
    r"[ABCDEFGHJKLMNPQRSTUVWXYZ23456789]{4}$"
)

#: Confusable glyphs excluded from the alphabet — 0/O, 1/I.
#: NB: ``L`` is kept (only ``I`` is excluded from the L/I pair, per the
#: ``A-HJ-NP-Z2-9`` shape in the proposal — RFC 4648 base32 omits 0/1/8/9
#: but the proposal explicitly keeps 8/9 and only drops the I/O/0/1 set).
_FORBIDDEN_GLYPHS: frozenset[str] = frozenset({"0", "1", "I", "O"})


def test_temp_password_format_is_four_groups_of_four() -> None:
    """Every sample matches ``XXXX-XXXX-XXXX-XXXX`` exactly."""
    for _ in range(200):
        pw = generate_temp_password()
        assert _TEMP_PASSWORD_RE.match(pw), f"format mismatch: {pw!r}"
        # And the unformatted character count matches the constant.
        assert len(pw.replace("-", "")) == TEMP_PASSWORD_CHAR_COUNT


def test_temp_password_alphabet_excludes_confusables() -> None:
    """No character is outside the no-confusables alphabet.

    The alphabet excludes the ``0/O`` and ``1/I`` confusable pairs (per
    the proposal §What alphabet ``A-HJ-NP-Z2-9``). ``L`` is intentionally
    kept — visually distinct from ``1`` in a monospace font.
    """
    allowed = set(TEMP_PASSWORD_ALPHABET)
    assert _FORBIDDEN_GLYPHS.isdisjoint(allowed)
    for _ in range(200):
        pw = generate_temp_password().replace("-", "")
        for ch in pw:
            assert ch in allowed, f"unexpected glyph {ch!r} in {pw!r}"


def test_temp_password_empirical_entropy_per_char_is_at_least_4_bits() -> None:
    """Coarse Shannon-entropy check guards against constant outputs.

    Theoretical: log2(32) = 5.0 bits. Sample 5000 chars; the empirical
    entropy converges close to 5 bits but with sampling noise we set
    the assertion floor at 4.5 bits — well above any pathological
    constant / biased generator the test is designed to catch.
    """
    samples = [
        generate_temp_password().replace("-", "")
        for _ in range(5000 // TEMP_PASSWORD_CHAR_COUNT + 1)
    ]
    chars = [ch for pw in samples for ch in pw]
    counts = Counter(chars)
    total = sum(counts.values())
    entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
    assert entropy >= 4.5, f"empirical entropy too low: {entropy}"
