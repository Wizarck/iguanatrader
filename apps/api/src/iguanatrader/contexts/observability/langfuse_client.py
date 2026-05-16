"""Langfuse SaaS client wrapper — cross-stack LLM observability.

Slice ``llm-observability-and-signals``. Wraps the Langfuse Python SDK
(v3.x, OpenTelemetry-based) behind a small typed surface so the rest
of the codebase never imports ``langfuse`` directly. Three reasons:

1. **Optional dependency at runtime**: when ``LANGFUSE_PUBLIC_KEY`` /
   ``LANGFUSE_SECRET_KEY`` are unset (dev, test, first-boot, or any
   environment that opts out of telemetry), every call routes to a
   no-op so call-sites do not have to branch on ``if langfuse_enabled``.

2. **Tag-shape contract**: every observation MUST carry
   ``metadata.consumer="iguanatrader"`` + ``metadata.application=<app>``
   so it bucket-aggregates correctly in the ELIGIA dashboard
   ``Top by Consumer`` / ``Top by Application`` widgets. The wrapper
   stamps the consumer literal in one place; callers only pass
   ``application``. Source: ``dashboard/backend/routes/langfuse.py``
   ``_obs_metadata_tag`` resolution chain (eligia-core).

3. **No-op identity for tests**: tests construct the wrapper with the
   creds missing and assert call-site behaviour without an SDK
   roundtrip; integration tests can flip an env-var override to verify
   the real SDK is invoked with the expected payload shape.

The Langfuse SDK is **thread-safe + lazy-flushing**. Boot-time
``init_langfuse(env)`` constructs the singleton; FastAPI lifespan
shutdown (and CLI atexit) call :func:`shutdown_langfuse` to flush
before terminating the worker.
"""

from __future__ import annotations

import functools
import inspect
import os
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Literal, TypeVar, cast

import structlog

from iguanatrader.shared.contextvars import tenant_id_var

if TYPE_CHECKING:
    from langfuse import Langfuse

log = structlog.get_logger("iguanatrader.contexts.observability.langfuse_client")

T = TypeVar("T")

#: Fixed consumer literal — the ELIGIA dashboard's ``Top by Consumer``
#: widget aggregates by ``metadata.consumer``; iguanatrader publishes
#: under this single bucket so all four module-applications nest under
#: one consumer row.
_CONSUMER_LITERAL: Literal["iguanatrader"] = "iguanatrader"


# --------------------------------------------------------------------------- #
# No-op surface — used when the SDK is disabled (missing creds / import fail)
# --------------------------------------------------------------------------- #


class _NoOpObservation:
    """No-op stand-in for a Langfuse observation (span or generation).

    Mirrors the subset of the real SDK surface that wrapper consumers
    touch: :meth:`update`, :meth:`end`, :meth:`start_observation`,
    :meth:`generation`. ``.generation()`` is wrapper-specific syntactic
    sugar that maps to ``start_observation(as_type="generation")`` on
    the real SDK.
    """

    def update(self, **kwargs: Any) -> _NoOpObservation:
        return self

    def end(self, **kwargs: Any) -> _NoOpObservation:
        return self

    def generation(self, **kwargs: Any) -> _NoOpObservation:
        return self

    def start_observation(self, **kwargs: Any) -> _NoOpObservation:
        return self


# --------------------------------------------------------------------------- #
# Singleton state
# --------------------------------------------------------------------------- #


_client: Langfuse | None = None
_enabled: bool = False
_env_tag: str = "dev"


