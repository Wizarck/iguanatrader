## Context

Slice T3 is the **first concrete strategy implementation** in iguanatrader. It plants two strategies (`DonchianATRStrategy` v0 MVP + `SMACrossStrategy` sanity-check) and the inheritance contract — `Strategy` ABC enforcing no-lookahead — that every future strategy must extend. The slice is downstream of T1 (which declared the `StrategyPort` Protocol + ORM tables) and parallel to T2 (IBKR adapter), R2 (historical bar adapters), R5 (research-brief synthesizer). T3 has no runtime coupling to T2 or R2 — strategies are pure functions of `BarHistory` + `StrategyConfigSnapshot`; the bar source is injected upstream by `TradingService` (T4). T3 uses an in-memory `FakeHistoricalBarAdapter` for tests so it doesn't block on R2's adapter delivery.

The challenge is **the no-lookahead invariant**. In algorithmic trading, the silent killer of every backtest is a strategy that inadvertently peeks at bar N+1 to decide bar N's signal — sometimes via off-by-one indexing (`bars[-1]` instead of `bars[-2]`), sometimes via a closure capturing future state (`compute_signal` calls a helper that re-reads the bar list), sometimes via timezone confusion (a "today's" bar that is actually tomorrow in UTC). Such bugs survive paper trading (where the bot trains on its own past) and surface only in live trading, often at significant capital cost. iguanatrader closes the entire class of bugs by **physically not giving the strategy author access to the current bar**: the abstract `Strategy.compute_signal(bars)` wrapper slices `bars` to `bars[:-1]` before delegating to subclass-implemented `_compute_signal_impl(history)`. The subclass author cannot peek at `bars[-1]` because it is not in `history`. A property-based test (Hypothesis) certifies the guarantee on every CI run for every registered strategy: signal at bar N from `bars[0..N]` must equal signal at bar N from `bars[0..N+M]` for any M>0.

The second design tension is **Decimal-vs-numpy arithmetic**. Money + sizing paths MUST use `Decimal` (project hard rule, `docs/data-model.md §money-types`). But indicator math (rolling max, ATR, SMA, std-dev) over O(100k) bars in `Decimal` is too slow (~50× the numpy equivalent). The compromise: indicator computation runs in `numpy` at the strategy's internal boundary; the result (a single scalar — current ATR, current SMA, current rolling-max) is converted to `Decimal` *before* it enters the `Proposal` construction. Each strategy declares `_to_decimal(np_value)` helper and uses it at every numpy-Decimal boundary; mypy's `numpy.typing.NDArray` annotations + a custom ruff rule (slice-2 lint) flag any leakage of `np.float64` into `Proposal` fields. ATR warmup period is the related gotcha: `ATR(14)` is undefined for the first 14 bars; the wrapper's `_validate_history` returns False when `len(history) < required_warmup`, short-circuiting to `None`.

The third tension is **manager orchestration with hot-reload**. T1's `StrategyConfigRepository.upsert` bumps the row's `version` column on every UPDATE. The manager must detect this and rebuild its cached strategy instance with new params *without* a process restart (FR4). The manager keeps a `dict[strategy_config_id, tuple[Strategy, int]]` cache; on every dispatch, it checks `current_version == cached_version`; mismatch → rebuild. The race condition (config change during `compute_signal` execution) is acceptable: the in-flight call uses the old params; the next call uses the new ones. Documented in D4 below.

Slice 5's contract is consumed unchanged: no new routes, no new SSE, no new CLI commands. T3 is pure infra inside the trading bounded context. T4 will surface management endpoints later.

## Goals / Non-Goals

**Goals:**

