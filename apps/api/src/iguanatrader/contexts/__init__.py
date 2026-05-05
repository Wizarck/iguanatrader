"""Bounded-context root package.

Per AGENTS.md / docs/architecture-decisions.md, every domain bounded
context (``research``, ``trading``, ``risk``, ``approval``,
``observability``) lives under ``apps/api/src/iguanatrader/contexts/``.
This package is intentionally empty — each subpackage owns its own
ORM models, ports, repository, and event declarations.

R1 (``research-bitemporal-schema``) is the first slice to populate
this directory; sibling Wave 2 slices (T1 ``trading-models-interfaces``,
K1 ``risk-models-interfaces``) populate ``trading/`` and ``risk/`` in
parallel.
"""

from __future__ import annotations
