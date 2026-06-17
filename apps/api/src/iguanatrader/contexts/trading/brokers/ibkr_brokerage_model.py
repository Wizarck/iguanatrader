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

#: Map the domain order-type vocabulary (the lowercase values stored on
#: ``orders.order_type`` per the ``ck_orders_order_type_allowed`` CHECK)
#: to the IBKR/ib_async order-type codes the translator (`_to_order`) and
#: the whitelist (`assert_supports_order_type`) expect. Before this map
#: existed the service submitted ``order_type="market"`` which the
#: whitelist + translator both reject — every real order failed.
_DOMAIN_TO_IBKR_ORDER_TYPE: dict[str, str] = {
    "market": "MKT",
    "limit": "LMT",
    "stop": "STP",
    "stop_limit": "STP LMT",
}

#: IBKR codes ``_to_order`` already understands. ``translate_order_type``
#: passes these through unchanged so callers (and tests) that already
#: speak IBKR codes keep working; the whitelist still gates which ones a
#: given brokerage config will actually submit.
IBKR_ORDER_TYPES: frozenset[str] = frozenset(
    {"MKT", "LMT", "STP", "STP LMT", "TRAIL", "TRAIL LIMIT", "MOC", "LOC"}
)

_PAPER_PORT = 7497
_LIVE_PORT = 7496
# IB Gateway (gnzsnz/ib-gateway) exposes its API on 4002 (paper) / 4001 (live),
# while standalone TWS uses 7497 / 7496. Accept either per mode so the daemon can
# run against an IB Gateway container without weakening paper/live separation.
_PAPER_PORTS = frozenset({_PAPER_PORT, 4002})
_LIVE_PORTS = frozenset({_LIVE_PORT, 4001})


def translate_order_type(order_type: str) -> str:
    """Translate a domain order-type to its IBKR code (idempotent).

    Accepts either the lowercase domain vocabulary
    (``market``/``limit``/``stop``/``stop_limit``) or an IBKR code that
    ``_to_order`` already understands (returned unchanged). Raises
    :class:`UnsupportedOrderTypeError` for anything else so an unknown
    value fails loudly at submission rather than silently producing a
    malformed order.
    """
    mapped = _DOMAIN_TO_IBKR_ORDER_TYPE.get(order_type)
    if mapped is not None:
        return mapped
    if order_type in IBKR_ORDER_TYPES:
        return order_type
    raise UnsupportedOrderTypeError(
        detail=(
            f"order_type {order_type!r} has no IBKR mapping; known domain "
            f"types: {sorted(_DOMAIN_TO_IBKR_ORDER_TYPE)}"
        ),
    )


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
        if self.mode == "paper" and self.port not in _PAPER_PORTS:
            raise ValueError(f"paper mode requires a paper port {sorted(_PAPER_PORTS)}, got {self.port}")
        if self.mode == "live" and self.port not in _LIVE_PORTS:
            raise ValueError(f"live mode requires a live port {sorted(_LIVE_PORTS)}, got {self.port}")

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

    @classmethod
    def from_env(cls, mode: Literal["paper", "live"]) -> IBKRBrokerageModel:
        """Build a brokerage config from env vars for ``mode``.

        Reads ``IGUANATRADER_IBKR_HOST`` (default ``127.0.0.1``),
        ``IGUANATRADER_IBKR_CLIENT_ID`` (default ``1``) and, for live,
        the required ``IGUANATRADER_IBKR_ACCOUNT_CODE``. The TWS/Gateway
        port stays mode-canonical (paper=7497, live=7496) per IBKR
        convention and the ``__post_init__`` guard. Used by the daemon
        composition root so ``IBKRAdapter`` is constructed with a real
        brokerage rather than the previously-missing kwarg.
        """
        import os

        # Prefer the IBKR_HOST / IBKR_PORT names the compose deployment sets
        # (they point at the ib-gateway-paper container on 4002); fall back to
        # the legacy IGUANATRADER_* names and the mode-canonical TWS port.
        host = (
            os.environ.get("IBKR_HOST")
            or os.environ.get("IGUANATRADER_IBKR_HOST")
            or "127.0.0.1"
        )
        _canonical_port = _PAPER_PORT if mode == "paper" else _LIVE_PORT
        port = int(os.environ.get("IBKR_PORT") or _canonical_port)
        client_id = int(
            os.environ.get("IBKR_CLIENT_ID")
            or os.environ.get("IGUANATRADER_IBKR_CLIENT_ID", "1")
        )
        account_code = os.environ.get("IGUANATRADER_IBKR_ACCOUNT_CODE")
        if mode == "live":
            if not account_code:
                raise ValueError("live mode requires IGUANATRADER_IBKR_ACCOUNT_CODE to be set")
            return cls(
                mode="live",
                host=host,
                port=port,
                client_id=client_id,
                account_code=account_code,
            )
        return cls(
            mode="paper",
            host=host,
            port=port,
            client_id=client_id,
            account_code=account_code,
        )


__all__ = [
    "IBKR_ORDER_TYPES",
    "SUPPORTED_ORDER_TYPES_DEFAULT",
    "IBKRBrokerageModel",
    "UnsupportedOrderTypeError",
    "translate_order_type",
]
