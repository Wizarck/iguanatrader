## Context

Slice T2 plants the **only live-broker adapter for MVP** — every consumer of `BrokerPort` (slice T4's `service.py::execute_on_approval`, slice K1's kill-switch state machine, slice O1's cost meter narrating broker latency) consumes `IBKRAdapter` indirectly via T1's Protocol. The adapter has a small surface (5 methods on `BrokerPort` + a `connect()/disconnect()` lifecycle pair) but a large failure-mode surface: TWS Gateway crashes, network partitions, daylight-saving misalignments in execution timestamps, market-data subscription gating, paper vs live port confusion, idempotency holes when a partial-network-drop hides the broker's `OrderPlaced` ack from the client. This design freezes the resilience contract so K1 (kill-switch) + T4 (daemon) can build on top deterministically.

The library landscape: the original `ib-insync` (Patrick Erdelen) was archived by upstream in 2024 after the maintainer stepped back; the active maintained fork is `ib_async` on PyPI (MIT-licensed, same API surface, ongoing patches for newer TWS API versions). The matching mock library `ib-insync-mock` exists for the original; whether its mock works against `ib_async` is verified in D7 — if not, this slice ships an in-tree fake at `apps/api/tests/_fakes/ib_async_fake.py` that mimics the `IB` client surface needed by `IBKRAdapter` (≤8 methods: `connect`, `disconnect`, `reqCurrentTime`, `placeOrder`, `cancelOrder`, `reqAllOpenOrders`, `reqExecutions`, `accountSummary`).

The `HeartbeatMixin` from slice 2 is the resilience kernel. It owns the state machine (`CONNECTED ↔ RECONNECTING ↔ DISCONNECTED`), the disconnect-fires-once invariant, and the canonical `[3, 6, 12, 24, 48]` backoff in `reconnect_loop`. **What it doesn't own**: a 5-attempt ceiling. Slice 2 deliberately left the loop unbounded ("runs forever until either it succeeds or the surrounding task is cancelled") so each adapter can choose its escalation. T2 wraps it: 5 attempts → publish `KillSwitchTripped`.

The reconciliation contract sits at the seam between broker state (authoritative for fills + open orders) and local state (authoritative for proposals + trade aggregates). After a disconnect, the broker may have processed orders the adapter never observed (a stop-loss triggered while the network was down); the catchup query MUST be exhaustive — missing one fill desyncs P&L permanently.

Slice T1's `BrokerPort.reconcile_fills(since)` returns an `AsyncIterator[FillEvent]`. The adapter implements it as a generator that internally pages through `client.reqExecutions()` (IBKR API returns up to 7 days of executions per call; for any `since` beyond 7 days the adapter raises `IntegrationError` with a clear "broker history window exhausted" message — operator must run the slice-T4 export-from-csv tooling for older history).

## Goals / Non-Goals

**Goals:**

- Implement `BrokerPort` over `ib_async` with all five methods passing mypy `--strict` + structural typing test in T1's `test_ports_protocol_conformance.py`.
- Integrate `HeartbeatMixin` so connection state is observable + state transitions emit MessageBus events (the kernel for slice K1's kill-switch + slice O1's observability narration).
- Enforce 5-attempt reconnect ceiling per NFR-R7 + NFR-I2 → publish `KillSwitchTripped` on exhaustion.
- Idempotent `place_order` keyed by `client_order_id` so a service-layer retry never produces a duplicate broker submission (NFR-I1 invariant).
- Reconciliation-on-reconnect: every successful reconnect runs `_post_reconnect_reconciliation()` querying open orders + executions since `last_disconnect_at` + emitting `broker.fill.catchup` events per missed fill (FR16, NFR-R2).
- `IBKRBrokerageModel` encapsulates IBKR quirks (paper port 7497 / live port 7496, order-type whitelist, MD subscription flags, commission model) in a frozen dataclass — no runtime mutation, single point of change for "where do paper trading credentials point".
- Mock-based integration tests deterministic on Linux + Windows + macOS without a live TWS; CI runs them on every push.

**Non-Goals:**

- No live TWS in CI. CI uses `ib-insync-mock` (or in-tree fake — see D7).
- No multi-account / Financial Advisor (FA) account routing. MVP assumes one IBKR account per `tenant_id`.
- No options / futures order types. MVP whitelist is equities-only: `MKT`, `LMT`, `STP`, `STP LMT`. Bracket orders + OCO are deferred to v1.5.
- No real-time market-data streaming inside the adapter. T2 only places + cancels + reconciles. Streaming bar data for research lives in slice R3 (`research-news-catalysts-adapters` ships the `ibkr_bars.py` adapter for historical bars).
- No automatic recovery from auth failure. If `client.connectAsync()` raises an auth-related error, the adapter raises `IntegrationError` with `default_status=502` and does NOT retry — operator intervention required (manual TWS re-login, API permissions toggle, etc.).
- No commission modelling beyond passing through what the broker reports on `Fill.commission`. Slice T4 may add per-trade commission analytics; T2 just records.
- No paper-mode "simulate fills" override. If TWS paper mode behaves differently from live (e.g., lower slippage), that's an inherent property of the paper environment, not the adapter's concern.

## Decisions

### D1. Use `ib_async` (maintained MIT fork), NOT archived upstream `ib-insync`

**Decision**: `pyproject.toml` declares `ib_async = "^1.0"` (verify exact version + MIT license at lock time per slice 1 `license-boundary-check.yml` workflow). The original `ib-insync` package is left out — it's archived upstream and no longer accepts patches; security fixes only flow through `ib_async`.

**Why**:
- Active maintenance: `ib_async` has shipped patches for TWS API 10.x compatibility (2024-2025) that `ib-insync` never received.
- Same API surface: `ib_async` is a hard fork that preserved the public surface of `ib-insync` (the `IB` client class + `Contract`/`Order`/`Trade`/`Execution` value types). Migration cost is zero — just `pip install ib_async; from ib_async import IB`.
- License compatibility: MIT license, compatible with iguanatrader's Apache-2.0 + Commons Clause root.

**Alternatives considered**:
- **Stick with `ib-insync` and self-patch**: rejected — adds maintenance burden + we'd be the only consumer of an archived lib; security CVEs would have no upstream channel.
- **Direct integration with IBKR's official `ibapi` library** (the C++-with-Python-bindings primary client): rejected — `ibapi` is callback-based + sync-only; would force us to wrap it ourselves to get an asyncio-friendly surface (which is exactly what `ib_async` already does).
- **Build adapter against an alternative broker like Alpaca + skip IBKR for MVP**: rejected — IBKR is THE broker requirement for iguanatrader (per PRD + AGENTS.md); not negotiable for MVP. Alpaca becomes a v1.5 multi-broker addition.

**Rationale**: `ib_async` is the modern, maintained, asyncio-native, MIT-licensed wrapper. Adopt it as the canonical client; abstract via T1's `BrokerPort` so a future Alpaca / Tradier adapter implements the same Protocol structurally.

### D2. `IBKRAdapter` composes `HeartbeatMixin` rather than reimplementing the state machine

**Decision**: `class IBKRAdapter(HeartbeatMixin):` — direct multiple inheritance is unnecessary because `BrokerPort` is a Protocol (slice 2 D8 + slice T1 D1; structural typing means no inheritance edge required). The adapter overrides `_send_heartbeat` (calls `client.reqCurrentTime()`) and `_on_disconnect` (publishes `broker.connection.lost` event + records `last_disconnect_at_utc` on the instance for the next reconciliation pass). Calls `mark_connected()` after every successful `client.connectAsync()`.

**Why**:
- `HeartbeatMixin` already owns the disconnect-fires-once invariant (slice 2 property test pins it). Reimplementing in T2 risks divergence.
- Composition via inheritance keeps state-machine surface area in one place (the mixin's `_state` attribute is the single source of truth).
- mypy --strict is comfortable with the pattern: `IBKRAdapter` is both `HeartbeatMixin` (nominal subclass) and `BrokerPort` (structural subtype) — no contradiction.

**Alternatives considered**:
- **Reimplement state machine inline in `IBKRAdapter`**: rejected — duplicate logic across IBKR + Telegram + Hermes adapters (Telegram + Hermes both inherit `HeartbeatMixin` in P1).
- **Use `HeartbeatMixin` as a member field rather than a parent**: rejected — adds delegation boilerplate (`self.heartbeat.mark_connected()`) for no win; the mixin is designed to be a parent.

**Rationale**: this is exactly what the slice 2 design intended — `HeartbeatMixin` as parent of every live-connection adapter. T2 is its first consumer.

### D3. Wrap `HeartbeatMixin.reconnect_loop` with a 5-attempt ceiling that publishes `KillSwitchTripped`

**Decision**: `IBKRAdapter` does NOT call the inherited `reconnect_loop` directly. Instead it implements `_resilient_reconnect_loop()`:

```python
async def _resilient_reconnect_loop(self) -> None:
    self.mark_reconnecting()
    for attempt in range(5):  # NFR-R7: 5 attempts max
        delay = backoff_seconds(attempt, with_jitter=True)
        await asyncio.sleep(delay)
        try:
            await self._connect_client()  # ib_async.IB.connectAsync
            await self._send_heartbeat()  # confirm reachability
        except Exception as exc:
            await self._emit_event(BrokerConnectionAttemptFailed(attempt=attempt + 1, error=str(exc)))
            continue
        # Success path
        self.mark_connected()
        await self._emit_event(BrokerConnectionRestored(restored_at=utc_now()))
        await self._post_reconnect_reconciliation()
        return
    # Exhausted: trigger kill-switch
    await self._bus.publish(
        KillSwitchTripped(
            tenant_id=self._tenant_id,
            reason="ibkr.adapter.reconnect_exhausted",
            metadata={"attempts": 5, "backoff_sequence": [3, 6, 12, 24, 48]},
        )
    )
```

`KillSwitchTripped` is imported from `iguanatrader.contexts.risk.events` (cross-context allowed for events per slice 2 ruff exclusion). K1's kill-switch state machine subscribes and halts trading per FR30.

**Why**:
- NFR-R7 + NFR-I2 explicitly say "5 retries before kill-switch". The mixin's unbounded loop is wrong for this adapter.
- Publishing `KillSwitchTripped` rather than raising lets K1's centralised state machine handle the halt — operator gets a single, uniform halt path whether the trip was from a daily-loss breach or a broker-reconnect-exhausted.
- The attempt-failed event lets O1's structlog narrator log progress without polluting INFO with five lines per outage.

**Alternatives considered**:
- **Raise an exception that propagates to a background task supervisor**: rejected — there's no global supervisor in MVP; the MessageBus is the supervisor.
- **Just stop reconnecting silently after 5 attempts**: rejected — silent failure is the worst possible mode for live trading.
- **Use `tenacity` library for retry semantics**: rejected — adds runtime dep for what is 15 lines of code; `HeartbeatMixin.reconnect_loop` already supplies the backoff function.

**Rationale**: NFR-R7 is the canonical contract; T2 enforces it inline rather than depending on the mixin doing it (the mixin deliberately stays generic).

### D4. Idempotent `place_order` via `client_order_id` lookup → `orders` table BEFORE broker submission

**Decision**: Service layer (T4) generates `client_order_id: UUID` (UUIDv4) when constructing `NewOrder` from an approved `Proposal`. `IBKRAdapter.place_order(order)` does:

```python
async def place_order(self, order: NewOrder) -> BrokerOrderId:
    # 1. Idempotency lookup
    existing = await self._order_repo.get_by_client_order_id(order.client_order_id)
    if existing is not None and existing.broker_order_id is not None:
        # Service-layer retry after broker confirmed; return cached
        return BrokerOrderId(existing.broker_order_id)

    # 2. Pre-submission INSERT (status=pending) — idempotency anchor
    if existing is None:
        await self._order_repo.insert_pending(order)

    # 3. Broker submission
    self._brokerage.assert_supports_order_type(order.order_type)
    contract = self._build_contract(order.symbol)
    ib_order = self._build_ib_order(order)
    trade = self._client.placeOrder(contract, ib_order)
    broker_order_id = BrokerOrderId(str(trade.order.permId))

    # 4. Post-submission UPDATE (status: pending → submitted, broker_order_id populated)
    await self._order_repo.mark_submitted(order.client_order_id, broker_order_id)
    return broker_order_id
```

`NewOrder` (T1's frozen dataclass) does NOT currently carry `client_order_id`. **Resolution**: T2 extends the `metadata: dict[str, Any]` slot already on `Proposal` (T1) → service propagates to a new `NewOrder.client_order_id: UUID` field (T2 extends `NewOrder` by editing `ports.py`? **NO** — T1's contract is frozen). Instead, T2 adds `client_order_id: UUID = field(default_factory=uuid4)` as a new field via subclassing in `brokers/ibkr_adapter.py` is also wrong (changes Protocol contract). **Correct path**: extend `NewOrder` is genuinely required for the idempotency contract — propose a small T1 amendment as a separate openspec change `trading-models-newOrder-client-order-id` (one-line field addition). For T2's first-pass implementation, the field is added at NewOrder construction site in service.py (T4) and read off `order.client_order_id` in `IBKRAdapter`. Since T4 hasn't landed yet, T2 documents the dependency: **T2 PR cannot merge until either NewOrder gains `client_order_id` (via T1 amendment) or T2 ships its own intermediate `NewOrderWithIdempotency` wrapper internal to `brokers/`**. Designed below D8. The cleanest path is the T1 amendment — proposed in this slice's `tasks.md` group 1 as a prerequisite gate.

**Why**:
- IBKR's own `permId` is broker-side; if the API call partially fails (network drop after broker received but before client received the ack), retrying with the same `client_order_id` lets the adapter detect the duplicate via local DB without trusting broker idempotency (which IBKR doesn't fully provide).
- Pre-submission INSERT means even if the process dies between `placeOrder()` and the response handler, the next startup sees the pending row + can query the broker for the matching `permId`.
- NFR-I1 says "BrokerInterface abstracta documentada con contract tests" — idempotency is part of the documented contract; a future adapter (Alpaca) implements the same shape.

**Alternatives considered**:
- **Trust broker-side idempotency by submitting the same order twice and assuming the broker dedupes**: rejected — IBKR does NOT dedupe; you'd get two submissions.
- **Use a transactional outbox pattern (write order to DB then have a background worker submit to broker)**: rejected — adds complexity disproportionate to the win; the in-line pre-submission INSERT covers the same recovery-after-crash scenario.
- **Use `ib_async`'s built-in `client.placeOrder(...)` retry semantics**: rejected — `ib_async` has no idempotency; it's a thin wrapper.

**Rationale**: pre-INSERT-then-submit is the canonical at-least-once → exactly-once pattern when the downstream system has no native idempotency. NFR-I1 makes it a contract requirement.

### D5. Reconciliation-on-reconnect uses `client.reqAllOpenOrders()` + `client.reqExecutions(since=last_disconnect)`

**Decision**: After every successful reconnect (line in D3 above: `await self._post_reconnect_reconciliation()`), the adapter:

1. Calls `client.reqAllOpenOrders()` (NOT `client.openOrders()`) — the former returns ALL open orders TWS knows about, including manually-placed orders + orders from a prior API session that survived the disconnect; the latter only returns orders submitted by the current API session.
2. Calls `client.reqExecutions(ExecutionFilter(time=last_disconnect_at_utc.strftime('%Y%m%d-%H:%M:%S'), acctCode=self._brokerage.account_code))` — IBKR requires a UTC timestamp in `YYYYMMDD-HH:MM:SS` format (no separator before `HH`); the adapter uses `slice 2 format_iso8601` then converts. **Caveat**: IBKR's execution history window is 7 days; for `last_disconnect_at` older than that the adapter raises `IntegrationError("ibkr.executions.window_exhausted")` and instructs the operator to run a manual reconciliation via T4's `iguana ops reconcile --since=YYYY-MM-DD` (out of T2 scope).
3. For each execution returned, looks up local `fills` by `broker_fill_id` (IBKR's `Execution.execId`); if not present, emits `broker.fill.catchup(FillEvent(...))` to the MessageBus. Service layer (T4) subscribes and INSERTs the row.
4. For each open order returned, looks up local `orders` by `broker_order_id`; if local says CLOSED but broker says open, the local record is wrong (rare; usually means a reconciliation race) → emit `broker.order.state_drift` event for operator review (logs + alert; no auto-fix).

Document in `gotchas.md`: `client.openOrders()` vs `client.reqAllOpenOrders()` distinction (the former is a synchronous local-cache read; the latter is an async round-trip to TWS that returns ALL accounts' orders). The adapter ALWAYS uses `reqAllOpenOrders()` for reconciliation.

**Why**:
- TWS restart wipes session-scoped state but not account-scoped state; `reqAllOpenOrders()` survives restarts.
- 7-day execution window is documented IBKR limitation; operator-driven reconciliation for older windows is a runbook concern, not adapter logic.
- `broker.order.state_drift` event is observability; auto-fix is out of scope (correct behaviour requires human judgment about which side is canonical).

**Alternatives considered**:
- **Use `client.openOrders()` (sync local cache)**: rejected — misses orders from prior sessions.
- **Compare via `permId` directly without local DB join**: rejected — local DB is the audit-trail anchor; bypassing it defeats FR46.
- **Periodic (every 5min) full reconciliation regardless of disconnect**: rejected — unnecessary; the disconnect-triggered path covers all cases. A runbook can call `iguana ops reconcile` manually if operator suspects drift.

**Rationale**: matches IBKR's API contract semantics + avoids the well-documented `openOrders()` gotcha.

### D6. Heartbeat: 30s interval via `client.reqCurrentTime()` with 90s deadline → `mark_disconnected`

**Decision**: `IBKRAdapter._heartbeat_loop()` is an `asyncio.Task` started after first connect:

```python
async def _heartbeat_loop(self) -> None:
    while not self._shutting_down:
        try:
            async with asyncio.timeout(90):  # NFR-P8 ceiling
                ts = await self._client.reqCurrentTime()  # ib_async returns datetime
                self._last_heartbeat_at = utc_now()
        except (asyncio.TimeoutError, Exception) as exc:
            await self._emit_event(BrokerConnectionLost(reason=str(exc)))
            await self.mark_disconnected()  # HeartbeatMixin: idempotent
            asyncio.create_task(self._resilient_reconnect_loop())
            return  # heartbeat loop exits; reconnect path takes over
        await asyncio.sleep(30)  # NFR-P8 cadence
```

**Why**:
- `reqCurrentTime()` is the lightest TWS call (returns a `datetime`); doesn't trigger market-data subscription billing or any side-effect.
- 30s cadence + 90s timeout matches NFR-P8 exactly (`alert disparada si gap > 90s`).
- Returning from the heartbeat loop after kicking the reconnect loop avoids two concurrent loops competing; the reconnect loop will start a fresh `_heartbeat_loop` task on success.

**Alternatives considered**:
- **Use TCP keepalive on the socket level**: rejected — TWS doesn't ack quickly enough; you'd see false-positives on slow networks.
- **Heartbeat every 10s with 30s timeout**: rejected — increases TWS API call load disproportionately for no resilience win; PRD pins 30s/90s.
- **Use `client.isConnected()` polling**: rejected — that's a local-state check, doesn't catch zombie connections where TWS is unreachable but the local socket thinks it's open.

**Rationale**: PRD NFR-P8 is canonical; this implementation matches it with one round-trip per 30s.

### D7. Test strategy: prefer `ib-insync-mock`; fall back to in-tree fake at `tests/_fakes/ib_async_fake.py`

**Decision**: The `ib-insync-mock` PyPI package was built for the original `ib-insync` library. T2 spikes early (group 1 of `tasks.md`): does it work transparently against `ib_async`? If yes, adopt as dev dep. If no, T2 ships a 200-300 line in-tree fake that implements the IB-client surface needed by `IBKRAdapter` (≤8 methods listed in Context).

The in-tree fake (if used) is a `IBFake` class with public methods `connectAsync(host, port, clientId)`, `disconnect()`, `reqCurrentTime()`, `placeOrder(contract, order)`, `cancelOrder(order)`, `reqAllOpenOrders()`, `reqExecutions(filter)`, `accountSummary()` — each method's behaviour is configurable from test setup (e.g., `fake.set_connect_failure(True)` to simulate a TWS-down scenario). The fake is async-native and uses `asyncio.Queue` internally for fill-stream simulation. Tests inject `IBFake` instead of the real `ib_async.IB` via constructor parameter on `IBKRAdapter` (`client_factory: Callable[[], IB] = lambda: IB()`).

**Why**:
- TWS in CI is operationally expensive (paper account + persistent VM) and non-deterministic (real network → flaky).
- `ib-insync-mock`'s author has historically updated the lib alongside `ib-insync`; whether that extends to `ib_async` is unverified — hence the spike.
- The in-tree fake is a known-cost fallback (~1 day of work) and gives full control over failure-mode injection.

**Alternatives considered**:
- **Use `pytest-mock` to monkeypatch `ib_async.IB` methods inline**: rejected — gets unwieldy for multi-step scenarios; an in-tree fake is more maintainable.
- **Run TWS Paper inside a Docker container in CI**: rejected — IBKR's TWS image is not officially redistributable; would require building one + dealing with auth flow.
- **Skip integration tests and rely on unit tests**: rejected — NFR-R2 requires E2E reconciliation verification; integration tests are the canonical gate.

**Rationale**: deterministic, fast, no external dependencies in CI. The spike outcome is documented inline in `tasks.md` group 1.

### D8. `IBKRBrokerageModel` is a frozen dataclass; instantiated once per adapter; never mutated

**Decision**: `apps/api/src/iguanatrader/contexts/trading/brokers/ibkr_brokerage_model.py` ships:

```python
@dataclass(frozen=True, slots=True)
class IBKRBrokerageModel:
    mode: Literal["paper", "live"]
    host: str = "127.0.0.1"
    port: int = field(default=7497)  # 7497 paper; 7496 live
    client_id: int = 1
    account_code: str | None = None  # optional FA account code; None = primary
    supported_order_types: frozenset[str] = field(
        default_factory=lambda: frozenset({"MKT", "LMT", "STP", "STP LMT"})
    )
    market_data_subscriptions: dict[str, bool] = field(default_factory=dict)
    commission_model: Literal["tiered", "fixed"] = "tiered"

    def __post_init__(self) -> None:
        if self.mode == "paper" and self.port != 7497:
            raise ValueError(f"paper mode requires port 7497, got {self.port}")
        if self.mode == "live" and self.port != 7496:
            raise ValueError(f"live mode requires port 7496, got {self.port}")

    def assert_supports_order_type(self, order_type: str) -> None:
        if order_type not in self.supported_order_types:
            raise IntegrationError(
                detail=f"order type {order_type!r} not in IBKR supported set",
                type_uri="urn:iguanatrader:error:broker-order-type-unsupported",
            )

    @classmethod
    def from_settings(cls, settings: Settings) -> "IBKRBrokerageModel":
        ...  # reads from slice 2 settings layer
```

The `__post_init__` port validation is a defensive guard — operators sometimes copy paper credentials to live config + forget to update the port; the assert catches that before the adapter calls `connectAsync()` against the wrong endpoint.

**Why**:
- Frozen → no mid-run mutation; if config changes, restart the daemon (simple operational model).
- Single point of change for IBKR-specific quirks; new MVP-supported order type? Add to the frozenset.
- Market-data subscription gating: T2 doesn't enforce it (placement of an order for a symbol without an active MD sub still works in IBKR; you just don't get streaming quotes), but the field is here so T4 / O1 can warn operators when symbols lack subs.

**Alternatives considered**:
- **Spread the quirks across `IBKRAdapter` directly**: rejected — couples adapter logic to config; harder to test in isolation.
- **Use a Pydantic model**: rejected — Pydantic adds validation cost on every read; frozen dataclass + `__post_init__` is cheaper + sufficient for our needs.

**Rationale**: separation of concerns + defensive defaults match the slice-T1 design idiom (small frozen dataclasses for cross-cutting value types).

### D9. `place_order` requires `NewOrder.client_order_id` — propose a one-line T1 amendment

**Decision**: T2 cannot ship without `client_order_id` reaching the adapter. T1's `NewOrder` dataclass currently lacks the field. **Resolution path**:

1. **Preferred**: open a tiny followup openspec change `trading-newOrder-client-order-id` that adds `client_order_id: UUID = field(default_factory=uuid4)` to `NewOrder` in T1's `ports.py`. Single-line change; ~10 lines in tests; merges in <1 day. T2 depends on it.
2. **Fallback** (if amendment is delayed): T2 ships an internal `NewOrderWithIdempotency` wrapper dataclass in `brokers/ibkr_adapter.py` carrying `inner: NewOrder` + `client_order_id: UUID`. Service layer (T4) constructs the wrapper. Slight ugliness — the Protocol still says `NewOrder`, so the adapter has a special `place_order_with_idempotency` method NOT on `BrokerPort`. This is the explicit fallback because it preserves T1's frozen contract.

`tasks.md` group 1 includes "verify T1 amendment is queued or document fallback path explicitly". This is the single non-trivial design risk in T2.

**Why**:
- T1 is archived and its contract is frozen; a clean amendment is the right pattern (per slice T1 D3 risk mitigation: "additions go in `metadata: dict`" was the lighter path, but `client_order_id` is a primary-key-grade field, deserves a typed home).
- The fallback wrapper is clunky but unblocks T2 if the amendment slips.

**Alternatives considered**:
- **Stuff `client_order_id` into `NewOrder.metadata`** (which T1's amendment-shaped extension slot anticipates): could work but typed accessor would be `cast(UUID, order.metadata["client_order_id"])`, which loses static type safety. Rejected as final shape; OK as temporary.
- **Generate `client_order_id` inside the adapter** (UUIDv4 derived from `(tenant_id, trade_id, retry_attempt)`): rejected — service-layer retries with the same logical order would generate different UUIDs, defeating idempotency.

**Rationale**: T1 amendment is the cleanest; fallback wrapper is the safety net. Document both in `tasks.md`.

## Risks / Trade-offs

- **[Risk] `ib_async` ships breaking change in a minor version** — pin to `^1.0` semver; CI re-runs nightly to catch. **Mitigation**: dependabot PRs surface the diff; tests + types act as the canary.

- **[Risk] In-tree fake drifts from real `ib_async` API** — fake says success, prod fails because the real `IB.placeOrder()` argument name changed. **Mitigation**: a smoke test scaffold `tests/integration/test_ibkr_smoke_against_paper.py` (marked `@pytest.mark.skipif(not os.getenv("IBKR_PAPER_AVAILABLE"))`) is shipped + documented; operators run it manually against a paper account before any production deploy. Not CI-gated.

- **[Risk] `client_order_id` propagation cuts across T1's frozen contract** — already covered in D9. Worst case: T2 ships with the wrapper fallback for a sprint; T1 amendment lands later; T2 cleans up.

- **[Risk] `KillSwitchTripped` is published from a background task that may run after the main service has shut down** — gross-safety problem (event lost, kill-switch never engages). **Mitigation**: adapter holds a strong reference to the `MessageBus` instance + the bus uses `asyncio.create_task` internally for subscriber notification (slice 2 contract); slice O1's structlog narrator logs every published event so even if the kill-switch state machine missed it, the operator sees it in logs.

- **[Risk] Reconciliation emits duplicate `broker.fill.catchup` events if reconnect happens twice quickly** — service layer would INSERT duplicate `fills` rows. **Mitigation**: service-layer subscriber uses `idempotency_key=broker_fill_id` on the MessageBus subscription (slice 2 D1 idempotency contract). The bus dedupes within the configured window. Documented in tasks group 5.

- **[Risk] IBKR market-data subscription gating** — placing a `LMT` order for a symbol without an active MD subscription works (IBKR uses delayed quotes for the gating check) but slice T3's strategy may have produced the proposal based on stale data; the proposal-time price could be drastically off-current. **Mitigation**: out of T2 scope (T3 + T4 own proposal-time data freshness); T2 documents in `gotchas.md` that operators must keep MD subs current for symbols on the active watchlist.

- **[Risk] DST timestamp confusion in `reqExecutions` filter** — IBKR expects the `time` filter in TWS-server-local time, NOT UTC, depending on TWS configuration. **Mitigation**: documented in `gotchas.md`; the adapter sends UTC and the integration test verifies on a fake that the format string is correct. Production TWS is typically configured to interpret as UTC; if not, operator sets TWS Edit→Global Configuration→API→Settings→"Use UTC for execution times" + documented in runbook.

- **[Trade-off] T2 imports `KillSwitchTripped` from `iguanatrader.contexts.risk.events`** — cross-context import. The slice 2 ruff exclusion for `events.py` paths covers this (per T1 D3 risk mitigation note). If the rule isn't yet plumbed for `brokers/ibkr_adapter.py` (only `events.py` files are excluded by default), T2's ruff config gets a one-line addition: `"contexts/trading/brokers/ibkr_adapter.py"` to the cross-context exclusion list. Documented in tasks group 6.

- **[Trade-off] Adapter ships ~400 lines of code in `ibkr_adapter.py`** — bigger than other single-file modules in the project. **Mitigation**: structure with explicit sections (lifecycle, heartbeat, idempotency, reconciliation, contract-builder helpers); each section has a region comment + a unit test file matching its section.

## Migration Plan

1. **T1 amendment lands** (the `client_order_id` field on `NewOrder`) — separate openspec change, ≤1 day. Or, if delayed, T2 ships with the fallback wrapper from D9.
2. **Slice T2 PR opens** with `ib_async` + `ib-insync-mock` (or in-tree fake) added to deps. CI runs `license-boundary-check.yml` workflow → confirms `ib_async` is MIT.
3. **Merge to main**. No DB migration. No route-surface change. The new adapter sits inside the trading bounded context, accessible via T4's service layer when T4 lands.
4. **T4 begins consuming `IBKRAdapter`**: constructs an instance with `IBKRBrokerageModel.from_settings(settings)`, calls `adapter.connect()`, registers `adapter` as the `broker` argument to `TradingService(...)`. T4 also ships the `iguana ops reconcile` CLI command for operator-driven reconciliation outside the disconnect-triggered path.

**Rollback** = revert PR. No data exists in production yet (no `orders` / `fills` rows ever inserted via T1's stub paths). The migration is purely additive.

## Open Questions

- **Q**: Should `IBKRAdapter._post_reconnect_reconciliation()` block reconnect-success acknowledgment until the reconciliation completes, or run it as a fire-and-forget background task? **Tentative answer**: block. Operator-experience clarity matters more than reconnect-latency optimisation; the operator sees `broker.connection.restored` only after the local DB matches the broker. Documented in D5.

- **Q**: What if `client.reqAllOpenOrders()` returns an open order that local DB has NO record of (manually-placed via TWS GUI)? **Tentative answer**: emit `broker.order.unknown` event with the broker order details; T4's runbook says "operator should `iguana ops adopt-order <broker_order_id>` to bring it into local tracking". T2 only emits the event; adoption logic is T4.

- **Q**: How does the adapter handle TWS API rate limits (50 messages/sec is the documented limit)? **Tentative answer**: not a T2 concern at MVP scale (one tenant placing ≤10 orders/day); explicit non-goal. If v1.5 introduces high-frequency scenarios, an `ib_async`-aware `RateLimiter` mixin lands then. Documented in non-goals.

- **Q**: Should `IBKRBrokerageModel.market_data_subscriptions` be loaded from a static config or queried from TWS at connect time? **Tentative answer**: loaded statically from settings for MVP (operator manually keeps the dict in sync with their IBKR account subscriptions). v1.5 can add a `client.reqMktDataRights()` query to auto-populate. Documented in `gotchas.md`.
