"""OpenTelemetry port stub (per design D7).

Slice O1 declares the OTEL surface — :class:`Tracer` + :class:`Meter`
:class:`Protocol` classes, :func:`traced` + :func:`metered` decorators,
:func:`init_otel` initializer — but the bodies are no-ops in MVP. v2
SaaS replaces the no-op decorator bodies with
``tracer.start_as_current_span(...)`` + meter increments configured
via OTLP exporters; caller-side ``@traced(...)`` usage is wire-stable.

Why declare the ports now: downstream slices (R5 brief synthesis, with
multi-step LLM chains) benefit from ``@traced`` on Day 1 even when no
exporter is wired yet — the no-op decorator is one function-call
indirection, immeasurable in production.

Why no real exporter MVP: the OTEL collector + Grafana / Tempo wiring
is non-trivial; it lives in the v2-SaaS migration ADR (deferred). MVP
saves a moving part for now while keeping the caller-side surface
stable.
"""

from __future__ import annotations

import functools
import inspect
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar, cast, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class Tracer(Protocol):
    """Minimal tracer port — start a span. v2 SaaS swaps in OTLP."""

    def start_span(self, name: str) -> Span:  # pragma: no cover — port surface
        ...


@runtime_checkable
class Span(Protocol):
    """Span Protocol — ``__enter__`` / ``__exit__`` for ``with`` usage."""

    def __enter__(self) -> Span:  # pragma: no cover — port surface
        ...

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:  # pragma: no cover
        ...


@runtime_checkable
class Meter(Protocol):
    """Minimal meter port — record counter / histogram increments."""

    def add(
        self, name: str, value: float, attributes: dict[str, Any] | None = None
    ) -> None:  # pragma: no cover
        ...


class _NoOpSpan:
    """No-op :class:`Span` — used by :class:`_NoOpTracer` until v2."""

    def __enter__(self) -> _NoOpSpan:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None


class _NoOpTracer:
    """No-op :class:`Tracer` — :func:`start_span` returns a :class:`_NoOpSpan`."""

    def start_span(self, name: str) -> Span:
        return cast(Span, _NoOpSpan())


class _NoOpMeter:
    """No-op :class:`Meter` — :func:`add` swallows the increment."""

    def add(
        self,
        name: str,
        value: float,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        return None


_tracer: Tracer = _NoOpTracer()
_meter: Meter = _NoOpMeter()


def get_tracer() -> Tracer:
    """Return the process-global tracer (no-op MVP, OTLP v2 SaaS)."""
    return _tracer


def get_meter() -> Meter:
    """Return the process-global meter (no-op MVP, OTLP v2 SaaS)."""
    return _meter


def traced(span_name: str) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """No-op MVP tracing decorator — wire-stable for v2 swap.

    Async-aware: if the wrapped callable is a coroutine function, the
    returned wrapper is too. v2 SaaS replaces the body with
    ``with get_tracer().start_span(span_name): return await fn(...)``.
    """

    def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> T:
                return await cast("Callable[..., Awaitable[T]]", fn)(*args, **kwargs)

            return cast("Callable[..., T]", _async_wrapper)

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return fn(*args, **kwargs)

        return _sync_wrapper

    return _decorator


def metered(
    metric_name: str,
    *,
    kind: str = "counter",
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """No-op MVP metric decorator — wire-stable for v2 swap.

    ``kind`` accepts ``counter`` / ``histogram`` / ``gauge``; v2 SaaS
    routes to the matching meter primitive.
    """

    def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> T:
                return await cast("Callable[..., Awaitable[T]]", fn)(*args, **kwargs)

            return cast("Callable[..., T]", _async_wrapper)

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return fn(*args, **kwargs)

        return _sync_wrapper

    return _decorator


def init_otel(env: str) -> None:
    """Initialise OTEL ports for ``env``.

    MVP: registers :class:`_NoOpTracer` + :class:`_NoOpMeter` as the
    process globals; safe to call multiple times. v2 SaaS replaces
    this body with OTLP exporter wiring driven by env vars
    (``OTEL_EXPORTER_OTLP_ENDPOINT`` etc.).
    """
    global _tracer, _meter
    _tracer = _NoOpTracer()
    _meter = _NoOpMeter()


__all__ = [
    "Meter",
    "Span",
    "Tracer",
    "get_meter",
    "get_tracer",
    "init_otel",
    "metered",
    "traced",
]
