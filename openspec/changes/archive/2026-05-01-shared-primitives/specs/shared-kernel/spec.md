## ADDED Requirements

### Requirement: MessageBus delivers events FIFO per subscriber

The system SHALL provide an in-process `MessageBus` that delivers published events to each subscriber in the order they were published, independent of other subscribers' consumption rate.

#### Scenario: Single subscriber receives events in publication order

- **WHEN** a publisher publishes events `[E1, E2, E3]` in that order
- **AND** a subscriber is registered for the event type
- **THEN** the subscriber's handler is invoked with `E1`, then `E2`, then `E3`, in that order

#### Scenario: Slow subscriber does not block fast subscriber

- **WHEN** subscriber A handles events in 1ms and subscriber B blocks for 100ms per event
- **AND** the publisher publishes 10 events
- **THEN** subscriber A finishes processing all 10 events before subscriber B finishes the second
- **AND** both subscribers eventually receive all 10 events in publication order

#### Scenario: Idempotency key suppresses duplicate delivery within window

- **WHEN** a subscriber is registered with `idempotent=True`
- **AND** the publisher publishes two events with the same `idempotency_key` within the dedup window
- **THEN** the subscriber's handler is invoked exactly once

### Requirement: BaseRepository reads session and tenant scope from ContextVars

The system SHALL provide a `BaseRepository` class that reads its database session from a module-level `session_var: ContextVar[AsyncSession]` and never accepts a session as a constructor argument.

#### Scenario: Repository uses session from ContextVar

- **WHEN** `session_var` is set to an `AsyncSession` and a `BaseRepository` subclass instance is constructed without arguments
- **THEN** the repository operates against the session in `session_var`

#### Scenario: Repository raises if session ContextVar is unset

- **WHEN** `session_var` has no value set in the current async context
- **AND** a `BaseRepository` method is called
- **THEN** the method raises `LookupError` (or a wrapping `IguanaError`) before issuing any SQL

#### Scenario: tenant_id ContextVar is independent of session ContextVar

- **WHEN** `tenant_id_var` is set to a UUID and `session_var` is set to a session
- **THEN** both ContextVars are readable from any coroutine in the same async task tree
- **AND** resetting either does not affect the other

### Requirement: Money values are Decimal-based with explicit currency

The system SHALL provide a `Money` value object that stores amount as `decimal.Decimal` and currency as an ISO 4217 alphabetic code, and SHALL prohibit float arithmetic on monetary values.

#### Scenario: Money rejects float input at construction

- **WHEN** `Money(amount=1.5, currency="USD")` is called with a `float`
- **THEN** construction raises `TypeError` (or `ValidationError`)

#### Scenario: Same-currency arithmetic is exact

- **WHEN** `Money(Decimal("0.1"), "USD") + Money(Decimal("0.2"), "USD")` is computed
- **THEN** the result equals `Money(Decimal("0.3"), "USD")` exactly (no float drift)

#### Scenario: Cross-currency arithmetic raises

- **WHEN** `Money(Decimal("100"), "USD") + Money(Decimal("100"), "EUR")` is computed
- **THEN** the operation raises `CurrencyMismatchError`

#### Scenario: Quantization uses banker's rounding at currency precision

- **WHEN** `Money(Decimal("1.005"), "USD").quantize()` is called
- **THEN** the result equals `Money(Decimal("1.00"), "USD")` (ROUND_HALF_EVEN, USD precision = 2)

### Requirement: tenant_id ContextVar carries scope across async boundaries

The system SHALL provide a `tenant_id_var: ContextVar[UUID | None]` that auth middleware sets at request start and persistence listeners read at query execution.

#### Scenario: ContextVar value propagates across await

- **WHEN** `tenant_id_var.set(t1)` is called in coroutine A
- **AND** coroutine A awaits coroutine B
- **THEN** coroutine B reads `tenant_id_var.get()` as `t1`

#### Scenario: Helper context manager scopes tenant_id

- **WHEN** `async with with_tenant_context(t1):` is entered and an inner block reads `tenant_id_var`
- **THEN** the inner block reads `t1`
- **AND** after the context manager exits, `tenant_id_var` returns to its previous value (or unset)

### Requirement: Error hierarchy maps to RFC 7807 Problem Details fields

The system SHALL provide a root `IguanaError` exception class with attributes `type` (URI string), `title` (short summary), `status` (HTTP status code int), `detail` (longer explanation, optional), and `instance` (specific occurrence URI, optional). Subclasses SHALL set sane defaults for `type`, `title`, and `status`.

#### Scenario: ValidationError has status 400

- **WHEN** `ValidationError("field required")` is constructed
- **THEN** the exception has `status == 400`, `title == "Validation Error"` (or equivalent), and a `type` URI distinct from other subclasses

#### Scenario: Subclass list covers required HTTP semantic codes

- **GIVEN** the IguanaError hierarchy
- **THEN** subclasses exist for status codes 400, 401, 403, 404, 409, 429, 500, 502
- **AND** each subclass carries a unique `type` URI

#### Scenario: IguanaError serializes to dict matching RFC 7807