- Plant `Strategy(ABC)` in `contexts/trading/strategies/base.py` enforcing no-lookahead structurally — the wrapper `compute_signal` slices `bars` to `bars[:-1]` before delegating to abstract `_compute_signal_impl(history)`. Subclass authors physically cannot read the current bar.
- Implement `DonchianATRStrategy` (v0 MVP, long-only, breakout 20d high + ATR(14) stop, position sized by `risk_pct * equity / (entry - stop)`).
- Implement `SMACrossStrategy` (long-only, SMA(50) > SMA(200), volatility-sized) as a sanity-check strategy verifying the manager handles >1 active strategy per tenant.
- Plant `StrategyManager` per-tenant: reads `strategy_configs` via T1's repository, instantiates enabled strategies, dispatches `compute_signal`, aggregates per-strategy outputs (long-only intersection v0), hot-reloads on `version` bump.
- Plant `config/strategies.yaml.template` with documented defaults; loaded by manager on first-tenant bootstrap.
- Plant the **CI-blocking property test** `test_strategy_no_lookahead.py` certifying the invariant for every registered strategy — Hypothesis-based, ≥100 examples per strategy.
- Provide unit tests for entry/exit/sizing per strategy; integration test for manager + 2 strategies + mock bars.
- Maintain Decimal arithmetic at every money-touching boundary; numpy is allowed only inside indicator math, with explicit `_to_decimal(np_value)` conversion at the boundary.

**Non-Goals:**

- No additional strategies beyond the two v0 (mean-reversion, pairs, options, sentiment, RL — all post-MVP).
- No backtest engine or harness (deferred to T-track v3 per Gate A amendment 2026-04-28).
- No LLM-driven strategy DSL or generation.
- No portfolio-level capital allocation across strategies (manager v0 uses long-only intersection; post-MVP can introduce regime-detection, weighted aggregation).
- No API routes / CLI subcommands / frontend pages for strategy management (T4 owns).
- No research-brief enrichment in `Proposal.reasoning` (R5 + T4 own).
- No no-lookahead enforcement at the indicator-library level (e.g., custom future-blind numpy wrapper). The bar-slice at the contract layer is sufficient.
- No real `HistoricalBarPort` adapter (R2 owns; T3 uses `FakeHistoricalBarAdapter` for tests).

## Decisions

### D1. `Strategy(ABC)` wrapper enforces no-lookahead by slicing `bars` to `bars[:-1]` before delegating to `_compute_signal_impl(history)`

**Decision**: `apps/api/src/iguanatrader/contexts/trading/strategies/base.py` declares:

```python
class Strategy(ABC):
    """Abstract base for all strategies — enforces no-lookahead invariant.

    Subclasses implement ``_compute_signal_impl(history)`` ONLY. The
    wrapper ``compute_signal(bars)`` slices ``bars`` to ``bars[:-1]``
    before delegation; the subclass author cannot read ``bars[-1]``.
    """

    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def version(self) -> str: ...

    @abstractmethod
    def _compute_signal_impl(
        self,
        history: BarHistory,
        config: StrategyConfigSnapshot,
        equity: Decimal,
    ) -> Proposal | None: ...

    def compute_signal(
        self,
        bars: BarHistory,
        config: StrategyConfigSnapshot,
        equity: Decimal,
    ) -> Proposal | None:
        if len(bars.bars) < 2:
            return None  # need at least one history bar + one current
        history = BarHistory(symbol=bars.symbol, bars=bars.bars[:-1])
        if not self._validate_history(history):
            log.info("trading.strategy.no_signal", reason="insufficient_history", ...)
            return None
        proposal = self._compute_signal_impl(history, config, equity)
        if proposal is None:
            log.info("trading.strategy.no_signal", ...)
            return None
        log.info("trading.strategy.evaluated", signal_kind="proposal", ...)
        return proposal

    def _validate_history(self, history: BarHistory) -> bool:
        # default: subclass overrides for warmup-period checks
        return len(history.bars) > 0
```

The contract: **"predict bar N+1 using bars[0..N]"**. The current bar `bars[-1]` is the bar whose signal we are computing; the strategy receives bars[0..N-1] = `bars[:-1]` = `history`. The strategy's job is to look at the historical bars and decide whether the *next* bar (the current one, which it cannot see) should trigger an entry/exit.

**Why slice in the wrapper, not document and trust**:

- **Documentation alone is insufficient**: every strategy author would have to remember the invariant; a single off-by-one slip silently breaks production.
- **Slicing physically denies access**: the subclass cannot peek at the current bar because it does not have it.
- **The contract is testable**: the property test feeds `bars[0..N]` and `bars[0..N+M]` to the *wrapper* (not the subclass) and asserts identical output. Because the wrapper slices `[-1]` off, the subclass sees `bars[0..N-1]` in the first call and `bars[0..N+M-1]` in the second; the assertion is "the proposal at bar N is the same regardless of how many future bars are appended" — which is exactly the no-lookahead guarantee.

