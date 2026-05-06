## ADDED Requirements

### Requirement: `Strategy(ABC)` abstract base implements `StrategyPort` and enforces no-lookahead via wrapper bar-slice

The system SHALL expose `iguanatrader.contexts.trading.strategies.base.Strategy` as an abstract base class implementing T1's `StrategyPort` Protocol. Subclasses SHALL implement abstract methods `name() -> str`, `version() -> str`, `_compute_signal_impl(history: BarHistory, config: StrategyConfigSnapshot, equity: Decimal) -> Proposal | None`. The concrete wrapper `compute_signal(bars: BarHistory, config: StrategyConfigSnapshot, equity: Decimal) -> Proposal | None` SHALL slice `bars.bars[:-1]` to construct `history` BEFORE delegating to `_compute_signal_impl`; subclass authors physically cannot read `bars[-1]` (the current bar). The wrapper SHALL invoke `_validate_history(history)` and short-circuit to `None` (with structlog `trading.strategy.no_signal` and `reason` field) when the validator returns False (insufficient bars, NaN/gap corruption, or any subclass-defined invalid condition). On non-None proposal, the wrapper SHALL emit `trading.strategy.evaluated` with `strategy_kind`, `strategy_version`, `symbol`, `signal_kind`, `tenant_id`, `entry_price`, `stop_price`, `quantity`.

#### Scenario: Subclass cannot access bars[-1] because the wrapper slices it off

- **WHEN** `Strategy.compute_signal(bars=10-bar BarHistory)` is called
- **THEN** `_compute_signal_impl(history, ...)` is invoked with `len(history.bars) == 9`
- **AND** the bar at original `bars.bars[-1]` is not present in `history.bars`
- **AND** the unit test `test_base.py::test_wrapper_slices_off_current_bar` asserts the slice via mock subclass introspection

#### Scenario: Validator-failure short-circuits to None with structured reason

- **WHEN** a subclass's `_validate_history` returns False (e.g., insufficient warmup)
- **THEN** the wrapper returns `None` without invoking `_compute_signal_impl`
- **AND** structlog event `trading.strategy.no_signal` is emitted with `reason="insufficient_history"` (or the subclass-provided reason via custom validator)
- **AND** the integration test asserts the early-return path on a 15-bar `BarHistory` with `donchian_atr` (warmup=20)

#### Scenario: Successful signal emits trading.strategy.evaluated with full payload

- **WHEN** `_compute_signal_impl` returns a non-None `Proposal`
- **THEN** the wrapper returns the same Proposal unmodified
- **AND** structlog event `trading.strategy.evaluated` is emitted with `strategy_kind`, `strategy_version`, `symbol`, `signal_kind="proposal"`, `tenant_id`, `entry_price`, `stop_price`, `quantity`
- **AND** the unit test asserts the event payload via structlog `caplog`-style capture

### Requirement: No-lookahead invariant is CI-blocking via property-based Hypothesis test on every registered strategy

The system SHALL ship `apps/api/tests/property/test_strategy_no_lookahead.py` as a CI-blocking pytest module (pytest marker `property`; included in `.github/workflows/ci.yml`'s default suite per slice 2's contract). The test SHALL use Hypothesis to generate, for each registered strategy class (`STRATEGY_REGISTRY`), random `BarHistory` sequences (≥200 bars, OHLC-coherent, monotone timestamps, no NaN, prices > 0) and random parameter dictionaries within each strategy's documented param ranges. For every example, the test SHALL: (1) compute a proposal from `bars[0..N]`; (2) extend `bars` by `extra_bars ∈ [1, 50]` random future bars; (3) truncate the extended sequence back to `bars[0..N]`; (4) recompute the proposal; (5) assert both proposals are equal (both None, or both non-None with identical `side`, `quantity`, `entry_price_indicative`, `stop_price`). Failure on PR SHALL block merge per NFR-R5.

#### Scenario: Property test catches a strategy that reads the current bar

- **GIVEN** a deliberately-broken `_LookaheadStrategy(Strategy)` that overrides `compute_signal` to read `bars[-1]` (bypassing the wrapper)
- **WHEN** the property test runs against `_LookaheadStrategy`
- **THEN** Hypothesis finds a counter-example where extending future bars changes the proposal
- **AND** the test fails loudly with the counter-example printed
- **AND** the meta-test `test_property_catches_lookahead_strategy` (pytest marker `property_meta`) asserts the failure as a regression guard

