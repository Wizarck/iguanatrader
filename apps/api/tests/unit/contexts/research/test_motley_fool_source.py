"""Unit tests for the Motley Fool transcript adapter (slice I5).

Pure-unit — no network, no fool.com. A fake ScrapeLadder returns a
canned HTML body so we can validate URL composition, opt-in env
gating, body extraction, title extraction, dedupe-key shape, and the
"escalate to Playwright" failure surface.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from iguanatrader.contexts.research.errors import ConfigError, SourceUnavailableError
from iguanatrader.contexts.research.scraping.errors import (
    ScrapeBlockedError,
    ScrapeNotImplementedError,
)
from iguanatrader.contexts.research.scraping.ladder import ScrapeResult, ScrapeTier
from iguanatrader.contexts.research.sources.motley_fool import (
    MotleyFoolTranscriptSource,
    _extract_article_body,
    _extract_title,
    _slug_to_title,
)

_SAMPLE_HTML = """
<!doctype html>
<html>
<head>
  <meta property="og:title" content="NVIDIA (NVDA) Q1 2026 Earnings Call Transcript" />
  <title>Some boring fallback title</title>
  <script>window.boot=1;</script>
  <style>.x { color: red; }</style>
</head>
<body>
  <header>nav junk</header>
  <div class="article-body">
    <p><strong>Operator</strong></p>
    <p>Good afternoon, ladies and gentlemen.</p>
    <p><strong>Jensen Huang &mdash; CEO</strong></p>
    <p>Thank you. Q1 was&nbsp;exceptional.</p>
  </div>
  <footer>copyright junk</footer>
</body>
</html>
"""


class _FakeLadder:
    """Stands in for :class:`ScrapeLadder` — returns canned body or raises."""

    def __init__(self, *, body: str | None = None, raises: Exception | None = None) -> None:
        self._body = body
        self._raises = raises
        self.calls: list[str] = []

    async def fetch(self, url: str, **_kw: Any) -> ScrapeResult:
        self.calls.append(url)
        if self._raises is not None:
            raise self._raises
        assert self._body is not None
        return ScrapeResult(
            body=self._body,
            status_code=200,
            final_url=url,
            tier_used=ScrapeTier.TIER_1_WEBFETCH,
        )


@pytest.fixture(autouse=True)
def _fool_scraper_enabled(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Default: scraper enabled (each opt-in test overrides as needed)."""
    monkeypatch.setenv("ENABLE_FOOL_SCRAPER", "true")
    yield


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Construction / opt-in gating
# ---------------------------------------------------------------------------


def test_construct_raises_when_env_flag_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ENABLE_FOOL_SCRAPER", raising=False)
    with pytest.raises(ConfigError, match="ENABLE_FOOL_SCRAPER"):
        MotleyFoolTranscriptSource()


def test_construct_raises_when_env_flag_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENABLE_FOOL_SCRAPER", "false")
    with pytest.raises(ConfigError):
        MotleyFoolTranscriptSource()


def test_construct_succeeds_when_explicitly_enabled() -> None:
    # `enabled=True` overrides env (so tests can build the adapter even
    # under hostile env state).
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    assert source is not None


# ---------------------------------------------------------------------------
# URL composition
# ---------------------------------------------------------------------------


def test_fetch_uses_date_plus_slug_to_build_url() -> None:
    ladder = _FakeLadder(body=_SAMPLE_HTML)
    source = MotleyFoolTranscriptSource(ladder=ladder, enabled=True)
    _run(
        source.fetch_transcript_async(
            year=2026,
            month=5,
            day=15,
            slug="nvidia-corp-nvda-q1-2026-earnings-call-transcript",
            symbol="NVDA",
        )
    )
    assert ladder.calls == [
        "https://www.fool.com/earnings/call-transcripts/2026/05/15/"
        "nvidia-corp-nvda-q1-2026-earnings-call-transcript/"
    ]


def test_fetch_accepts_explicit_url() -> None:
    ladder = _FakeLadder(body=_SAMPLE_HTML)
    source = MotleyFoolTranscriptSource(ladder=ladder, enabled=True)
    _run(
        source.fetch_transcript_async(
            url="https://www.fool.com/earnings/call-transcripts/2026/05/15/nvidia-corp-nvda-q1-2026/",
            symbol="NVDA",
        )
    )
    assert ladder.calls == [
        "https://www.fool.com/earnings/call-transcripts/2026/05/15/nvidia-corp-nvda-q1-2026/"
    ]


def test_fetch_raises_on_missing_url_components() -> None:
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    with pytest.raises(ValueError, match="requires either 'url='"):
        _run(source.fetch_transcript_async(year=2026, month=5))


# ---------------------------------------------------------------------------
# Body extraction + draft shape
# ---------------------------------------------------------------------------


