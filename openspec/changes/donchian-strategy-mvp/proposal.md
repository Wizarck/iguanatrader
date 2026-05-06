## Why

Slice T1 (`trading-models-interfaces`, archived 2026-05-06) just landed the trading bounded context skeleton — `BrokerPort`, `StrategyPort`, ORM models, migration `0003_trading_tables.py`, event contract, 501-stub routes. The contract for "what a strategy is" exists; **what does not exist is a single concrete strategy that satisfies it**. Without a real `StrategyPort` implementation, `TradingService.propose` cannot be exercised end-to-end, the manager-level dispatch path (FR1/FR2/FR4/FR11) has no consumer to validate, and the entire Wave-3 trading family (T2 IBKR adapter + T4 routes/daemon) has no concrete strategy to drive proposals through their pipelines. The point of slice T3 is to plant the **first end-to-end working strategy** — Donchian-channel breakout with ATR-based sizing — and to do so with the **no-lookahead invariant enforced at the contract layer**, so every future strategy automatically inherits the guarantee.

Donchian channels are the right choice for v0: they are well-studied (Turtle Traders 1980s lineage), simple (a single rolling-max indicator), observable (entry condition is human-readable: "today's high broke the 20-day max"), and don't require any LLM-side tooling — they exercise the entire infrastructure (strategy → proposal → risk → approval → broker → fill → equity) without coupling to research-domain dependencies. Sma-cross is added as a sanity-check second strategy: it exists solely to prove the manager (`StrategyManager`) handles >1 active strategy per tenant without coupling to Donchian-specific assumptions.

The no-lookahead invariant is **THE headline of this slice**. Lookahead bugs are the canonical silent killer of backtests + paper-to-live transitions: a strategy that "works" on historical data because it inadvertently peeked at future bars degrades catastrophically when run forward. iguanatrader sidesteps the entire class of bugs by **enforcing the invariant at the abstract base class** — the wrapper `Strategy.compute_signal(bars)` slices to `bars[:-1]` before delegating to `_compute_signal_impl(history)`; subclasses physically cannot read the current bar, no matter how badly they try. A property-based test (Hypothesis) certifies the guarantee on every CI run for every strategy, by generating random bar sequences + random params and asserting that signals computed at bar N are identical whether the strategy is shown bars[0..N] or bars[0..N+M] for arbitrary M>0. This is **NFR-R5 reliability** territory and the test is CI-blocking.

## What Changes