**Alternatives considered**:

- **Trust + document**: rejected — silent killer.
- **Static-analysis rule (custom mypy plugin) detecting `bars[-1]` usage**: too brittle (false positives on bars unrelated to the bar-list; misses indirect access via helpers).
- **Wrap each indicator function**: indicator-library scope creep; the strategy boundary is the right enforcement point.
- **Two methods (`compute_entry`, `compute_exit`)**: doubles the API surface; same enforcement issue.

**Rationale**: physical denial > documentation. One enforcement point at the abstract class.

### D2. `DonchianATRStrategy` v0 — 20-day high breakout entry; ATR(14)-based 2× stop; position sized by `risk_pct * equity / (entry - stop)`

**Decision**: `apps/api/src/iguanatrader/contexts/trading/strategies/donchian_atr.py` declares:

```python
class DonchianATRStrategy(Strategy):
    """Donchian channel breakout + ATR-based stop. Long-only v0.

    Defaults: lookback=20, atr_period=14, atr_mult=Decimal("2.0"),
    risk_pct=Decimal("0.01") (1%), warmup=20.
    """

    def name(self) -> str: return "donchian_atr"
    def version(self) -> str: return "1.0.0"

    def _validate_history(self, history: BarHistory) -> bool:
        lookback = self._lookback(history.config)  # from params
        return len(history.bars) >= max(lookback, 14)

    def _compute_signal_impl(
        self, history: BarHistory, config: StrategyConfigSnapshot, equity: Decimal
    ) -> Proposal | None:
        # numpy work
        closes = np.array([float(b.close) for b in history.bars])
        highs = np.array([float(b.high) for b in history.bars])
        lows = np.array([float(b.low) for b in history.bars])
        lookback = config.params.get("lookback", 20)
        atr_period = config.params.get("atr_period", 14)
        atr_mult = Decimal(str(config.params.get("atr_mult", "2.0")))
        risk_pct = Decimal(str(config.params.get("risk_pct", "0.01")))

        rolling_max = highs[-lookback:].max()
        last_close = closes[-1]
        last_high = highs[-1]

        atr_np = self._compute_atr(highs, lows, closes, period=atr_period)
        atr = self._to_decimal(atr_np)

        # Entry condition: last bar's high broke the rolling max
        if last_high < rolling_max:
            return None

        # Sizing: risk_pct of equity divided by stop distance
        entry = self._to_decimal(last_close)
        stop = entry - atr_mult * atr
        if stop >= entry:
            return None  # invalid; should never happen but defensive
        risk_per_share = entry - stop
        quantity = (risk_pct * equity / risk_per_share).quantize(Decimal("0.0001"))
        if quantity <= 0:
            return None

        return Proposal(
            tenant_id=config.tenant_id,
            strategy_config_id=config.id,
            symbol=history.symbol,
            side="buy",
            quantity=quantity,
            entry_price_indicative=entry,
            stop_price=stop,
            confidence_score=None,  # v0 leaves None
            reasoning={
                "signal_source": f"donchian_breakout_{lookback}d_high",
                "sizing_rationale": f"risk_pct={risk_pct} * equity / (entry - stop)",
                "stop_placement": f"entry - {atr_mult} * ATR({atr_period})",
                "rolling_max": str(self._to_decimal(rolling_max)),
                "atr": str(atr),
            },
            mode=config.params.get("mode", "paper"),
            correlation_id=uuid4(),
            research_brief_id=None,
        )
```

**Defaults** (per docs/prd.md FR1-FR5 + research note):

