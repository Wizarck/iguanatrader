"""Per-symbol IBKR contract resolution — exchange + currency (WS-3 UCITS cutover).

The US watchlist resolves cleanly as ``SMART`` / ``USD``. The UCITS cutover swaps
the US ETFs to their LSE / Xetra UCITS equivalents (``VUSA``, ``IGLN``, …) that
an EU account trades in ``GBP`` / ``EUR`` — those need the correct currency
(and sometimes a specific exchange) or IBKR qualifies the wrong instrument, or
none at all. Both the order path (``IBKRAdapter._build_contract``) and the
historical-bar path (``IbAsyncIBClient.fetch_historical``) previously hardcoded
``SMART`` / ``USD``; this resolves the pair per symbol.

Resolution is an OPT-IN override map, so the existing US watchlist is
byte-identical (a symbol with no override → ``SMART`` / ``USD``):

    IGUANATRADER_SYMBOL_CONTRACT_OVERRIDES = {
        "VUSA": {"currency": "GBP"},
        "IGLN": {"currency": "USD"},
        "VWRL": {"currency": "GBP", "exchange": "SMART"}
    }

Per entry, ``exchange`` + ``currency`` are both optional (a missing field falls
back to the ``SMART`` / ``USD`` default for that field). A malformed env value
logs + degrades to "no overrides" — a bad env var must never crash the daemon
on the order / market-data path. The actual UCITS values are operator-supplied
and validated against IBKR paper before the live cutover (see the WS-3 runbook).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

#: IBKR defaults for a US equity — unchanged behaviour for the US watchlist.
DEFAULT_EXCHANGE = "SMART"
DEFAULT_CURRENCY = "USD"

#: Env var holding the JSON ``{symbol: {"exchange"?, "currency"?}}`` override map.
OVERRIDES_ENV_VAR = "IGUANATRADER_SYMBOL_CONTRACT_OVERRIDES"


@dataclass(frozen=True, slots=True)
class ContractParams:
    """Resolved IBKR routing for one symbol."""

    exchange: str
    currency: str


def parse_overrides(raw: str | None) -> dict[str, ContractParams]:
    """Parse the override JSON into ``{SYMBOL: ContractParams}`` (pure).

    Fail-safe: empty / missing / malformed input → ``{}`` (no overrides), with a
    warning. Symbols are upper-cased so lookups are case-insensitive.
    """
    if not raw or not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("trading.symbol_contract.bad_override_json", extra={"error": str(exc)})
        return {}
    if not isinstance(data, dict):
        logger.warning(
            "trading.symbol_contract.override_not_object",
            extra={"got": type(data).__name__},
        )
        return {}
    out: dict[str, ContractParams] = {}
    for sym, spec in data.items():
        if not isinstance(spec, dict):
            logger.warning("trading.symbol_contract.override_entry_not_object", extra={"sym": sym})
            continue
        exchange = str(spec.get("exchange") or DEFAULT_EXCHANGE)
        currency = str(spec.get("currency") or DEFAULT_CURRENCY)
        out[str(sym).upper()] = ContractParams(exchange=exchange, currency=currency)
    return out


def resolve_contract_params(
    symbol: str,
    *,
    overrides: dict[str, ContractParams] | None = None,
) -> ContractParams:
    """Return the ``(exchange, currency)`` for ``symbol``.

    ``overrides`` (tests) takes precedence; otherwise the env map is parsed.
    A symbol absent from the map resolves to the ``SMART`` / ``USD`` default, so
    the US watchlist is unchanged.
    """
    table = (
        overrides if overrides is not None else parse_overrides(os.environ.get(OVERRIDES_ENV_VAR))
    )
    return table.get(symbol.upper(), ContractParams(DEFAULT_EXCHANGE, DEFAULT_CURRENCY))


__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_EXCHANGE",
    "OVERRIDES_ENV_VAR",
    "ContractParams",
    "parse_overrides",
    "resolve_contract_params",
]
