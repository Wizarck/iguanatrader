## 1. Setup + dependencies

- [x] 1.1 Verify `hypothesis = ">=6.100,<7.0"` is present in root `pyproject.toml` dev deps (already added by slice 2 for property tests). No new runtime deps required for K1. — confirmed `hypothesis = ">=6.115"` (slice-2 pin); compatible with K1 strategy use.
- [x] 1.2 Verify Alembic migration sequencing: `0001_*` (slice 1), `0002_*` (slice 3 persistence), `0003_*` (T1 trading) — K1 adds `0004_risk_tables.py`. Reconcile if T1's actual filename diverges before merging K1. — slice 3 actually shipped `0001_initial_schema.py` (tenants/users/authorized_senders) + slice 4 `0002_users_role_enum.py`. T1 is unmerged; K1 migration uses `down_revision='0002'` and the FK to `trade_proposals.id` ships *deferred* — the column is plain UUID (no FK constraint emitted) until T1 lands a follow-up `0004b_risk_fk.py`. Documented as deviation under §9.7 + commit note.
- [x] 1.3 Confirm `sqlalchemy` JSON / JSONB column type is available in the existing slice-3 base models (already true for `state_snapshot` / `confirmation_chain` columns). — `from sqlalchemy import JSON` works on SQLite + Postgres.
- [x] 1.4 Add new `IguanaError` subclasses to `apps/api/src/iguanatrader/shared/errors.py`: `RiskCapBreachedError(IguanaError)` (status=400, type=`urn:iguanatrader:error:risk-cap-breached`), `KillSwitchActiveError(IguanaError)` (status=409, type=`urn:iguanatrader:error:risk-kill-switch-active`), `OverrideAuditMissingError(ValidationError)` (status=400, type=`urn:iguanatrader:error:risk-override-audit-missing`). Re-export from `shared/__init__.py`. — done; `pytest.ini_options.markers` extended with `ci_blocking`.

## 2. Models + migration

- [x] 2.1 Create `apps/api/src/iguanatrader/contexts/risk/__init__.py` exporting public API: `RiskService`, `RiskEngine` (the `evaluate` callable bound under a class facade if needed), `Decision`, `RiskCaps`, `RiskState`, `Protection`, the 5 event payload classes. — re-exports `evaluate` (pure function, no class facade needed per design D1).
- [x] 2.2 Create `apps/api/src/iguanatrader/contexts/risk/models.py` with frozen Pydantic v2 models — done; also added `TradeProposalInput` so the engine types-check without depending on T1's ORM, and `CapType` Literal aligned to data-model §3.3 (`daily_loss`/`weekly_loss` not `daily`/`weekly`).
- [x] 2.3 Create `apps/api/src/iguanatrader/contexts/risk/ports.py` with `RiskRepositoryPort(Protocol)` — done; added `load_risk_state` + `has_today_automatic_breach_event` per design D6 auto-activation flow.
- [x] 2.4 Create SQLAlchemy ORM models — placed in `apps/api/src/iguanatrader/contexts/risk/orm.py` (Pydantic value objects already occupy `models.py`; per `persistence/models.py` docstring "Subsequent slices' models live under `contexts/<name>/...`"). Append-only flags + tenant-scoping flags set per slice-3 listener contract.
- [x] 2.5 Write Alembic migration `0004_risk_tables.py` — done with all 4 tables + CHECK constraints + indexes. Notable deviations: (a) `proposal_id` columns omit FK to `trade_proposals` (T1 unmerged at K1 propose-time; bridge via follow-up `0004b_risk_fk.py`); (b) `kill_switch_state.last_event_id` self-ref FK deferred to keep SQLite migration clean.
- [x] 2.6 Migration adds `'cli'` to the `kill_switch_events.source` CHECK list — done; CHECK reads `IN ('file_flag','env_var','channel_command','dashboard_button','automatic_backoff','automatic_cap_breach','cli')`.

## 3. Pure-functional engine + 5 protections

