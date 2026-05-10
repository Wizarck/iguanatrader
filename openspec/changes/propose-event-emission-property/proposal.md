# Proposal: propose-event-emission-property

> Hypothesis property test: `TradingService.propose` emits **exactly one** `ProposalCreated` event per non-None strategy result and **zero** events when the strategy returns None. Companion to `test_proposal_shape_invariants.py` (slice hypothesis-proposal-invariants, PR #110); test-only slice — zero runtime code changes.

## Why

The hypothesis-proposal-invariants slice (PR #110) covers the **payload** invariants of `Proposal` objects emitted by strategies. The **emission contract** of `TradingService.propose` is still only covered by per-case unit tests in `test_service_orchestration.py`:

- "Strategy returns Proposal → 1 ProposalCreated published" — verified for one fixed input.
- "Strategy returns None → 0 events published" — verified for one fixed input.

A Hypothesis property test that generates random strategy outputs (Proposal | None) and asserts the bus emission contract over `max_examples=50` runs catches the class of bugs where an edge case (e.g. a Proposal with `quantity=0` borderline, an exception path partially-emitting) silently breaks the canonical 1:1 invariant.

## What

Single new test file: `apps/api/tests/property/test_propose_event_emission.py` — `@pytest.mark.property` (NOT `ci_blocking` — emission is already covered by unit tests; this is the regression net).

For every random `Proposal | None` returned by a stub strategy, when `TradingService.propose(symbol, strategy_config_id, bars, config)` is invoked:

1. If the stub returns a `Proposal`: assert `len(captured_proposal_created) == 1`.
2. If the stub returns `None`: assert `len(captured_proposal_created) == 0`.
3. If `KillSwitchActiveError` is raised before `evaluate`: assert `len(captured_proposal_created) == 0` (defensive — the bus is not touched on early-raise).

The strategy stub is constructed via Hypothesis composite from random `Proposal` shapes (or `None`). The TradingService is constructed with a fake broker + async resolver returning the stub strategy.

~120 LoC. No new runtime code.

## Out of scope

- Stateful sequence tests (multi-tick): out of scope; v2 backtest-engine slice.
- Property tests on the K1+P1 bus-bridge handlers: separate slice.
- Property tests on `OrchestrationService.bootstrap_routines` propose loops: separate slice.

## Acceptance criteria

1. `pytest apps/api/tests/property/test_propose_event_emission.py` passes 50 examples.
2. mypy --strict + ruff + black + pre-commit + CI green.

## Blast radius

ZERO runtime code. NEW test file only.

## Estimated effort

~1.5h, ~150 LoC.
