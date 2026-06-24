## ADDED Requirements

### Requirement: Feature-flagged native IBKR bracket on entry

The system SHALL submit an entry order as a native IBKR bracket — a parent market entry plus a child stop-loss (`STP`, reverse side, trigger = the proposal's `stop_price`) and an optional child take-profit (`LMT`, reverse side, limit = the proposal's `target_price`) — when the `IGUANATRADER_NATIVE_BRACKET` feature flag is enabled AND the order carries a protective `stop_price`. The children SHALL be linked to the parent (`parentId`) and transmitted atomically, and SHALL share an OCA group when both exist so a fill on one cancels the other. The flag SHALL default OFF; when OFF the system SHALL submit the order exactly as before (a single naked order).

#### Scenario: Buy entry with stop and target becomes a bracket

- **GIVEN** the native-bracket flag is ON
- **WHEN** a BUY entry with a `stop_price` and a `target_price` is placed
- **THEN** the broker receives a parent BUY market order, a SELL `STP` child at the stop price, and a SELL `LMT` child at the target price, and `place_order` returns the parent's broker order id

#### Scenario: Stop-only entry omits the take-profit leg

- **GIVEN** the native-bracket flag is ON
- **WHEN** an entry with a `stop_price` but no `target_price` is placed
- **THEN** the bracket contains the parent and the protective `STP` child only, with no take-profit leg

#### Scenario: Flag OFF keeps the single-order path

- **GIVEN** the native-bracket flag is OFF (default)
- **WHEN** an entry carrying a `stop_price` is placed
- **THEN** the broker receives a single naked order (no bracket), identical to the pre-change behavior

#### Scenario: Flag ON but no protective stop falls back to a single order

- **GIVEN** the native-bracket flag is ON
- **WHEN** an entry with no `stop_price` is placed
- **THEN** the broker receives a single naked order (no bracket)

### Requirement: Broker bracket and cron stop-sweeps are mutually exclusive

The system SHALL NOT run the daemon's `stop_hit_sweep` or `trailing_stop_sweep` cron routines while native brackets are enabled, because a broker-side resting stop and a daemon-side close would both act on the same position and double-close it. When the flag is enabled the daemon SHALL skip constructing and registering those sweeps; when disabled it SHALL wire them as before. The daemon SHALL record which protection model is active.

#### Scenario: Native bracket disables the cron sweeps

- **GIVEN** the native-bracket flag is ON
- **WHEN** the daemon boots
- **THEN** neither the stop-hit sweep nor the trailing-stop sweep is registered, and the daemon logs the active protection model as broker-side bracket

#### Scenario: Flag off keeps the cron sweeps wired

- **GIVEN** the native-bracket flag is OFF
- **WHEN** the daemon boots
- **THEN** the stop-hit and trailing-stop sweeps are constructed and registered exactly as before

### Requirement: Bracket submission is idempotent on client_order_id

The system SHALL dedupe a repeated bracket submission carrying the same `client_order_id` within the adapter's idempotency cache, returning the cached broker order id without a second broker submission.

#### Scenario: Repeat client_order_id submits once

- **GIVEN** the native-bracket flag is ON and an entry was already placed as a bracket
- **WHEN** the same `client_order_id` is placed again in the same session
- **THEN** exactly one bracket reaches the broker and the cached parent broker order id is returned
