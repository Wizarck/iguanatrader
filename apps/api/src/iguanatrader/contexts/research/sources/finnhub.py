"""Finnhub Tier-B news + sentiment + earnings adapter (slice R3).

Per slice R3 + FR61 + FR62: Finnhub is the primary source for company
news + headline sentiment + earnings calendar. Free tier is 60
requests / minute; production deployments lift to a paid tier per
operator config.

Endpoints consumed:

* ``/company-news?symbol=SYMBOL&from=YYYY-MM-DD&to=YYYY-MM-DD`` —
  news headlines for a single symbol.
* ``/calendar/earnings?from=YYYY-MM-DD&to=YYYY-MM-DD&symbol=SYMBOL`` —
  earnings calendar entries (analyst estimates + report dates).

Bitemporal mapping:

* ``effective_from`` = headline ``datetime`` (when the news was
  published in the world).
* ``recorded_from`` = ``utc_now()`` at fetch time (when iguanatrader
  observed the headline).
* ``dedupe_key`` = ``finnhub:<id>`` (Finnhub assigns a numeric id per
  article).
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_BASE_URL = "https://finnhub.io/api/v1"
_DEFAULT_LOOKBACK_DAYS = 7


class FinnhubSource(TierASourceAdapter):
    """Tier-B Finnhub adapter — news + earnings calendar.

    Inherits :class:`TierASourceAdapter` for retry / backoff / token
    bucket / structlog plumbing. Sets ``SOURCE_ID="finnhub"`` so the
    persisted facts join to ``research_sources(id='finnhub', pit_class='B')``
    seeded by migration ``0010_research_sources_tier_b_c``.
    """

    SOURCE_ID: ClassVar[str] = "finnhub"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.0  # 60 req/min free tier

    def __init__(self, **kwargs: Any) -> None:
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            raise ConfigError(detail="FINNHUB_API_KEY env var is required")
        self._api_key = api_key
        super().__init__(**kwargs)

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        from_date, to_date = self._date_range(since)
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        payload = self._request_json("GET", f"{_BASE_URL}/company-news", params=params)
        if payload is None or not isinstance(payload, list):
            payload_list: list[dict[str, Any]] = []
        else:
            payload_list = [item for item in payload if isinstance(item, dict)]

        for entry in payload_list:
            draft = self._build_news_draft(entry, symbol)
            if draft is not None:
                yield draft

    def fetch_earnings_calendar(
        self,
        symbol: str,
        since: datetime | None = None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield earnings-calendar facts for ``symbol`` (FR62)."""
        from_date, to_date = self._date_range(since, lookback_days=30)
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        payload = self._request_json("GET", f"{_BASE_URL}/calendar/earnings", params=params)
        if payload is None:
            return
        rows = payload.get("earningsCalendar", [])
        if not isinstance(rows, list):
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            draft = self._build_earnings_draft(row, symbol)
            if draft is not None:
                yield draft

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_news_draft(
        self,
        entry: dict[str, Any],
        symbol: str,
    ) -> ResearchFactDraft | None:
        try:
            article_id = int(entry.get("id", 0))
            datetime_unix = int(entry.get("datetime", 0))
        except (TypeError, ValueError):
            return None
        if article_id == 0 or datetime_unix == 0:
            return None
        effective_from = datetime.fromtimestamp(datetime_unix, tz=UTC)
        draft = self._make_draft(
            fact_kind="finnhub.company_news",
            effective_from=effective_from,
            source_url=str(entry.get("url", "")) or f"{_BASE_URL}/company-news",
            value_text=str(entry.get("headline", "")),
            value_jsonb={
                "id": article_id,
                "headline": entry.get("headline"),
                "summary": entry.get("summary"),
                "source": entry.get("source"),
                "url": entry.get("url"),
                "image": entry.get("image"),
                "category": entry.get("category"),
                "related": entry.get("related") or symbol,
            },
            fact_metadata={"symbol": symbol, "article_id": article_id},
            dedupe_key=f"finnhub:news:{article_id}",
        )
        return draft.with_payload(json.dumps(entry, default=str).encode("utf-8"))

    def _build_earnings_draft(
        self,
        row: dict[str, Any],
        symbol: str,
    ) -> ResearchFactDraft | None:
        date_str = row.get("date")
        if not date_str:
            return None
        try:
            effective_from = datetime.fromisoformat(str(date_str)).replace(tzinfo=UTC)
        except ValueError:
            return None
        eps_estimate = row.get("epsEstimate")
        eps_actual = row.get("epsActual")
        draft = self._make_draft(
            fact_kind="finnhub.earnings_calendar",
            effective_from=effective_from,
            source_url=f"{_BASE_URL}/calendar/earnings?symbol={symbol}",
            value_jsonb={
                "date": date_str,
                "eps_estimate": eps_estimate,
                "eps_actual": eps_actual,
                "revenue_estimate": row.get("revenueEstimate"),
                "revenue_actual": row.get("revenueActual"),
                "hour": row.get("hour"),
            },
            fact_metadata={
                "symbol": symbol,
                "year": row.get("year"),
                "quarter": row.get("quarter"),
            },
            dedupe_key=f"finnhub:earnings:{symbol}:{date_str}",
        )
        return draft.with_payload(json.dumps(row, default=str).encode("utf-8"))

    @staticmethod
    def _date_range(
        since: datetime | None,
        *,
        lookback_days: int = _DEFAULT_LOOKBACK_DAYS,
    ) -> tuple[str, str]:
        end = datetime.now(tz=UTC)
        start = since or (end - timedelta(days=lookback_days))
        return start.date().isoformat(), end.date().isoformat()


__all__ = ["FinnhubSource"]
