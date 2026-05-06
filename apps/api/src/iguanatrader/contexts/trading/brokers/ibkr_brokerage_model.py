"""IBKR brokerage configuration model (slice T2 design D8).

Frozen dataclass that captures the IBKR-specific operational config:

* Paper vs live port enforcement (paper=7497, live=7496 — IBKR
  docs).
* Supported order-type whitelist (MVP: MKT / LMT / STP / STP LMT).
* Market-data subscription flags per symbol (informational; adapter
  does NOT enforce — operator responsibility, gotcha #35).
* Commission model identifier (informational; commissions land via
  the fill event itself).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from iguanatrader.shared.errors import IntegrationError

#: Default whitelist of IBKR order types the adapter will accept.
SUPPORTED_ORDER_TYPES_DEFAULT: frozenset[str] = frozenset({"MKT", "LMT", "STP", "STP LMT"})

_PAPER_PORT = 7497
_LIVE_PORT = 7496


class UnsupportedOrderTypeError(IntegrationError):
    """Adapter rejected an order whose ``order_type`` isn't in the whitelist.

    Keeps the canonical ``urn:`` type URI distinct so operators can
    pattern-match in dashboards.
    """

    type_uri = "urn:iguanatrader:error:broker-order-type-unsupported"
    default_title = "Broker Order Type Unsupported"
    default_status = 422


@dataclass(frozen=True, slots=True)
class IBKRBrokerageModel:
    """Frozen IBKR runtime config consumed by :class:`IBKRAdapter`."""

    mode: Literal["paper", "live"]
    host: str = "127.0.0.1"
    port: int = _PAPER_PORT
    client_id: int = 1
    account_code: str | None = None
    supported_order_types: frozenset[str] = field(
        default_factory=lambda: SUPPORTED_ORDER_TYPES_DEFAULT
    )
    market_data_subscriptions: dict[str, bool] = field(default_factory=dict)
    commission_model: Literal["tiered", "fixed"] = "tiered"

    def __post_init__(self) -> None:
        if self.mode == "paper" and self.port != _PAPER_PORT:
            raise ValueError(f"paper mode requires port {_PAPER_PORT}, got {self.port}")
        if self.mode == "live" and self.port != _LIVE_PORT:
            raise ValueError(f"live mode requires port {_LIVE_PORT}, got {self.port}")

    def assert_supports_order_type(self, order_type: str) -> None:
        """Raise :class:`UnsupportedOrderTypeError` if ``order_type`` not whitelisted."""
        if order_type not in self.supported_order_types:
            raise UnsupportedOrderTypeError(
                detail=(
                    f"order_type {order_type!r} not in IBKRBrokerageModel "
                    f"supported list {sorted(self.supported_order_types)}"
                ),
            )

    @classmethod
    def for_paper(cls, *, account_code: str | None = None) -> IBKRBrokerageModel:
        """Convenience constructor for the canonical paper config."""
        return cls(mode="paper", port=_PAPER_PORT, account_code=account_code)

    @classmethod
    def for_live(cls, *, account_code: str) -> IBKRBrokerageModel:
        """Convenience constructor for the canonical live config.

        ``account_code`` is required for live (IBKR multi-account login
        means the adapter needs to know which account to scope orders /
        positions / equity queries to).
        """
        return cls(mode="live", port=_LIVE_PORT, account_code=account_code)


__all__ = [
    "SUPPORTED_ORDER_TYPES_DEFAULT",
    "IBKRBrokerageModel",
    "UnsupportedOrderTypeError",
]
