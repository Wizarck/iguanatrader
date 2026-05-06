"""Unit tests for the alert filter rule engine (slice O2 D2)."""

from __future__ import annotations

from iguanatrader.contexts.orchestration.alert_filter import (
    AlertTier,
    RoutingDecision,
    classify_event,
)


def test_kill_switch_activated_is_tier_1() -> None:
    cls = classify_event("risk.kill_switch.activated", {})
    assert cls.tier is AlertTier.TIER_1
    assert cls.routing is RoutingDecision.EMITTED_TO_CHANNELS


def test_ibkr_disconnected_is_tier_1() -> None:
    cls = classify_event("trading.ibkr.disconnected_90s", {})
    assert cls.tier is AlertTier.TIER_1


def test_fda_approval_on_watchlist_is_tier_1() -> None:
    cls = classify_event("research.fda.approval_on_watchlist", {"symbol": "ABBV"})
    assert cls.tier is AlertTier.TIER_1


def test_insider_buy_pct_predicate_above_threshold_is_tier_1() -> None:
    cls = classify_event("research.insider.buy_pct", {"buy_pct": "12.5"})
    assert cls.tier is AlertTier.TIER_1
    assert cls.routing is RoutingDecision.EMITTED_TO_CHANNELS


def test_insider_buy_pct_predicate_below_threshold_downgrades_to_tier_3() -> None:
    cls = classify_event("research.insider.buy_pct", {"buy_pct": "5.0"})
    assert cls.tier is AlertTier.TIER_3
    assert cls.routing is RoutingDecision.AUDIT_ONLY


def test_insider_buy_pct_predicate_missing_payload_downgrades() -> None:
    cls = classify_event("research.insider.buy_pct", {})
    assert cls.tier is AlertTier.TIER_3


def test_earnings_surprise_above_25pct_is_tier_1() -> None:
    cls = classify_event("research.earnings.surprise", {"surprise_pct": "30.0"})
    assert cls.tier is AlertTier.TIER_1


def test_earnings_surprise_below_25pct_is_tier_3() -> None:
    cls = classify_event("research.earnings.surprise", {"surprise_pct": "10.0"})
    assert cls.tier is AlertTier.TIER_3


def test_proposal_timed_out_is_tier_2() -> None:
    cls = classify_event("approval.proposal.timed_out", {})
    assert cls.tier is AlertTier.TIER_2
    assert cls.routing is RoutingDecision.DEFERRED_TO_DIGEST


def test_fact_added_is_tier_3() -> None:
    cls = classify_event("research.fact.added", {})
    assert cls.tier is AlertTier.TIER_3
    assert cls.routing is RoutingDecision.AUDIT_ONLY


def test_unknown_event_defaults_to_tier_3() -> None:
    cls = classify_event("totally.made.up", {})
    assert cls.tier is AlertTier.TIER_3
    assert cls.routing is RoutingDecision.AUDIT_ONLY


def test_budget_block_100_is_tier_1() -> None:
    cls = classify_event("observability.budget.block_100", {})
    assert cls.tier is AlertTier.TIER_1


def test_budget_warn_80_is_tier_2() -> None:
    cls = classify_event("observability.budget.warn_80", {})
    assert cls.tier is AlertTier.TIER_2
