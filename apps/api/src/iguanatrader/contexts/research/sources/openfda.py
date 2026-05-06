"""OpenFDA Tier-B drug approvals adapter (slice R3 FR62).

OpenFDA (https://open.fda.gov/) exposes FDA drug approval + adverse-
event endpoints with no auth required (240 req/min courtesy floor).
Used to detect "drug approval" catalysts for biotech / pharma symbols.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


_DRUGSFDA_URL = "https://api.fda.gov/drug/drugsfda.json"
_DEFAULT_LOOKBACK_DAYS = 90


class OpenFDASource(TierASourceAdapter):
    """Tier-B OpenFDA drug approvals adapter."""

    SOURCE_ID: ClassVar[str] = "openfda"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 4.0  # 240/min courtesy

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        start, _end = self._date_range(since)
        # OpenFDA's drug-approvals endpoint indexes by sponsor_name.
        # ``symbol`` is a stock ticker — the caller is expected to map it
        # to a company name elsewhere. MVP: search by sponsor_name=symbol
        # AND submission_status_date within window.
        params = {
            "search": (
                f'sponsor_name:"{symbol}" '
                f'AND submissions.submission_status_date:[{start.strftime("%Y%m%d")} TO 99999999]'
            ),
            "limit": 50,
        }
        payload = self._request_json("GET", _DRUGSFDA_URL, params=params)
        if payload is None:
            return
        results = payload.get("results", [])
        if not isinstance(results, list):
            return
        for result in results:
            if not isinstance(result, dict):
                continue
            yield from self._build_drafts_for_drug(result, symbol)

    def _build_drafts_for_drug(
        self,
        drug: dict[str, Any],
        symbol: str,
    ) -> Iterable[ResearchFactDraft]:
        application_number = drug.get("application_number") or "unknown"
        submissions = drug.get("submissions", [])
        if not isinstance(submissions, list):
            return
        for submission in submissions:
            if not isinstance(submission, dict):
                continue
            status_date = submission.get("submission_status_date")
            status = submission.get("submission_status")
            if not status_date or not status:
                continue
            try:
                effective_from = datetime.strptime(str(status_date), "%Y%m%d").replace(tzinfo=UTC)
            except ValueError:
                continue
            sub_type = submission.get("submission_type", "")
            sub_number = submission.get("submission_number", "")
            yield self._make_draft(
                fact_kind="openfda.drug_submission",
                effective_from=effective_from,
                source_url=(
                    f"https://www.fda.gov/drugs/drug-approvals-and-databases/"
                    f"drugsfda-data-files#{application_number}"
                ),
                value_text=f"{sub_type} {sub_number} → {status}",
                value_jsonb={
                    "application_number": application_number,
                    "sponsor_name": drug.get("sponsor_name"),
                    "products": drug.get("products"),
                    "submission_type": sub_type,
                    "submission_number": sub_number,
                    "submission_status": status,
                    "submission_status_date": status_date,
                },
                fact_metadata={"symbol": symbol, "application_number": application_number},
                dedupe_key=f"openfda:{application_number}:{sub_type}:{sub_number}",
            )

    @staticmethod
    def _date_range(since: datetime | None) -> tuple[datetime, datetime]:
        end = datetime.now(tz=UTC)
        start = since or (end - timedelta(days=_DEFAULT_LOOKBACK_DAYS))
        return start, end


__all__ = ["OpenFDASource"]