- [x] 3.1 Create `apps/api/src/iguanatrader/contexts/risk/protections/__init__.py` — done; documents the `(proposal, state, caps) -> Decision` contract.
- [x] 3.2 Create `protections/per_trade.py` — done; handles zero-capital edge (returns reject with `current_pct=None`).
- [x] 3.3 Create `protections/daily.py` — done; reports breached cap as `daily_loss` (matching data-model §3.3 wire form, not the design.md prose `daily`).
- [x] 3.4 Create `protections/weekly.py` — done; cap label `weekly_loss`.
- [x] 3.5 Create `protections/max_open.py` — done; surfaces a normalised `current_pct = open_count / max_open_positions` so SSE consumers can plot uniformly with %-based caps.
- [x] 3.6 Create `protections/max_drawdown.py` — done.
- [x] 3.7 Create `contexts/risk/engine.py` — pure-functional composition with NO datetime/time/sqlalchemy/requests/httpx imports. Snapshot built via `state.model_dump(mode="json")` then stringified. `model_copy(update=...)` used to attach snapshot to short-circuit decisions — Pydantic pure transform, not in the forbidden list.

## 4. Service + repository

- [x] 4.1 Create `contexts/risk/repository.py` implementing `RiskRepositoryPort` — done. Uses `sqlalchemy.dialects.sqlite.insert` for the cache upsert (Postgres has equivalent syntax — follow-up engine-aware swap when prod hits Postgres). `load_risk_state` returns a neutral default until T1+O1 land (per bridge contract).
- [x] 4.2 Create `contexts/risk/service.py::RiskService` — done with `evaluate_proposal`, `record_override`, `activate_kill_switch`, `deactivate_kill_switch`. Kill-switch gate runs first; `OverrideAuditMissingError` raised before any DB write; double-validation (Pydantic + service + DB CHECK); structlog event names match the K1 prompt contract (`risk.evaluation.accepted`, `risk.evaluation.rejected`, `risk.override.recorded`, `risk.kill_switch.activated`, `risk.kill_switch.deactivated`).
- [x] 4.3 Service-layer auto-activation on first daily/weekly/max_drawdown breach — implemented in `_maybe_auto_activate_on_breach`. Per_trade + max_open breaches do NOT auto-activate (single-trade rejections, not regime-level). Idempotent via `has_today_automatic_breach_event`.
- [x] 4.4 Create `contexts/risk/events.py` — done. Used `@dataclass(kw_only=True)` because parent `Event` has a defaulted `idempotency_key` field (Python rejects non-default fields after defaulted ones unless kw_only=True).

## 5. API routes + SSE + DTOs

- [x] 5.1 Create `api/dtos/risk.py` with Pydantic v2 DTOs — done. `OverrideRequest.reason_text` uses `Field(min_length=20)` so Pydantic 422 catches short reasons before reaching the service (service-layer `OverrideAuditMissingError` is fallback for non-DTO entry points like CLI ops).
- [x] 5.2 Create `api/routes/risk.py` — done with `GET /risk/state` + `POST /risk/override`. Discovered automatically by slice-5's `register_routers`. K1 deviation: `POST /risk/override` is auth-required but NOT role-gated (single-seat-per-tenant model — multi-seat RBAC adds `Depends(requires_role(...))` post-MVP).
- [x] 5.3 Create `api/sse/risk.py` — done. Lazy bus singleton via `get_risk_bus()`; tenant filtering at the SSE level (events for other tenants silently dropped). Slice-O1 follow-up moves bus to `app.state.risk_bus` lifespan-managed.

## 6. CLI ops commands

- [x] 6.1 Create `cli/ops.py` exporting `app: typer.Typer` — done. Commands: `halt`, `resume`, `override`. Auto-discovered by `cli/main.py` (module name `ops` → CLI surface `iguanatrader ops`). Tenant + actor user resolved from `--tenant-id`/`--actor-user-id` flags or `IGUANATRADER_OPS_TENANT_ID`/`IGUANATRADER_OPS_ACTOR_USER_ID` env vars (operator-friendly default for single-tenant deployments).
- [x] 6.2 ≥20 char `--reason` enforced via `_validate_reason` Typer-level helper; rejects with `typer.BadParameter` before reaching the service. SQLAlchemy + persistence imports are lazy inside each command body per gotcha #29 (top-of-module imports only `typer` + stdlib).

## 7. Tests — integration + Hypothesis property test (CRITICAL CI gate)

