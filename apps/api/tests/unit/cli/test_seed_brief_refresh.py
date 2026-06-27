"""WS-1b on-add-stock brief trigger — ``_refresh_briefs_for_symbols``.

The seed-watchlist command's ``--refresh-briefs`` opt-in synthesises a fresh
brief per seeded symbol right after the configs commit, so the LLM entry/exit
gates read current fundamentals from the first tick rather than waiting for the
daily 07:00 brief cron. This locks the helper's contract: every symbol is
attempted with the house methodology, and one bad symbol never aborts the batch
(best-effort per symbol, mirroring the daemon brief cron).
"""

from __future__ import annotations

import pytest
from iguanatrader.cli.admin import _SEED_BRIEF_METHODOLOGY, _refresh_briefs_for_symbols


class _RecordingBrief:
    def __init__(self, raise_for: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._raise_for = raise_for or set()

    async def refresh(self, *, symbol: str, methodology: str) -> None:
        self.calls.append((symbol, methodology))
        if symbol in self._raise_for:
            raise RuntimeError(f"boom:{symbol}")


@pytest.mark.asyncio
async def test_refresh_attempts_every_symbol_with_house_methodology() -> None:
    brief = _RecordingBrief()
    refreshed = await _refresh_briefs_for_symbols(brief, symbols=["AMD", "AAPL", "MSFT"])
    assert refreshed == 3
    assert brief.calls == [
        ("AMD", _SEED_BRIEF_METHODOLOGY),
        ("AAPL", _SEED_BRIEF_METHODOLOGY),
        ("MSFT", _SEED_BRIEF_METHODOLOGY),
    ]


@pytest.mark.asyncio
async def test_one_bad_symbol_does_not_abort_the_batch() -> None:
    brief = _RecordingBrief(raise_for={"AAPL"})
    refreshed = await _refresh_briefs_for_symbols(brief, symbols=["AMD", "AAPL", "MSFT"])
    # AAPL raised but AMD + MSFT still refreshed; the loop continued past it.
    assert refreshed == 2
    assert [c[0] for c in brief.calls] == ["AMD", "AAPL", "MSFT"]


@pytest.mark.asyncio
async def test_empty_symbol_list_refreshes_nothing() -> None:
    brief = _RecordingBrief()
    refreshed = await _refresh_briefs_for_symbols(brief, symbols=[])
    assert refreshed == 0
    assert brief.calls == []
