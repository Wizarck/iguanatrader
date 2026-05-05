"""``observability`` bounded context — cost meter, throttle, routing, budget, audit.

Owns the following primitives (planted by slice O1
``observability-cost-meter``):

- :mod:`.cost_meter` — ``@cost_meter(provider, model)`` decorator that
  records every LLM call into ``api_cost_events`` (FR40, NFR-O1, NFR-O7).
- :mod:`.perplexity_throttle` — in-process sliding-window rate-limit per
  NFR-I4 (Perplexity 60 RPM hard cap).
- :mod:`.llm_routing` — rule-based routing of task class → model tier
  (FR39); single chokepoint for budget gating.
- :mod:`.budget` — per-tenant monthly budget cap with WARN_80 +
  BLOCK_100 semantics; auto-downgrade on WARN_80 (FR41).
- :mod:`.replay_cache` — deterministic test-mode LLM replay cache
  (``IGUANATRADER_LLM_REPLAY=1``).
- :mod:`.cost_dashboard_publisher` — 5-minute aggregation publisher
  emitting ``observability.cost.snapshot`` MessageBus events (NFR-O4).
- :mod:`.structlog_config` — env-aware structlog configuration; lands
  ``RotatingFileHandler`` 100 MB / 7 backups for paper / live (NFR-O3).
- :mod:`.otel` — port-only OTEL stub; ``@traced`` / ``@metered`` decorators
  are no-ops MVP, swapped for OTLP exporters in v2 SaaS.
- :mod:`.models` — ORM mappings for ``api_cost_events``, ``config_changes``,
  ``audit_log`` (all append-only).
- :mod:`.repository` — :class:`BaseRepository` subclasses for the three
  observability tables.
- :mod:`.events` — Pydantic payloads for the bounded-context's bus events.
- :mod:`.ports` — :class:`Protocol` declarations for swap-in dependencies
  (``LLMProvider``, ``PriceTable``, ``ClockPort``).
- :mod:`.errors` — slice-local :class:`IguanaError` subclasses
  (``BudgetExceededError``, ``PerplexityRateLimitError``,
  ``ReplayCacheMissError``).

Boundary contract: nothing under :mod:`iguanatrader.contexts` (other
contexts) may import from this package's internals. The public surface
is the cost-meter / throttle / routing / budget functions, the bus
events declared in :mod:`.events`, and the DTOs in
:mod:`iguanatrader.api.dtos.observability`.
"""

from __future__ import annotations

# Eager import of the ORM models so :data:`iguanatrader.persistence.base.Base`
# registry sees them when the slice-3 tenant listener walks
# ``Base.registry.mappers``. Without this import, the listener cannot
# inject the audit_log NULL-tenant filter (per design D8) because the
# mapper is unknown until the model module is imported by some caller.
# Side-effect import; the symbols are re-exported below for callers.
from iguanatrader.contexts.observability import models as _models  # noqa: F401
