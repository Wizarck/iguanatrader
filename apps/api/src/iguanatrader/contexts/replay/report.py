"""Render a :class:`ReplayResult` to a self-contained HTML file.

No Jinja2 dependency — the template is a single f-string with light
HTML + inline CSS. The output is a one-page file the operator opens
locally; no JS runtime, no external assets.
"""

from __future__ import annotations

import html
from decimal import Decimal
from pathlib import Path

from iguanatrader.contexts.replay.models import (
    GateCalibration,
    PolicyAggregate,
    ProposalReplayRow,
    ReplayResult,
)


def _fmt_decimal(value: Decimal | None, *, places: int = 2) -> str:
    if value is None:
        return "—"
    quant = Decimal(10) ** -places
    return str(value.quantize(quant))


def _fmt_pct(value: Decimal | None, *, places: int = 2) -> str:
    if value is None:
        return "—"
    return f"{_fmt_decimal(value * Decimal(100), places=places)}%"


def _render_aggregates_table(aggregates: tuple[PolicyAggregate, ...]) -> str:
    if not aggregates:
        return "<p><em>No aggregates — empty window or no policies.</em></p>"
    rows = "".join(
        f"<tr>"
        f"<td><code>{html.escape(a.policy_name)}</code></td>"
        f"<td>{a.proposals_evaluated}</td>"
        f"<td>{a.proposals_exited}</td>"
        f"<td>{_fmt_decimal(a.total_pnl)}</td>"
        f"<td>{_fmt_pct(a.mean_pnl_pct)}</td>"
        f"<td>{_fmt_pct(a.win_rate)}</td>"
        f"<td>{_fmt_pct(a.stop_rate)}</td>"
        f"<td>{_fmt_pct(a.target_rate)}</td>"
        f"<td>{_fmt_pct(a.horizon_rate)}</td>"
        f"</tr>"
        for a in aggregates
    )
    return (
        "<table>"
        "<thead><tr>"
        "<th>Policy</th>"
        "<th>Evaluated</th>"
        "<th>Exited</th>"
        "<th>Total PnL</th>"
        "<th>Mean PnL %</th>"
        "<th>Win rate</th>"
        "<th>Stop rate</th>"
        "<th>Target rate</th>"
        "<th>Horizon rate</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _render_calibration_table(calibrations: tuple[GateCalibration, ...]) -> str:
    if not calibrations:
        return "<p><em>No gate calibration — no approved + no rejected outcomes in this window.</em></p>"
    rows = "".join(
        f"<tr>"
        f"<td><code>{html.escape(c.policy_name)}</code></td>"
        f"<td>{c.historical_approved_count}</td>"
        f"<td>{c.historical_approved_profitable_count}</td>"
        f"<td>{c.historical_rejected_count}</td>"
        f"<td>{c.historical_rejected_would_have_profited_count}</td>"
        f"<td>{_fmt_pct(c.gate_precision)}</td>"
        f"<td>{_fmt_pct(c.gate_recall)}</td>"
        f"</tr>"
        for c in calibrations
    )
    return (
        "<table>"
        "<thead><tr>"
        "<th>Policy</th>"
        "<th>Approved (N)</th>"
        "<th>Approved+Profitable</th>"
        "<th>Rejected (N)</th>"
        "<th>Rejected+WouldHaveProfited</th>"
        "<th>Gate precision</th>"
        "<th>Gate recall</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


def _render_proposal_rows(
    rows: tuple[ProposalReplayRow, ...], policy_names: tuple[str, ...]
) -> str:
    if not rows:
        return "<p><em>No proposals in this window.</em></p>"
    header_cells = (
        "<th>Proposal</th>"
        "<th>Symbol</th>"
        "<th>Side</th>"
        "<th>Opened</th>"
        "<th>Historical</th>"
        "<th>Actual PnL</th>"
        + "".join(f"<th>{html.escape(name)}<br>(PnL)</th>" for name in policy_names)
        + "".join(f"<th>{html.escape(name)}<br>(reason)</th>" for name in policy_names)
    )
    body_lines: list[str] = []
    for row in rows:
        sim_pnl_cells = []
        sim_reason_cells = []
        for name in policy_names:
            o = row.sim_outcomes.get(name)
            if o is None:
                sim_pnl_cells.append("<td>—</td>")
                sim_reason_cells.append("<td>—</td>")
            else:
                pnl_css = "pos" if o.pnl_absolute > 0 else ("neg" if o.pnl_absolute < 0 else "")
                sim_pnl_cells.append(f"<td class='{pnl_css}'>{_fmt_decimal(o.pnl_absolute)}</td>")
                sim_reason_cells.append(f"<td><code>{html.escape(o.exit_reason)}</code></td>")
        body_lines.append(
            "<tr>"
            f"<td><code>{html.escape(str(row.proposal_id)[:8])}</code></td>"
            f"<td>{html.escape(row.symbol)}</td>"
            f"<td>{html.escape(row.side)}</td>"
            f"<td>{html.escape(row.opened_at.isoformat())}</td>"
            f"<td>{html.escape(row.historical_decision)}</td>"
            f"<td>{_fmt_decimal(row.actual_pnl)}</td>"
            + "".join(sim_pnl_cells)
            + "".join(sim_reason_cells)
            + "</tr>"
        )
    return (
        "<table>"
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(body_lines)}</tbody>"
        "</table>"
    )


_STYLE = """
body { font-family: -apple-system, system-ui, sans-serif; max-width: 1400px; margin: 2em auto; padding: 0 1em; color: #222; }
h1 { font-size: 1.5em; margin-bottom: 0.2em; }
h2 { font-size: 1.2em; margin-top: 2em; color: #444; border-bottom: 1px solid #ddd; padding-bottom: 0.3em; }
.meta { color: #666; font-size: 0.9em; }
table { border-collapse: collapse; width: 100%; margin-top: 1em; font-size: 0.85em; }
th, td { border: 1px solid #ddd; padding: 0.4em 0.6em; text-align: left; }
th { background: #f4f4f6; font-weight: 600; }
tbody tr:nth-child(even) { background: #fafafa; }
td.pos { color: #1a7f37; font-weight: 600; }
td.neg { color: #b42318; font-weight: 600; }
code { font-family: ui-monospace, monospace; font-size: 0.85em; background: #f0f0f2; padding: 0.1em 0.3em; border-radius: 3px; }
"""


def render_html(result: ReplayResult) -> str:
    """Render a :class:`ReplayResult` to a self-contained HTML string."""
    policy_names = tuple(p.name for p in result.policies)
    aggregates_html = _render_aggregates_table(result.aggregates)
    calibration_html = _render_calibration_table(result.gate_calibrations)
    rows_html = _render_proposal_rows(result.rows, policy_names)
    title = (
        f"iguanatrader replay — "
        f"{result.window_start.date().isoformat()} → "
        f"{result.window_end.date().isoformat()}"
    )
    return (
        "<!doctype html>"
        "<html><head>"
        f'<meta charset="utf-8">'
        f"<title>{html.escape(title)}</title>"
        f"<style>{_STYLE}</style>"
        "</head><body>"
        f"<h1>{html.escape(title)}</h1>"
        f"<p class='meta'>"
        f"{len(result.rows)} proposals evaluated · "
        f"{result.proposals_skipped_no_bars} skipped (no bars) · "
        f"{len(result.policies)} policies"
        f"</p>"
        "<h2>Policy aggregates</h2>"
        f"{aggregates_html}"
        "<h2>Gate calibration</h2>"
        f"<p class='meta'>Gate precision = approved-and-profitable / approved. "
        f"Gate recall = approved-and-profitable / (approved-and-profitable + "
        f"rejected-but-would-have-profited).</p>"
        f"{calibration_html}"
        "<h2>Per-proposal detail</h2>"
        f"{rows_html}"
        "</body></html>"
    )


def write_report(result: ReplayResult, *, out_path: Path) -> Path:
    """Render + write to ``out_path``. Returns the absolute path written."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(render_html(result), encoding="utf-8")
    return out_path.resolve()


__all__ = ["render_html", "write_report"]
