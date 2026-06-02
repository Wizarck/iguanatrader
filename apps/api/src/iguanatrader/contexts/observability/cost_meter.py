"""``@cost_meter(provider, model)`` decorator — records every LLM call.

Per design D1: parametrised decorator factory. Wraps any function that
returns an :class:`LLMResponse` (Protocol with ``tokens_input``,
``tokens_output``, ``cached``); on each invocation the decorator:

1. Reads :data:`tenant_id_var` (per NFR-O7).
2. Calls the wrapped function (sync or async — detected via
   :func:`inspect.iscoroutinefunction`).
3. Computes ``cost_usd`` from the price table for ``(provider, model)``.
4. Persists :class:`ApiCostEvent` via :class:`ApiCostEventRepository`.
5. Emits structlog ``observability.cost.recorded`` (or
   ``observability.cost.upstream_error`` on failure).
6. Returns the unwrapped response.

The price table is a module-level static :class:`dict` (data, not
algorithm). v2 SaaS may switch to a port-injected table for multi-region
pricing.

If :data:`session_var` is unset at call time (callsite outside a
request scope), the cost event is logged but NOT persisted — emitting
the structlog event is best-effort visibility (``persisted=False``).
This avoids hard failures in CLI / test paths where DB context is
not always available.
"""

from __future__ import annotations

import functools
import inspect
import uuid
from collections.abc import Awaitable, Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, TypeVar, cast, overload
from uuid import UUID

import structlog

from iguanatrader.contexts.observability.models import ApiCostEvent
from iguanatrader.contexts.observability.ports import LLMResponse, PriceTable
from iguanatrader.contexts.observability.repository import ApiCostEventRepository
from iguanatrader.shared.contextvars import session_var, tenant_id_var

log = structlog.get_logger("iguanatrader.contexts.observability.cost_meter")

T = TypeVar("T", bound=LLMResponse)
SyncF = Callable[..., T]
AsyncF = Callable[..., Awaitable[T]]
F = AsyncF[T] | SyncF[T]


#: Provider+model price catalogue (USD per million tokens). Values
#: reflect public list pricing as of slice-O1 land date; updates are a
#: data-only edit (no behaviour change). The dict shape is:
#:
#:     {(provider, model): (input_per_million, output_per_million)}
#:
#: Missing entries cause :class:`KeyError`; the wrapper rescues that as
#: a structured-log warning + persists ``cost_usd=0``. This is a soft-
#: fail: an unknown model still records the call (NFR-O1 100%
#: persistence) but with a placeholder cost the operator can correct
#: later by editing the table + replaying.
_PRICE_TABLE_USD_PER_MILLION: dict[tuple[str, str], tuple[Decimal, Decimal]] = {
    # Anthropic (USD per million tokens — input, output).
    ("anthropic", "claude-3-5-sonnet"): (Decimal("3.00"), Decimal("15.00")),
    ("anthropic", "claude-3-5-haiku"): (Decimal("0.80"), Decimal("4.00")),
    ("anthropic", "claude-3-opus"): (Decimal("15.00"), Decimal("75.00")),
    # OpenAI fallback tier.
    ("openai", "gpt-4o-mini"): (Decimal("0.15"), Decimal("0.60")),
    ("openai", "gpt-4o"): (Decimal("2.50"), Decimal("10.00")),
    # Perplexity (online tier).
    ("perplexity", "sonar"): (Decimal("1.00"), Decimal("1.00")),
    ("perplexity", "sonar-pro"): (Decimal("3.00"), Decimal("15.00")),
}


class _StaticPriceTable:
    """Default :class:`PriceTable` adapter backed by :data:`_PRICE_TABLE_USD_PER_MILLION`.

    Tests / future adapters may inject an alternative
    :class:`PriceTable` Protocol implementation.
    """

    def cost_per_million_input(self, provider: str, model: str) -> Decimal:
        return _PRICE_TABLE_USD_PER_MILLION[(provider, model)][0]

    def cost_per_million_output(self, provider: str, model: str) -> Decimal:
        return _PRICE_TABLE_USD_PER_MILLION[(provider, model)][1]


_DEFAULT_PRICE_TABLE: PriceTable = _StaticPriceTable()


def _compute_cost_usd(
    response: LLMResponse,
    *,
    provider: str,
    model: str,
    price_table: PriceTable,
) -> Decimal:
    """Compute USD cost for ``response`` using ``price_table``.

    ``cached=True`` short-circuits to :data:`Decimal("0")` per NFR-I3:
    Anthropic prompt-caching reports the hit at SDK level; the cost
    meter records the call with ``cost_usd=0`` so the dashboard
    correctly attributes the savings.
    """
    if response.cached:
        return Decimal("0")
    try:
        per_in = price_table.cost_per_million_input(provider, model)
        per_out = price_table.cost_per_million_output(provider, model)
    except KeyError:
        log.warning(
            "observability.cost.unknown_model",
            provider=provider,
            model=model,
        )
        return Decimal("0")
    cost = Decimal(response.tokens_input) * per_in / Decimal(1_000_000) + Decimal(
        response.tokens_output
    ) * per_out / Decimal(1_000_000)
    # #19: quantize to the stored column scale (Numeric(12, 6)) at this
    # single point, so an in-memory SUM of per-call costs matches the
    # SUM(cost_usd) the budget check reads back from the DB. Without it the
    # full-precision Decimal is silently rounded on INSERT and the two
    # diverge (the budget gate then trusts a number the DB never stored).
    return cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)


