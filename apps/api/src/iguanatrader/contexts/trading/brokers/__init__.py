"""IBKR broker adapter package — slice T2 ``ibkr-adapter-resilient``.

Public exports:

* :class:`IBKRAdapter` — :class:`BrokerPort` implementation over the
  :class:`IBClient` Protocol.
* :class:`IBKRBrokerageModel` — frozen-dataclass configuration: paper
  vs live ports, supported order types, market-data flags, account.
* :class:`IBClient` — Protocol describing the subset of ``ib_async.IB``
  the adapter consumes. Production wiring uses ``ib_async.IB``;
  ``apps/api/tests/_fakes/ib_async_fake.py`` ships the in-tree test
  double. The real ``ib_async`` package is **not** added as a runtime
  dep in this slice; the deployment-foundation slice wires it.
"""

from __future__ import annotations

from iguanatrader.contexts.trading.brokers.client_protocol import (
    Contract,
    Execution,
    IBClient,
    IBOrder,
    OpenOrder,
    PositionRecord,
)
from iguanatrader.contexts.trading.brokers.ibkr_adapter import (
    DEFAULT_HEARTBEAT_INTERVAL_SECONDS,
    DEFAULT_HEARTBEAT_TIMEOUT_SECONDS,
    MAX_RECONNECT_ATTEMPTS,
    IBKRAdapter,
)
from iguanatrader.contexts.trading.brokers.ibkr_brokerage_model import (
    SUPPORTED_ORDER_TYPES_DEFAULT,
    IBKRBrokerageModel,
)

__all__ = [
    "DEFAULT_HEARTBEAT_INTERVAL_SECONDS",
    "DEFAULT_HEARTBEAT_TIMEOUT_SECONDS",
    "MAX_RECONNECT_ATTEMPTS",
    "SUPPORTED_ORDER_TYPES_DEFAULT",
    "Contract",
    "Execution",
    "IBClient",
    "IBKRAdapter",
    "IBKRBrokerageModel",
    "IBOrder",
    "OpenOrder",
    "PositionRecord",
]