- `lookback = 20` (Donchian channel period — well-studied default).
- `atr_period = 14` (Wilder's standard ATR window).
- `atr_mult = Decimal("2.0")` (Turtle Traders 2N stop).
- `risk_pct = Decimal("0.01")` (1% of equity per trade).
- `warmup = max(lookback, atr_period) = 20`.

**Key invariant**: `entry > stop` (long-only); the strategy returns None if violated. The Decimal arithmetic ensures sizing precision; numpy handles the rolling-window math.

**Alternatives considered**:

- **Long + short**: out of scope for v0; short adds margin/borrow complexity.
- **Trailing stop** (instead of fixed at entry): post-MVP enhancement.
- **Donchian channel exits** (break of N-day low): post-MVP; v0 stop is ATR-based.
- **Fractional sizing rounding to broker lot size**: T2 / T4 layer concern; T3 returns Decimal quantity, T4 rounds to broker-permitted increment.

**Rationale**: Donchian + ATR is canonical; well-tested in the academic + practitioner literature; cleanly maps onto the StrategyPort contract.

### D3. `SMACrossStrategy` — SMA(50) > SMA(200) entry, volatility-sized — exists to exercise the manager with >1 strategy

**Decision**: `apps/api/src/iguanatrader/contexts/trading/strategies/sma_cross.py` declares an `SMACrossStrategy(Strategy)` whose entry condition is `SMA(fast) > SMA(slow)` (and ideally crosses just turned positive — `prev_fast <= prev_slow AND curr_fast > curr_slow`). Sizing uses rolling std-dev of returns (volatility) instead of ATR: `quantity = risk_pct * equity / (k * volatility * entry)`, where `k` is a configurable scaling factor (default 1.0). Defaults: `fast=50, slow=200, vol_window=20, risk_pct=0.01, k=1.0`. Same warmup-period validation pattern.

**Why this strategy**: it is **deliberately different** from Donchian — different indicator (SMA vs rolling-max), different sizing approach (vol-based vs ATR-based), different param schema (fast/slow/vol_window vs lookback/atr_period/atr_mult). If the manager handles both correctly, it has demonstrated coverage of orthogonal strategy families; future strategies (mean-reversion, momentum, etc.) extend the manager's range without requiring its rewrite.

**Alternatives considered**:

- **Same family as Donchian (e.g., 50d high)**: doesn't stress the manager; one strategy in one family is the same as one strategy.
- **A more interesting second strategy (e.g., RSI mean-reversion)**: post-MVP. v0's job is sanity-check, not breadth.

**Rationale**: SMA-cross is the "hello world" of trend strategies; it is well-understood, easy to test, and orthogonal in mechanism to Donchian.

### D4. `StrategyManager` — per-tenant, hot-reloads on `strategy_configs.version` bump, aggregates per-strategy proposals via long-only intersection

**Decision**: `apps/api/src/iguanatrader/contexts/trading/strategies/manager.py` declares:

```python
class StrategyManager:
    """Per-tenant orchestrator of active strategies.

    On every `dispatch(symbol, bars, equity)` call:
      1. Load active strategy_configs for this tenant (cached per
         dispatch; refreshed if version bumped).
      2. Instantiate or reuse the cached Strategy instance per
         strategy_config_id.
      3. Run compute_signal on each strategy.
      4. Aggregate proposals (v0: long-only intersection — return the
         first non-None Proposal; if any strategy returns a SELL/exit
         signal for the same symbol, return None for safety).
    """

    def __init__(self, repo: StrategyConfigRepository):
        self._repo = repo
        self._cache: dict[UUID, tuple[Strategy, int]] = {}

    def dispatch(
        self, symbol: str, bars: BarHistory, equity: Decimal
    ) -> Proposal | None:
        configs = self._repo.list_active(tenant_id_var.get(), symbol=symbol)
        proposals: list[Proposal] = []
        for cfg in configs:
            strategy = self._get_or_build(cfg)
            snapshot = StrategyConfigSnapshot(...)  # from cfg
            proposal = strategy.compute_signal(bars, snapshot, equity)
            if proposal is not None:
                proposals.append(proposal)
        return self._aggregate(proposals)

    def _get_or_build(self, cfg: StrategyConfig) -> Strategy:
        cached = self._cache.get(cfg.id)
        if cached and cached[1] == cfg.version:
            return cached[0]
        strategy = STRATEGY_REGISTRY[cfg.strategy_kind](**cfg.params)
        self._cache[cfg.id] = (strategy, cfg.version)
        return strategy

    def _aggregate(self, proposals: list[Proposal]) -> Proposal | None:
        # v0: long-only intersection. Return first BUY proposal; abort on any SELL.
        if not proposals:
            return None
        if any(p.side == "sell" for p in proposals):
            return None  # conflict — safer to abstain
        return proposals[0]  # first wins; v0 simplification
```

**Hot-reload contract** (FR4):

- `_get_or_build` checks `cached_version == cfg.version`. If the operator runs `/override risk_pct 0.005` (P1's command → `StrategyConfigRepository.upsert` → bumps `version`), the next `dispatch` call sees the version mismatch and rebuilds the strategy instance with the new params.
- **Race**: a config change *during* an in-flight `compute_signal` call. The in-flight call uses the stale params; the next call uses the new. Acceptable per FR4 wording ("hot-reload without restart" — does not require atomic replacement mid-evaluation).

**Aggregation v0** (long-only intersection):

- If at least one active strategy returns a non-None BUY Proposal AND no active strategy returns a SELL/exit signal: return the first BUY proposal.
- If any active strategy returns a SELL: abstain (return None) — safer to skip than to hold a conflicting position.
- If all active strategies return None: return None (no signal).

**Alternatives considered**:

- **Average sizing across strategies**: post-MVP — requires capital allocation logic.
- **Weighted aggregation by strategy confidence**: requires confidence scores (v0 leaves them None).
- **Each strategy gets independent capital allocation (separate Proposals, separate executions)**: post-MVP; T4's daemon can choose to run them as parallel pipelines.
- **Atomic mid-evaluation reload**: too complex; FR4 wording doesn't require it.

**Rationale**: long-only intersection is the safest v0; future slices can introduce richer aggregation policies without changing the manager's contract.

### D5. Decimal vs numpy: indicator math runs in numpy; conversion happens at the strategy boundary via `_to_decimal(np_value)` helper

**Decision**: every strategy declares a `_to_decimal(np_value: np.floating | float) -> Decimal` helper:

```python
@staticmethod
def _to_decimal(value: np.floating | float) -> Decimal:
    """Convert a numpy scalar to Decimal at the boundary."""
    return Decimal(str(float(value))).quantize(Decimal("0.00000001"))
```

Used at every numpy → Decimal transition. Strategies MUST NOT pass `np.float64` directly into `Proposal` fields. The custom ruff rule (slice-2 lint, `no-numpy-money`) flags any assignment of `np.float64` to a `Decimal`-typed attribute or function arg; the rule's exemption list includes the `_to_decimal` helper line so the conversion itself is allowed.

**Quantization precision**: `Decimal("0.00000001")` (8 decimal places) for prices + ATR. For position size: `Decimal("0.0001")` (4 decimal places — finer than any plausible broker lot increment; T4 rounds to broker-permitted minimum).

**Why not all-Decimal**:

- Decimal-only ATR over 100k bars is ~50× slower than numpy. Over 10 strategies × N tenants × per-bar dispatch, the latency budget is real.
- The numpy → Decimal conversion at the boundary is a single call per indicator-output; the precision loss is bounded (Decimal(str(float(x))) preserves all the precision a float64 carries, ~15 significant digits — well within the precision needed for prices in [0.01, 100000]).

**Alternatives considered**:

- **All-Decimal indicator math**: rejected on perf grounds.
- **All-float indicator math + late Decimal conversion** (no `_to_decimal` helper, just `Decimal(str(x))` inline): the helper centralizes the quantization choice; if we change precision across the codebase, one edit instead of ~40.
- **Use `numpy.financial` decimal types**: the library is unmaintained.

**Rationale**: numpy for speed inside, Decimal at the boundary, helper for centralization.

### D6. Property test `test_strategy_no_lookahead.py` — Hypothesis-driven, ≥100 examples per strategy, CI-blocking

**Decision**: `apps/api/tests/property/test_strategy_no_lookahead.py` declares:

```python
from hypothesis import given, strategies as st, settings

@settings(max_examples=100, deadline=2000)
@given(
    bars=hypothesis_bar_history_strategy(min_bars=200, max_bars=500),
    extra_bars=st.integers(min_value=1, max_value=50),
    strategy_class=st.sampled_from([DonchianATRStrategy, SMACrossStrategy]),
    params=hypothesis_param_strategy(),  # per-strategy param ranges
)
def test_no_lookahead(bars, extra_bars, strategy_class, params):
    strategy = strategy_class(**params)
    config = make_config_snapshot(params)
    equity = Decimal("100000")

    # Compute signal at bar N=last from bars[0..N]
    proposal_short = strategy.compute_signal(bars, config, equity)

    # Now extend bars with `extra_bars` random future bars
    extended = extend_history(bars, extra_bars)

    # Compute signal at the SAME bar N (now bars_extended[:-extra_bars]) — must match
    truncated = BarHistory(
        symbol=extended.symbol,
        bars=extended.bars[:len(bars.bars)],
    )
    proposal_long = strategy.compute_signal(truncated, config, equity)

    assert proposals_equal(proposal_short, proposal_long), (
        "Lookahead detected: proposal changed when future bars were added"
    )
```

`hypothesis_bar_history_strategy` generates synthetic OHLCV with realistic invariants: `low <= min(open, close)`, `high >= max(open, close)`, monotone timestamps, no NaN; volatility profiles vary across examples. `hypothesis_param_strategy` generates random parameters within each strategy's documented ranges (e.g., `lookback ∈ [10, 50]`, `atr_period ∈ [7, 28]`).

**CI gate**: the test is in `tests/property/` which slice 2 declares CI-blocking via `pytest -m property`. Failure on PR blocks merge.

**Alternatives considered**:

- **Manual unit tests with hand-crafted bar sequences**: insufficient coverage; misses the long tail of edge cases Hypothesis catches.
- **Smaller `max_examples`**: 100 is the slice-2 default for `--hypothesis-profile=ci`; lowering trades coverage for speed.
- **Including a dev profile that runs more (1000+)**: slice-2 declares `--hypothesis-profile=dev` for local runs; CI runs the smaller. Cited in tasks.md group 6.

**Rationale**: Hypothesis is the canonical Python property-testing library; slice 2 already declares it as the project standard; this slice extends the pattern to strategy invariants.

## Risks / Trade-offs

- **[Risk] Numpy → Decimal conversion loses precision in extreme cases (e.g., ATR of a synthetic price ladder where consecutive bars differ by 1e-10)** — the `Decimal(str(float(x)))` path inherits float64's ~15-digit precision; below that, you lose information. **Mitigation**: realistic price levels (≥$0.01, typically) keep the lost precision below the broker's quoted-price granularity, so the loss is invisible. The ruff rule `no-numpy-money` flags the pattern; the helper centralizes the quantization. Documented in `gotchas.md` entry T3-1.

- **[Risk] Hypothesis-generated bar sequences hit pathological cases the Donchian/SMA logic doesn't gracefully handle (e.g., constant prices, single-direction monotone, NaN sneaking through synthetic generation)** — strategy crashes mid-property-test, blocking CI. **Mitigation**: (a) `hypothesis_bar_history_strategy` validates invariants before yielding (no NaN, sane OHLC ordering, monotone timestamps, prices > 0); (b) `_validate_history` in each strategy short-circuits to None on insufficient bars or detected corruption; (c) the property-test asserts proposal equality, not non-Noneness — both calls returning None counts as identical (the invariant holds).

- **[Risk] ATR warmup period (`atr_period=14`) means the first 14 bars produce no signals — tests must use ≥20 bars; the property test's `min_bars=200` covers this** — but a real production deployment with insufficient historical bars at boot would silently emit no signals. **Mitigation**: T4's daemon checks bar-history depth at boot per active strategy; logs warning + skips dispatch if <warmup. T3's `_validate_history` returns False, the wrapper logs `trading.strategy.no_signal` with `reason="insufficient_history"`. Documented in `gotchas.md` entry T3-2.

- **[Risk] Pandas/numpy timestamp tz-awareness** — `Bar.timestamp: datetime` (T1's port type) is tz-aware UTC per project hard rule; numpy operations on `int64` ns-precision tz-naive timestamps would silently strip the tz. **Mitigation**: strategies do NOT use timestamps for math (only for ordering, which is preserved by sequence index). When timestamps are needed (e.g., for ATR's "true range" calculation that crosses session boundaries), the strategy converts via `pd.to_datetime(..., utc=True)` explicitly. Documented in `gotchas.md` entry T3-3. Slice 2's `iguanatrader.shared.time.utc_now` is the canonical clock.

- **[Risk] Signal-aggregation edge case: one strategy returns BUY, another returns HOLD (None), a third returns SELL** — manager v0 returns None (abstain) on any SELL. But what if SELL means "exit existing position" and BUY means "open new long"? V0 doesn't distinguish — both are coercion to Proposal.side. **Mitigation**: v0 manager's `Proposal.side` is restricted to "buy" only; "sell" Proposals from strategies are treated as exit signals at the manager-level, NOT as short entries. If an exit signal exists for the same symbol, manager abstains from new buy proposals (don't open while exit is pending). Post-MVP can introduce explicit signal-type taxonomy. Documented in D4 + tasks.md group 4.

- **[Risk] FR4 hot-reload race: config change mid-evaluation** — the in-flight `compute_signal` call uses stale params; the next call uses new. **Mitigation**: documented as acceptable per FR4 ("without restart"; not "atomic"). The race window is ~milliseconds (single bar evaluation); the next bar-tick uses the new params. No correctness violation — the proposal is always self-consistent w.r.t. the params it was computed with. Logged via `trading.strategy.config_reloaded` event for observability.

- **[Risk] R2 (historical bar adapters) ships in parallel; T3 uses `FakeHistoricalBarAdapter` for tests** — when R2 lands, T3's tests still pass (they use the fake) but the real adapter may surface issues. **Mitigation**: T4's integration tests (separate slice) use the real R2 adapter; T3's tests use the fake to remain isolated from R2's delivery schedule. Documented in proposal "Affected dependencies".

- **[Trade-off] Two strategies feels light for "Wave 3 unblock"** — but the slice's headline is the no-lookahead invariant + the ABC contract, not strategy breadth. Future slices add strategies cheaply (each is ~150 LOC inheriting the Strategy ABC, automatically inheriting the no-lookahead guarantee + the property test).

- **[Trade-off] Manager aggregation v0 (long-only intersection) is restrictive** — if a tenant runs Donchian + SMA, both must agree (or the only strategy emitting a signal must be alone in its decision) for a Proposal to flow. V0 is intentionally conservative; the alternative (each strategy independently emits Proposals → multiple positions per symbol) requires capital-allocation logic that is post-MVP.

## Migration Plan

This slice plants pure-infra files inside the trading bounded context; no DB migration, no API surface change, no operational rollout.

1. **Confirm T1 is on `main`**: archived 2026-05-06; `StrategyPort`, `StrategyConfigSnapshot`, `Bar`, `BarHistory`, `Proposal`, `StrategyConfigRepository` all available.
2. **Add `numpy` runtime dep + `hypothesis` dev dep** to root `pyproject.toml` if not already present (likely already there via R1/R2 transitive). Regenerate `poetry.lock`.
3. **Plant the strategy files + tests** in the worktree.
4. **CI runs**: unit tests, property tests (`tests/property/test_strategy_no_lookahead.py`), integration test (`test_strategy_manager_with_mocks.py`). All must pass.
5. **Merge slice T3 to main**. Wave 3 unblocks T4 (which can now wire `TradingService.propose` to `StrategyManager.dispatch`).

**Rollback** = revert PR. No DB state, no API state — pure code revert.

## Open Questions

- **Q**: Should `Strategy._validate_history` be more granular — distinguishing "insufficient bars" from "corrupted bars (NaN, gap, negative price)"? **Tentative answer**: v0 returns False uniformly with a structured-log `reason` field (`"insufficient_history"`, `"corrupted_bar"`, `"negative_price"`); short-circuit to None either way. The reason is observable but doesn't gate the decision. Post-MVP can introduce harder enforcement (raise on corrupted; only short-circuit on insufficient).

- **Q**: `StrategyManager.dispatch` v0 returns at most one `Proposal` per call (long-only intersection); should it return `list[Proposal]` so multiple non-conflicting strategies can each contribute proposals? **Tentative answer**: v0 sticks with `Proposal | None` to keep the downstream `TradingService.propose` flow simple (one dispatch → one proposal → one approval cycle). Post-MVP can switch to list semantics when capital allocation logic lands.

- **Q**: Should the property test cover *both* `_compute_signal_impl` (subclass) AND `compute_signal` (wrapper), or only the wrapper? **Tentative answer**: only the wrapper. The wrapper is the public contract; the property test treats the subclass as a black box. Subclass-level unit tests cover indicator-math correctness; the wrapper's no-lookahead is the invariant.

- **Q**: `config/strategies.yaml.template` lives at the project root or under `apps/api/`? **Tentative answer**: project root `config/strategies.yaml.template` per `docs/openspec-slice.md` row T3 + `docs/project-structure.md` (configs are deployment-side, not API-side). The manager loads via `Path("config/strategies.yaml.template")` resolved relative to project root + `IGUANATRADER_CONFIG_DIR` env override.
