## 1. Setup + dependencies

- [x] 1.1 Verify `hypothesis` is in `[tool.poetry.group.dev.dependencies]` in `pyproject.toml`; add if missing (no version pin tighter than `^6.0`).
- [x] 1.2 Create the package skeleton: `apps/api/src/iguanatrader/__init__.py` and `apps/api/src/iguanatrader/shared/__init__.py` (both empty placeholders so Python recognizes the package).
- [x] 1.3 Create the test directory skeleton: `apps/api/tests/__init__.py`, `apps/api/tests/unit/__init__.py`, `apps/api/tests/unit/shared/__init__.py`, `apps/api/tests/property/__init__.py`.
- [x] 1.4 Verify `mypy --strict` passes on the empty `shared/` package (sanity check that slice 1's mypy config sees the new path).

## 2. Time + ContextVars + Errors (foundations consumed by everything else)

- [x] 2.1 Implement `apps/api/src/iguanatrader/shared/time.py` — `now()` returning UTC-aware `datetime`, `parse_iso8601(s)` rejecting naive input, `format_iso8601(dt)` emitting `Z` suffix per design D5.
- [x] 2.2 Implement `apps/api/src/iguanatrader/shared/contextvars.py` — `tenant_id_var: ContextVar[UUID | None]` and `session_var: ContextVar[AsyncSession | None]` (forward-ref `AsyncSession` via `TYPE_CHECKING` to avoid SQLAlchemy import here); plus `with_tenant_context(tenant_id)` async context manager.
- [x] 2.3 Implement `apps/api/src/iguanatrader/shared/errors.py` — `IguanaError` root + 8 subclasses (`ValidationError` 400, `AuthError` 401, `ForbiddenError` 403, `NotFoundError` 404, `ConflictError` 409, `RateLimitError` 429, `IntegrationError` 502, `InternalError` 500) per design D4 + `to_problem_dict()` method on the root.
- [x] 2.4 Add a `CurrencyMismatchError` subclass (or include under `ValidationError` per design D3 cross-currency scenario; pick one and document in the module docstring).
- [x] 2.5 Unit tests `apps/api/tests/unit/shared/test_time.py`, `test_contextvars.py`, `test_errors.py` — cover scenarios from `specs/shared-kernel/spec.md` for these requirements.

## 3. Decimal + Money

- [x] 3.1 Implement `apps/api/src/iguanatrader/shared/decimal_utils.py` — `quantize(amount: Decimal, places: int) -> Decimal` using `ROUND_HALF_EVEN`; helper `currency_precision(currency: str) -> int` returning ISO 4217 minor-unit precision (USD=2, JPY=0, BTC=8 — at least these three; add more on demand).
- [x] 3.2 Implement `apps/api/src/iguanatrader/shared/types.py` — frozen `Money` dataclass with `amount: Decimal` + `currency: str`, `__post_init__` rejecting `float` input, `__add__`/`__sub__`/`__neg__` enforcing same-currency invariant, `quantize()` method using `currency_precision`.
- [x] 3.3 Unit tests `apps/api/tests/unit/shared/test_types.py` — covers float-input rejection, cross-currency error, banker's rounding scenarios.
- [x] 3.4 Property test `apps/api/tests/property/test_decimal_arithmetic.py` (Hypothesis) — for any pair of Decimals, `Money(a) + Money(b) - Money(b) == Money(a)` exactly (no float drift).

## 4. Backoff + HeartbeatMixin

- [x] 4.1 Implement `apps/api/src/iguanatrader/shared/backoff.py` — `backoff_seconds(attempt: int, with_jitter: bool = False) -> float` per design D7 (sequence `[3, 6, 12, 24, 48]` capped, `ValueError` on negative, ±20% jitter when enabled).
- [x] 4.2 Implement `apps/api/src/iguanatrader/shared/heartbeat.py` — `HeartbeatMixin` with state enum `{CONNECTED, RECONNECTING, DISCONNECTED}`, idempotent `mark_connected/mark_disconnected/mark_reconnecting`, abstract async `_send_heartbeat()` and `_on_disconnect()`, reconnection loop using `backoff_seconds`.
- [x] 4.3 Unit tests `apps/api/tests/unit/shared/test_backoff.py` and `test_heartbeat.py` — cover idempotency + state transitions + canonical sequence.
- [x] 4.4 Property test `apps/api/tests/property/test_backoff_monotonicity.py` (Hypothesis) — for `attempt` drawn from `[0, 1000]`, `backoff_seconds(attempt + 1) >= backoff_seconds(attempt)`.
- [x] 4.5 Property test `apps/api/tests/property/test_heartbeat_idempotency.py` (Hypothesis) — for any sequence of `mark_connected/mark_disconnected/mark_reconnecting` calls drawn from a state-machine grammar, the final state matches the last call's intent and side-effect callbacks fire at most once per real transition.

## 5. MessageBus

- [x] 5.1 Implement `apps/api/src/iguanatrader/shared/messagebus.py` — generic `Event` base, `MessageBus` with `subscribe(event_type, handler, *, idempotent=False)`, `publish(event)`, per-subscriber `asyncio.Queue`, dedup window for idempotent subscribers per design D1.
- [x] 5.2 Unit test `apps/api/tests/unit/shared/test_messagebus.py` — cover scenarios: FIFO single-subscriber, slow-vs-fast subscribers don't head-of-line block each other, idempotency dedup.
- [x] 5.3 Property test `apps/api/tests/property/test_message_ordering.py` (Hypothesis) — for any sequence of `N` distinct events published, every subscriber's observed sequence equals the publication sequence.

## 6. Kernel (BaseRepository) + Ports

- [ ] 6.1 Implement `apps/api/src/iguanatrader/shared/kernel.py` — `BaseRepository` reading `session_var`, raising `LookupError` (or wrapping `IguanaError`) when unset; helper `propagate_tenant_to(coro)` for `asyncio.create_task` callers per design risk-mitigation.
- [ ] 6.2 Implement `apps/api/src/iguanatrader/shared/ports.py` — abstract `Port = Protocol` (PEP 544) with no methods (concrete subtypes added in T1/R1); export marker for downstream slices.
- [ ] 6.3 Unit test `apps/api/tests/unit/shared/test_kernel.py` — covers ContextVar resolution, LookupError when unset, ContextVar isolation across async tasks.

## 7. Boundary enforcement + structlog convention

- [ ] 7.1 Add an import-boundary check (script under `apps/api/scripts/check_shared_boundary.py` OR inline in `.pre-commit-config.yaml` as a regex hook) that scans `apps/api/src/iguanatrader/shared/**/*.py` and fails on any `from iguanatrader\.(contexts|api|persistence|cli)` line per spec requirement "shared/ has no domain dependencies".
- [ ] 7.2 Wire the boundary check into `.pre-commit-config.yaml` so it runs locally + in CI.
- [ ] 7.3 Document the structlog event-name convention `<context>.<entity>.<action>` in `apps/api/src/iguanatrader/shared/__init__.py` module docstring (no logger config yet; that's slice O1).

## 8. Verification + acceptance gate

- [ ] 8.1 `mypy --strict apps/api/src/iguanatrader/shared/` exits 0.
- [ ] 8.2 `pytest apps/api/tests/unit/shared/ apps/api/tests/property/` exits 0 with all tests passing.
- [ ] 8.3 Coverage ≥80% on `apps/api/src/iguanatrader/shared/*` (per NFR-M1) — record the coverage number in PR description.
- [ ] 8.4 `pre-commit run --from-ref origin/main --to-ref HEAD` passes (gitleaks + ruff + black + mypy strict + check-toml + new boundary check).
- [ ] 8.5 Append any non-obvious lessons to `docs/gotchas.md` (per per-slice acceptance template).
- [ ] 8.6 PR description includes: scope summary, coverage number, AI-reviewer signoff section per `.ai-playbook/specs/release-management.md` §4.5 (left empty until CodeRabbit comments are addressed).
