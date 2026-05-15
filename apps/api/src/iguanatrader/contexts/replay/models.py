"""Data shapes for the replay context.

Pure dataclasses — no DB, no I/O. The :class:`ExitPolicy` is frozen
so it can be hashed + used as a dict key when collecting per-policy
results in the report.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class ExitPolicy:
    """How a simulated trade exits the position.

    Combinable: ``use_trailing_stop`` and ``use_target`` are
    orthogonal flags that layer on top of the always-on stop +
    horizon. All four combinations are valid (stop-only / trailing /
    target / quad).

    * ``name``: short label for the report ("stop-only-30d", etc.).
    * ``horizon_days``: mark-to-market exit at horizon end if no
      other trigger fires earlier.
    * ``use_trailing_stop``: ratchet the active stop forward each
      bar using :func:`risk.stop_management.compute_trailing_stop`.
    * ``use_target``: add a take-profit trigger at
      ``entry + target_atr_multiplier * ATR(entry_date)``. ATR is
      recomputed at entry time from the pre-entry bars.
    * ``target_atr_multiplier``: only consulted when
      ``use_target=True``.
    * ``trail_trigger_pct`` / ``trail_atr_mult`` / ``trail_atr_period``:
      pass-through to :func:`compute_trailing_stop`; defaults match
      the trailing-stops slice's canonical values.
    """

    name: str
    horizon_days: int = 30
    use_trailing_stop: bool = False
    use_target: bool = False
    target_atr_multiplier: Decimal = Decimal("2")
    trail_trigger_pct: Decimal = Decimal("0.02")  # 2% favorable move
    trail_atr_mult: Decimal = Decimal("2")
    trail_atr_period: int = 14


# Canonical exit-policy set shipped by default. Operators override
# via the CLI to add custom horizons, ATR multipliers, etc.
DEFAULT_POLICIES: tuple[ExitPolicy, ...] = (
    ExitPolicy(name="stop-only-30d", horizon_days=30),
    ExitPolicy(name="trailing-30d", horizon_days=30, use_trailing_stop=True),
    ExitPolicy(
        name="stop+target-30d",
        horizon_days=30,
        use_target=True,
        target_atr_multiplier=Decimal("2"),
    ),
    ExitPolicy(
        name="quad-30d",
        horizon_days=30,
        use_trailing_stop=True,
        use_target=True,
        target_atr_multiplier=Decimal("2"),
    ),
)


@dataclass(frozen=True, slots=True)
class SimulatedOutcome:
    """Result of :func:`simulate_pnl` for one proposal + one policy."""

    proposal_id: UUID
    policy_name: str
    exited: bool  # True if an exit trigger fired; False if data ran out
    exit_reason: str  # "stop" / "target" / "horizon" / "no_bars" / "no_exit"
    exit_price: Decimal
    exit_at: datetime | None
    bars_held: int
    pnl_absolute: Decimal  # (exit - entry) * qty for buy; reversed for sell
    pnl_pct: Decimal  # (exit - entry) / entry for buy; reversed for sell


@dataclass(frozen=True, slots=True)
class ProposalReplayRow:
    """One row of the per-proposal report — flatlist for HTML rendering."""

    proposal_id: UUID
    symbol: str
    side: str
    opened_at: datetime
    historical_decision: str  # "approved" / "rejected" / "timeout" / "unknown"
    would_pass_gate_now: bool | None  # None when risk engine not invoked
    actual_pnl: Decimal | None  # populated when historical_decision="approved" + trade closed
    sim_outcomes: dict[str, SimulatedOutcome] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyAggregate:
    """Aggregate metrics per exit policy across the replay window."""

    policy_name: str
    proposals_evaluated: int
    proposals_exited: int  # excludes "no_bars" / "no_exit"
    total_pnl: Decimal
    mean_pnl_pct: Decimal
    win_rate: Decimal  # fraction with pnl_absolute > 0 among exited
    stop_rate: Decimal  # fraction exited via "stop"
    target_rate: Decimal  # fraction exited via "target"
    horizon_rate: Decimal  # fraction exited via "horizon"


@dataclass(frozen=True, slots=True)
class GateCalibration:
    """Gate-precision + gate-recall over the replay window.

    Computed against ONE policy (the canonical reference). The HTML
    report renders one calibration block per policy so the operator
    can see which exit assumption yields the most useful calibration
    signal.
    """

    policy_name: str
    historical_approved_count: int
    historical_approved_profitable_count: int
    historical_rejected_count: int
    historical_rejected_would_have_profited_count: int
    # gate_precision = approved_profitable / approved
    # gate_recall    = approved_profitable / (approved_profitable + rejected_would_have_profited)
    gate_precision: Decimal | None  # None when denominator == 0
    gate_recall: Decimal | None


@dataclass(frozen=True, slots=True)
class ReplayResult:
    """Top-level result of :meth:`ReplayService.replay_window`."""

    window_start: datetime
    window_end: datetime
    policies: tuple[ExitPolicy, ...]
    rows: tuple[ProposalReplayRow, ...]
    aggregates: tuple[PolicyAggregate, ...]
    gate_calibrations: tuple[GateCalibration, ...]
    proposals_skipped_no_bars: int


__all__ = [
    "DEFAULT_POLICIES",
    "ExitPolicy",
    "GateCalibration",
    "PolicyAggregate",
    "ProposalReplayRow",
    "ReplayResult",
    "SimulatedOutcome",
]