- **WHEN** `err.to_problem_dict()` is called on any `IguanaError` instance
- **THEN** the returned dict contains keys `type`, `title`, `status`, and conditionally `detail` and `instance` if set
- **AND** no extra keys leak (so the FastAPI handler in slice 5 can serialize directly)

### Requirement: Time helpers enforce UTC and ISO 8601

The system SHALL provide `now()`, `parse_iso8601(s)`, and `format_iso8601(dt)` functions that operate exclusively on timezone-aware UTC datetimes and use the canonical ISO 8601 format `YYYY-MM-DDTHH:MM:SS.ffffffZ`.

#### Scenario: now() returns UTC-aware datetime

- **WHEN** `now()` is called
- **THEN** the returned datetime has `tzinfo == timezone.utc`

#### Scenario: parse_iso8601 rejects naive input

- **WHEN** `parse_iso8601("2026-05-01T10:00:00")` is called (no `Z` or offset)
- **THEN** the function raises `ValidationError`

#### Scenario: format_iso8601 emits Z suffix not +00:00

- **WHEN** `format_iso8601(now())` is called
- **THEN** the resulting string ends with `Z` and does not contain `+00:00`

#### Scenario: parse → format roundtrip is identity for canonical strings

- **GIVEN** a canonical string `s = "2026-05-01T10:00:00.123456Z"`
- **WHEN** `format_iso8601(parse_iso8601(s))` is computed
- **THEN** the result equals `s`

### Requirement: HeartbeatMixin provides idempotent connection state transitions

The system SHALL provide a `HeartbeatMixin` class that adapters inherit to expose a `{CONNECTED, RECONNECTING, DISCONNECTED}` state machine where every public transition method (`mark_connected`, `mark_disconnected`, `mark_reconnecting`) is idempotent.

#### Scenario: Repeated mark_connected has no effect after the first

- **GIVEN** an adapter inheriting `HeartbeatMixin` in state `CONNECTED`
- **WHEN** `mark_connected()` is called twice in a row
- **THEN** the state remains `CONNECTED` and no `_on_connected` side-effect fires the second time

#### Scenario: Disconnect → reconnect cycle uses canonical backoff

- **WHEN** an adapter transitions `CONNECTED → DISCONNECTED` and the reconnection loop runs
- **THEN** consecutive reconnect attempts wait `3, 6, 12, 24, 48` seconds (per `backoff_seconds`)
- **AND** further attempts continue waiting `48` seconds (cap)

### Requirement: Canonical exponential backoff sequence

The system SHALL provide a `backoff_seconds(attempt: int) -> int` function returning the sequence `[3, 6, 12, 24, 48]` indexed by `attempt` (zero-based), capped at `48` for `attempt >= 4`.

#### Scenario: Sequence values are exact and monotonically non-decreasing

- **WHEN** `backoff_seconds(0..6)` is computed
- **THEN** the values are `[3, 6, 12, 24, 48, 48, 48]`
- **AND** the sequence is monotonically non-decreasing

#### Scenario: Negative attempt raises

- **WHEN** `backoff_seconds(-1)` is called
- **THEN** the function raises `ValueError`

#### Scenario: Optional jitter stays within ±20%

- **GIVEN** `with_jitter=True`
- **WHEN** `backoff_seconds(0, with_jitter=True)` is sampled 1000 times
- **THEN** every sample is within the closed interval `[2.4, 3.6]` (3 ± 20%)

### Requirement: Port abstract base uses Protocol structural typing

The system SHALL provide a `Port` abstract base implemented as `typing.Protocol` so that adapter classes satisfy the contract by structural conformance (duck typing) verified at type-check time, not by inheritance.

#### Scenario: Adapter without inheriting Port satisfies the protocol

- **GIVEN** a class `MyAdapter` that defines all methods declared in a `Port` subtype
- **WHEN** `mypy --strict` checks code that passes `MyAdapter()` where the `Port` subtype is expected
- **THEN** type checking succeeds

#### Scenario: Adapter missing a method fails type check

- **GIVEN** a class `MyAdapter` that omits a method declared in a `Port` subtype
- **WHEN** `mypy --strict` checks code that passes `MyAdapter()` where the `Port` subtype is expected
- **THEN** type checking fails with a clear "missing attribute" error

### Requirement: shared/ has no domain dependencies

The system SHALL prevent any module under `apps/api/src/iguanatrader/shared/` from importing modules under `apps/api/src/iguanatrader/contexts/`, `apps/api/src/iguanatrader/api/`, `apps/api/src/iguanatrader/persistence/`, or `apps/api/src/iguanatrader/cli/`.

#### Scenario: Static import check rejects domain imports

- **WHEN** the slice's `tasks.md` import-boundary linter step (or pre-commit hook) scans `apps/api/src/iguanatrader/shared/**/*.py`
- **THEN** any line matching `from iguanatrader\.(contexts|api|persistence|cli)` causes the check to fail

#### Scenario: shared imports only stdlib + a small allowlist

- **GIVEN** the shared kernel as shipped in this slice
- **WHEN** imports are inventoried
- **THEN** every import resolves to a Python standard library module OR to another module under `apps/api/src/iguanatrader/shared/`
- **AND** no third-party runtime package is imported (test code under `apps/api/tests/property/` and `apps/api/tests/unit/shared/` may use `hypothesis` and `pytest`)
