"""Shared kernel — dependency-free primitives consumed by every bounded context.

This package is intentionally minimal: stdlib-only, zero domain knowledge,
zero imports from ``iguanatrader.contexts``, ``iguanatrader.api``,
``iguanatrader.persistence``, or ``iguanatrader.cli``. The boundary check
hook in ``.pre-commit-config.yaml`` enforces that constraint statically.

The public surface (semver-locked from slice 2 onwards):

* :mod:`iguanatrader.shared.time` — UTC + ISO 8601 helpers
* :mod:`iguanatrader.shared.contextvars` — ``tenant_id_var``, ``session_var``,
  ``with_tenant_context``
* :mod:`iguanatrader.shared.errors` — :class:`IguanaError` hierarchy + RFC 7807
* :mod:`iguanatrader.shared.decimal_utils` — banker's rounding helpers
* :mod:`iguanatrader.shared.types` — :class:`Money` value object
* :mod:`iguanatrader.shared.backoff` — canonical exponential backoff
* :mod:`iguanatrader.shared.heartbeat` — :class:`HeartbeatMixin`
* :mod:`iguanatrader.shared.messagebus` — in-process FIFO-per-subscriber bus
* :mod:`iguanatrader.shared.kernel` — :class:`BaseRepository`
* :mod:`iguanatrader.shared.ports` — :class:`Port` Protocol root

structlog event-name convention (config lands in slice O1):

    ``<context>.<entity>.<action>``

For shared-kernel events, ``<context> == "shared"`` (e.g.
``shared.messagebus.publish``, ``shared.heartbeat.reconnect``). Bounded
contexts substitute their own (e.g. ``trading.proposal.created``).
"""
