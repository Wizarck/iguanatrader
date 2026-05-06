"""User-Agent rotation pool (slice R3 FR79).

Per FR79, every scrape MUST carry an iguanatrader-identifying User-Agent
that includes the operator's contact email so a site administrator can
reach us if our crawl impacts their service.
"""

from __future__ import annotations

import random
from collections.abc import Iterable

#: Canonical UA template. Operators override via env vars in the
#: deployment slice; MVP uses the project default.
DEFAULT_OPS_EMAIL = "arturo6ramirez@gmail.com"
DEFAULT_VERSION = "0.0.0"


class UserAgentRotation:
    """Cycle through a pool of compatible User-Agent strings.

    Each entry MUST contain the iguanatrader identifier + ops email.
    The pool is intentionally small — too much rotation is itself a
    signal to anti-bot defences. ``next()`` returns the next UA in
    a round-robin order; ``random_choice()`` picks at random.
    """

    def __init__(
        self,
        *,
        ops_email: str = DEFAULT_OPS_EMAIL,
        version: str = DEFAULT_VERSION,
        extra: Iterable[str] = (),
    ) -> None:
        self._ops_email = ops_email
        self._version = version
        base = f"iguanatrader/{version} (+{ops_email})"
        firefox = f"{base} Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0"
        chrome = (
            f"{base} Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            f"AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self._pool: list[str] = [base, firefox, chrome, *extra]
        self._index = 0

    def next(self) -> str:
        ua = self._pool[self._index % len(self._pool)]
        self._index += 1
        return ua

    def random_choice(self) -> str:
        return random.choice(self._pool)

    def all(self) -> tuple[str, ...]:
        return tuple(self._pool)


__all__ = ["DEFAULT_OPS_EMAIL", "DEFAULT_VERSION", "UserAgentRotation"]
