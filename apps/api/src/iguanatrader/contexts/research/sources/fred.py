"""FRED (Federal Reserve Economic Data) Tier-A source adapter (slice R2).

Per slice R2 design D4: ALFRED-aware vintage mode preserves all
publication vintages so revisions land as new facts rather than
overwriting prior values. Bitemporal mapping:

* ``effective_from = observation.date`` — the period the value refers to.
* ``recorded_from = observation.realtime_start`` — the date FRED published
  this vintage.
* ``effective_to = observation.realtime_end`` (or ``NULL`` when the
  ``9999-12-31`` sentinel is returned).

The adapter exposes :meth:`fetch_series` (series-based, not symbol-based);
the inherited :meth:`fetch` raises :class:`NotImplementedError` because
FRED does not have a ticker concept. R5's scheduler will register the
relevant series IDs per methodology.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"
# FRED's "no end" sentinel — observations with ``realtime_end == 9999-12-31``
# represent the current vintage.
_REALTIME_END_OPEN = "9999-12-31"


class FREDSource(TierASourceAdapter):
    """FRED adapter — ALFRED vintage-aware macro time-series ingestion."""

    SOURCE_ID: ClassVar[str] = "fred"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 2.0  # 120 req/min

    def __init__(self, **kwargs: Any) -> None:
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(detail="FRED_API_KEY env var is required")
        self._api_key = api_key
        super().__init__(**kwargs)

    def fetch_series(
        self,
        series_id: str,
        since: datetime | None = None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield drafts for ``series_id`` whose vintages are newer than ``since``."""
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._api_key,
            "file_type": "json",
            "realtime_end": _REALTIME_END_OPEN,
        }
        if since is not None:
            params["realtime_start"] = since.date().isoformat()
        else:
            # FRED documents 1776-07-04 as the historic floor; using a
            # safer 1900 default keeps the response size bounded for
            # series that start mid-20th-century.
            params["realtime_start"] = "1900-01-01"

        payload = self._request_json("GET", _OBSERVATIONS_URL, params=params)
        if payload is None:
            return

        for obs in payload.get("observations", []):
            draft = self._build_draft(obs, series_id=series_id)
            if draft is not None:
                yield draft

    def _build_draft(
        self,
        obs: dict[str, Any],
        *,
        series_id: str,
    ) -> ResearchFactDraft | None:
        date_str = obs.get("date")
        value_str = obs.get("value")
        rt_start_str = obs.get("realtime_start")
        rt_end_str = obs.get("realtime_end")
        if not (date_str and value_str and rt_start_str and rt_end_str):
            return None
        if value_str in {".", ""}:
            logger.info(
                "research.fred.skipped_missing",
                extra={"series_id": series_id, "date": date_str},
            )
            return None
        try:
            effective_from = datetime.fromisoformat(date_str).replace(tzinfo=UTC)
            recorded_from = datetime.fromisoformat(rt_start_str).replace(tzinfo=UTC)
        except ValueError:
            logger.warning(
                "research.fred.skipped_unparseable_date",
                extra={"series_id": series_id, "date": date_str, "realtime_start": rt_start_str},
            )
            return None
        effective_to: datetime | None = None
        if rt_end_str != _REALTIME_END_OPEN:
            try:
                effective_to = datetime.fromisoformat(rt_end_str).replace(tzinfo=UTC)
            except ValueError:
                effective_to = None
        try:
            value_numeric = Decimal(value_str)
        except InvalidOperation:
            logger.warning(
                "research.fred.skipped_unparseable_value",
                extra={"series_id": series_id, "value": value_str},
            )
            return None
        fact_metadata = {
            "series_id": series_id,
            "realtime_start": rt_start_str,
            "realtime_end": rt_end_str,
        }
        payload = {
            "series_id": series_id,
            "date": date_str,
            "value": value_str,
            "realtime_start": rt_start_str,
            "realtime_end": rt_end_str,
        }
        return self._make_draft(
            fact_kind=f"fred.{series_id}",
            effective_from=effective_from,
            recorded_from=recorded_from,
            effective_to=effective_to,
            source_url=f"{_OBSERVATIONS_URL}?series_id={series_id}",
            value_numeric=value_numeric,
            fact_metadata=fact_metadata,
            dedupe_key=f"fred:{series_id}:{date_str}:{rt_start_str}",
        ).with_payload(json.dumps(payload, sort_keys=True).encode())


__all__ = ["FREDSource"]
