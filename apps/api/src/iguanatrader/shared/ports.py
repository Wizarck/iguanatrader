"""Port abstract base — PEP 544 :class:`Protocol` for the hexagonal pattern.

Per design decision D8 (slice 2 ``shared-primitives``): bounded contexts
declare their dependencies as ``Protocol`` subtypes — duck-typed
structural interfaces — rather than ABC inheritance. Adapter classes
satisfy the contract by providing the right method signatures;
``mypy --strict`` enforces conformance at type-check time.

This module exports the abstract :class:`Port` marker so downstream
slices have a single import to extend. Concrete subtypes
(:class:`BrokerPort`, :class:`StrategyPort`, :class:`SourcePort`, …)
land in the slices that own their bounded context (``T1``,
``trading-models-interfaces``; ``R1``, ``research-bitemporal-schema``;
etc.).

Example (in a future slice)::

    class BrokerPort(Port, Protocol):
        async def place_order(self, order: Order) -> OrderId: ...
        async def cancel_order(self, order_id: OrderId) -> None: ...

    class IBKRAdapter:  # NOT inheriting BrokerPort — structural typing.
        async def place_order(self, order: Order) -> OrderId:
            ...
        async def cancel_order(self, order_id: OrderId) -> None:
            ...

    def execute(broker: BrokerPort, order: Order) -> ...:
        # `IBKRAdapter()` passes here because mypy verifies the methods
        # match. No `isinstance(adapter, BrokerPort)` check at runtime.
        ...
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Port(Protocol):
    """Marker base for the hexagonal Port/Adapter pattern.

    Empty by design — concrete protocols (subclasses) declare their own
    method signatures. ``@runtime_checkable`` is set so a downstream
    consumer can do a defensive ``isinstance(adapter, BrokerPort)``
    check at module boundaries if it wants — but the primary
    enforcement is static via ``mypy --strict``.
    """


__all__ = ["Port"]
