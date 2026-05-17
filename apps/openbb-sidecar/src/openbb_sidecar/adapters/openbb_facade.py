"""OpenBB SDK facade — single point of contact with the AGPL package.

Per design D5: this module is the ONLY one in the sidecar that imports
``openbb``. Routes call into the facade; the facade lazy-imports openbb
on first use so cold-start `/health` returns 200 immediately while the
heavy import resolves in the background.

All exceptions raised inside ``openbb`` calls are caught and re-raised
as ``OpenBBFacadeError`` so route handlers can map them to 502 without
leaking SDK internals.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class OpenBBFacadeError(RuntimeError):
    """Raised when an OpenBB SDK call fails or the SDK is not loadable."""


class OpenBBFacade:
    """Thread-safe lazy facade around the OpenBB Platform SDK.

    The first call to :meth:`is_ready` (or any data method) imports
    ``openbb`` and caches the readiness result. Subsequent calls reuse
    the cached client.
    """

    _import_lock = threading.Lock()
    _import_result: bool | None = None
    _import_error: str | None = None

    def is_ready(self) -> bool:
        """Return True iff ``openbb`` imports cleanly. Cached after first call."""
        with self._import_lock:
            if self._import_result is not None:
                return self._import_result
            try:
                import openbb  # noqa: F401  — readiness probe only

                self._import_result = True
                self._import_error = None
            except ImportError as exc:  # pragma: no cover — exercised in unit test via mock
                self._import_result = False
                self._import_error = str(exc)
                logger.warning("openbb_sidecar.facade.import_failed", extra={"error": str(exc)})
            except Exception as exc:  # noqa: BLE001 — defensive: openbb may raise non-Import
                self._import_result = False
                self._import_error = str(exc)
                logger.warning("openbb_sidecar.facade.init_failed", extra={"error": str(exc)})
            assert self._import_result is not None
            return self._import_result

    @property
    def import_error(self) -> str | None:
        """Last error message captured during import, or None if ready."""
        return self._import_error

    def equity_fundamentals(self, symbol: str) -> dict[str, Any]:
        """Return P/E, market cap, dividend yield + as-of date for a ticker."""
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            from openbb import obb  # noqa: PLC0415 — lazy

            # OpenBB v4 surface: `obb.equity.fundamental.metrics(symbol=...)` returns an OBBject
            # whose `.results` is a list of pydantic rows. We pull the first row and reshape
            # to the route contract. The exact field names depend on the configured provider
            # (default: yfinance); this code reads the canonical pydantic attrs that are
            # provider-agnostic in v4 schemas.
            obj = obb.equity.fundamental.metrics(symbol=symbol)
            results = getattr(obj, "results", None) or []
            if not results:
                raise OpenBBFacadeError(f"no fundamentals for {symbol}")
            row = results[0]

            def _g(name: str) -> Any:
                return getattr(row, name, None)

            return {
                "symbol": symbol.upper(),
                "pe_ratio": _g("pe_ratio"),
                # Forward P/E and price-to-book are surfaced by yfinance via
                # `forward_pe` and `price_to_book` on the v4 unified schema.
                # When the provider doesn't populate them they stay None and
                # the value pillar falls back to trailing pe_ratio only.
                "forward_pe": _g("forward_pe"),
                "price_to_book": _g("price_to_book"),
                "market_cap": _g("market_cap"),
                "dividend_yield": _g("dividend_yield"),
                "as_of_date": _g("date") or _g("period_ending"),
            }
        except OpenBBFacadeError:
            raise
        except Exception as exc:  # noqa: BLE001 — boundary
            raise OpenBBFacadeError(f"equity_fundamentals({symbol}) failed: {exc}") from exc

    def equity_ratings(self, symbol: str) -> dict[str, Any]:
        """Return analyst consensus + target price + analyst count + as-of date."""
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            from openbb import obb  # noqa: PLC0415 — lazy

            obj = obb.equity.estimates.consensus(symbol=symbol)
            results = getattr(obj, "results", None) or []
            if not results:
                raise OpenBBFacadeError(f"no analyst consensus for {symbol}")
            row = results[0]

            def _g(name: str) -> Any:
                return getattr(row, name, None)

            return {
                "symbol": symbol.upper(),
                "consensus": _g("recommendation") or _g("consensus"),
                "target_price": _g("target_high") or _g("target_consensus"),
                "analyst_count": _g("number_of_analysts") or _g("analyst_count"),
                "as_of_date": _g("date") or _g("as_of_date"),
            }
        except OpenBBFacadeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"equity_ratings({symbol}) failed: {exc}") from exc

    def equity_esg(self, symbol: str) -> dict[str, Any]:
        """Return ESG composite + E/S/G sub-scores + as-of date.

        ESG endpoint depends on provider config; OpenBB v4's ``equity.fundamental.esg``
        wraps yfinance.sustainability when available. We surface the four canonical
        scores (composite + E/S/G) per design D7.
        """
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            from openbb import obb  # noqa: PLC0415 — lazy

            # `equity.fundamental.esg` may not exist in all OpenBB builds — fall back
            # to yfinance.sustainability semantics if the dedicated endpoint is missing.
            try:
                obj = obb.equity.fundamental.esg(symbol=symbol)
            except AttributeError as exc:
                raise OpenBBFacadeError(
                    f"equity_esg({symbol}) unsupported in this openbb build: {exc}"
                ) from exc

            results = getattr(obj, "results", None) or []
            if not results:
                raise OpenBBFacadeError(f"no ESG data for {symbol}")
            row = results[0]

            def _g(name: str) -> Any:
                return getattr(row, name, None)

            return {
                "symbol": symbol.upper(),
                "esg_score": _g("total_esg_score") or _g("esg_score"),
                "environmental_score": _g("environmental_score") or _g("environment_score"),
                "social_score": _g("social_score"),
                "governance_score": _g("governance_score"),
                "as_of_date": _g("date") or _g("as_of_date"),
            }
        except OpenBBFacadeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"equity_esg({symbol}) failed: {exc}") from exc

    def economy_macro(self, indicator: str) -> dict[str, Any]:
        """Return macro indicator series + unit + frequency.

        ``indicator`` is a FRED series id (e.g. ``CPIAUCSL`` for headline CPI,
        ``UNRATE`` for unemployment). OpenBB v4 surfaces this via ``economy.fred_series``.
        """
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            from openbb import obb  # noqa: PLC0415 — lazy

            obj = obb.economy.fred_series(symbol=indicator)
            results = getattr(obj, "results", None) or []
            if not results:
                raise OpenBBFacadeError(f"no macro data for indicator={indicator}")

            # Series rows: list of {date, value}. Compress to a list of dicts; metadata
            # (unit, frequency) on the OBBject's `.extra` if present.
            extra = getattr(obj, "extra", {}) or {}
            series = [
                {
                    "date": getattr(r, "date", None),
                    "value": getattr(r, "value", None),
                }
                for r in results
            ]
            return {
                "indicator": indicator.upper(),
                "series": series,
                "unit": extra.get("unit") if isinstance(extra, dict) else None,
                "frequency": extra.get("frequency") if isinstance(extra, dict) else None,
            }
        except OpenBBFacadeError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"economy_macro({indicator}) failed: {exc}") from exc
