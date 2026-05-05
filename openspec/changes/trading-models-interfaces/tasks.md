## 1. Setup + dependencies

- [x] 1.1 Verify the slice-T1 worktree branches from the latest `main` containing slice-5 `api-foundation-rfc7807` (route discovery + global RFC 7807 handler) and rebase onto R1's `0002_research_tables.py` migration once R1 merges (per design D5 merge order). Document the rebase step in the PR description.
- [x] 1.2 No new runtime deps. Verify `pydantic>=2`, `sqlalchemy>=2`, `alembic`, `fastapi`, `typer` are already in root `pyproject.toml` from prior slices. No `package.json` changes.
- [x] 1.3 No `poetry.lock` regeneration needed (no dep changes); skip the `regenerate-lock.yml` step unless 1.2 reveals an unexpected gap.

## 2. Models + migration + listener config

- [x] 2.1 Create `apps/api/src/iguanatrader/contexts/trading/__init__.py` (empty package marker; docstring: "Bounded context for trading — entities, ports, service, repositories, events. Adapters live in slice T2 (`brokers/`) + T3 (`strategies/`); routes in slice T4.").
- [x] 2.2 Create `apps/api/src/iguanatrader/contexts/trading/models.py` with ORM classes `StrategyConfig`, `TradeProposal`, `Trade`, `Order`, `Fill`, `EquitySnapshot` matching `docs/data-model.md §3.2` line-for-line. Set `__tablename_is_append_only__ = True` on `TradeProposal`, `Fill`, `EquitySnapshot`. Set `__append_only_mutable_columns__ = frozenset({...})` on `Trade` (state, closed_at) and `Order` (state, broker_order_id, submitted_at, acknowledged_at, closed_at). All inherit `__tenant_scoped__ = True` (default). Use `Uuid` + `UUID` types per slice 4 model convention. Money columns as `NUMERIC(18,8)`.
- [x] 2.3 Create `apps/api/src/iguanatrader/migrations/versions/0003_trading_tables.py` with `revision="0003_trading_tables"`, `down_revision="0002_research_tables"`. Implement `upgrade()` creating the 6 tables with NOT NULLs, CHECK constraints (side/mode/state/snapshot_kind enums), indexes (per data-model index list), FK to `research_briefs(id)` ON DELETE RESTRICT (nullable). Implement `downgrade()` dropping tables in reverse-FK order. Use `naming_convention` (slice 3 metadata) for constraint names.
- [x] 2.4 Verify `equity_snapshots.snapshot_kind` CHECK uses `IN ('event','minute','daily')` per data-model §7.2 update (NOT the §3.2 `'tick'` variant). Add inline comment citing §7.2 inconsistency for traceability.
- [x] 2.5 Add SQLAlchemy event hook stub in `models.py` for `StrategyConfig.before_update` that increments `version` + emits structlog event `trading.config.changed`. Slice O1 will wire the `config_changes` row insert; T1 just plants the version-bump + log.
- [x] 2.6 Add `NotImplementedFeatureError(IguanaError)` to `apps/api/src/iguanatrader/shared/errors.py` with `default_status=501`, `default_title="Feature Not Implemented"`, `type_uri="urn:iguanatrader:error:not-implemented"`. Re-export from `shared/__init__.py`. Inline docstring justifies the addition (T1 stub-routes + slice-5 D9 precedent).

## 3. Ports + repository + service skeleton

