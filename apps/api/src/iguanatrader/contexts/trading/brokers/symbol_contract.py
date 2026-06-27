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
        "VUSA": {"exchange": "LSEETF", "con_id": 107968728},
        "CRUD": {"exchange": "LSE",    "con_id": 41015921},
        "VWRL": {"currency": "GBP",    "exchange": "SMART"}
    }

Per entry, ``exchange`` + ``currency`` are both optional (a missing field falls
back to the ``SMART`` / ``USD`` default for that field). The optional ``con_id``
is the IBKR conId — the *authoritative* contract key. When present, the contract
is qualified by conId alone, so the trading **currency** need not be known: the
conId encodes it. This matters because LSE UCITS lines share a symbol across
GBP/USD/EUR share classes, so a symbol+currency guess can pick the wrong
instrument (verified 2026-06-27: e.g. ``VUSA`` is ``USDD`` and ``CRUD`` lists on
``LSE``, not ``LSEETF``). The conIds are read off IBKR ``reqContractDetails`` and
recorded in the WS-3 runbook. A malformed env value logs + degrades to "no
overrides" — a bad env var must never crash the daemon on the order /
market-data path.
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
    """Resolved IBKR routing for one symbol.

    ``con_id`` (when set) is the authoritative IBKR contract key; the builders
    qualify by it and ignore ``currency``, so an unverifiable trading currency
    never has to be guessed.
    """

    exchange: str
    currency: str
    con_id: int | None = None


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
        con_id: int | None = None
        con_id_raw = spec.get("con_id")
        if con_id_raw is not None:
            try:
                con_id = int(con_id_raw)
            except (TypeError, ValueError):
                logger.warning(
                    "trading.symbol_contract.bad_con_id",
                    extra={"sym": sym, "got": repr(con_id_raw)},
                )
        out[str(sym).upper()] = ContractParams(exchange=exchange, currency=currency, con_id=con_id)
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
