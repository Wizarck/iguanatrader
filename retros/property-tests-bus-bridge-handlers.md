# Retrospective: property-tests-bus-bridge-handlers

> **Forward-authored** — fill at archive with squash SHA, CI rounds, and pre-flag candidates.

- **PR**: [#116](https://github.com/Wizarck/iguanatrader/pull/116) (merged 2026-05-12, squash `cd04d5c`).
- **Archive path**: `openspec/changes/archive/2026-05-12-property-tests-bus-bridge-handlers/`
- **Lines shipped**: 612 insertions across 5 files (2 test files + openspec proposal/tasks + retro). CI 12/12 verde tras 1 fix round.

## What worked

- Reused the canonical async-property-test shape from PR #112: sync `def test_...` wrapping `async def _run(): ...; asyncio.run(_run())`. Cero ambigüedad sobre cómo combinar Hypothesis + async — el patrón ya está documentado en 3 retros (#112, #114, this one).
- Composite Hypothesis strategy `_decision_pairs` constructs valid `(outcome, cap_type_breached)` pairs honoring the Decision model invariant ("`cap_type_breached` is None iff outcome == 'allow'") at strategy level rather than via `assume(...)` — Hypothesis never wastes examples on rejected inputs.
- `monkeypatch.setattr` to swap `TradeProposalRepository` factory inline avoids the integration-test DB seed overhead (50 examples × seed-rows would be slow).
- Property `test_handler_missing_proposal_emits_nothing` asserts negative invariants ("evaluate_proposal MUST NOT be called when row missing") by patching it to `raise AssertionError` — defensive double-check that the early-return path is exercised.

## What didn't

- **Round 1 mypy --strict failure** — Hypothesis `sampled_from(["allow", "reject", "clip"])` returns `str`, but `Decision.outcome` is `Literal["allow", "reject", "clip"]`. mypy strict refuses the assignment without an explicit cast. Fix: `cast(Outcome, outcome)` + `cast("CapType | None", cap_type_breached)` at the `Decision(...)` construction site. Pre-flag candidate: when Hypothesis sampled_from values flow into Pydantic Literal fields, the cast is unavoidable (sampled_from doesn't narrow the static type even though it constrains the value).

## Carry-forward

- **Property tests for the 3 outbound bridges** in `ApprovalService` (`_bridge_to_trading_{approved,rejected,timeout}_handler`) — analogous shape, deliberately deferred to keep this slice scoped. Could be a follow-up `property-tests-approval-outbound-bridges`.
- **Stateful Hypothesis tests** (multi-tick sequences) — v2 backtest-engine slice.

## Pattern usage

- 3rd `tests/property/` file authored using the canonical async-property-test shape: sync `def test_...` wrapping `async def _run(): ...; asyncio.run(_run())`. Codifies the pattern documented in #112 + #114 retros.
