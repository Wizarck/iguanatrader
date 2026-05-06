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
            import openbb  # noqa: F401  — lazy

            # Wiring to real openbb endpoints lands in tasks 3.1–3.5 with
            # contract tests + recorded fixtures. The MVP returns a dict
            # shape that matches the route contract (assertable in tests
            # without the SDK present).
            raise NotImplementedError("openbb integration ships in R4 group 3.x")
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001 — boundary
            raise OpenBBFacadeError(f"equity_fundamentals({symbol}) failed: {exc}") from exc

    def equity_ratings(self, symbol: str) -> dict[str, Any]:
        """Return analyst consensus + target price + analyst count + as-of date."""
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            import openbb  # noqa: F401  — lazy

            raise NotImplementedError("openbb integration ships in R4 group 3.x")
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"equity_ratings({symbol}) failed: {exc}") from exc

    def equity_esg(self, symbol: str) -> dict[str, Any]:
        """Return ESG composite + E/S/G sub-scores + as-of date."""
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            import openbb  # noqa: F401  — lazy

            raise NotImplementedError("openbb integration ships in R4 group 3.x")
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"equity_esg({symbol}) failed: {exc}") from exc

    def economy_macro(self, indicator: str) -> dict[str, Any]:
        """Return macro indicator series + unit + frequency."""
        if not self.is_ready():
            raise OpenBBFacadeError(f"openbb not loadable: {self._import_error}")
        try:
            import openbb  # noqa: F401  — lazy

            raise NotImplementedError("openbb integration ships in R4 group 3.x")
        except NotImplementedError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise OpenBBFacadeError(f"economy_macro({indicator}) failed: {exc}") from exc