#### Scenario: CI runs property test with deterministic profile (100 examples)

- **WHEN** CI invokes `pytest -m property --hypothesis-profile=ci`
- **THEN** each registered strategy is exercised with exactly 100 Hypothesis examples
- **AND** each example completes in <2s (deadline=2000ms)
- **AND** the test PASSES for both `DonchianATRStrategy` and `SMACrossStrategy`

### Requirement: `DonchianATRStrategy` v0 — 20-day high breakout entry; ATR(14) 2× stop; risk-pct sized; long-only

The system SHALL expose `iguanatrader.contexts.trading.strategies.donchian_atr.DonchianATRStrategy(Strategy)` with `name() == "donchian_atr"` and `version() == "1.0.0"`. The default param schema is `{lookback: 20, atr_period: 14, atr_mult: Decimal("2.0"), risk_pct: Decimal("0.01")}` overridable via `StrategyConfig.params`. The strategy is **long-only**: it returns BUY-side `Proposal` only; it does NOT return SELL-side proposals (exit signals are out of scope for v0; positions held until external close). Entry condition: `bars[-1].high >= max(highs[-lookback:])` over the historical bars window. Stop price: `entry - atr_mult * ATR(atr_period)` where ATR uses Wilder smoothing. Position quantity: `risk_pct * equity / (entry - stop)` quantized to `Decimal("0.0001")`. The `Proposal.reasoning` dict SHALL contain keys `signal_source`, `sizing_rationale`, `stop_placement`, `rolling_max`, `atr` (all serializable as JSON; Decimal values stringified).

#### Scenario: Breakout entry produces correctly-sized BUY proposal

- **GIVEN** a 30-bar `BarHistory` for SPY where `max(highs[-20:]) = Decimal("400.00")` and `bars[-1].high = Decimal("400.50")` and `bars[-1].close = Decimal("400.25")`
- **GIVEN** `equity = Decimal("100000")` and default params (lookback=20, atr_mult=2.0, risk_pct=0.01)
- **WHEN** `DonchianATRStrategy().compute_signal(bars, config, equity)` is called
- **THEN** the returned `Proposal.side == "buy"`
- **AND** `Proposal.entry_price_indicative == Decimal("400.25")` (last close)
- **AND** `Proposal.stop_price == entry - Decimal("2.0") * atr` for the computed ATR
- **AND** `Proposal.quantity == Decimal("0.01") * Decimal("100000") / (entry - stop)` quantized to 0.0001
- **AND** `Proposal.reasoning["signal_source"] == "donchian_breakout_20d_high"`

#### Scenario: No breakout returns None

- **GIVEN** a 30-bar BarHistory where `bars[-1].high < max(highs[-20:])`
- **WHEN** `compute_signal` is called
- **THEN** the result is `None`
- **AND** structlog event `trading.strategy.no_signal` is emitted with `reason="no_breakout"` (or equivalent subclass reason)

#### Scenario: Insufficient warmup returns None

- **GIVEN** a 15-bar BarHistory and default params (lookback=20, atr_period=14, warmup=20)
- **WHEN** `compute_signal` is called
- **THEN** `_validate_history` returns False
- **AND** the wrapper returns `None` with `reason="insufficient_history"`

### Requirement: `SMACrossStrategy` — golden-cross entry, volatility-sized, sanity-check second strategy

The system SHALL expose `iguanatrader.contexts.trading.strategies.sma_cross.SMACrossStrategy(Strategy)` with `name() == "sma_cross"` and `version() == "1.0.0"`. Default params: `{fast: 50, slow: 200, vol_window: 20, risk_pct: Decimal("0.01"), k: Decimal("1.0")}`. Long-only. Entry condition: **golden cross** — `prev_fast <= prev_slow AND curr_fast > curr_slow` (the cross transition itself, NOT the post-crossed state). Position sizing: `quantity = risk_pct * equity / (k * volatility * entry)` where volatility is the std-dev of returns over `vol_window`. Stop price: `entry * (Decimal("1") - 2 * volatility / entry)` (~2-sigma below entry, documented as `"~2 standard deviations below entry"`).

#### Scenario: Golden cross fires exactly once on the cross bar