- [x] 7.1 Create `tests/unit/contexts/risk/test_protections.py` — done. Per-protection tests + boundary cases (allow at exact cap = strictly-greater contract; zero capital reject) + parametrised composition test verifying short-circuit behaviour.
- [x] 7.2 Create `tests/unit/contexts/risk/test_engine_purity.py` — done. AST inspection over `engine.py` + every protection module under `protections/`. Forbidden imports: datetime, time, sqlalchemy, requests, httpx, aiohttp, asyncpg, aiosqlite, iguanatrader.persistence, iguanatrader.shared.time. Forbidden call patterns: now/utcnow/commit/execute/add/delete.
- [x] 7.3 Create `tests/property/test_risk_caps_invariant.py` — **CI-BLOCKING** done. `@given(proposal=_proposal_strategy(), state=_state_strategy(), caps=_caps_strategy())` `@settings(max_examples=200, deadline=None)` `@pytest.mark.property` `@pytest.mark.ci_blocking`. Asserts post-trade utilisation ≤ every cap on every allow decision; second test asserts engine determinism. Hypothesis strategies generate Decimal values within sane bounds (`places=2`/`places=4` to avoid MAX_PREC overflow).
- [x] 7.4 Create `tests/integration/test_risk_engine_flow.py` — happy + reject + kill-switch-active + valid-override + short-reason paths via real SQLite + real RiskService. Imports the ORM module so `Base.metadata.create_all` builds the K1 tables.
- [x] 7.5 Create `tests/integration/test_kill_switch_latency.py` — NFR-R5 wall-clock assertion. Uses `time.monotonic()` between `activate_kill_switch + commit` and `evaluate_proposal raising KillSwitchActiveError`. Budget 2s.
- [x] 7.6 Create `tests/integration/test_override_audit.py` — service-layer rejection on 19-char reason + nil-UUID user; DB-level CHECK rejection via raw SQL bypassing the service-layer.
- [x] 7.7 Create `tests/integration/test_risk_routes.py` — `GET /risk/state` 200 shape; `POST /risk/override` 201 happy path + 422 on short reason (Pydantic native body validation, NOT 400 — DTO `Field(min_length=20)` triggers FastAPI's native 422 before the service-layer error path); 401 unauthenticated.

## 8. Documentation

- [ ] 8.1 Append to `docs/gotchas.md`: gotcha #31 — RiskEngine purity is enforced by `test_engine_purity.py`; do NOT import `datetime`/`time` inside `engine.py` even for "convenience". Use `service.py` for all I/O. Gotcha #32 — kill-switch cache row + event log MUST be written in the same transaction; partial writes leave the cache stale. Gotcha #33 — override `reason_text` 20-char floor is satisfiable with `"a" * 20`; weekly review humans flag junk reasons (no automated semantic check in MVP).
- [ ] 8.2 Update `apps/api/README.md`: document `iguanatrader ops halt|resume|override` CLI surface; document the `risk` bounded context's public API in `contexts/risk/__init__.py`; document the property test as a CI-blocking gate (cannot be skipped without `ai-self-review-required` failure).
- [ ] 8.3 Add `docs/runbooks/risk-kill-switch.md` — operator playbook: how to activate (cli/dashboard/channel), how to confirm activation propagated (`SELECT * FROM kill_switch_state WHERE tenant_id=...`), how to read the event log for "who/why/when," how to recover the cache from the event log if drift detected.

## 9. Pre-merge verification

- [ ] 9.1 `mypy --strict apps/api/src/iguanatrader/contexts/risk/ apps/api/src/iguanatrader/api/routes/risk.py apps/api/src/iguanatrader/api/sse/risk.py apps/api/src/iguanatrader/cli/ops.py` clean.
- [ ] 9.2 `pytest apps/api/tests/property/test_risk_caps_invariant.py` exits 0 with 200 examples completed (NFR-R6 CI-blocking gate verified locally before push).
- [ ] 9.3 `pytest apps/api/tests/unit/contexts/risk/ apps/api/tests/integration/test_risk_engine_flow.py apps/api/tests/integration/test_kill_switch_latency.py apps/api/tests/integration/test_override_audit.py apps/api/tests/integration/test_risk_routes.py` all green.
- [ ] 9.4 Coverage on `contexts/risk/{engine,service,repository,events}.py + protections/*.py + api/routes/risk.py + api/sse/risk.py + cli/ops.py` ≥ 80% (or higher; engine + protections should hit 100%).
- [ ] 9.5 `pre-commit run --from-ref origin/main --to-ref HEAD` passes.
- [ ] 9.6 Manual smoke: `iguanatrader ops halt --reason "test halt for slice K1 verification"` → `kill_switch_events` row appended + cache updated + structlog event emitted; `iguanatrader ops resume --reason "test resume for slice K1 verification"` → second event row + cache `is_active=False`.
- [ ] 9.7 PR description includes "AI-reviewer signoff" subsection per release-management.md §4.5; populate self-review findings + L1 detection result; PR template's "T1 already merged?" gate confirmed YES (or follow-up `0004b_risk_fk.py` migration scoped if NO).
