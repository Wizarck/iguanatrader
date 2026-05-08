# Retrospective: r6-hindsight-integration

> **Forward-authored**. Closes original MVP plan slice 19 of 20.

- **PR**: TBD
- **Archive path**: `openspec/changes/archive/<archive-date>-r6-hindsight-integration/`
- **Lines shipped**: ~900 LoC (~480 src + ~470 tests + ~150 retro/openspec).

## What worked

- _(fill on archive — pre-flag candidates: 5th canonical bus-bridge follow-up; 4th skeleton-then-fill; 2nd Protocol+InTreeFake+DeferredProductionInstall (all 3 adapters in one slice). Backwards-compat via optional kwargs on `BriefService.__init__` + `Synthesizer.synthesize` (no archive caller breaks). InMemoryHindsightAdapter as default daemon adapter when `IGUANATRADER_HINDSIGHT_URL` unset is a clean dev-friendly fallback.)_

## What didn't

- _(fill on archive — pre-flag candidates: BriefService.refresh integration tests are LIGHT — just unit tests for the `_maybe_recall_hindsight` helper because full BriefService construction needs CompositeFeatureProvider + Synthesizer + AuditTrailService fakes (~150 LoC fixture). Tradeoff acceptable for v1; full e2e brief-with-hindsight test deferable to a research-e2e slice.)_

## Carry-forward

- **Web Settings page** (Svelte `/settings/+page.svelte` toggle UI) — folded into slice `research-frontend-components` per the proposal §"Out of scope" decision.
- **Hindsight prompt-cache observability** (NFR-I3 instrumentation) — generic obs slice, not slice-specific.
- **MVP v1.0 status**: 20/20 original slices closed (after this slice merges).
- **Auto-recommendation of when to flip the recall flag** (≥12 months heuristic) — v2.

## Pattern usage

- **Bus-bridge follow-up #5**: K1-followup (#103) + P1-followup (#104) + T4-followup-market-data internal (#105) + R6 (this). Five recurrences confirms the pattern; promote to ai-playbook v0.11.1.
- **Skeleton-then-fill #4**: R5 declared `BriefService.__init__` extension points; R6 fills the optional Hindsight slot. R1→R5, T1→T4, T1+T4→t4-followup-market-data, R5→R6.
- **Protocol+InTreeFake+DeferredProductionInstall #2**: HindsightPort + 3 adapters (InMemory + Http + retain handler) ship together. After T4-followup-market-data, this is the 2nd canonical instance with all-in-one shipping.

## Acceptance status (operator-driven, post-merge)

- [ ] Daemon boots cleanly; `IGUANATRADER_HINDSIGHT_URL` unset → InMemory fallback log line emitted.
- [ ] `iguanatrader settings feature-flag get` prints current flags JSON.
- [ ] `iguanatrader settings feature-flag set hindsight_recall_enabled=true` persists.
- [ ] Manual brief refresh with flag ON → narrative context fetched (visible in synth logs); flag OFF → no recall call.
- [ ] mypy --strict + pre-commit + CI green.