- **GIVEN** a 250-bar BarHistory where SMA(50) crosses above SMA(200) at bar index 230
- **WHEN** `compute_signal` is called with `bars[0..230]`
- **THEN** the result is a non-None BUY `Proposal` with the documented reasoning shape
- **AND** when `compute_signal` is called with `bars[0..231]` (post-cross, both fast > slow), the result is `None` (cross has already happened)

#### Scenario: Zero volatility (constant prices) returns None defensively

- **GIVEN** a 250-bar BarHistory with all bars at identical price
- **WHEN** `compute_signal` is called
- **THEN** the result is `None` (volatility=0 would divide by zero)
- **AND** structlog event `trading.strategy.no_signal` is emitted with `reason="zero_volatility"` (or equivalent)

### Requirement: Position sizing uses Decimal arithmetic; numpy is allowed only inside indicator math with `_to_decimal` boundary helper

The system SHALL enforce that every money-touching path (price, quantity, equity, stop distance, ATR scalar value) uses `Decimal`. Numpy arithmetic is permitted only inside indicator-computation helpers (rolling max, SMA, ATR, std-dev) operating on numpy arrays; the resulting scalar SHALL pass through a `_to_decimal(value: np.floating | float) -> Decimal` helper that quantizes to `Decimal("0.00000001")` (8 decimal places) before being assigned to any `Proposal` field. Direct assignment of `np.float64` (or `float`) to a `Decimal`-typed field SHALL be flagged by the project's `no-numpy-money` ruff rule (slice-2 lint); the only exempt line per strategy is the `_to_decimal` helper itself.

#### Scenario: Quantity is Decimal in the resulting Proposal

- **WHEN** any strategy returns a non-None `Proposal`
- **THEN** `type(proposal.quantity) is Decimal`
- **AND** `type(proposal.entry_price_indicative) is Decimal`
- **AND** `type(proposal.stop_price) is Decimal`
- **AND** the unit test enforces this via `isinstance` checks

#### Scenario: Direct numpy-to-Decimal-field assignment is flagged by ruff

- **WHEN** a developer writes `Proposal(quantity=np_quantity, ...)` (without going through `_to_decimal`)
- **THEN** `ruff check` reports the `no-numpy-money` violation on the assignment line
- **AND** the slice-2 lint rule's CI gate fails the PR

### Requirement: `StrategyManager` orchestrates active strategies per-tenant with hot-reload on `strategy_configs.version` bump

The system SHALL expose `iguanatrader.contexts.trading.strategies.manager.StrategyManager` constructed with a `StrategyConfigRepository`. The public method `dispatch(symbol: str, bars: BarHistory, equity: Decimal) -> Proposal | None` SHALL: (1) load active `strategy_configs` rows for `tenant_id_var.get()` (optionally filtered by symbol); (2) for each active config, instantiate or reuse a cached `Strategy` instance keyed by `strategy_config_id` with version-check hot-reload; (3) invoke `Strategy.compute_signal(bars, snapshot, equity)` on each; (4) aggregate proposals via long-only intersection (return first BUY if no SELL signals exist; abstain on any SELL; return None on all-None). On version mismatch between cached and current `strategy_configs.version`, the manager SHALL invalidate the cached instance, rebuild via `STRATEGY_REGISTRY[strategy_kind](**params)`, store with the new version, and emit `trading.strategy.config_reloaded` with `old_version`, `new_version`, `strategy_kind`, `tenant_id` — fulfilling FR4 hot-reload-without-restart.

#### Scenario: Hot-reload picks up new params on next dispatch after version bump

- **GIVEN** a tenant with one active `donchian_atr` config at version=1, params={lookback: 20}
- **GIVEN** the manager has dispatched once and cached the Strategy instance
- **WHEN** `StrategyConfigRepository.upsert(...)` updates params to {lookback: 10} and bumps version=2
- **AND** `manager.dispatch(...)` is called again
- **THEN** the manager detects `cached_version=1 != cfg.version=2`
- **AND** rebuilds the strategy with `lookback=10`
- **AND** emits structlog `trading.strategy.config_reloaded` with `old_version=1, new_version=2`
- **AND** the rebuilt strategy is used for the current dispatch

#### Scenario: Long-only intersection: BUY + SELL conflict abstains

