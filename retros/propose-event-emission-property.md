# Retrospective: propose-event-emission-property

> **Forward-authored**. Test-only slice; companion to hypothesis-proposal-invariants (PR #110).

- **PR**: [#112](https://github.com/Wizarck/iguanatrader/pull/112) (merged 2026-05-10, squash `7498f89`).
- **Archive path**: `openspec/changes/archive/2026-05-10-propose-event-emission-property/`
- **Lines shipped**: 361 insertions across 4 files. CI 14/14 verde tras 1 fix round (round 1: 4 unused `# type: ignore[arg-type]` comments — TradingService accepts the fakes via Protocol structural typing).

## What worked

- Regression net for the 1:1 emission contract of `TradingService.propose`; complements hypothesis-proposal-invariants (Proposal payload shape) + test_service_orchestration.py (per-case unit tests).
- Covers the kill-switch path (raises before evaluate, bus untouched) — the most-likely silent-emission-bug failure mode.
- 70 examples (50 + 20) across both tests; Hypothesis catches edge cases unit tests would miss.

## What didn't

- 4 prophylactic `# type: ignore[arg-type]` comments slipped through; mypy --strict flagged them as `unused-ignore`. Pre-flag: don't pre-emptively add type-ignores; only add when mypy actually complains.
- Not `@pytest.mark.ci_blocking` — emission contract already validated by unit tests; this is the regression net.

## Carry-forward

- **Stateful Hypothesis tests** (multi-tick sequence: propose → publish → consume → re-propose) — out of scope for v1; v2 backtest-engine slice.
- **Property tests for K1+P1 bus-bridge handlers** — analogous shape but on `RiskService._proposal_created_handler` + `ApprovalService._approval_requested_handler`. Could ship as a 4th `tests/property/` file.
- **Property tests for `OrchestrationService.bootstrap_routines` propose loop** — assert per-symbol FR-isolation (one bad symbol must not skip the rest).
