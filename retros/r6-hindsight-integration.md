# Retrospective: r6-hindsight-integration

> **Forward-authored**. Closes original MVP plan slice 19 of 20.

- **PR**: [#107](https://github.com/Wizarck/iguanatrader/pull/107) (merged 2026-05-08, squash `a5de401`).
- **Archive path**: `openspec/changes/archive/2026-05-08-r6-hindsight-integration/`
- **Lines shipped**: 1958 insertions across 26 files (~480 src + ~990 tests + ~490 openspec/retro). 2 CI rounds (round 1 mypy: list[str] cast on recall + LLMCompletion test fixture mismatch; round 2 verde 14/14).

## What worked

- 5th canonical bus-bridge follow-up + 4th skeleton-then-fill + 2nd Protocol+InTreeFake+DeferredProductionInstall (all 3 adapters in one slice).
- Backwards-compat via optional kwargs on `BriefService.__init__` + `Synthesizer.synthesize` (no R5 archive caller breaks).
- `InMemoryHindsightAdapter` as default daemon adapter when `IGUANATRADER_HINDSIGHT_URL` unset is a clean dev-friendly fallback (matches pattern from T4-followup-market-data `build_hindsight_adapter_from_env`).
- mypy --strict + ruff + black + pytest + lighthouse + coderabbit all green at round 2 (1 fix push needed).

## What didn't

- BriefService.refresh integration tests are LIGHT — just unit tests for the `_maybe_recall_hindsight` helper because full BriefService construction needs CompositeFeatureProvider + Synthesizer + AuditTrailService fakes (~150 LoC fixture). Tradeoff acceptable for v1; full e2e brief-with-hindsight test deferable to a research-e2e slice.
- Synthesizer narrative-context test was BRITTLE on round 1 (constructed real `LLMCompletion` + `FeatureBundle` with wrong field names). Fix: monkeypatch `_render_prompt` + spy LLMClient (no real fixture types). Pre-flag for future test-design: when isolating prompt-composition logic, monkeypatch the surrounding methods instead of constructing the full bundle types.
- `service.py:261` returned `Any` from `list[str]`-typed func because `self._hindsight: Any`; cast via `[str(x) for x in result]`. Same lesson as T4-followup-market-data: when typing optional injection slots as `Any`, downstream return types need explicit casts to satisfy mypy --strict.

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

- [x] mypy --strict + ruff + black + pre-commit + pytest + Helm + Lighthouse + CodeRabbit ALL green (after 1 mypy fix round).
- [ ] Daemon boots cleanly; `IGUANATRADER_HINDSIGHT_URL` unset → InMemory fallback log line emitted (operator-verified at next paper-mode run).
- [ ] `iguanatrader settings feature-flag get` prints current flags JSON.
- [ ] `iguanatrader settings feature-flag set hindsight_recall_enabled=true` persists.
- [ ] Manual brief refresh with flag ON → narrative context fetched (visible in synth logs); flag OFF → no recall call.
