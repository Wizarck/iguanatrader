"""SEC EDGAR Tier-A source adapter (slice R2).

Per slice R2 design D3:

* Resolves CIK from ticker via the SEC company-tickers JSON
  (``https://www.sec.gov/files/company_tickers.json``), cached in-memory.
* Lists submissions via ``data.sec.gov/submissions/CIK<10>.json`` —
  iterates the recent-filings array and emits one
  :class:`ResearchFactDraft` per filing newer than ``since``.
* For 10-K and 10-Q filings ALSO pulls XBRL company-facts and emits one
  draft per ``(taxonomy, concept, end_date)`` tuple newer than ``since``.
* Honours SEC's mandatory ``User-Agent`` header (``<company> <email>``)
  read from the ``SEC_EDGAR_USER_AGENT`` env var; raises
  :class:`ConfigError` at init if missing or malformed.

Sync :class:`SourcePort` implementation built on top of
:class:`TierASourceAdapter` — ``httpx.Client``, token-bucket rate limiter
(class-shared, 10 req/s per design D3), exponential backoff
(``[3,6,12,24,48]`` from slice 2's :func:`backoff_seconds`).
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import ConfigError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.base import TierASourceAdapter

logger = logging.getLogger(__name__)


# Per design D3 + SEC's Fair Access policy: User-Agent must include a
# contact email. Regex below is intentionally permissive — SEC documents
# the format informally and operators may include version strings, etc.
_UA_REGEX = re.compile(r"^.+\s.+@.+\..+$")

_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
_COMPANY_FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession_no_dashes}/{document}"


class SECEdgarSource(TierASourceAdapter):
    """SEC EDGAR adapter — Form 4 / 10-K / 10-Q / 8-K / 13F filings + XBRL."""

    SOURCE_ID: ClassVar[str] = "sec_edgar"
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 10.0
    XBRL_FORM_TYPES: ClassVar[frozenset[str]] = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A"})

    # Class-level CIK cache — populated lazily from the public ticker map.
    _cik_cache: ClassVar[dict[str, int] | None] = None

    def __init__(self, **kwargs: Any) -> None:
        ua = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
        if not ua:
            raise ConfigError(
                detail="SEC_EDGAR_USER_AGENT env var is required (format: '<company> <email>')",
            )
        if not _UA_REGEX.match(ua):
            raise ConfigError(
                detail=(
                    "SEC_EDGAR_USER_AGENT must contain a contact email per SEC Fair Access; "
                    f"got {ua!r}"
                ),
            )
        self._user_agent = ua
        super().__init__(**kwargs)

    # ------------------------------------------------------------------
    # SourcePort
    # ------------------------------------------------------------------

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        cik = self._resolve_cik(symbol)
        if cik is None:
            logger.warning(
                "research.sec_edgar.permanent_skip",
                extra={"symbol": symbol, "reason": "cik_not_found"},
            )
            return

        submissions = self._request_json(
            "GET",
            _SUBMISSIONS_URL.format(cik=cik),
            headers=self._headers(),
        )
        if submissions is None:
            return

        recent = submissions.get("filings", {}).get("recent", {})
        if not recent:
            return

        yield from self._iterate_filings(recent, cik=cik, since=since)

        # XBRL drafts only for 10-K / 10-Q filings of this issuer. We pull the
        # full company-facts JSON once and emit one draft per concept tuple.
        has_xbrl = any(ft in self.XBRL_FORM_TYPES for ft in recent.get("form", []))
        if not has_xbrl:
            return
        company_facts = self._request_json(
            "GET",
            _COMPANY_FACTS_URL.format(cik=cik),
            headers=self._headers(),
        )
        if company_facts is None:
            return
        yield from self._iterate_xbrl(company_facts, cik=cik, since=since)

    # ------------------------------------------------------------------
    # CIK lookup
    # ------------------------------------------------------------------

    def _resolve_cik(self, symbol: str) -> int | None:
        cache = type(self)._cik_cache
        if cache is None:
            cache = self._load_cik_cache()
            type(self)._cik_cache = cache
        return cache.get(symbol.upper())

    def _load_cik_cache(self) -> dict[str, int]:
        payload = self._request_json("GET", _TICKERS_URL, headers=self._headers())
        if not payload:
            return {}
        # Schema: ``{"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}}``.
        cache: dict[str, int] = {}
        for entry in payload.values():
            ticker = str(entry.get("ticker", "")).upper()
            cik = entry.get("cik_str")
            if ticker and isinstance(cik, int):
                cache[ticker] = cik
        return cache

    # ------------------------------------------------------------------
    # Filing iteration
    # ------------------------------------------------------------------

    def _iterate_filings(
        self,
        recent: dict[str, list[Any]],
        *,
        cik: int,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        accession_numbers = recent.get("accessionNumber", [])
        forms = recent.get("form", [])
        filing_dates = recent.get("filingDate", [])
        primary_documents = recent.get("primaryDocument", [])
        period_of_report = recent.get("periodOfReport", [])

        for idx, accession in enumerate(accession_numbers):
            form = forms[idx] if idx < len(forms) else ""
            filing_date_str = filing_dates[idx] if idx < len(filing_dates) else ""
            if not filing_date_str:
                continue
            try:
                filing_date = datetime.fromisoformat(filing_date_str).replace(tzinfo=UTC)
            except ValueError:
                continue
            if since is not None and filing_date < since:
                continue
            primary_document = primary_documents[idx] if idx < len(primary_documents) else ""
            period = period_of_report[idx] if idx < len(period_of_report) else None

            accession_no_dashes = accession.replace("-", "")
            source_url = _FILING_URL.format(
                cik=cik,
                accession_no_dashes=accession_no_dashes,
                document=primary_document or "",
            )
            value_jsonb = {
                "accession_number": accession,
                "form_type": form,
                "filing_date": filing_date_str,
                "period_of_report": period,
                "primary_document": primary_document,
            }
            yield self._make_draft(
                fact_kind=f"sec_filing.{form}" if form else "sec_filing.unknown",
                effective_from=filing_date,
                source_url=source_url,
                value_jsonb=value_jsonb,
                fact_metadata={"cik": cik},
                dedupe_key=f"sec_edgar:{accession}",
            ).with_payload(json.dumps(value_jsonb, sort_keys=True).encode())

    # ------------------------------------------------------------------
    # XBRL iteration
    # ------------------------------------------------------------------

    def _iterate_xbrl(
        self,
        payload: dict[str, Any],
        *,
        cik: int,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        facts = payload.get("facts", {})
        for taxonomy, concepts in facts.items():
            for concept_name, concept_payload in concepts.items():
                units = concept_payload.get("units", {})
                for unit_label, observations in units.items():
                    for obs in observations:
                        end_str = obs.get("end")
                        form = obs.get("form")
                        accn = obs.get("accn")
                        value = obs.get("val")
                        if not end_str or value is None or accn is None:
                            continue
                        try:
                            end_dt = datetime.fromisoformat(end_str).replace(tzinfo=UTC)
                        except ValueError:
                            continue
                        if since is not None and end_dt < since:
                            continue
                        # Hard-skip non-10K/Q forms — Form 4 etc. don't come
                        # through company-facts in practice but defence in depth.
                        if form not in self.XBRL_FORM_TYPES:
                            continue
                        xbrl_metadata = {
                            "cik": cik,
                            "form": form,
                            "accession_number": accn,
                            "taxonomy": taxonomy,
                            "concept": concept_name,
                            "fiscal_period": obs.get("fp"),
                            "fiscal_year": obs.get("fy"),
                        }
                        xbrl_payload = {
                            "value": value,
                            "unit": unit_label,
                            "end": end_str,
                            "metadata": xbrl_metadata,
                        }
                        yield self._make_draft(
                            fact_kind=f"sec_xbrl.{taxonomy}.{concept_name}",
                            effective_from=end_dt,
                            source_url=_SUBMISSIONS_URL.format(cik=cik),
                            value_numeric=value,
                            unit=unit_label,
                            fact_metadata=xbrl_metadata,
                            dedupe_key=(
                                f"sec_edgar:xbrl:{cik}:{concept_name}:"
                                f"start={obs.get('start', '')}:end={end_str}:"
                                f"{form}:{unit_label}:{accn}:"
                                f"fp={obs.get('fp', '')}:fy={obs.get('fy', '')}:"
                                f"frame={obs.get('frame', '')}:filed={obs.get('filed', '')}"
                            ),
                        ).with_payload(
                            json.dumps(xbrl_payload, sort_keys=True, default=str).encode()
                        )

    # ------------------------------------------------------------------
    # Headers
    # ------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": self._user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
        }


__all__ = ["SECEdgarSource"]