def test_fetch_returns_draft_with_body_text() -> None:
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    draft = _run(
        source.fetch_transcript_async(
            year=2026,
            month=5,
            day=15,
            slug="nvidia-corp-nvda-q1-2026-earnings-call-transcript",
            symbol="NVDA",
        )
    )
    assert draft is not None
    assert draft.fact_kind == "fool.earnings_transcript"
    assert draft.source_id == "motley-fool"
    assert draft.value_text is not None
    assert "Good afternoon" in draft.value_text
    assert "Jensen Huang" in draft.value_text
    # &nbsp; entity decoded to a literal space.
    assert "Q1 was exceptional" in draft.value_text
    # Script + style blocks stripped.
    assert "window.boot" not in draft.value_text
    assert "color: red" not in draft.value_text


def test_draft_payload_carries_url_title_and_metadata() -> None:
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    draft = _run(
        source.fetch_transcript_async(
            year=2026,
            month=5,
            day=15,
            slug="nvidia-corp-nvda-q1-2026-earnings-call-transcript",
            symbol="NVDA",
        )
    )
    assert draft is not None
    payload = draft.value_jsonb
    assert isinstance(payload, dict)
    assert payload["title"].startswith("NVIDIA")
    assert payload["body_length"] > 0
    assert payload["url"].endswith("nvidia-corp-nvda-q1-2026-earnings-call-transcript/")
    assert payload["tier_used"] == 1
    assert payload["symbol"] == "NVDA"
    # Dedupe key is the canonical fool URL (final_url after redirects).
    assert draft.dedupe_key is not None
    assert draft.dedupe_key.startswith("motley-fool:")


def test_effective_from_uses_url_date_when_supplied() -> None:
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    draft = _run(
        source.fetch_transcript_async(
            year=2026,
            month=5,
            day=15,
            slug="nvda-q1",
            symbol="NVDA",
        )
    )
    assert draft is not None
    assert draft.effective_from.date().isoformat() == "2026-05-15"


# ---------------------------------------------------------------------------
# Empty / unrecoverable bodies
# ---------------------------------------------------------------------------


def test_fetch_returns_none_when_body_missing() -> None:
    empty_html = "<html><body>no article-body here</body></html>"
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=empty_html), enabled=True)
    draft = _run(source.fetch_transcript_async(url="https://example/", symbol="X"))
    assert draft is None


# ---------------------------------------------------------------------------
# Ladder failure surfaces
# ---------------------------------------------------------------------------


def test_blocked_raises_source_unavailable_with_playwright_hint() -> None:
    ladder = _FakeLadder(raises=ScrapeBlockedError(detail="tier-1 403 at fool.com"))
    source = MotleyFoolTranscriptSource(ladder=ladder, enabled=True)
    with pytest.raises(SourceUnavailableError, match="Playwright"):
        _run(source.fetch_transcript_async(url="https://example/", symbol="X"))


def test_ladder_not_implemented_propagates_as_source_unavailable() -> None:
    ladder = _FakeLadder(raises=ScrapeNotImplementedError(detail="tier-2 not installed"))
    source = MotleyFoolTranscriptSource(ladder=ladder, enabled=True)
    with pytest.raises(SourceUnavailableError):
        _run(source.fetch_transcript_async(url="https://example/", symbol="X"))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_extract_article_body_handles_article_tag_fallback() -> None:
    html = "<html><body><article>Hello <b>world</b></article></body></html>"
    # Each `<tag>` becomes a newline; the rest is preserved literal.
    # We only assert the meaningful content survived, not the exact
    # whitespace shape (regex collapse rules can shift on entity tweaks).
    out = _extract_article_body(html)
    assert "Hello" in out
    assert "world" in out
    assert "<" not in out and ">" not in out


def test_extract_title_prefers_og_title() -> None:
    html = '<meta property="og:title" content="The Real Title" />' "<title>Old fallback</title>"
    assert _extract_title(html) == "The Real Title"


def test_extract_title_falls_back_to_title_tag() -> None:
    html = "<head><title>Just A Title</title></head>"
    assert _extract_title(html) == "Just A Title"


def test_slug_to_title_humanises_dashes() -> None:
    assert (
        _slug_to_title("nvidia-corp-nvda-q1-2026-earnings-call-transcript")
        == "Nvidia Corp Nvda Q1 2026 Earnings Call Transcript"
    )


def test_sourceport_fetch_is_empty_iter() -> None:
    source = MotleyFoolTranscriptSource(ladder=_FakeLadder(body=_SAMPLE_HTML), enabled=True)
    # ``fetch(symbol, since)`` is the legacy sync port; for Fool it
    # cannot enumerate from a symbol alone, so it must return empty
    # rather than raise (so a registry-driven runner does not crash).
    assert list(source.fetch("NVDA", None)) == []
