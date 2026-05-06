"""World Bank Worldwide Governance Indicators (WGI) adapter (slice R3 FR67/FR77).

WGI is published annually with a ~1-year lag; iguanatrader treats this
as a **Tier-C bootstrap** source — facts are loaded once at the
bootstrapped reference timestamp and subsequent reads return ``None``
until the next yearly bootstrap.

The World Bank Indicators API (https://api.worldbank.org/v2) is JSON-
queryable without auth. Politeness floor: ≤1 req/s.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import ClassVar

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_INDICATOR_URL = "https://api.worldbank.org/v2/country/{country}/indicator/{indicator}"

# Six WGI canonical indicator IDs.
WGI_INDICATORS: tuple[str, ...] = (
    "GE.EST",  # Government effectiveness
    "RQ.EST",  # Regulatory quality
    "RL.EST",  # Rule of law
    "CC.EST",  # Control of corruption
    "VA.EST",  # Voice and accountability
    "PV.EST",  # Political stability and absence of violence
)


class WGISource(TierASourceAdapter):
    """Tier-C bootstrap WGI adapter."""

    SOURCE_ID: ClassVar[str] = "wgi_world_bank"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.0

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        # ``symbol`` is interpreted as a 3-letter ISO country code (e.g.
        # ``USA``); for stock-ticker callers, R5's feature_provider maps
        # the company's headquarters country externally.
        country = symbol.upper()
        for indicator in WGI_INDICATORS:
            yield from self._fetch_indicator(country, indicator, since)

    def _fetch_indicator(
        self,
        country: str,
        indicator: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        url = _INDICATOR_URL.format(country=country, indicator=indicator)
        params = {"format": "json", "per_page": 50}
        payload = self._request_json("GET", url, params=params)
        if not isinstance(payload, list) or len(payload) < 2:
            return
        rows = payload[1]
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            year = row.get("date")
            value = row.get("value")
            if year is None or value is None:
                continue
            try:
                effective_from = datetime(int(str(year)), 12, 31, tzinfo=UTC)
                value_decimal = Decimal(str(value))
            except (ValueError, InvalidOperation):
                continue
            if since is not None and effective_from < since:
                continue
            yield self._make_draft(
                fact_kind=f"wgi.{indicator}",
                effective_from=effective_from,
                source_url=url,
                value_numeric=value_decimal,
                fact_metadata={"country": country, "indicator": indicator, "year": year},
                dedupe_key=f"wgi:{country}:{indicator}:{year}",
            )


__all__ = ["WGI_INDICATORS", "WGISource"]
