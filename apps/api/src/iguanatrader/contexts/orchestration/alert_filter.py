"""Alert filter rule engine — slice O2 design D2.

Maps incoming MessageBus event names + payloads to one of three
:class:`AlertTier`s + a :class:`RoutingDecision`. Tier-1 events are
emitted immediately to P1 channels (Telegram/Hermes); Tier-2 events
accumulate into the next routine digest; Tier-3 events live in the
audit log only.

The rule table is data, not algorithm — a sorted lookup over event
names with optional payload predicates. Adding a rule is a one-line
addition + a unit test.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum, StrEnum
from typing import Any


class AlertTier(IntEnum):
    """Alert tier — drives downstream routing."""

    TIER_1 = 1  # Immediate emit (Telegram / Hermes / SMS).
    TIER_2 = 2  # Accumulate into next routine digest.
    TIER_3 = 3  # Audit-log only.


class RoutingDecision(StrEnum):
    """Per-event routing outcome."""

    EMITTED_TO_CHANNELS = "emitted_to_channels"
    DEFERRED_TO_DIGEST = "deferred_to_digest"
    AUDIT_ONLY = "audit_only"


PayloadPredicate = Callable[[dict[str, Any]], bool]


@dataclass(frozen=True, slots=True)
class AlertRule:
    """One row in the static rule table."""

    event_name: str
    tier: AlertTier
    payload_predicate: PayloadPredicate | None = None
    description: str = ""


# ----------------------------------------------------------------------
# Predicates
# ----------------------------------------------------------------------


def _insider_buy_pct_ge_10(payload: dict[str, Any]) -> bool:
    raw = payload.get("buy_pct")
    if raw is None:
        return False
    try:
        return Decimal(str(raw)) >= Decimal("10")
    except Exception:
        return False


def _earnings_surprise_beat_ge_25(payload: dict[str, Any]) -> bool:
    raw = payload.get("surprise_pct")
    if raw is None:
        return False
    try:
        return Decimal(str(raw)) >= Decimal("25")
    except Exception:
        return False


# ----------------------------------------------------------------------
# Canonical rule table (slice O2 design D2).
# Order matters only for documentation — the lookup is event-name-keyed.
# ----------------------------------------------------------------------


CANONICAL_RULES: tuple[AlertRule, ...] = (
    AlertRule(
        event_name="risk.kill_switch.activated",
        tier=AlertTier.TIER_1,
        description="Kill-switch flipped — wake operator immediately.",
    ),
    AlertRule(
        event_name="trading.ibkr.disconnected_90s",
        tier=AlertTier.TIER_1,
        description="Broker reconnect exhausted; live trading impacted.",
    ),
    AlertRule(
        event_name="research.fda.approval_on_watchlist",
        tier=AlertTier.TIER_1,
        description="FDA approval for a watchlist symbol — material catalyst.",
    ),
    AlertRule(
        event_name="research.insider.buy_pct",
        tier=AlertTier.TIER_1,
        payload_predicate=_insider_buy_pct_ge_10,
        description="Insider purchase ≥10% of float — strong signal.",
    ),
    AlertRule(
        event_name="observability.budget.block_100",
        tier=AlertTier.TIER_1,
        description="Monthly LLM budget exhausted — no more synthesis until reset.",
    ),
    AlertRule(
        event_name="research.earnings.surprise",
        tier=AlertTier.TIER_1,
        payload_predicate=_earnings_surprise_beat_ge_25,
        description="Earnings surprise ≥25% — outlier reaction expected.",
    ),
    AlertRule(
        event_name="approval.proposal.timed_out",
        tier=AlertTier.TIER_2,
        description="Proposal timed out — defer to next digest.",
    ),
    AlertRule(
        event_name="research.fact.added",
        tier=AlertTier.TIER_3,
        description="Routine fact ingest — audit only.",
    ),
    AlertRule(
        event_name="trading.fill.received",
        tier=AlertTier.TIER_2,
        description="Fill arrived — surface in next routine digest.",
    ),
    AlertRule(
        event_name="observability.budget.warn_80",
        tier=AlertTier.TIER_2,
        description="Budget at 80% — surface in next routine digest.",
    ),
)


_RULE_BY_NAME: dict[str, AlertRule] = {r.event_name: r for r in CANONICAL_RULES}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Classification:
    """Result of :func:`classify_event`."""

    event_name: str
    tier: AlertTier
    routing: RoutingDecision
    payload: dict[str, Any] = field(default_factory=dict)


def classify_event(
    event_name: str,
    payload: dict[str, Any] | None = None,
) -> Classification:
    """Classify ``(event_name, payload)`` into one of three tiers.

    Unknown event names default to :class:`AlertTier.TIER_3` (audit only).
    """
    payload = payload or {}
    rule = _RULE_BY_NAME.get(event_name)
    if rule is None:
        return Classification(
            event_name=event_name,
            tier=AlertTier.TIER_3,
            routing=RoutingDecision.AUDIT_ONLY,
            payload=payload,
        )
    if rule.payload_predicate is not None and not rule.payload_predicate(payload):
        # The rule matched the name but its payload predicate failed →
        # downgrade to TIER_3.
        return Classification(
            event_name=event_name,
            tier=AlertTier.TIER_3,
            routing=RoutingDecision.AUDIT_ONLY,
            payload=payload,
        )
    routing = {
        AlertTier.TIER_1: RoutingDecision.EMITTED_TO_CHANNELS,
        AlertTier.TIER_2: RoutingDecision.DEFERRED_TO_DIGEST,
        AlertTier.TIER_3: RoutingDecision.AUDIT_ONLY,
    }[rule.tier]
    return Classification(
        event_name=event_name,
        tier=rule.tier,
        routing=routing,
        payload=payload,
    )


__all__ = [
    "CANONICAL_RULES",
    "AlertRule",
    "AlertTier",
    "Classification",
    "RoutingDecision",
    "classify_event",
]
