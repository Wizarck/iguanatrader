"""Bounded-context root package.

Per AGENTS.md / docs/architecture-decisions.md, every domain bounded
context lives under ``apps/api/src/iguanatrader/contexts/``. Wave 2
slices populating this directory:

* ``research`` — slice R1 (bitemporal facts + provenance)
* ``trading`` — slice T1 (models + ports + service skeleton)
* ``risk`` — slice K1 (engine + 5 protections + kill switch)
* ``approval`` — slice P1 (Telegram + Hermes channels + 17 commands)
* ``observability`` — slice O1 (cost meter + LLM routing + audit log)

This package is intentionally empty — each subpackage owns its own
ORM models, ports, repository, and event declarations. Cross-context
imports are restricted by a ruff rule (slice-2 contract); ``events.py``
paths are excluded so MessageBus event types — the documented
inter-context wire format — can be shared without violating the
boundary.
"""

from __future__ import annotations
