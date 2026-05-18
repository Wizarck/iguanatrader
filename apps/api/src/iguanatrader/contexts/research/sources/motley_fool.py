"""Motley Fool earnings-call transcript adapter — slice ``I5``.

Per ingestion-wave roadmap §I5: scrapes ``fool.com/earnings/call-transcripts/``
to harvest the literal text of company earnings calls — the largest
gap our XBRL-only fundamentals coverage leaves. Output is a single
``ResearchFactDraft`` per fetch with ``fact_kind='fool.earnings_transcript'``,
``value_text`` carrying the body, and ``value_jsonb`` carrying URL +
metadata.

Operational hedges:

* **Opt-in env flag** — adapter raises :class:`ConfigError` unless
  ``ENABLE_FOOL_SCRAPER=true``. Default disabled. A single source going
  dark (UI change, IP block, ToS amendment) must not silently fail the
  whole pipeline.
* **Robots-aware** — fetched via the canonical :class:`ScrapeLadder`,
  which checks ``robots.txt`` per request before issuing the HTTP call.
* **Polite rate limit** — module-level :class:`TokenBucket` enforces
  one request per 3 seconds (``RATE_LIMIT_PER_SECOND = 1/3``). The
  Fool's robots.txt does not declare a crawl-delay; 0.33 req/s is a
  defensive lower bound.
* **Ladder escalation deferred** — Tier-1 webfetch only in this slice.
  If Fool starts returning 403/Cloudflare, the ladder raises
  :class:`ScrapeBlockedError` and the adapter surfaces a clear
  ``"escalate to Playwright tier"`` error rather than silently failing
  open. Higher tiers wire in when (and if) the free path proves
  insufficient — same spend-decision principle as the roadmap's paid
  options table.

Body extraction is regex-driven: the Fool's transcript pages use a
fairly stable ``<div class="article-body">`` (or ``<article>``) wrapper
around the spoken text. We strip surrounding ``<script>`` / ``<style>``
blocks and unwrap remaining HTML tags to plain text. Speaker structure
(``<strong>Bob Smith — CFO</strong>``-style) is preserved in the body
verbatim because the LLM consumes the prose directly; structured
speaker JSON is out of scope until the index-page enumeration slice
extends this adapter.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import ClassVar

from iguanatrader.contexts.research.errors import ConfigError, SourceUnavailableError
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.scraping.errors import (
    ScrapeBlockedError,
    ScrapeNotImplementedError,
)
from iguanatrader.contexts.research.scraping.ladder import ScrapeLadder, ScrapeTier
from iguanatrader.contexts.research.scraping.user_agent import UserAgentRotation
from iguanatrader.contexts.research.sources._token_bucket import TokenBucket
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)


#: URL template for a Motley Fool earnings-call transcript page.
#: Slugs are dash-separated and include ticker + quarter + year (e.g.
#: ``nvidia-corp-nvda-q1-2026-earnings-call-transcript``).
_URL_TEMPLATE = (
    "https://www.fool.com/earnings/call-transcripts/{year}/{month:02d}/{day:02d}/{slug}/"
)


class MotleyFoolTranscriptSource:
    """Tier-B Fool.com transcript scraper — single transcript per fetch.

    Construction is DI-friendly: tests inject a fake
    :class:`ScrapeLadder` returning a recorded HTML body. Production
    leaves the ladder default — Tier-1 webfetch with robots.txt enforced.
    """

    SOURCE_ID: ClassVar[str] = "motley-fool"

    #: Token-bucket replenishment — one request every 3 seconds. Shared
    #: across instances so concurrent CLI runs do not stampede the host.
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.0 / 3.0

    _bucket: ClassVar[TokenBucket | None] = None

    def __init__(
        self,
        ladder: ScrapeLadder | None = None,
        *,
        enabled: bool | None = None,
    ) -> None:
        if enabled is None:
            enabled = os.environ.get("ENABLE_FOOL_SCRAPER", "false").lower() == "true"
        if not enabled:
            raise ConfigError(
                detail=(
                    "MotleyFoolTranscriptSource is opt-in. Set "
                    "ENABLE_FOOL_SCRAPER=true to enable. The adapter is "
                    "disabled by default to keep ToS / IP-block risk "
                    "contained — a single source going dark must not "
                    "silently fail the broader ingestion pipeline."
                )
            )
        self._ladder = ladder or ScrapeLadder(
            user_agents=UserAgentRotation(),
            tier_max=ScrapeTier.TIER_1_WEBFETCH,  # explicit cap; raise later if free path proves insufficient
        )

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    async def fetch_transcript_async(
        self,
        *,
        url: str | None = None,
        year: int | None = None,
        month: int | None = None,
        day: int | None = None,
        slug: str | None = None,
        symbol: str | None = None,
    ) -> ResearchFactDraft | None:
        """Fetch one transcript by direct URL or by (year, month, day, slug).

        Returns ``None`` when the page returns no recoverable body —
        e.g. a redirect to a 404 placeholder or a Fool-branded "no
        article here" stub. The adapter prefers a quiet None to a
        misleading empty draft.
        """
        target_url = self._resolve_url(url, year, month, day, slug)
        self._acquire_token()
        try:
            result = await self._ladder.fetch(target_url)
        except ScrapeBlockedError as exc:
            raise SourceUnavailableError(
                detail=(
                    f"motley-fool ladder blocked at {target_url}; "
                    "escalate to Playwright tier (deployment-foundation slice). "
                    f"Original: {exc.detail}"
                )
            ) from exc
        except ScrapeNotImplementedError as exc:
            raise SourceUnavailableError(detail=str(exc)) from exc

        body_text = _extract_article_body(result.body)
        if not body_text:
            logger.warning(
                "research.motley_fool.empty_body",
                extra={"url": target_url, "final_url": result.final_url},
            )
            return None

        title = _extract_title(result.body) or _slug_to_title(slug or "")
        now = utc_now()
        effective_from = _datetime_from_parts(year, month, day) or now

        payload = {
            "url": target_url,
            "final_url": result.final_url,
            "title": title,
            "scraped_at": now.isoformat(),
            "body_preview": body_text[:280],
            "body_length": len(body_text),
            "tier_used": int(result.tier_used),
            "symbol": symbol,
        }

        return ResearchFactDraft(
            source_id=self.SOURCE_ID,
            fact_kind="fool.earnings_transcript",
            effective_from=effective_from,
            recorded_from=now,
            source_url=result.final_url,
            retrieval_method="scrape",
            retrieved_at=now,
            value_text=body_text,
            value_jsonb=payload,
            fact_metadata={"symbol": symbol, "slug": slug, "title": title},
            dedupe_key=f"motley-fool:{result.final_url}",
        )

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        """Sync ``SourcePort`` shim — unsupported for Fool.

        Fool's discovery requires URL or (date, slug) inputs; the
        ``symbol``-only ``SourcePort.fetch`` signature does not carry
        enough information to enumerate. The CLI uses
        :meth:`fetch_transcript_async` directly. Documented in the
        roadmap (I5 enumeration deferred to a follow-up slice).
        """
        del symbol, since
        return iter(())

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_url(
        self,
        url: str | None,
        year: int | None,
        month: int | None,
        day: int | None,
        slug: str | None,
    ) -> str:
        if url:
            return url
        if year is None or month is None or day is None or not slug:
            raise ValueError(
                "MotleyFoolTranscriptSource.fetch_transcript_async requires either "
                "'url=' or all of ('year=', 'month=', 'day=', 'slug=')."
            )
        return _URL_TEMPLATE.format(year=year, month=month, day=day, slug=slug)

    def _acquire_token(self) -> None:
        cls = type(self)
        if cls._bucket is None:
            cls._bucket = TokenBucket(rate=self.RATE_LIMIT_PER_SECOND, capacity=1)
        cls._bucket.acquire()


# ---------------------------------------------------------------------------
# HTML extraction (regex — intentionally minimal-dep)
# ---------------------------------------------------------------------------


_SCRIPT_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Two-tier body locator: prefer an explicit ``<div class="article-body">``
# wrapper (Fool's canonical), fall back to ``<article>``. Greedy DOTALL
# match captures everything between the opening and the matching
# closing tag's first occurrence.
_BODY_LOCATORS = [
    re.compile(
        r'<div\b[^>]*class="[^"]*article-body[^"]*"[^>]*>(?P<body>.*?)</div>\s*<(?:footer|aside|div\b[^>]*class="[^"]*footer)',
        re.IGNORECASE | re.DOTALL,
    ),
    re.compile(r"<article\b[^>]*>(?P<body>.*?)</article>", re.IGNORECASE | re.DOTALL),
]

_TITLE_RE = re.compile(
    r'<meta\b[^>]*property="og:title"[^>]*content="(?P<title>[^"]+)"',
    re.IGNORECASE,
)
_FALLBACK_TITLE_RE = re.compile(r"<title>(?P<title>[^<]+)</title>", re.IGNORECASE)


def _extract_article_body(html: str) -> str:
    if not html:
        return ""
    cleaned = _SCRIPT_RE.sub("", html)
    body_html = ""
    for pattern in _BODY_LOCATORS:
        match = pattern.search(cleaned)
        if match:
            body_html = match.group("body")
            break
    if not body_html:
        return ""
    text = _TAG_RE.sub("\n", body_html)
    # Decode the few HTML entities the Fool consistently emits without
    # pulling in a full entity dictionary.
    text = (
        text.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&quot;", '"')
        .replace("&apos;", "'")
        .replace("&#39;", "'")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    text = _WS_RE.sub(" ", text)
    text = _BLANK_LINES_RE.sub("\n\n", text)
    return text.strip()


def _extract_title(html: str) -> str:
    if not html:
        return ""
    match = _TITLE_RE.search(html) or _FALLBACK_TITLE_RE.search(html)
    return (match.group("title").strip() if match else "").strip()


def _slug_to_title(slug: str) -> str:
    """Best-effort prose title from a URL slug.

    ``nvidia-corp-nvda-q1-2026-earnings-call-transcript`` →
    ``Nvidia Corp Nvda Q1 2026 Earnings Call Transcript``.
    """
    if not slug:
        return ""
    return " ".join(part.capitalize() for part in slug.split("-") if part)


def _datetime_from_parts(year: int | None, month: int | None, day: int | None) -> datetime | None:
    if year is None or month is None or day is None:
        return None
    try:
        return datetime(year, month, day, tzinfo=UTC)
    except ValueError:
        return None


__all__ = [
    "MotleyFoolTranscriptSource",
]
