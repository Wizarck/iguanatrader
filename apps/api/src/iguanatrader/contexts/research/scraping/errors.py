"""Scrape-ladder error classes (slice R3 ADR-017)."""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IntegrationError


class ScrapeBlockedError(IntegrationError):
    """A scrape tier hit an anti-bot block (HTTP 403/429/CAPTCHA challenge).

    The ladder catches this + escalates to the next tier (per ADR-017).
    Distinct ``type`` URI so structlog dashboards can pattern-match
    "tier escalation" events vs generic 502 lifts.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:scrape-blocked"
    default_title: ClassVar[str] = "Scrape Blocked — Escalating Tier"
    default_status: ClassVar[int] = 503


class ScrapeNotImplementedError(IntegrationError):
    """A tier higher than 1 was requested but its dependencies aren't installed.

    Tier-2 needs Playwright; tier-3 needs Camoufox; tier-4 needs a
    paid CAPTCHA solver. The ``deployment-foundation`` slice wires these.
    Until then, the ladder raises this when escalation crosses the
    Tier-1 boundary.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:scrape-tier-not-installed"
    default_title: ClassVar[str] = "Scrape Tier Dependencies Not Installed"
    default_status: ClassVar[int] = 501


class UnsafeUrlError(IntegrationError):
    """#13: a scrape target failed the SSRF guard (bad scheme, no host, or a
    host that resolves to a private/loopback/link-local/reserved address).

    Deliberately NOT a :class:`ScrapeBlockedError` — the ladder must NOT
    escalate to a higher tier and retry the same dangerous URL. This is a
    hard refusal that propagates straight out of the ladder.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:scrape-unsafe-url"
    default_title: ClassVar[str] = "Scrape Target Failed SSRF Guard"
    default_status: ClassVar[int] = 400


__all__ = ["ScrapeBlockedError", "ScrapeNotImplementedError", "UnsafeUrlError"]
