"""BEA (Bureau of Economic Analysis) Tier-A source adapter (slice R2).

Per slice R2 design D6: NIPA tables (T10101 GDP etc.) get advance,
second, third, and annual revision releases. Each release lands as its
own fact — the adapter encodes the source release date into
``recorded_from`` so the bitemporal axis preserves the "what we believed
about Q1 GDP at time T" semantics.
"""

from __future__ import annotations

import calendar
import logging
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_API_URL = "https://apps.bea.gov/api/data/"

# Quarterly time-period tokens BEA returns: ``2024Q1``, ``2024Q2``, etc.
# Annual tokens: ``2024``. Monthly tokens: ``2024M01``..``2024M12``.
_QUARTERLY_RE = re.compile(r"^(\d{4})Q([1-4])$")
_MONTHLY_RE = re.compile(r"^(\d{4})M(\d{2})$")
_ANNUAL_RE = re.compile(r"^(\d{4})$")


class BEASource(TierASourceAdapter):
    """BEA adapter — NIPA + national accounts via the BEA Data API."""

    SOURCE_ID: ClassVar[str] = "bea"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.66  # ~100/min

    def __init__(self, **kwargs: Any) -> None:
        api_key = os.environ.get("BEA_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(detail="BEA_API_KEY env var is required")
        self._api_key = api_key
        super().__init__(**kwargs)

    def fetch_dataset(
        self,
        dataset: str,
        table: str,
        frequency: str,
        year_range: str | None = None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield drafts for ``(dataset, table, frequency)`` rows.

        Mirrors BEA's ``GetData`` parameters. ``year_range`` follows BEA
        syntax (e.g. ``"X"`` for "all available", ``"2020,2021,2022"``,
        ``"2010-2020"``).
        """
        params = {
            "UserID": self._api_key,
            "method": "GetData",
            "datasetname": dataset,
            "TableName": table,
            "Frequency": frequency,
            "Year": year_range or "X",
            "ResultFormat": "JSON",
        }
        payload = self._request_json("GET", _API_URL, params=params)
        if payload is None:
            return
        results = payload.get("BEAAPI", {}).get("Results", {})
        rows = results.get("Data", [])
        for row in rows:
            draft = self._build_draft(
                row,
                dataset=dataset,
                table=table,
                frequency=frequency,
            )
            if draft is not None:
                yield draft

    def _build_draft(
        self,
        row: dict[str, Any],
        *,
        dataset: str,
        table: str,
        frequency: str,
    ) -> ResearchFactDraft | None:
        time_period = row.get("TimePeriod") or ""
        value_str = row.get("DataValue") or ""
        if not time_period or value_str.strip() in {"", "..."}:
            return None
        try:
            period_start, period_end = self._parse_time_period(time_period)
        except ValueError:
            logger.info(
                "research.bea.skipped_unparseable_period",
                extra={"dataset": dataset, "table": table, "period": time_period},
            )
            return None
        # BEA returns numeric strings with thousands-separator commas; strip
        # them before Decimal parsing.
        cleaned_value = value_str.replace(",", "").strip()
        try:
            value_numeric = Decimal(cleaned_value)
        except InvalidOperation:
            return None
        # Recorded_from approximation: BEA quarterly GDP advance estimate
        # publishes ~30 days post-quarter-end. Using period_end + 30 days as
        # a calendar-free fallback; R5 will refine via the BEA release
        # calendar surface.
        recorded_from = period_end + timedelta(days=30)
        line_description = row.get("LineDescription") or row.get("LineNumber") or "value"
        return self._make_draft(
            fact_kind=f"bea.{dataset}.{table}.{line_description}",
            effective_from=period_start,
            effective_to=period_end,
            recorded_from=recorded_from,
            source_url=f"{_API_URL}?datasetname={dataset}&TableName={table}",
            value_numeric=value_numeric,
            unit=row.get("CL_UNIT"),
            fact_metadata={
                "dataset": dataset,
                "table": table,
                "frequency": frequency,
                "time_period": time_period,
                "line_number": row.get("LineNumber"),
                "line_description": row.get("LineDescription"),
                "series_code": row.get("SeriesCode"),
                "note_ref": row.get("NoteRef"),
            },
            dedupe_key=(
                f"bea:{dataset}:{table}:{frequency}:{time_period}:"
                f"{recorded_from.date().isoformat()}"
            ),
        )

    @staticmethod
    def _parse_time_period(token: str) -> tuple[datetime, datetime]:
        """Return (start, end) UTC datetimes for a BEA TimePeriod token."""
        m = _QUARTERLY_RE.match(token)
        if m:
            year = int(m.group(1))
            quarter = int(m.group(2))
            start_month = (quarter - 1) * 3 + 1
            end_month = start_month + 2
            last_day = calendar.monthrange(year, end_month)[1]
            return (
                datetime(year, start_month, 1, tzinfo=UTC),
                datetime(year, end_month, last_day, 23, 59, 59, tzinfo=UTC),
            )
        m = _MONTHLY_RE.match(token)
        if m:
            year = int(m.group(1))
            month = int(m.group(2))
            if not 1 <= month <= 12:
                raise ValueError(f"month out of range in {token!r}")
            last_day = calendar.monthrange(year, month)[1]
            return (
                datetime(year, month, 1, tzinfo=UTC),
                datetime(year, month, last_day, 23, 59, 59, tzinfo=UTC),
            )
        m = _ANNUAL_RE.match(token)
        if m:
            year = int(m.group(1))
            return (
                datetime(year, 1, 1, tzinfo=UTC),
                datetime(year, 12, 31, 23, 59, 59, tzinfo=UTC),
            )
        raise ValueError(f"unparseable BEA TimePeriod {token!r}")


__all__ = ["BEASource"]
