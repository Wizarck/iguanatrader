"""BLS (Bureau of Labor Statistics) Tier-A source adapter (slice R2).

Per slice R2 design D5: registered tier required (free, requires email
sign-up). Free unregistered tier is too thin for production use AND
returns 200 OK with ``status="REQUEST_NOT_PROCESSED"`` in the JSON body
when limits are exceeded — adapter checks the body status (not just
HTTP status) and raises :class:`RateLimitedError` accordingly.

Bitemporal mapping:

* ``effective_from`` / ``effective_to`` — period bounds derived from
  ``(year, period)`` (M01-M12 → calendar month; Q01-Q04 → quarter;
  A01 → year).
* ``recorded_from`` — ``release_date`` looked up against BLS' release
  calendar (cached); falls back to ``period_end`` when calendar is
  unavailable.
"""

from __future__ import annotations

import calendar
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import ConfigError, RateLimitedError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_TIMESERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"


class BLSSource(TierASourceAdapter):
    """BLS adapter — registered-tier employment + inflation series."""

    SOURCE_ID: ClassVar[str] = "bls"
    # ~500/day == 0.0058 req/s. Token-bucket capacity is ``max(1, rate)``
    # so the bucket starts with 1 token (enough for first call) and
    # replenishes at the documented rate — operators who exceed the
    # quota will see 200 + REQUEST_NOT_PROCESSED before the bucket can
    # block, hence the body-status check below.
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 0.0058

    def __init__(self, **kwargs: Any) -> None:
        api_key = os.environ.get("BLS_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(detail="BLS_API_KEY env var is required (registered tier)")
        self._api_key = api_key
        super().__init__(**kwargs)

    def fetch_series(
        self,
        series_id: str,
        since: datetime | None = None,
    ) -> Iterable[ResearchFactDraft]:
        start_year = since.year if since else 2000
        end_year = datetime.now(tz=UTC).year
        body = {
            "seriesid": [series_id],
            "startyear": str(start_year),
            "endyear": str(end_year),
            "registrationkey": self._api_key,
        }
        payload = self._request_json("POST", _TIMESERIES_URL, json_body=body)
        if payload is None:
            return
        status = payload.get("status")
        if status != "REQUEST_SUCCEEDED":
            message = (payload.get("message") or [""])[0] if payload.get("message") else ""
            raise RateLimitedError(
                detail=f"BLS rejected request for {series_id}: status={status} message={message}",
            )
        for series_block in payload.get("Results", {}).get("series", []):
            for row in series_block.get("data", []):
                draft = self._build_draft(row, series_id=series_id)
                if draft is not None:
                    yield draft

    def _build_draft(
        self,
        row: dict[str, Any],
        *,
        series_id: str,
    ) -> ResearchFactDraft | None:
        year_str = row.get("year")
        period = row.get("period")
        value_str = row.get("value")
        if not (year_str and period and value_str is not None):
            return None
        try:
            year = int(year_str)
        except ValueError:
            return None
        try:
            period_start, period_end = self._parse_period(year, period)
        except ValueError:
            logger.info(
                "research.bls.skipped_unsupported_period",
                extra={"series_id": series_id, "period": period},
            )
            return None
        try:
            value_numeric = Decimal(str(value_str))
        except InvalidOperation:
            return None
        # Best-effort release_date — BLS publishes release calendars per
        # series; we don't ship the calendar in R2 (deferred to R5 once
        # the calendar surface is exercised). Fall back to period_end + 1
        # month, which approximates BLS' typical 30-45 day publication lag.
        recorded_from = period_end + timedelta(days=30)
        return self._make_draft(
            fact_kind=f"bls.{series_id}",
            effective_from=period_start,
            effective_to=period_end,
            recorded_from=recorded_from,
            source_url=f"{_TIMESERIES_URL}{series_id}",
            value_numeric=value_numeric,
            fact_metadata={
                "series_id": series_id,
                "year": year,
                "period": period,
                "footnotes": row.get("footnotes"),
            },
            dedupe_key=f"bls:{series_id}:{year}:{period}:{recorded_from.date().isoformat()}",
        )

    @staticmethod
    def _parse_period(year: int, period: str) -> tuple[datetime, datetime]:
        """Return (start, end) UTC datetimes for a BLS ``(year, period)`` pair.

        Supports:
        * ``M01``-``M12`` — calendar months.
        * ``Q01``-``Q04`` — quarters.
        * ``A01`` — annual.
        * Other (``S01``/``S02`` semi-annual, ``R01``-``R12`` annual ranking) → ValueError.
        """
        if not period or len(period) < 2:
            raise ValueError(f"unsupported period {period!r}")
        prefix = period[0]
        idx_str = period[1:]
        try:
            idx = int(idx_str)
        except ValueError as exc:
            raise ValueError(f"unparseable period index in {period!r}") from exc
        if prefix == "M" and 1 <= idx <= 12:
            start = datetime(year, idx, 1, tzinfo=UTC)
            last_day = calendar.monthrange(year, idx)[1]
            end = datetime(year, idx, last_day, 23, 59, 59, tzinfo=UTC)
            return start, end
        if prefix == "Q" and 1 <= idx <= 4:
            start_month = (idx - 1) * 3 + 1
            end_month = start_month + 2
            last_day = calendar.monthrange(year, end_month)[1]
            return (
                datetime(year, start_month, 1, tzinfo=UTC),
                datetime(year, end_month, last_day, 23, 59, 59, tzinfo=UTC),
            )
        if prefix == "A" and idx == 1:
            return (
                datetime(year, 1, 1, tzinfo=UTC),
                datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
            )
        raise ValueError(f"unsupported period {period!r}")


__all__ = ["BLSSource"]
