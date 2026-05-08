# tasks — r6-hindsight-integration

## 1. Hindsight subsystem

- [ ] **1.1** Create `apps/api/src/iguanatrader/contexts/research/hindsight/` package with `__init__.py` declaring 3 errors (Unavailable / Timeout / WriteFailed). ~25 LoC.
- [ ] **1.2** `port.py` — `HindsightPort` Protocol per design §1. ~30 LoC.
- [ ] **1.3** `in_memory.py` — `InMemoryHindsightAdapter` per design §2. ~50 LoC.
- [ ] **1.4** `http_adapter.py` — `HttpHindsightAdapter` + `build_hindsight_adapter_from_env()` per design §2 + §7. ~90 LoC.
- [ ] **1.5** `retain_handler.py` — `HindsightRetainHandler` per design §3. ~70 LoC.

## 2. R5 modifications (additive)

- [ ] **2.1** `BriefService.__init__` accepts optional `hindsight: HindsightPort | None`. ~3 LoC.
- [ ] **2.2** `BriefService.refresh` adds the recall block per design §4. ~20 LoC + a private `_tenant_feature_flag` helper (~10 LoC).
- [ ] **2.3** `Synthesizer.synthesize` accepts optional `narrative_context: list[str] | None`; `_render_prompt` prepends Hindsight section if non-empty. ~10 LoC.

## 3. Settings backend

- [ ] **3.1** `api/routes/settings.py` (NEW) with GET/PUT + Pydantic DTOs (FeatureFlagsIn/Out). ~70 LoC.
- [ ] **3.2** Wire router into `api/app.py` (`include_router(settings_router)`). ~3 LoC.

## 4. CLI

- [ ] **4.1** `cli/settings.py` (NEW) — Typer subcommand auto-discovered as `settings`. `feature-flag get/set` per design §6. ~100 LoC.

## 5. Daemon wiring

- [ ] **5.1** `cli/trading.py` `_run_daemon` adds Hindsight construction + retain handler registration per design §7. ~12 LoC.

## 6. Tests

- [ ] **6.1** 6 test files per design §8.

## 7. Lint + commit + PR

- [ ] **7.1** ruff + black + mypy --strict.
- [ ] **7.2** Branch `slice/r6-hindsight-integration` → push → PR → admin merge → archive + retro.

## Estimated effort

| Group | Files | Effort | LoC |
|---|---|---|---|
| 1 Hindsight subsystem | 5 NEW | 2.5h | ~265 |
| 2 R5 modifications | 2 EXISTING | 0.5h | ~45 |
| 3 Settings backend | 1 NEW + 1 EXISTING | 0.5h | ~75 |
| 4 CLI | 1 NEW | 0.75h | ~100 |
| 5 Daemon wiring | 1 EXISTING | 0.25h | ~12 |
| 6 Tests | 6 NEW | 3h | ~400 |
| 7 Lint + PR | — | 0.5h | – |

**Total**: ~8h, ~900 LoC.
