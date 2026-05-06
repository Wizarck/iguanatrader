"""GDELT Tier-B events + global news adapter (slice R3 FR67).

GDELT (https://www.gdeltproject.org/) is a global event database
updated every 15 minutes. The DOC API returns articles matching a
query; we use it to surface PESTEL signals (political, economic,
social, technological, environmental, legal) for a watchlist symbol
or company name.

No auth required; politeness recommends ≤1 request per few seconds
+ honouring the 15-minute refresh cadence.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_DOC_API = "https://api.gdeltproject.org/api/v2/doc/doc"
_DEFAULT_LOOKBACK_DAYS = 7


class GDELTSource(TierASourceAdapter):
    """Tier-B GDELT events + global news adapter.

    Persists facts under ``source_id='gdelt'`` (joins to
    ``research_sources`` with ``pit_class='B'``).
    """

    SOURCE_ID: ClassVar[str] = "gdelt"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 0.25  # ~1 req every 4s

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        start_dt, end_dt = self._date_range(since)
        # GDELT DOC API timespan format: STARTDATETIME ENDDATETIME (UTC,
        # YYYYMMDDHHMMSS).
        params = {
            "query": f'"{symbol}"',
            "mode": "ArtList",
            "format": "json",
            "startdatetime": start_dt.strftime("%Y%m%d%H%M%S"),
            "enddatetime": end_dt.strftime("%Y%m%d%H%M%S"),
            "maxrecords": 100,
        }
        payload = self._request_json("GET", _DOC_API, params=params)
        if payload is None:
            return
        articles = payload.get("articles", [])
        if not isinstance(articles, list):
            return
        for article in articles:
            if not isinstance(article, dict):
                continue
            draft = self._build_article_draft(article, symbol)
            if draft is not None:
                yield draft

    def _build_article_draft(
        self,
        article: dict[str, Any],
        symbol: str,
    ) -> ResearchFactDraft | None:
        seendate = article.get("seendate")
        url = article.get("url")
        if not seendate or not url:
            return None
        try:
            # GDELT uses YYYYMMDDTHHMMSSZ (compact ISO 8601-ish).
            cleaned = str(seendate).replace("T", "").replace("Z", "").strip()
            if len(cleaned) >= 14:
                effective_from = datetime.strptime(cleaned[:14], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
            else:
                return None
        except ValueError:
            return None
        return self._make_draft(
            fact_kind="gdelt.article",
            effective_from=effective_from,
            source_url=str(url),
            value_text=str(article.get("title", "")),
            value_jsonb={
                "title": article.get("title"),
                "domain": article.get("domain"),
                "language": article.get("language"),
                "tone": article.get("tone"),
                "url": url,
            },
            fact_metadata={"symbol": symbol},
            dedupe_key=f"gdelt:{seendate}:{url}",
        )

    @staticmethod
    def _date_range(since: datetime | None) -> tuple[datetime, datetime]:
        end = datetime.now(tz=UTC)
        start = since or (end - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
        return start, end


__all__ = ["GDELTSource"]
