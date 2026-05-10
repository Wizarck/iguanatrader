# Retrospective: propose-event-emission-property

> **Forward-authored**. Test-only slice; companion to hypothesis-proposal-invariants (PR #110).

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-propose-event-emission-property/`
- **Lines shipped**: ~340 LoC (~280 test + ~60 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: regression net for the 1:1 emission contract of `TradingService.propose`; complements hypothesis-proposal-invariants (Proposal payload shape) + test_service_orchestration.py (per-case unit tests); covers the kill-switch path (raises before evaluate, bus untouched) which is the most-likely silent-emission-bug failure mode.)_

## What didn't

- _(fill on archive — pre-flag candidates: not @pytest.mark.ci_blocking — emission contract is already validated by unit tests + Hypothesis is the regression catch. Tradeoff between strict CI gate + Hypothesis flakiness on unusual examples.)_

## Carry-forward

- **Stateful Hypothesis tests** (multi-tick sequence: propose → publish → consume → re-propose) — out of scope for v1; v2 backtest-engine slice.
- **Property tests for K1+P1 bus-bridge handlers** — analogous shape but on `RiskService._proposal_created_handler` + `ApprovalService._approval_requested_handler`. Could ship as a 4th `tests/property/` file.
- **Property tests for `OrchestrationService.bootstrap_routines` propose loop** — assert per-symbol FR-isolation (one bad symbol must not skip the rest).