async def _persist_cost_event(
    *,
    tenant_id: UUID,
    provider: str,
    model: str,
    response: LLMResponse,
    cost_usd: Decimal,
    correlation_id: str | None,
) -> bool:
    """Persist one :class:`ApiCostEvent` if a session is bound; else log-only.

    Returns ``True`` iff the row was added to the session. Caller is
    responsible for the eventual ``commit()`` (the request-scoped
    session middleware in slice 5 commits at request end; ad-hoc
    callsites must commit manually).
    """
    session = session_var.get()
    if session is None:
        return False
    repo = ApiCostEventRepository()
    event = ApiCostEvent(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider=provider,
        model=model,
        node=None,
        tokens_input=response.tokens_input,
        tokens_output=response.tokens_output,
        cost_usd=cost_usd,
        cached=response.cached,
        prompt_hash=None,
        metadata_json={},
        routine_run_id=None,
        correlation_id=correlation_id,
    )
    # #20: isolate the metering INSERT in a SAVEPOINT. A failure here
    # (constraint, serialization error) must NEVER abort the caller's
    # business unit-of-work — observability is best-effort. Without the
    # savepoint a failed insert poisons the shared transaction so the
    # request's real writes can't commit either. We roll back just this
    # row and log; the caller proceeds.
    try:
        async with session.begin_nested():
            await repo.insert(event)
    except Exception as exc:
        log.warning(
            "observability.cost.persist_failed",
            provider=provider,
            model=model,
            error=str(exc),
        )
        return False
    return True


class _CostMeterDecorator:
    """Callable wrapper exposing overloads for sync + async wrapped fns.

    Mypy --strict needs overload signatures to narrow ``await fn()`` at
    call sites of decorated coroutines; the protocol-style class lets us
    declare both shapes in one decorator factory.
    """

    def __init__(
        self,
        provider: str,
        model: str,
        *,
        price_table: PriceTable | None = None,
    ) -> None:
        self._provider = provider
        self._model = model
        self._table: PriceTable = price_table or _DEFAULT_PRICE_TABLE

    @overload
    def __call__(self, fn: AsyncF[T]) -> AsyncF[T]: ...

    @overload
    def __call__(self, fn: SyncF[T]) -> SyncF[T]: ...

    def __call__(self, fn: F[T]) -> F[T]:
        return _build_wrapper(fn, self._provider, self._model, self._table)


def cost_meter(
    provider: str,
    model: str,
    *,
    price_table: PriceTable | None = None,
) -> _CostMeterDecorator:
    """Parametrised decorator factory — records the cost of every call.

    Usage::

        @cost_meter(provider="anthropic", model="claude-3-5-sonnet")
        async def synthesize_brief(prompt: str) -> LLMResponse:
            ...

    Async-aware: if the wrapped function is a coroutine function, the
    returned wrapper is also a coroutine function. Synchronous callers
    are supported but DO NOT persist the cost event (no async session
    available); the structlog breadcrumb still fires.
    """
    return _CostMeterDecorator(provider, model, price_table=price_table)


def _build_wrapper(
    fn: F[T],
    provider: str,
    model: str,
    table: PriceTable,
) -> F[T]:
    """Internal helper — produces sync or async wrapper depending on ``fn``."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> T:
            tenant_value = tenant_id_var.get()
            try:
                response = await cast("Callable[..., Awaitable[T]]", fn)(*args, **kwargs)
            except Exception:
                log.warning(
                    "observability.cost.upstream_error",
                    provider=provider,
                    model=model,
                    tenant_id=str(tenant_value) if tenant_value else None,
                )
                raise

            cost_usd = _compute_cost_usd(
                response,
                provider=provider,
                model=model,
                price_table=table,
            )

            persisted = False
            if tenant_value is not None:
                persisted = await _persist_cost_event(
                    tenant_id=tenant_value,
                    provider=provider,
                    model=model,
                    response=response,
                    cost_usd=cost_usd,
                    correlation_id=None,
                )

            log.info(
                "observability.cost.recorded",
                provider=provider,
                model=model,
                tenant_id=str(tenant_value) if tenant_value else None,
                tokens_input=response.tokens_input,
                tokens_output=response.tokens_output,
                cost_usd=str(cost_usd),
                cached=response.cached,
                persisted=persisted,
            )
            return response

        return cast("F[T]", _async_wrapper)

    @functools.wraps(fn)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> T:
        tenant_value = tenant_id_var.get()
        try:
            response = cast("Callable[..., T]", fn)(*args, **kwargs)
        except Exception:
            log.warning(
                "observability.cost.upstream_error",
                provider=provider,
                model=model,
                tenant_id=str(tenant_value) if tenant_value else None,
            )
            raise

        cost_usd = _compute_cost_usd(
            response,
            provider=provider,
            model=model,
            price_table=table,
        )
        log.info(
            "observability.cost.recorded",
            provider=provider,
            model=model,
            tenant_id=str(tenant_value) if tenant_value else None,
            tokens_input=response.tokens_input,
            tokens_output=response.tokens_output,
            cost_usd=str(cost_usd),
            cached=response.cached,
            persisted=False,
        )
        return response

    return cast("F[T]", _sync_wrapper)


__all__ = [
    "cost_meter",
]