def _build_real_client() -> Langfuse | None:
    """Instantiate the real Langfuse SDK client from env vars.

    Returns ``None`` when ``LANGFUSE_PUBLIC_KEY`` or
    ``LANGFUSE_SECRET_KEY`` is unset — observability is opt-in and
    missing creds is the documented disabled state.
    """
    pk = os.environ.get("LANGFUSE_PUBLIC_KEY")
    sk = os.environ.get("LANGFUSE_SECRET_KEY")
    host = os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
    if not pk or not sk:
        return None
    try:
        from langfuse import Langfuse as _Langfuse

        return _Langfuse(
            public_key=pk,
            secret_key=sk,
            host=host,
        )
    except Exception as exc:  # pragma: no cover — import / construct failure path
        log.warning(
            "observability.langfuse.init_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return None


def init_langfuse(env: str) -> None:
    """Construct the process-global Langfuse client for ``env``.

    Idempotent — calling twice rebinds the global. Stores ``env`` in a
    module-level so every published observation carries
    ``metadata.env`` without callers passing it.

    When creds are missing or the SDK init raises, the global stays
    ``None`` and all ``start_trace`` / ``start_generation`` calls fall
    through to :class:`_NoOpObservation`. The structlog event
    ``observability.langfuse.disabled`` documents this in JSON logs.
    """
    global _client, _enabled, _env_tag
    _env_tag = env or "unknown"
    _client = _build_real_client()
    _enabled = _client is not None
    if _enabled:
        log.info("observability.langfuse.initialised", env=_env_tag)
    else:
        log.info(
            "observability.langfuse.disabled",
            env=_env_tag,
            reason="missing-credentials-or-sdk-import-failed",
        )


def shutdown_langfuse() -> None:
    """Flush the Langfuse queue + null the client.

    Called from the FastAPI lifespan shutdown hook and the CLI atexit
    handler so background batches are flushed before the worker exits.
    Safe to call when the client was never initialised — short-circuits
    on ``_client is None``.
    """
    global _client, _enabled
    if _client is None:
        return
    try:
        _client.flush()
    except Exception as exc:  # pragma: no cover — flush is best-effort
        log.warning(
            "observability.langfuse.flush_failed",
            error=str(exc),
            error_type=type(exc).__name__,
        )
    _client = None
    _enabled = False


def is_enabled() -> bool:
    """Return whether the process-global Langfuse client is bound."""
    return _enabled


def get_client() -> Langfuse | None:
    """Return the process-global Langfuse client (or ``None`` if disabled).

    Exposed for the rare call-site that needs to manipulate the SDK
    directly (e.g. attaching scores after the fact). Most code should
    use :func:`start_generation` / :func:`start_trace`.
    """
    return _client


# --------------------------------------------------------------------------- #
# Tag-shape contract — every observation MUST carry these
# --------------------------------------------------------------------------- #


def _build_metadata(application: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    """Assemble the canonical metadata block for an observation.

    Stamps ``consumer="iguanatrader"`` + ``application`` + ``env`` +
    ``tenant_id`` (when bound). The ELIGIA dashboard reads
    ``metadata.consumer`` / ``metadata.application`` for the
    cost-by-tag widgets, ``metadata.env`` for environment filters,
    and ``metadata.tenant_id`` is iguanatrader-specific for per-tenant
    drill-down inside the Langfuse Cloud UI.
    """
    tenant = tenant_id_var.get()
    md: dict[str, Any] = {
        "consumer": _CONSUMER_LITERAL,
        "application": application,
        "env": _env_tag,
    }
    if tenant is not None:
        md["tenant_id"] = str(tenant)
    if extra:
        # Caller extras win on key collision — caller intent is local.
        md.update(extra)
    return md


# --------------------------------------------------------------------------- #
# Public surface — trace + generation helpers
# --------------------------------------------------------------------------- #


def start_trace(
    name: str,
    application: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> Any:
    """Open a Langfuse parent span for a multi-step LLM pipeline.

    In SDK v3 a "trace" is the top-level span; nested generations
    attach via ``parent.start_observation(as_type="generation", ...)``.
    Returns the real span when enabled, else a :class:`_NoOpObservation`.
    Both expose ``.generation(...)`` / ``.start_observation(...)`` /
    ``.update(...)`` / ``.end(...)`` for caller-side uniformity.

    Wrap the returned object with a wrapper-specific ``generation()``
    method so call-sites have a stable shape independent of SDK
    version.
    """
    if not _enabled or _client is None:
        return _NoOpObservation()
    md = _build_metadata(application, metadata)
    raw = _client.start_observation(
        name=name,
        as_type="span",
        metadata=md,
    )
    return _TraceWrapper(raw)


def start_generation(
    name: str,
    *,
    model: str,
    application: str,
    input_data: Any = None,
    metadata: dict[str, Any] | None = None,
    trace: Any = None,
) -> Any:
    """Open a Langfuse generation span for a single LLM call.

    Pass ``trace`` to nest under a parent span (e.g. the synthesizer's
    trace); omit it when the call-site is standalone (SDK creates an
    implicit top-level trace).

    Always call :meth:`update` with the response payload + usage tokens
    + ``level`` (DEFAULT on success, ERROR on exception) once the LLM
    response arrives; without ``usage_details`` Langfuse cannot
    compute ``calculatedTotalCost`` and the cost widgets will be blank
    for this row.
    """
    md = _build_metadata(application, metadata)
    if not _enabled or _client is None:
        return _NoOpObservation()
    if trace is not None and isinstance(trace, _TraceWrapper):
        return trace.generation(
            name=name,
            model=model,
            input=input_data,
            metadata=md,
        )
    if trace is not None and isinstance(trace, _NoOpObservation):
        return trace
    return _client.start_observation(
        name=name,
        as_type="generation",
        model=model,
        input=input_data,
        metadata=md,
    )


class _TraceWrapper:
    """Wraps a real :class:`LangfuseSpan` with the wrapper's stable API.

    Exposes ``.generation(...)`` as a thin alias for
    ``start_observation(as_type="generation", ...)`` so call-sites
    don't have to know v3-specific kwargs. Forwards ``.update`` and
    ``.end`` straight through.
    """

    def __init__(self, raw: Any) -> None:
        self._raw = raw

    def generation(
        self,
        *,
        name: str,
        model: str,
        input: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> Any:
        return self._raw.start_observation(
            name=name,
            as_type="generation",
            model=model,
            input=input,
            metadata=metadata,
        )

    def update(self, **kwargs: Any) -> _TraceWrapper:
        self._raw.update(**kwargs)
        return self

    def end(self, **kwargs: Any) -> _TraceWrapper:
        self._raw.end(**kwargs)
        return self


# --------------------------------------------------------------------------- #
# Decorator surface — convenience for call-sites
# --------------------------------------------------------------------------- #


def traced_generation(
    name: str,
    *,
    model: str | Callable[..., str],
    application: str,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator: open + close a generation span around the wrapped callable.

    ``model`` may be a static string OR a callable that receives the
    wrapped function's ``(*args, **kwargs)`` and returns the model id.

    The decorator is sync/async aware. On exception it sets the span
    ``level="ERROR"`` with the exception's repr, then re-raises so
    error semantics are unchanged.

    The wrapped function's return value is NOT introspected — populating
    ``output`` / ``usage_details`` is the call-site's responsibility
    because the LLM response shape varies per provider. Call-sites use
    :func:`start_generation` directly when they need to update the
    span body with usage tokens.
    """

    def _resolve_model(*args: Any, **kwargs: Any) -> str:
        if callable(model):
            return model(*args, **kwargs)
        return model

    def _decorator(fn: Callable[..., T]) -> Callable[..., T]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def _async_wrapper(*args: Any, **kwargs: Any) -> T:
                resolved_model = _resolve_model(*args, **kwargs)
                gen = start_generation(name=name, model=resolved_model, application=application)
                try:
                    result = await cast("Callable[..., Awaitable[T]]", fn)(*args, **kwargs)
                    gen.end(level="DEFAULT")
                    return result
                except Exception as exc:
                    gen.end(
                        level="ERROR",
                        status_message=f"{type(exc).__name__}: {exc!s}",
                    )
                    raise

            return cast("Callable[..., T]", _async_wrapper)

        @functools.wraps(fn)
        def _sync_wrapper(*args: Any, **kwargs: Any) -> T:
            resolved_model = _resolve_model(*args, **kwargs)
            gen = start_generation(name=name, model=resolved_model, application=application)
            try:
                result = fn(*args, **kwargs)
                gen.end(level="DEFAULT")
                return result
            except Exception as exc:
                gen.end(
                    level="ERROR",
                    status_message=f"{type(exc).__name__}: {exc!s}",
                )
                raise

        return _sync_wrapper

    return _decorator


__all__ = [
    "get_client",
    "init_langfuse",
    "is_enabled",
    "shutdown_langfuse",
    "start_generation",
    "start_trace",
    "traced_generation",
]
