## ADDED Requirements

### Requirement: `IBKRAdapter` SHALL implement `BrokerPort` over `ib_async` with `HeartbeatMixin` composition

The system SHALL provide `iguanatrader.contexts.trading.brokers.ibkr_adapter.IBKRAdapter` as a concrete class that satisfies the `iguanatrader.contexts.trading.ports.BrokerPort` Protocol structurally (mypy `--strict` enforced) and inherits from `iguanatrader.shared.heartbeat.HeartbeatMixin` for connection-state ownership. The adapter SHALL use the maintained MIT-licensed fork `ib_async` (NOT the archived upstream `ib-insync`) as the TWS/Gateway client. Composition with `HeartbeatMixin` is mandatory — the adapter MUST NOT reimplement the connection state machine.

#### Scenario: IBKRAdapter satisfies BrokerPort under mypy --strict

- **WHEN** the test suite asserts `isinstance(IBKRAdapter(brokerage=..., bus=..., order_repo=..., fill_repo=..., tenant_id=...), BrokerPort)`
- **THEN** the assertion passes (Protocol is `@runtime_checkable` per slice T1)
- **AND** mypy `--strict` accepts the assignment of `IBKRAdapter` instance to a `BrokerPort`-typed variable without error

#### Scenario: IBKRAdapter inherits HeartbeatMixin state machine