- [x] 3.1 Create `apps/api/src/iguanatrader/contexts/trading/ports.py` with `BrokerPort(Port, Protocol)` + `StrategyPort(Port, Protocol)` declarations per design D1. Include the supporting types (`NewOrder`, `BrokerOrderId` newtype, `FillEvent` dataclass, `Position`, `BarHistory`, `Proposal`) — minimal shapes adequate for the protocols' signatures. Docstrings explicitly forbid lookahead in `StrategyPort.evaluate`.
- [x] 3.2 Create `apps/api/src/iguanatrader/contexts/trading/repository.py` with the six `BaseRepository[Model]` subclasses per design D7. Plant `StrategyConfigRepository.upsert(symbol, strategy_kind, params, enabled)` concretely (bumps version, triggers the model's pre-update hook). Other repositories ship empty bodies (only the type binding); document inline that T4 adds query helpers.
- [x] 3.3 Create `apps/api/src/iguanatrader/contexts/trading/service.py` with `TradingService` class. Constructor takes `bus: MessageBus`, `broker: BrokerPort`, `strategy_resolver: Callable[[UUID], StrategyPort]`, `session: AsyncSession` (or sync-Session per slice-3 contract). Implement `propose(symbol, strategy_id) -> Proposal` concretely (calls strategy.evaluate, INSERTs trade_proposals row, publishes `ProposalCreated`). Plant skeletal handlers for `risk_check_handler`, `enqueue_approval_handler`, `execute_on_approval_handler`, `reconcile_fills_handler`, `halt_handler` — each logs structlog event + comments "wired in T4". Subscribe handlers to MessageBus in `register_subscriptions(bus)` helper.
- [x] 3.4 Verify ruff `no-cross-context-deep-imports` rule allows `events.py` to import from `contexts.risk.events` (KillSwitchTripped) — the rule excludes `events.py` paths per slice-2 contract. If the rule isn't yet plumbed for this exclusion, document the gap as a follow-up.

## 4. DTOs (trades, proposals)

- [x] 4.1 Create `apps/api/src/iguanatrader/api/dtos/trades.py` with Pydantic v2 models: `StrategyConfigOut`, `StrategyConfigIn`, `TradeOut`, `OrderOut`, `FillOut`, `EquitySnapshotOut`, paginated wrapper `TradeListOut`. Set `model_config = ConfigDict(from_attributes=True)` on every model. Use `Decimal` for money columns, `UUID` for IDs, `datetime` for timestamps.
- [x] 4.2 Create `apps/api/src/iguanatrader/api/dtos/proposals.py` with `ProposalIn` (request shape — for FR5 manual proposals if applicable; T4 confirms), `ProposalOut`, paginated wrapper `ProposalListOut`. Same Pydantic v2 conventions as 4.1.
- [x] 4.3 Add openapi `examples=...` on each DTO field where a sample value clarifies the contract for the slice-5 typegen output (frontend devs read examples in the generated `index.ts` JSDoc).

## 5. Routes stubs (501 until T4)

- [x] 5.1 Create `apps/api/src/iguanatrader/api/routes/trades.py` exporting `router: APIRouter` with the canonical endpoints from `docs/openspec-slice.md` row T4: `GET /trades`, `GET /trades/{trade_id}`, `GET /trades/{trade_id}/fills`. Each handler raises `NotImplementedFeatureError(detail="GET /api/v1/trades will be wired in slice T4 (trading-routes-and-daemon).")`. Each declares `response_model=...` (TradeOut, FillOut, etc.) so OpenAPI schema is complete.
- [x] 5.2 Create `apps/api/src/iguanatrader/api/routes/portfolio.py` exporting `router` with `GET /portfolio`, `GET /portfolio/positions`, `GET /portfolio/equity`. Same 501-stub pattern.
- [x] 5.3 Create `apps/api/src/iguanatrader/api/routes/strategies.py` exporting `router` with `GET /strategies`, `GET /strategies/{symbol}`, `PUT /strategies/{symbol}`, `DELETE /strategies/{symbol}`. Same 501-stub pattern.
- [x] 5.4 Create `apps/api/src/iguanatrader/api/routes/proposals.py` exporting `router` with `GET /proposals`, `GET /proposals/{proposal_id}`. Same 501-stub pattern.
- [x] 5.5 Verify slice-5 `register_routers` picks up all four modules without editing `app.py` or `routes/__init__.py` (smoke: boot the app, GET `/openapi.json`, assert all four prefix paths appear).

## 6. Events.py inter-context contract

- [x] 6.1 Create `apps/api/src/iguanatrader/contexts/trading/events.py` with the 8 dataclasses per design D3: `ProposalCreated`, `ProposalRiskEvaluated`, `ApprovalRequested`, `ProposalApproved`, `ProposalRejected`, `OrderPlaced`, `OrderFilled`, `EquityUpdated`. Each subclasses `iguanatrader.shared.messagebus.Event`. Each declares `event_name: ClassVar[str]` matching `<context>.<entity>.<action>` (e.g., `"trading.proposal.created"`). Each carries `tenant_id: UUID` explicitly + the entity's PK + `metadata: dict[str, Any] = field(default_factory=dict)` extension slot. `idempotency_key` is set in `__post_init__` from the entity PK.
- [x] 6.2 Document in module docstring: "This module is the wire-format contract between the trading bounded context and risk (K1) / approval (P1) / observability (O1). Subscribers in those contexts MUST treat field types as frozen; additions go in `metadata: dict`. Genuine structural changes require a deliberate cross-context PR."
- [x] 6.3 Add a `__all__ = [...]` listing all 8 event classes for clean re-export from `contexts.trading.__init__`.

## 7. Tests

- [x] 7.1 Create `apps/api/tests/unit/contexts/trading/test_ports_protocol_conformance.py`: assert a stub `_StubBroker` matching `BrokerPort` shape passes `isinstance(_StubBroker(), BrokerPort)`; assert a `_BrokenBroker` missing `cancel_order` fails `isinstance` (or fails mypy in a `# type: ignore` xfail). Same for `StrategyPort`.
- [x] 7.2 Create `apps/api/tests/unit/contexts/trading/test_service_orchestration.py`: pytest-asyncio + an in-memory `MessageBus`. Test `propose()` emits `ProposalCreated` with the right payload. Test that `execute_on_approval_handler` calls `BrokerPort.place_order` exactly once when `ProposalApproved` is published twice with the same idempotency key (slice 2 idempotency contract).
- [x] 7.3 Create `apps/api/tests/unit/contexts/trading/test_events_emission.py`: assert each event class's `event_name` matches the `<context>.<entity>.<action>` convention; assert `tenant_id` is a required field (mypy + Pydantic-style validation if used); assert `metadata` defaults to empty dict.
- [x] 7.4 Create `apps/api/tests/unit/contexts/trading/test_repository_filters_tenant.py`: set `tenant_id_var` to tenant-A; INSERT a proposal under tenant-A; switch `tenant_id_var` to tenant-B; assert `TradeProposalRepository(session).get(id_from_A)` returns `None`. Mirrors slice-3 cross-tenant test pattern.
- [x] 7.5 Create `apps/api/tests/integration/test_trading_route_stubs.py`: pytest-asyncio + httpx `ASGITransport` client. Test each of the ~10 stub endpoints returns `501 Not Implemented` with `application/problem+json` body whose `type` is `urn:iguanatrader:error:not-implemented` and `detail` mentions slice T4. Authentication required (use the slice-4 login fixture).
- [x] 7.6 Create `apps/api/tests/integration/test_trading_migration.py`: fixture creates a fresh SQLite DB. Run `alembic upgrade head` against `versions/` containing `0001 + 0002_users_role_enum + 0002_research_tables + 0003_trading_tables`. Assert all tables exist, FK `trade_proposals.research_brief_id → research_briefs.id` is enforced (INSERTing a proposal with a bogus brief_id raises IntegrityError). Assert `alembic downgrade -1` drops the trading tables. Assert that running `upgrade head` with R1's migration absent raises a `RevisionError` (merge-order gate).
- [x] 7.7 Create `apps/api/tests/integration/test_append_only_listener_trading.py`: assert UPDATE on `trade_proposals.reasoning` raises `AppendOnlyViolationError`; assert UPDATE on `trades.state` from `"open"` to `"closed_filled"` succeeds (whitelist); assert UPDATE on `trades.symbol` raises (not in whitelist).

## 8. Documentation

- [x] 8.1 Append to `docs/gotchas.md`: gotcha #31 — "Trading routes return 501 until slice T4 lands; frontend (W1) MUST check the `Problem.type` URI `urn:iguanatrader:error:not-implemented` and render 'Coming soon' rather than treating as a real error." Gotcha #32 — "Cross-slice FK `trade_proposals.research_brief_id → research_briefs.id` requires R1 merged before T1; alembic `down_revision='0002_research_tables'` is the linear-chain anchor. Document the merge-order constraint in any T1 PR."
- [x] 8.2 Update `docs/data-model.md` cross-reference: add a stub note next to the `equity_snapshots.snapshot_kind` enum row pointing to §7.2 ("authoritative enum is `('event','minute','daily')`; slice-T1 migration uses §7.2"). Out of strict scope but a one-line correction prevents drift.
- [x] 8.3 Add `docs/runbooks/trading-event-replay.md`: operator playbook for replaying trading events from `audit_log` if a downstream subscriber crashed mid-handler — mention slice-2 `MessageBus` is in-process (no durable queue), so replay is from DB, not from the bus. Slice O1 + O2 will refine; T1 plants the skeleton.

## 9. Pre-merge verification

- [ ] 9.1 `mypy --strict apps/api/src/iguanatrader/contexts/trading/ apps/api/src/iguanatrader/api/dtos/trades.py apps/api/src/iguanatrader/api/dtos/proposals.py apps/api/src/iguanatrader/api/routes/{trades,portfolio,strategies,proposals}.py` clean.
- [ ] 9.2 `pytest apps/api/tests/unit/contexts/trading/ apps/api/tests/integration/test_trading_route_stubs.py apps/api/tests/integration/test_trading_migration.py apps/api/tests/integration/test_append_only_listener_trading.py` all green.
- [ ] 9.3 Coverage on `apps/api/src/iguanatrader/contexts/trading/` ≥ 80% (per NFR-M1; slice-O1 will wire `--cov-fail-under` enforcement).
- [ ] 9.4 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (gitleaks + ruff + black + mypy + eslint + prettier + openapi-typescript regen + license-boundary-check).
- [ ] 9.5 Manual smoke: bring up `python -m iguanatrader.api`, GET `/openapi.json`, confirm 4 new route prefixes (`/api/v1/trades`, `/api/v1/portfolio`, `/api/v1/strategies`, `/api/v1/proposals`) and the 6 new DTO schemas (Trade, Order, Fill, EquitySnapshot, StrategyConfig, Proposal) are present. GET `/api/v1/trades` (with auth cookie) returns 501 + Problem body.
- [ ] 9.6 Verify `alembic upgrade head` + `alembic downgrade -1` + `alembic upgrade head` cycle on a fresh DB succeeds (idempotency smoke).
- [ ] 9.7 PR description includes "AI-reviewer signoff" subsection per release-management.md §4.5; document merge-order checkbox `[ ] R1 (research-bitemporal-schema) merged into main before this PR is merged`.
- [ ] 9.8 Verify the slice-5 OpenAPI typegen workflow fires on push and bot-commits the regenerated `packages/shared-types/src/index.ts` containing the new trading interfaces.
