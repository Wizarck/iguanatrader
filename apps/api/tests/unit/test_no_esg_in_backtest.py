"""CI assertion: no ESG fact reads in backtest feature builders (slice R3 FR75).

Greps every Python file under
``apps/api/src/iguanatrader/contexts/trading/`` (the backtest hot path)
for forbidden ESG fact references. Fails the CI build if any are
found.

Allow-list: a line containing ``# allow-esg-in-backtest: <reason>``
is exempt — used for explicit deviations the slice-R3 reviewer accepts.

The runtime gate also lives in the R5 feature_provider's ESG
guard; this test is the static defence in depth.
"""

from __future__ import annotations

from pathlib import Path

_FORBIDDEN_PATTERNS = (
    "esg.aggregate",
    "is_esg_aggregate",
    "value_esg_",
    "yfinance_sustainability",
)
_ALLOW_MARKER = "# allow-esg-in-backtest:"
_TRADING_ROOT = (
    Path(__file__).resolve().parents[2] / "src" / "iguanatrader" / "contexts" / "trading"
)


def test_no_esg_references_in_trading_strategies() -> None:
    """Walk apps/api/src/iguanatrader/contexts/trading/ — fail if ESG used."""
    if not _TRADING_ROOT.exists():
        # Trading context not present yet; skip.
        return
    offenders: list[str] = []
    for path in _TRADING_ROOT.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            for pattern in _FORBIDDEN_PATTERNS:
                if pattern in line and _ALLOW_MARKER not in line:
                    offenders.append(f"{path}:{line_no}: {line.strip()}")
    assert not offenders, (
        "ESG fact references forbidden in backtest hot path "
        f"(FR75); found {len(offenders)} occurrence(s):\n  " + "\n  ".join(offenders)
    )