- **GIVEN** two active strategies for SPY where strategy A returns BUY and strategy B returns a SELL/exit signal
- **WHEN** `manager.dispatch("SPY", bars, equity)` is called
- **THEN** the manager returns `None` (abstain — safer than executing one side of a conflict)
- **AND** the unit test asserts the abstention path

#### Scenario: Cross-tenant isolation: tenant B's strategies are not invoked when dispatching for tenant A

- **GIVEN** tenant A and tenant B both have active strategy configs for SPY
- **WHEN** `tenant_id_var` is set to tenant A
- **AND** `manager.dispatch("SPY", bars, equity)` is called
- **THEN** only tenant A's strategies are invoked (tenant B's are filtered by the slice-3 listener on `strategy_configs.list_active`)
- **AND** the integration test asserts via tenant-B strategy mocks that they receive zero invocations

### Requirement: `Proposal.reasoning` carries structured per-strategy explanation (FR11)

Every `Proposal` returned from a strategy's `_compute_signal_impl` SHALL populate the `reasoning: dict[str, Any]` field with at minimum the keys: `signal_source` (string identifier of the indicator/condition that fired), `sizing_rationale` (string describing the sizing formula applied), `stop_placement` (string describing how the stop was computed). Strategy-specific keys (e.g., `rolling_max`, `atr` for Donchian; `fast_sma`, `slow_sma`, `volatility` for SMA-cross) MAY be added. All values SHALL be JSON-serializable; Decimal values MUST be stringified (`str(Decimal)`); numpy values MUST NOT appear (use `_to_decimal` first).

#### Scenario: DonchianATRStrategy reasoning contains all required keys

- **WHEN** `DonchianATRStrategy.compute_signal(...)` returns a non-None Proposal
- **THEN** `proposal.reasoning` is a `dict[str, Any]` with keys `signal_source`, `sizing_rationale`, `stop_placement`, `rolling_max`, `atr`
- **AND** `proposal.reasoning["signal_source"] == "donchian_breakout_20d_high"` (or with the configured lookback)
- **AND** `json.dumps(proposal.reasoning)` succeeds (all values JSON-serializable)

#### Scenario: SMACrossStrategy reasoning contains all required keys

- **WHEN** `SMACrossStrategy.compute_signal(...)` returns a non-None Proposal
- **THEN** `proposal.reasoning` contains `signal_source`, `sizing_rationale`, `stop_placement`
- **AND** `proposal.reasoning["signal_source"]` describes the golden-cross condition (e.g., `"sma_cross_50_200_golden"`)

### Requirement: `config/strategies.yaml.template` declarative bootstrap is loaded by manager via Pydantic-validated schema

The system SHALL ship `config/strategies.yaml.template` at the repository root with documented default strategy entries for `donchian_atr` and `sma_cross` (both targeting SPY, both enabled, with the documented default params). The template SHALL be validated by a Pydantic model `StrategyConfigYAML` (in `manager.py` or a dedicated `config_schema.py`) on load. The `StrategyManager.bootstrap_from_yaml(path: Path, tenant_id: UUID) -> None` classmethod helper SHALL parse the file, validate it, and call `StrategyConfigRepository.upsert(...)` for each entry — idempotent (safe to invoke on already-bootstrapped tenants since `upsert` handles duplicates). The bootstrap is invoked on first-tenant-creation by T4's tenant-bootstrap CLI; runtime config changes go through DB upsert (FR3 + FR4).

#### Scenario: Template parses cleanly and bootstraps both strategies

- **WHEN** a fresh tenant is created and `StrategyManager.bootstrap_from_yaml(Path("config/strategies.yaml.template"), tenant_id)` is invoked
- **THEN** two `strategy_configs` rows are inserted: one for `donchian_atr` and one for `sma_cross`, both with `enabled=True`, `symbol="SPY"`, `version=1`, and the documented default params
- **AND** subsequent `manager.dispatch("SPY", ...)` calls instantiate both strategies

#### Scenario: Pydantic validation rejects an invalid template entry

- **GIVEN** a corrupted `strategies.yaml` with a malformed entry (e.g., missing required `kind` field, or `risk_pct: 1.5` exceeding the 1.0 cap if validation enforces param ranges)
- **WHEN** `bootstrap_from_yaml` is invoked
- **THEN** Pydantic raises `ValidationError` describing the offending field
- **AND** no `strategy_configs` rows are inserted (transactional integrity)
- **AND** the unit test asserts the validation failure
