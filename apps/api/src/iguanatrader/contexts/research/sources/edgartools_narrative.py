"""SEC EDGAR 10-K narrative supplement adapter — slice ``I6``.

Per ingestion-wave roadmap §I6: pulls 10-K **Item 7 (MD&A)** and
**Item 1A (Risk Factors)** prose text — the qualitative narrative our
XBRL-only ``SECEdgarSource`` cannot reach. Output is one
``ResearchFactDraft`` per requested section, with
``fact_kind ∈ {'sec_text.mdna', 'sec_text.risk_factors'}`` and
``value_text`` carrying the parsed paragraph(s).

Thin wrapper over the open-source ``edgartools`` library (MIT, free,
no API key). The lib resolves CIK from ticker, indexes 10-K filings,
and extracts well-known section headings — so this adapter is mostly
control flow + draft assembly.

Deferred-install pattern: ``edgartools`` is lazily imported. The
module is importable without the dep; the adapter constructor raises
:class:`ConfigError` with installation hints when the lib is missing.
That lets CI run pytest --collect-only without requiring a 3.2 MB
package in the base image; operators who want narrative ingestion
install the extra (``pip install iguanatrader[edgar-narrative]``).

PiT classification: row in ``research_sources`` is seeded with
``pit_class='A'`` — 10-K filings are timestamped by SEC ingest and
backwards-immutable. The per-fact ``effective_from`` matches the
filing's accepted-date.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, ClassVar

from iguanatrader.contexts.research.errors import (
    ConfigError,
    SourceUnavailableError,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)


#: Section selectors honoured by ``fetch_narrative_async(include=...)``.
SECTION_MDNA = "mdna"
SECTION_RISK = "risk_factors"
SUPPORTED_SECTIONS = frozenset({SECTION_MDNA, SECTION_RISK})


class EdgartoolsSource:
    """:class:`SourcePort`-shaped adapter — 10-K narrative supplement.

    Pulls the latest 10-K for a ticker (or a specific accession number
    when supplied) and emits one draft per requested section.

    Construction is DI-friendly: tests inject a fake company resolver
    so the live ``edgartools.Company`` call path is never exercised in
    unit tests. The default constructor lazy-imports ``edgartools.Company``
    and uses it as the resolver.
    """

    SOURCE_ID: ClassVar[str] = "edgartools-narrative"

    def __init__(
        self,
        *,
        company_resolver: Any | None = None,
        user_identity: str | None = None,
    ) -> None:
        """``company_resolver`` is a callable ``(ticker_or_cik) -> _Company``
        following edgartools' :class:`Company` constructor surface. In
        unit tests this is a fake; in production we lazy-import
        ``edgartools.Company``.
        """
        if company_resolver is None:
            try:
                from edgartools import Company, set_identity  # type: ignore[import-not-found]
            except ImportError as exc:
                raise ConfigError(
                    detail=(
                        "edgartools is not installed. Run "
                        "`pip install iguanatrader[edgar-narrative]` or set "
                        "PYTHONPATH so the lib is reachable. The adapter is "
                        "deferred-install so the broader pipeline keeps working "
                        "without it."
                    )
                ) from exc
            # SEC requires a User-Agent string identifying the requester;
            # edgartools surfaces this as `set_identity`. Default is
            # iguanatrader's project-level UA; operators can override.
            identity = user_identity or "iguanatrader research@iguanatrader.local"
            set_identity(identity)
            self._company_resolver = Company
        else:
            self._company_resolver = company_resolver

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def fetch_narrative_async(
        self,
        *,
        ticker_or_cik: str,
        symbol: str | None = None,
        accession_number: str | None = None,
        include: Iterable[str] | None = None,
    ) -> list[ResearchFactDraft]:
        """Pull 10-K narrative sections. Best-effort per section.

        ``include`` defaults to both ``mdna`` + ``risk_factors``. Unknown
        section names raise ``ValueError``. A missing section in the
        filing yields no draft for that section (and a structlog warn).
        """
        sections = self._resolve_sections(include)
        company = self._company_resolver(ticker_or_cik)
        filing = await _resolve_filing(company, accession_number)
        if filing is None:
            raise SourceUnavailableError(
                detail=f"edgartools could not resolve a 10-K for {ticker_or_cik!r}"
            )

        drafts: list[ResearchFactDraft] = []
        for section_key in sections:
            text, fact_kind = _extract_section(filing, section_key)
            if not text:
                logger.warning(
                    "research.edgartools.section_empty",
                    extra={"ticker": ticker_or_cik, "section": section_key},
                )
                continue
            drafts.append(_build_draft(filing, symbol or ticker_or_cik, fact_kind, text))
        return drafts

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        """Legacy sync ``SourcePort`` shim — unsupported here.

        edgartools' async surface is the canonical path; the symbol-only
        sync contract cannot carry the optional ``accession_number``
        scoping the adapter accepts. The CLI uses
        :meth:`fetch_narrative_async` directly. Returns empty iter so a
        registry-driven runner does not crash.
        """
        del symbol, since
        return iter(())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_sections(include: Iterable[str] | None) -> set[str]:
        if include is None:
            return set(SUPPORTED_SECTIONS)
        requested = {s.strip().lower() for s in include if s.strip()}
        unknown = requested - SUPPORTED_SECTIONS
        if unknown:
            raise ValueError(
                f"Unknown edgartools section(s): {sorted(unknown)}. "
                f"Allowed: {sorted(SUPPORTED_SECTIONS)}"
            )
        return requested or set(SUPPORTED_SECTIONS)


# ---------------------------------------------------------------------------
# Section extraction (edgartools-specific helpers — module-level so
# they're easy to mock per-test and isolate from class state)
# ---------------------------------------------------------------------------


async def _resolve_filing(company: Any, accession_number: str | None) -> Any | None:
    """Resolve the target 10-K. Synchronous in edgartools today;
    wrapping in ``async`` keeps the public surface consistent with the
    rest of the ingestion-wave adapters and lets future versions swap
    in an async resolver without breaking the call site.
    """
    if accession_number is not None:
        filings = company.get_filings(accession_number=accession_number)
        return filings[0] if filings else None
    # Default: latest 10-K.
    filings = company.get_filings(form="10-K")
    if not filings:
        return None
    return filings[0]


# Section heading aliases the edgartools sections API exposes. Newer
# versions normalise headings; older ones return the literal item text.
# Probe both shapes.
_SECTION_KEY_TO_EDGAR: dict[str, tuple[tuple[str, ...], str]] = {
    SECTION_MDNA: (
        (
            "Item 7. Management's Discussion and Analysis of Financial Condition and Results of Operations",
            "Item 7",
            "ITEM 7",
            "mdna",
        ),
        "sec_text.mdna",
    ),
    SECTION_RISK: (
        (
            "Item 1A. Risk Factors",
            "Item 1A",
            "ITEM 1A",
            "risk_factors",
        ),
        "sec_text.risk_factors",
    ),
}


def _extract_section(filing: Any, section_key: str) -> tuple[str, str]:
    """Return ``(text, fact_kind)`` for the requested section, or ``("", fact_kind)``.

    Probes several attribute / method shapes that edgartools releases
    have exposed over time: ``filing.tenK.financials.mdna``,
    ``filing.sections[heading]``, ``filing.text_for_section(name)``.
    The first non-empty result wins.
    """
    aliases, fact_kind = _SECTION_KEY_TO_EDGAR[section_key]

    # Probe 1: structured 10-K accessor. ONLY look at the attribute that
    # matches the requested section — don't fall through to the other
    # section's attribute or we'd cross-contaminate (mdna probe returning
    # risk_factors text and vice versa).
    tenk = getattr(filing, "tenK", None) or getattr(filing, "ten_k", None)
    if tenk is not None:
        value = getattr(tenk, section_key, None)
        if value:
            return (str(value), fact_kind)

    # Probe 2: sections dict.
    sections = getattr(filing, "sections", None)
    if isinstance(sections, dict):
        for alias in aliases:
            value = sections.get(alias)
            if value:
                return (str(value), fact_kind)

    # Probe 3: explicit text_for_section() method.
    text_for_section = getattr(filing, "text_for_section", None)
    if callable(text_for_section):
        for alias in aliases:
            value = text_for_section(alias)
            if value:
                return (str(value), fact_kind)

    return ("", fact_kind)


def _build_draft(filing: Any, symbol: str, fact_kind: str, text: str) -> ResearchFactDraft:
    accession = str(
        getattr(filing, "accession_number", "") or getattr(filing, "accession_no", "") or "unknown"
    )
    filing_date = _filing_date(filing)
    now = utc_now()
    payload: dict[str, Any] = {
        "symbol": symbol,
        "accession_number": accession,
        "filing_date": filing_date.isoformat() if filing_date else None,
        "form": "10-K",
        "fact_kind": fact_kind,
        "text_length": len(text),
        "text_preview": text[:280],
    }
    return ResearchFactDraft(
        source_id=EdgartoolsSource.SOURCE_ID,
        fact_kind=fact_kind,
        effective_from=filing_date or now,
        recorded_from=now,
        source_url=_filing_url(filing) or f"edgar://10K/{accession}",
        retrieval_method="api",
        retrieved_at=now,
        value_text=text,
        value_jsonb=payload,
        fact_metadata={"symbol": symbol, "accession_number": accession},
        dedupe_key=f"edgartools:{fact_kind}:{accession}",
    )


def _filing_date(filing: Any) -> datetime | None:
    for attr in ("filing_date", "accepted_at", "date_filed"):
        value = getattr(filing, attr, None)
        if value is None:
            continue
        if isinstance(value, datetime):
            return value if value.tzinfo else value.replace(tzinfo=UTC)
        if hasattr(value, "isoformat"):
            try:
                return datetime.fromisoformat(value.isoformat()).replace(tzinfo=UTC)
            except (TypeError, ValueError):
                continue
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value).replace(tzinfo=UTC)
            except ValueError:
                continue
    return None


def _filing_url(filing: Any) -> str | None:
    for attr in ("filing_url", "homepage_url", "url"):
        value = getattr(filing, attr, None)
        if value:
            return str(value)
    return None


__all__ = [
    "SECTION_MDNA",
    "SECTION_RISK",
    "SUPPORTED_SECTIONS",
    "EdgartoolsSource",
]
