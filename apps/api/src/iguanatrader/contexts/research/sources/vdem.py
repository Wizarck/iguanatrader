"""V-Dem democracy index adapter (slice R3 FR67/FR77, Tier-C bootstrap).

V-Dem (Varieties of Democracy, https://v-dem.net/) publishes the
canonical liberal/electoral/participatory democracy index annually
in CSV + REST snapshots. This adapter consumes the static REST
endpoint (``https://v-dem.net/dataservice/v1/country/<code>/year/<yyyy>``)
which returns a per-country indicator vector.

Tier-C: facts load once at bootstrap; subsequent reads are no-ops. The
caller (R5 feature_provider) mints the bootstrap year via the watchlist
config.

No auth required; politeness floor ≤1 req/s.
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


_BASE_URL = "https://v-dem.net/dataservice/v1"

# Canonical V-Dem indicator codes (subset).
VDEM_INDICATORS: tuple[str, ...] = (
    "v2x_polyarchy",
    "v2x_libdem",
    "v2x_partipdem",
    "v2x_delibdem",
    "v2x_egaldem",
)


class VDEMSource(TierASourceAdapter):
    """Tier-C bootstrap V-Dem democracy index adapter."""

    SOURCE_ID: ClassVar[str] = "vdem"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.0

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        country = symbol.upper()
        end_year = datetime.now(tz=UTC).year - 1  # V-Dem publishes with 1y lag
        url = f"{_BASE_URL}/country/{country}/year/{end_year}"
        payload = self._request_json("GET", url)
        if payload is None or not isinstance(payload, dict):
            return
        for indicator in VDEM_INDICATORS:
            value = payload.get(indicator)
            if value is None:
                continue
            try:
                value_decimal = Decimal(str(value))
            except InvalidOperation:
                continue
            effective_from = datetime(end_year, 12, 31, tzinfo=UTC)
            yield self._make_draft(
                fact_kind=f"vdem.{indicator}",
                effective_from=effective_from,
                source_url=url,
                value_numeric=value_decimal,
                fact_metadata={"country": country, "indicator": indicator, "year": end_year},
                dedupe_key=f"vdem:{country}:{indicator}:{end_year}",
            )


__all__ = ["VDEM_INDICATORS", "VDEMSource"]
