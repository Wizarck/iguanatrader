# mypy: disable-error-code="no-any-unimported"
"""Weekly review PDF generator (FR44; slice deployment-foundation §3.E).

Consumes the ``digest_payload`` dict from
:meth:`OrchestrationService.run_routine(routine_name="weekly_review")`
and renders a reportlab PDF with four sections:

1. Performance — equity curve summary + Sharpe + max drawdown
2. Strategy attribution — per-strategy P&L breakdown
3. Cost breakdown — API costs + commissions + slippage
4. Action items — surfaced from the digest's ``action_items`` field

The function is pure (no I/O beyond the bytes return). Persistence to
``data/weekly_reviews/<YYYY-MM-DD>.pdf`` is done by the caller (the
weekly_review routine wrapper) so unit tests exercise rendering only.
"""

from __future__ import annotations

import io
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from reportlab.lib.styles import StyleSheet1


_TITLE = "Weekly Review — iguanatrader"
_SECTION_HEADERS = [
    "1. Performance",
    "2. Strategy attribution",
    "3. Cost breakdown",
    "4. Action items",
]


def _styles() -> StyleSheet1:
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet

    base = getSampleStyleSheet()
    if "ReviewBody" not in base:
        base.add(
            ParagraphStyle(
                name="ReviewBody",
                parent=base["BodyText"],
                fontName="Helvetica",
                fontSize=10,
                leading=14,
                alignment=TA_LEFT,
                spaceAfter=6,
            )
        )
    if "ReviewSection" not in base:
        base.add(
            ParagraphStyle(
                name="ReviewSection",
                parent=base["Heading2"],
                fontName="Helvetica-Bold",
                fontSize=14,
                leading=18,
                alignment=TA_LEFT,
                spaceBefore=12,
                spaceAfter=8,
            )
        )
    return base


def _bullet(items: list[str]) -> str:
    if not items:
        return "<i>(none)</i>"
    return "<br/>".join(f"• {item}" for item in items)


def _format_performance(digest: dict[str, Any]) -> str:
    perf = digest.get("performance", {})
    if not isinstance(perf, dict):
        return "<i>No performance data in digest.</i>"
    parts: list[str] = []
    if "equity_close" in perf:
        parts.append(f"Equity close: {perf['equity_close']}")
    if "weekly_return_pct" in perf:
        parts.append(f"Weekly return: {perf['weekly_return_pct']}%")
    if "sharpe_30d" in perf:
        parts.append(f"30-day Sharpe: {perf['sharpe_30d']}")
    if "max_drawdown_pct" in perf:
        parts.append(f"Max drawdown: {perf['max_drawdown_pct']}%")
    return _bullet(parts) if parts else "<i>No performance data in digest.</i>"


def _format_attribution(digest: dict[str, Any]) -> str:
    attr = digest.get("strategy_attribution", [])
    if not isinstance(attr, list) or not attr:
        return "<i>No strategy attribution in digest.</i>"
    rows: list[str] = []
    for entry in attr:
        if not isinstance(entry, dict):
            continue
        name = entry.get("strategy", "?")
        pnl = entry.get("pnl_usd", 0)
        trades = entry.get("trades", 0)
        rows.append(f"{name}: PnL ${pnl} across {trades} trades")
    return _bullet(rows)


def _format_costs(digest: dict[str, Any]) -> str:
    costs = digest.get("costs", {})
    if not isinstance(costs, dict):
        return "<i>No cost breakdown in digest.</i>"
    parts: list[str] = []
    if "api_cost_usd" in costs:
        parts.append(f"API costs (Anthropic + scrape): ${costs['api_cost_usd']}")
    if "commission_usd" in costs:
        parts.append(f"Broker commissions: ${costs['commission_usd']}")
    if "slippage_usd" in costs:
        parts.append(f"Estimated slippage: ${costs['slippage_usd']}")
    return _bullet(parts) if parts else "<i>No cost breakdown in digest.</i>"


def _format_action_items(digest: dict[str, Any]) -> str:
    items = digest.get("action_items", [])
    if not isinstance(items, list):
        return "<i>No action items in digest.</i>"
    flat = [str(it) for it in items if it]
    return _bullet(flat)


def render_weekly_review_pdf(
    digest: dict[str, Any],
    *,
    review_date: date | None = None,
) -> bytes:
    """Render a 4-section weekly-review PDF and return its bytes.

    Pure function — no disk I/O. Caller writes to
    ``data/weekly_reviews/<YYYY-MM-DD>.pdf`` (or whichever sink is wired).
    """
    try:
        from reportlab.lib.pagesizes import LETTER
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise RuntimeError(
            "reportlab is not installed. Run `poetry install` before invoking "
            "render_weekly_review_pdf."
        ) from exc

    styles = _styles()
    review_date = review_date or date.today()

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        title=_TITLE,
        author="iguanatrader",
        # PDF /Subject lives in the uncompressed Info dict; embedding the
        # review_date here gives consumers a searchable date marker even
        # when stream compression is on (default), and lets test runners
        # assert on the date without parsing PDF text streams.
        subject=f"Review week ending {review_date.isoformat()}",
        leftMargin=54,
        rightMargin=54,
        topMargin=54,
        bottomMargin=54,
    )

    flowables: list[Any] = [
        Paragraph(f"<b>{_TITLE}</b>", styles["Title"]),
        Paragraph(f"Review week ending {review_date.isoformat()}", styles["ReviewBody"]),
        Spacer(1, 12),
    ]

    section_renderers = [
        _format_performance,
        _format_attribution,
        _format_costs,
        _format_action_items,
    ]
    for header, render in zip(_SECTION_HEADERS, section_renderers, strict=True):
        flowables.append(Paragraph(header, styles["ReviewSection"]))
        flowables.append(Paragraph(render(digest), styles["ReviewBody"]))
        flowables.append(Spacer(1, 6))

    doc.build(flowables)
    return buffer.getvalue()


__all__ = ["render_weekly_review_pdf"]