- **New abstract base `contexts/trading/strategies/base.py`** — `Strategy(ABC)` class implementing `StrategyPort` (T1's protocol). Defines the no-lookahead-enforcing wrapper `compute_signal(bars: BarHistory) -> Proposal | None` which slices bars to `bars[:-1]` then delegates to abstract `_compute_signal_impl(history: BarHistory) -> Proposal | None`. Subclasses implement `_compute_signal_impl` ONLY. Wrapper also handles structlog narration (`trading.strategy.evaluated`) + no-signal short-circuit (`trading.strategy.no_signal`). Defines abstract `name()`, `version()`, and concrete `_validate_history(history) -> bool` that returns False on insufficient bars or NaN/gap corruption, causing the wrapper to short-circuit to `None`.
- **New `contexts/trading/strategies/donchian_atr.py`** — `DonchianATRStrategy(Strategy)` v0 MVP. Long-only breakout: enter when `bars[-1].high >= max(bars[-lookback:].high)` (configurable `lookback`, default 20). Stop = `entry - atr_mult * ATR(atr_period)` (configurable `atr_mult` default 2.0, `atr_period` default 14). Position size = `risk_pct * equity / (entry - stop)` (Decimal arithmetic; `risk_pct` default 0.01 = 1%). Returns `Proposal | None`; never executes. ATR computed via numpy at the boundary, converted to `Decimal` before the Proposal is constructed.
- **New `contexts/trading/strategies/sma_cross.py`** — `SMACrossStrategy(Strategy)` v0 sanity-check. Long-only: enter when `SMA(50)` crosses above `SMA(200)`; exit signal when crosses below. Same `risk_pct * equity / volatility` sizing pattern, where volatility is the rolling standard deviation of returns (configurable `vol_window` default 20). Default params: `fast=50, slow=200, vol_window=20, risk_pct=0.01`.
- **New `contexts/trading/strategies/manager.py`** — `StrategyManager` per-tenant. Reads T1's `strategy_configs` table via `StrategyConfigRepository.list_active(tenant_id)`, instantiates each enabled strategy with its params, dispatches `compute_signal(bars)` calls, aggregates the per-strategy `Proposal | None` results (default aggregation: long-only intersection — proposal accepted only if at least one strategy returns a non-None Proposal AND no active strategy returns a SELL/exit signal). Hot-reload on `strategy_configs.version` bump (FR4): manager invalidates its cached strategy instance and rebuilds with new params.
- **New `contexts/trading/strategies/__init__.py`** — package marker; re-exports `Strategy`, `DonchianATRStrategy`, `SMACrossStrategy`, `StrategyManager` for clean imports.
- **New `config/strategies.yaml.template`** — declarative strategy config template with all default params + comments. Loaded by manager at boot for first-time-tenant bootstrap; subsequent runtime changes go through the DB (FR3 + FR4).
- **New property test `tests/property/test_strategy_no_lookahead.py`** — Hypothesis-driven CI-blocking test. For every registered strategy class, generate random `BarHistory` sequences (≥200 bars, varied volatility profiles, random params within strategy's declared param ranges); assert: signal at bar N computed from `bars[0..N]` equals signal at bar N computed from `bars[0..N+M]` for any M>0. Test runs both Donchian and SMA cross strategies. NFR-R5 invariant.
- **New unit + integration tests** — entry/exit/sizing unit tests per strategy; manager unit tests covering activation, hot-reload, multi-strategy aggregation; integration test wiring manager + 2 strategies + mock historical bars (R2's `HistoricalBarPort` mock — R2 ships in parallel; T3 uses an in-memory fake).
- **No new ORM models, no migration, no API routes, no daemon, no backtest engine** — every concrete plug-in lives in T4 (routes/daemon) or post-MVP (additional strategies, backtest harness).

## Capabilities

### New Capabilities

- `trading` (delta-spec; additions to T1's contract): introduces the **strategy abstraction layer** — `base.Strategy` ABC enforcing no-lookahead, two concrete strategies (`DonchianATRStrategy`, `SMACrossStrategy`), per-tenant `StrategyManager` orchestrating them, declarative yaml config bootstrap, property-test invariant for no-lookahead. Slice T1 declared the `StrategyPort` Protocol; slice T3 plants the implementations and the inheritance contract that future strategies extend.

### Modified Capabilities

(none — T1's `StrategyPort` is consumed unchanged via structural typing; the `Strategy` ABC declared here implements the Protocol but does not modify it. T1's `strategy_configs` table + `StrategyConfigRepository.upsert` are read unchanged.)

## Impact

- **Affected code (slice-T3-owned, write-allowed)**:
  - `apps/api/src/iguanatrader/contexts/trading/strategies/__init__.py` (NEW) — package marker + re-exports.
  - `apps/api/src/iguanatrader/contexts/trading/strategies/base.py` (NEW) — `Strategy(ABC)` with no-lookahead wrapper.
  - `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py` (NEW) — Donchian breakout v0 MVP.
  - `apps/api/src/iguanatrader/contexts/trading/strategies/sma_cross.py` (NEW) — SMA-cross sanity-check.
  - `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py` (NEW) — per-tenant orchestrator.
  - `config/strategies.yaml.template` (NEW) — declarative bootstrap template (loaded by manager).
  - `apps/api/tests/property/test_strategy_no_lookahead.py` (NEW) — CI-blocking Hypothesis invariant test.
  - `apps/api/tests/unit/contexts/trading/strategies/test_base.py` (NEW) — wrapper enforcement.
  - `apps/api/tests/unit/contexts/trading/strategies/test_donchian_atr.py` (NEW) — entry/exit/sizing.
  - `apps/api/tests/unit/contexts/trading/strategies/test_sma_cross.py` (NEW) — entry/exit/sizing.
  - `apps/api/tests/unit/contexts/trading/strategies/test_manager.py` (NEW) — activation/hot-reload/aggregation.
  - `apps/api/tests/integration/test_strategy_manager_with_mocks.py` (NEW) — manager + 2 strategies + mock bars.
- **Affected code (read-only consumed)**:
  - `iguanatrader.contexts.trading.ports.{StrategyPort, BarHistory, Bar, Proposal, StrategyConfigSnapshot}` — T1 contracts consumed unchanged via structural typing.
  - `iguanatrader.contexts.trading.repository.StrategyConfigRepository.list_active(tenant_id)` — manager consumes; helper added in T1 (or by T3 if T1 left empty body — verify with archived T1 spec). If T1 plants only `upsert`, T3 adds `list_active(tenant_id)` to its own repository in scope.
  - `iguanatrader.shared.{decimal_utils, time.utc_now, contextvars.tenant_id_var}` — slice-2 contracts consumed unchanged.
- **Affected APIs**: none directly. The strategies are invoked from `TradingService.propose` (T1's stubbed method); T4 wires the actual call chain. T3 plants the strategies; T4 invokes them.
- **Affected dependencies**:
  - **NEW dev dep**: `hypothesis>=6.100` — added to `[tool.poetry.group.dev.dependencies]` for the property test. Verify it isn't already in slice 2 or K1's `pyproject.toml`. If absent, regenerate `poetry.lock`.
  - **NEW runtime dep candidate**: `numpy>=1.26` — used inside indicator math (rolling max, ATR, SMA, std-dev). Decimal at the strategy boundary; numpy internally for performance. If `numpy` is already a transitive dep (e.g., via `pandas` from R1/R2), no new declaration needed. Otherwise add to runtime deps. The strategy MUST convert numpy → Decimal at the boundary before constructing `Proposal`.
- **Prerequisites**:
  - **slice T1 `trading-models-interfaces` (archived 2026-05-06)**: provides `StrategyPort`, `Bar`, `BarHistory`, `Proposal`, `StrategyConfigSnapshot`, `StrategyConfig` ORM model + `strategy_configs` table + `StrategyConfigRepository`. T3 implements the `StrategyPort` contract; ORM/migration are unchanged.
  - **slice R1 `research-bitemporal-schema` (archived 2026-05-06)**: not a runtime dep for T3, but proposals carry `research_brief_id: UUID | None` (nullable per T1 D5); T3 leaves this NULL in the v0 strategies (research-domain enrichment is post-R5).
  - **slice R2 `research-edgar-fred-adapters` (parallel Wave 3)**: provides historical bar adapters via `HistoricalBarPort` (yfinance / IBKR bars). **R2 ships in parallel — T3 uses an in-memory `FakeHistoricalBarAdapter` for dev + integration tests**. When R2 lands, T4 (the daemon slice) wires the real adapter; T3 has no dependency on R2's runtime code.
- **Capability coverage** (per `docs/openspec-slice.md` row T3 + `docs/prd.md`):
  - **FR1** (list strategies + versions) → `Strategy.name()` + `Strategy.version()` returning the strategy kind + semver string per instance; manager exposes `list_active() -> list[Strategy]` for inspection.
  - **FR2** (enable/disable per symbol) → manager reads `strategy_configs.enabled` + `(symbol)`; only enabled rows are instantiated.
  - **FR3** (per-symbol params via yaml or runtime) → `config/strategies.yaml.template` provides the bootstrap defaults; runtime changes via `StrategyConfigRepository.upsert` (T1) bump `version`; manager hot-reloads on next `compute_signal` call.
  - **FR4** (hot-reload without restart) → manager checks `strategy_configs.version` on each dispatch; if mismatch, manager invalidates its cached strategy instance + rebuilds with new params. No process restart.
  - **FR5** (parameter override via approval channel) → no T3-side change needed; P1 (`approval-channels-multichannel`) wires the `/override` command to `StrategyConfigRepository.upsert`; manager picks up the change on next `compute_signal` via the FR4 path. T3 only verifies the manager's hot-reload path is robust to mid-evaluation version bumps.
  - **FR11** (proposals carry structured reasoning) → every `Proposal` returned from `_compute_signal_impl` populates `reasoning: dict` with: `signal_source` (e.g., `"donchian_breakout_20d_high"`), `sizing_rationale` (e.g., `"risk_pct=0.01 * equity / (entry - stop)"`), `stop_placement` (e.g., `"entry - 2.0 * ATR(14)"`), `confidence_score` (Decimal | None; v0 leaves None — confidence is research-domain output post-R5). Reasoning is a JSON-serializable dict; `TradeProposal.reasoning` (T1 column) accepts it.
  - **NFR-R5** (reliability — no-lookahead invariant) → property test `test_strategy_no_lookahead.py` is CI-blocking; failure on PR blocks merge.
  - **NFR-O8** (structlog narration) → wrapper emits `trading.strategy.evaluated` (with `strategy_kind`, `strategy_version`, `symbol`, `signal_kind`, `tenant_id`) and `trading.strategy.no_signal` (no-op path) per NFR-O8 convention.
- **Out of scope** (per `docs/openspec-slice.md` row T3):
  - **More strategies (mean-reversion, pairs, options, sentiment-driven)** — deferred to post-MVP. Adding a third strategy is a new slice.
  - **Backtest engine + harness** — deferred to T-track v3 per `docs/openspec-slice.md` row T3 + Gate A amendment 2026-04-28 (backtest mode removed from MVP). Strategies are runnable forward-only against live bars in v0.
  - **LLM-driven strategy generation, prompt-based strategy DSL, RL-based strategies** — deferred to post-MVP.
  - **Strategy selection / portfolio allocation across multiple strategies** — manager v0 uses long-only intersection; post-MVP can introduce regime-detection, weighted aggregation, capital allocation per strategy.
  - **API routes + CLI subcommands + frontend pages for strategy management** — slice T4 owns. T3 plants the strategies; T4 wires the management UI.
  - **Strategy reasoning enrichment via research briefs** — deferred to R5 + T4 integration. T3's `reasoning.research_brief_id` stays None.
  - **No-lookahead enforcement at indicator-library level** (forcing all indicators to use a "future-blind" wrapper) — out of scope; the wrapper's bar-slice is sufficient for the contract layer.

## Acceptance

- Two strategies (`DonchianATRStrategy`, `SMACrossStrategy`) implement `StrategyPort` via the `Strategy` ABC; `mypy --strict` accepts both.
- `StrategyManager` orchestrates ≥2 active strategies per tenant; activation, hot-reload (version bump), and aggregation all unit-tested.
- The CI-blocking property test `test_strategy_no_lookahead.py` runs ≥100 Hypothesis examples per strategy and PASSES — confirming the no-lookahead invariant for both v0 strategies.
- `config/strategies.yaml.template` exists with documented defaults; manager loads it on first-tenant bootstrap.
- Coverage ≥80% on all `contexts/trading/strategies/*` files (NFR-M1).
- All structlog events use `<context>.<entity>.<action>` per NFR-O8; all money + sizing paths use `Decimal` (no float for money).