- **WHEN** an `IBKRAdapter` instance is constructed
- **THEN** `instance.state` returns `ConnectionState.DISCONNECTED` (the mixin's initial state per slice 2 D6)
- **AND** after `await instance.connect()` succeeds, `instance.state` returns `ConnectionState.CONNECTED`
- **AND** after `await instance.disconnect()` returns, `instance.state` returns `ConnectionState.DISCONNECTED` exactly once (idempotency guaranteed by the mixin)

### Requirement: Heartbeat SHALL run every 30 seconds against TWS via `reqCurrentTime()` with a 90-second deadline

The adapter SHALL emit a heartbeat ping every 30 seconds while in `ConnectionState.CONNECTED` by calling `client.reqCurrentTime()` (the lightest TWS round-trip). Each ping SHALL have a 90-second deadline enforced via `asyncio.timeout(90)`. If the deadline elapses without response — or if the call raises — the adapter SHALL: (a) emit `broker.connection.lost` to the MessageBus, (b) call `await self.mark_disconnected()` (idempotent per `HeartbeatMixin`), (c) start `_resilient_reconnect_loop` as a background `asyncio.Task`, (d) exit the heartbeat loop. Cadence (30s) and deadline (90s) match NFR-P8 exactly.

#### Scenario: Heartbeat at 30s cadence with 90s deadline

- **WHEN** the adapter is in CONNECTED state
- **THEN** `_send_heartbeat()` is invoked every 30 seconds (±jitter not applied to the heartbeat cadence — only to backoff)
- **AND** each invocation wraps the underlying `reqCurrentTime` call in `asyncio.timeout(90)`
- **AND** if `reqCurrentTime` returns a `datetime` within the deadline, `self._last_heartbeat_at = utc_now()` is recorded and the loop sleeps another 30 seconds

#### Scenario: Heartbeat timeout transitions to RECONNECTING and emits broker.connection.lost

- **WHEN** `reqCurrentTime` does not return within 90 seconds (`asyncio.TimeoutError` raised)
- **THEN** `broker.connection.lost` event is published to the MessageBus with `tenant_id`, `mode`, `reason`, and ISO 8601 UTC `lost_at` fields
- **AND** `self._last_disconnect_at` is set to `utc_now()`
- **AND** `mark_disconnected()` is called (idempotent — `_on_disconnect` hook fires exactly once)
- **AND** `_resilient_reconnect_loop` is scheduled as a background task
- **AND** the heartbeat loop exits (does not race with the reconnect path)

### Requirement: Resilient reconnect loop SHALL walk the canonical `[3, 6, 12, 24, 48]` backoff sequence and publish `KillSwitchTripped` after 5 attempts

On every disconnect, the adapter SHALL execute `_resilient_reconnect_loop` which walks at most 5 reconnect attempts using the canonical backoff sequence `[3, 6, 12, 24, 48]` seconds (sourced from `iguanatrader.shared.backoff.backoff_seconds` per slice 2 D7 — the NFR-R7 canonical sequence). Jitter `with_jitter=True` (±20%) is enabled per the slice 2 D7 default. After 5 exhausted attempts (no successful reconnect), the adapter SHALL publish `iguanatrader.contexts.risk.events.KillSwitchTripped(reason="ibkr.adapter.reconnect_exhausted")` to the MessageBus and stop further reconnect attempts. Authentication-related connection failures (e.g., TWS rejecting credentials) SHALL short-circuit the loop — the adapter publishes `KillSwitchTripped(reason="ibkr.adapter.auth_failed")` immediately on the first auth-failure exception, without retrying.

#### Scenario: Successful reconnect on attempt 3

- **WHEN** the resilient reconnect loop is invoked
- **AND** attempts 0 and 1 fail (network errors)
- **AND** attempt 2 succeeds (`_connect_client()` + `_send_heartbeat()` both return)
- **THEN** the backoff sequence `[3, 6]` (with ±20% jitter) is consumed via `asyncio.sleep` before each attempt
- **AND** on attempt 2 success, `mark_connected()` is called
- **AND** `broker.connection.restored` event is published with ISO 8601 UTC `restored_at`
- **AND** `_post_reconnect_reconciliation()` runs to completion (blocking — design D5 + open question Q1)
- **AND** a fresh `_heartbeat_loop()` task is started

#### Scenario: All 5 attempts exhausted publishes KillSwitchTripped

- **WHEN** the resilient reconnect loop is invoked
- **AND** all 5 attempts fail
- **THEN** the full backoff sequence `[3, 6, 12, 24, 48]` (with jitter) has been walked
- **AND** `KillSwitchTripped(tenant_id=..., reason="ibkr.adapter.reconnect_exhausted", metadata={"attempts": 5, "backoff_sequence": [3, 6, 12, 24, 48]})` is published to the MessageBus
- **AND** the loop exits without further reconnect attempts
- **AND** the adapter remains in `ConnectionState.RECONNECTING` until the operator manually restarts the daemon (kill-switch state is K1's concern)

#### Scenario: Auth failure short-circuits without retry

- **WHEN** the first reconnect attempt raises an authentication-related exception
- **THEN** `KillSwitchTripped(reason="ibkr.adapter.auth_failed")` is published immediately
- **AND** no `asyncio.sleep` for backoff is consumed
- **AND** the loop exits without attempting attempts 1-4

### Requirement: `place_order` SHALL be idempotent via `client_order_id` (NFR-I1)

`IBKRAdapter.place_order(order: NewOrder) -> BrokerOrderId` SHALL be idempotent: if invoked twice with a `NewOrder` carrying the same `client_order_id`, the second invocation SHALL NOT submit a duplicate order to IBKR. The implementation MUST: (1) look up the order by `client_order_id` in the `orders` table; if a row exists with non-NULL `broker_order_id`, return that ID without contacting the broker; (2) if no row exists, INSERT a pending row keyed by `client_order_id` BEFORE calling `client.placeOrder()`; (3) submit to broker; (4) UPDATE the pending row with the returned `broker_order_id` + `submitted_at`. Steps 1-2 ensure exactly-once semantics even when the process crashes between broker submission and ack reception. The validation `IBKRBrokerageModel.assert_supports_order_type` MUST run before step 1 — invalid order types raise `IntegrationError` BEFORE any DB write.

#### Scenario: Duplicate place_order call returns cached broker_order_id

- **WHEN** `place_order(order)` is called with `order.client_order_id = X` and the local `orders` table contains an existing row keyed by X with `broker_order_id = "PERM_123"`
- **THEN** the method returns `BrokerOrderId("PERM_123")` without calling `client.placeOrder()`
- **AND** no new `orders` row is inserted
- **AND** the structlog event `trading.broker.idempotent_replay` is emitted with `client_order_id`, `broker_order_id`, `tenant_id`

#### Scenario: First-time place_order writes pending then submits then updates

- **WHEN** `place_order(order)` is called with a fresh `client_order_id` (no existing row)
- **THEN** an `orders` row is INSERTed with `status="pending"`, `broker_order_id=NULL`, `client_order_id=order.client_order_id`
- **AND** `client.placeOrder(contract, ib_order)` is called
- **AND** on success, the row is UPDATEd with `status="submitted"`, `broker_order_id=str(trade.order.permId)`, `submitted_at=utc_now()`
- **AND** the returned `BrokerOrderId` matches the persisted `broker_order_id`

#### Scenario: Crash-recovery path re-submits when broker_order_id is NULL

- **WHEN** `place_order(order)` is called with a `client_order_id` matching an existing pending row (from a prior crashed session) where `broker_order_id IS NULL`
- **THEN** no new INSERT is attempted (the row already exists)
- **AND** `client.placeOrder()` is called (the prior crash never confirmed broker submission)
- **AND** the row is UPDATEd with the new `broker_order_id` returned

#### Scenario: Unsupported order type raises before any DB write

- **WHEN** `place_order(order)` is called with `order.order_type = "TRAIL"` (not in default whitelist `{MKT, LMT, STP, STP LMT}`)
- **THEN** `IBKRBrokerageModel.assert_supports_order_type` raises `IntegrationError` with `type_uri="urn:iguanatrader:error:broker-order-type-unsupported"`
- **AND** no `orders` row is inserted
- **AND** `client.placeOrder()` is NOT called

### Requirement: Reconciliation-on-reconnect SHALL diff broker state against local state and emit catch-up events for missed fills (FR16, NFR-R2)

After every successful reconnect, `_post_reconnect_reconciliation()` SHALL run to completion before the heartbeat loop restarts. The reconciliation SHALL: (1) call `client.reqAllOpenOrders()` (NOT `client.openOrders()`) to capture orders that may have been placed in a prior session or via TWS GUI; (2) call `client.reqExecutions(ExecutionFilter(time=last_disconnect_at_utc, acctCode=brokerage.account_code))` to capture fills that arrived during the outage; (3) for each execution returned, look up the local `fills` table by `broker_fill_id` (= IBKR `Execution.execId`); (4) for each broker execution NOT present locally, emit `broker.fill.catchup` event carrying a fully-populated `FillEvent`; (5) for each open broker order whose local record is in a closed state, emit `broker.order.state_drift` event for operator review (no auto-fix). If `last_disconnect_at` is older than 7 days (IBKR's documented execution-window limit), `reconcile_fills` SHALL raise `IntegrationError(type_uri="urn:iguanatrader:error:broker-history-window-exhausted")` instead of silently truncating.

#### Scenario: Missed fill during outage produces catch-up event

- **WHEN** an order with `broker_order_id="PERM_42"` was placed before the disconnect
- **AND** during the disconnect the broker filled the order (`Execution.execId="EXEC_99"`, `quantity=100`, `fillPrice=50.25`, `commission=1.00 USD`)
- **AND** the local `fills` table has NO row with `broker_fill_id="EXEC_99"`
- **AND** the adapter reconnects and `_post_reconnect_reconciliation()` runs
- **THEN** exactly ONE `broker.fill.catchup` event is published with `FillEvent(order_id=<local order_id matching PERM_42>, quantity_filled=Decimal("100"), fill_price=Decimal("50.25"), commission=Decimal("1.00"), commission_currency="USD", filled_at=<execution time>, broker_fill_id="EXEC_99")`
- **AND** the structlog event `trading.broker.fill_catchup` is emitted with `tenant_id`, `correlation_id`, `broker_fill_id`, `order_id`

#### Scenario: Already-recorded fill produces no catch-up event (idempotent)

- **WHEN** the local `fills` table already has a row with `broker_fill_id="EXEC_99"` (the service layer subscribed to a prior catch-up event and INSERTed the row)
- **AND** the adapter disconnects and reconnects again
- **AND** `_post_reconnect_reconciliation()` queries `client.reqExecutions(...)` returning the same `EXEC_99`
- **THEN** ZERO `broker.fill.catchup` events are published for `EXEC_99`
- **AND** the structlog event `trading.broker.reconciliation.no_op` is emitted with `executions_seen=N`, `catchups_emitted=0`

#### Scenario: State drift detected when broker says open but local says closed

- **WHEN** `client.reqAllOpenOrders()` returns an order with `permId="PERM_77"` in OPEN state
- **AND** the local `orders` table has a row with `broker_order_id="PERM_77"` in `state="closed_filled"`
- **THEN** `broker.order.state_drift` event is published with `order_id`, `broker_order_id="PERM_77"`, `local_state="closed_filled"`, `broker_state="open"`, `reason="broker_open_local_closed"`
- **AND** NO auto-fix is attempted (operator review required per design D5)

#### Scenario: Reconcile beyond 7-day window raises window-exhausted

- **WHEN** `adapter.reconcile_fills(since=utc_now() - timedelta(days=8))` is invoked
- **THEN** `IntegrationError(type_uri="urn:iguanatrader:error:broker-history-window-exhausted", detail="...")` is raised before any iterator iteration
- **AND** the structlog event `trading.broker.history_window_exhausted` is emitted with the requested `since` timestamp + the broker's 7-day limit

### Requirement: Connection-lifecycle events SHALL follow the `<context>.<entity>.<action>` naming convention (NFR-O8)

The adapter SHALL emit five connection-lifecycle event names matching the `<context>.<entity>.<action>` structlog convention: `broker.connection.established`, `broker.connection.lost`, `broker.connection.restored`, `broker.fill.received`, `broker.fill.catchup`. Each event SHALL carry `tenant_id`, `mode` (`"paper"` | `"live"`), and an ISO 8601 UTC timestamp field. Each event SHALL be published to the MessageBus AND emitted as a structlog event in a single helper call (`_emit_event`) so observability + bus subscribers receive identical context. The `event_name: ClassVar[str]` attribute on each event dataclass SHALL match the structlog event name exactly.

#### Scenario: Each lifecycle event has matching event_name

- **WHEN** the test suite introspects each event class
- **THEN** `BrokerConnectionEstablished.event_name == "broker.connection.established"`
- **AND** `BrokerConnectionLost.event_name == "broker.connection.lost"`
- **AND** `BrokerConnectionRestored.event_name == "broker.connection.restored"`
- **AND** `BrokerFillReceived.event_name == "broker.fill.received"`
- **AND** `BrokerFillCatchup.event_name == "broker.fill.catchup"`

#### Scenario: Every emitted event carries tenant_id, mode, ISO 8601 timestamp

- **WHEN** any of the five events is published via `_emit_event`
- **THEN** the event payload includes `tenant_id: UUID`, `mode: Literal["paper", "live"]`, and a timestamp field formatted per `iguanatrader.shared.time.format_iso8601` (UTC, microsecond precision, `Z` suffix)
- **AND** the structlog narration carries the same fields plus `correlation_id` if present in `contextvars`

### Requirement: `IBKRBrokerageModel` SHALL encapsulate IBKR-specific configuration with port-mode validation

The system SHALL provide `iguanatrader.contexts.trading.brokers.ibkr_brokerage_model.IBKRBrokerageModel` as a frozen dataclass (`@dataclass(frozen=True, slots=True)`) declaring: `mode: Literal["paper","live"]`, `host: str` (default `"127.0.0.1"`), `port: int` (default `7497`), `client_id: int` (default `1`), `account_code: str | None`, `supported_order_types: frozenset[str]` (default `{"MKT","LMT","STP","STP LMT"}`), `market_data_subscriptions: dict[str,bool]`, `commission_model: Literal["tiered","fixed"]` (default `"tiered"`). `__post_init__` SHALL raise `ValueError` if `mode == "paper"` and `port != 7497`, OR `mode == "live"` and `port != 7496`. The method `assert_supports_order_type(order_type: str)` SHALL raise `IntegrationError(type_uri="urn:iguanatrader:error:broker-order-type-unsupported")` for any `order_type` not in `supported_order_types`. A `from_settings(settings)` classmethod SHALL construct an instance from the slice-2 settings layer.

#### Scenario: Paper mode with wrong port raises ValueError

- **WHEN** `IBKRBrokerageModel(mode="paper", port=7496)` is constructed
- **THEN** `ValueError("paper mode requires port 7497, got 7496")` is raised in `__post_init__`

#### Scenario: Live mode with wrong port raises ValueError

- **WHEN** `IBKRBrokerageModel(mode="live", port=7497)` is constructed
- **THEN** `ValueError("live mode requires port 7496, got 7497")` is raised in `__post_init__`

#### Scenario: Order type whitelist enforces supported set

- **WHEN** `model.assert_supports_order_type("TRAIL")` is called on an instance with default `supported_order_types`
- **THEN** `IntegrationError` is raised with `type_uri="urn:iguanatrader:error:broker-order-type-unsupported"`
- **AND** the error `detail` contains the offending order type `"TRAIL"`

#### Scenario: Default supported set covers MVP equity order types

- **WHEN** `IBKRBrokerageModel(mode="paper", port=7497)` is constructed
- **THEN** `model.supported_order_types == frozenset({"MKT","LMT","STP","STP LMT"})`
- **AND** `model.assert_supports_order_type("MKT")` returns silently (no raise)
- **AND** `model.assert_supports_order_type("LMT")` returns silently
- **AND** `model.assert_supports_order_type("STP")` returns silently
- **AND** `model.assert_supports_order_type("STP LMT")` returns silently

### Requirement: Integration tests SHALL use a mock IB client (no live TWS in CI) and run deterministically

The system SHALL provide deterministic integration tests for the resilience contract that NEVER require a real TWS or Gateway instance. Tests SHALL inject a mock IB client via `IBKRAdapter`'s constructor parameter `client_factory: Callable[[], IB]` — defaulting to the real `ib_async.IB` factory in production but overridable in tests. The mock layer SHALL be either: (a) the `ib-insync-mock` PyPI package, if it works against `ib_async` (verified by a pre-implementation spike per design D7), or (b) an in-tree fake at `apps/api/tests/_fakes/ib_async_fake.py` providing the IB client surface needed by the adapter (≤8 methods: `connectAsync`, `disconnect`, `reqCurrentTime`, `placeOrder`, `cancelOrder`, `reqAllOpenOrders`, `reqExecutions`, `accountSummary`). CI SHALL run the integration tests `test_ibkr_resilience.py` and `test_reconciliation.py` on every push; failure SHALL block merge.

#### Scenario: Integration tests run without a live TWS

- **WHEN** the CI workflow runs `pytest apps/api/tests/integration/test_ibkr_resilience.py apps/api/tests/integration/test_reconciliation.py`
- **THEN** all tests pass with no IBKR-related environment variables set (`IBKR_HOST`, `IBKR_PORT` etc. are NOT required)
- **AND** the tests complete in under 30 seconds wall-clock (asyncio.sleep fast-forwarded via test fixture)
- **AND** no network connections to ports 7497 / 7496 are attempted

#### Scenario: Operator-driven smoke against TWS Paper (out of CI)

- **WHEN** an operator with TWS Paper running invokes `python -m apps.api.scripts.smoke_ibkr_paper`
- **THEN** the script connects to TWS Paper on port 7497, sends one heartbeat, and disconnects cleanly
- **AND** the script's exit code is 0 on success, non-zero on failure
- **AND** structlog narration is captured to stdout for operator review
- **AND** the script is NOT invoked by CI; it serves as a manual smoke gate before production deploys
