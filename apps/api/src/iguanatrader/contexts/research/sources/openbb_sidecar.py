"""OpenBB sidecar adapter — `SourcePort` implementation over HTTP.

Per slice R4 design D3 + D7: the iguanatrader monolith reaches the
AGPL-isolated OpenBB Platform sidecar exclusively over HTTP (compose-DNS
in dev, k8s ClusterIP DNS in paper/live). This adapter wraps the
:class:`SourcePort` contract from R1 and yields :class:`ResearchFactDraft`
objects for the three equity surfaces the sidecar exposes (fundamentals,
ratings, ESG).

Liveness is NOT wired through ``HeartbeatMixin`` here — the k8s
``livenessProbe`` + ``readinessProbe`` on the sidecar Pod (Service stops
routing on unready Pods) cover the same role at the cluster layer.
The HeartbeatMixin contract is async-only; ``SourcePort.fetch`` is sync.
Deviation documented in tasks.md §5.2 + design.md D3.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any
from urllib.parse import quote

import httpx

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.shared.backoff import backoff_seconds
from iguanatrader.shared.errors import IntegrationError
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)


# Default URL points at the docker-compose service DNS in dev. In k8s
# (paper/live) the helm chart sets ``OPENBB_SIDECAR_URL=http://openbb-sidecar:8765``
# (Service DNS in the iguanatrader namespace). Either way, never localhost.
DEFAULT_BASE_URL = "http://openbb_sidecar:8765"

# How many transient-failure attempts before the per-fetch call gives up.
# Each attempt sleeps ``backoff_seconds(attempt-1)`` from the canonical
# ``[3, 6, 12, 24, 48]`` sequence — total max sleep 93s before raising.
MAX_RETRY_ATTEMPTS = 5

# Per-request HTTP timeout. The sidecar's openbb call can take 30-60s
# on cold cache; allow plenty.
DEFAULT_TIMEOUT_SECONDS = 90.0

# #24: ticker allow-list for border validation. Equity symbols are
# letters/digits plus ``.`` (class shares: BRK.B) and ``-`` (some ADRs).
# Anything else (slashes, spaces, ``?``/``#``, path traversal) is rejected
# before it can be interpolated into the sidecar URL path — defence in
# depth on top of the per-segment ``quote`` encoding below.
_TICKER_RE = re.compile(r"^[A-Za-z0-9.\-]{1,15}$")


class OpenBBSidecarSource:
    """:class:`SourcePort` bound to the AGPL-isolated OpenBB sidecar."""

    SOURCE_ID = "openbb-sidecar"

    def __init__(
        self,
        base_url: str | None = None,
        client: httpx.Client | None = None,
        enabled: bool | None = None,
    ) -> None:
        self._base_url = (
            base_url or os.environ.get("OPENBB_SIDECAR_URL", DEFAULT_BASE_URL)
        ).rstrip("/")
        # Owned client by default; tests inject a fake.
        self._client = client or httpx.Client(timeout=DEFAULT_TIMEOUT_SECONDS)
        self._owns_client = client is None
        # Allow op-time disable via env without removing the adapter from
        # the registry. Useful when openbb is broken upstream and we want
        # the rest of the research pipeline to continue without it.
        env_flag = os.environ.get("OPENBB_SIDECAR_ENABLED", "true").lower()
        self._enabled = enabled if enabled is not None else env_flag != "false"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # SourcePort contract
    # ------------------------------------------------------------------

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield up to 3 drafts (fundamentals + ratings + ESG) for ``symbol``.

        ``since`` is part of the SourcePort contract but is not honoured by
        this adapter — the sidecar always returns the latest snapshot. The
        bitemporal `recorded_from`/`effective_from` columns on the persisted
        rows preserve the per-fetch timestamps that downstream queries need.
        """
        del since  # See docstring; intentional no-op consumption.
        if not self._enabled:
            logger.info(
                "research.openbb_sidecar.skipped_disabled",
                extra={"symbol": symbol},
            )
            return
        if not self._validate_symbol(symbol):
            return

        # #24: ``quote(safe="")`` percent-encodes the symbol so it cannot
        # break out of its path segment (``/``, ``?``, ``#`` … no longer
        # reinterpret the URL). Normal tickers (AAPL, BRK.B) pass through
        # unchanged.
        enc = quote(symbol, safe="")
        endpoints = [
            ("fundamentals", f"/v1/equity/fundamentals/{enc}", "fundamentals"),
            ("ratings", f"/v1/equity/ratings/{enc}", "analyst_ratings"),
            ("esg", f"/v1/equity/esg/{enc}", "esg_score"),
        ]
        for name, path, fact_kind in endpoints:
            payload = self._get_or_skip(symbol=symbol, name=name, path=path)
            if payload is None:
                continue
            yield self._draft_from_payload(
                symbol=symbol, fact_kind=fact_kind, name=name, payload=payload
            )

    def fetch_prices(
        self,
        symbol: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield one ``historical_prices_window`` fact per fetch.

        Stored as a single bitemporal blob rather than one-fact-per-bar
        because (a) the tier-A return computation only needs three points
        out of ~252 bars and (b) one fact per bar would inflate the
        ``research_facts`` table by ~250x per refresh. The blob format
        preserves the full series for any future expansion (drawdown,
        volatility, max-drawdown features).

        ``start_date`` / ``end_date`` are passed through to the sidecar's
        query string when set; otherwise the provider's default window is
        used (yfinance: ~5 years).
        """
        if not self._enabled:
            logger.info(
                "research.openbb_sidecar.skipped_disabled",
                extra={"symbol": symbol, "endpoint": "historical_prices"},
            )
            return
        if not self._validate_symbol(symbol):
            return

        # #24: date params go through httpx ``params=`` (URL-encoded by the
        # client) instead of hand-concatenated query string, and the symbol
        # is percent-encoded into its path segment.
        params = {k: v for k, v in (("start_date", start_date), ("end_date", end_date)) if v}
        path = f"/v1/equity/historical_prices/{quote(symbol, safe='')}"

        payload = self._get_or_skip(
            symbol=symbol, name="historical_prices", path=path, params=params or None
        )
        if payload is None:
            return
        yield self._draft_from_payload(
            symbol=symbol,
            fact_kind="historical_prices_window",
            name="historical_prices",
            payload=payload,
        )

    # ------------------------------------------------------------------
    # HTTP plumbing — backoff loop + 4xx/5xx routing
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_symbol(symbol: str) -> bool:
        """#24: reject symbols that don't match the ticker allow-list.

        Logs + returns False (caller yields nothing) rather than raising,
        so one malformed symbol never aborts a multi-symbol batch — and,
        critically, no HTTP request is issued with an attacker-influenced
        path. Defence in depth alongside per-segment ``quote`` encoding.
        """
        if _TICKER_RE.match(symbol):
            return True
        logger.warning(
            "research.openbb_sidecar.invalid_symbol",
            extra={"symbol": symbol},
        )
        return False

    def _get_or_skip(
        self,
        *,
        symbol: str,
        name: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any] | None:
        """Issue GET to the sidecar with retries; return parsed JSON or None.

        Returns ``None`` on 4xx (no-data / unsupported) — caller skips that
        endpoint without aborting the rest of the fetch. Raises
        :class:`IntegrationError` if all retries on transient errors fail.
        """
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            try:
                response = self._client.get(url, params=params)
            except httpx.HTTPError as exc:
                last_exc = exc
                self._sleep_for_attempt(attempt, name=name, exc=exc)
                continue

            status = response.status_code
            if 200 <= status < 300:
                try:
                    parsed: dict[str, Any] = response.json()
                except json.JSONDecodeError as exc:
                    raise IntegrationError(
                        f"openbb-sidecar {name} returned non-JSON: {exc}"
                    ) from exc
                return parsed
            if 400 <= status < 500 or status == 502:
                # 4xx = upstream rejection; 502 = sidecar mapping of openbb
                # facade errors (e.g. YFinance doesn't have ESG for this
                # symbol). Both mean "skip this endpoint, don't fail the
                # whole ingest" — the caller iteration drops this endpoint.
                logger.warning(
                    "research.openbb_sidecar.skipped_upstream_error",
                    extra={"symbol": symbol, "endpoint": name, "status": status},
                )
                return None
            # Other 5xx (503/504/etc.) — transient; retry per backoff schedule.
            last_exc = IntegrationError(f"openbb-sidecar {name} returned HTTP {status}")
            self._sleep_for_attempt(attempt, name=name, exc=last_exc)

        # Exhausted retries.
        logger.error(
            "research.openbb_sidecar.unreachable",
            extra={"symbol": symbol, "endpoint": name, "error": str(last_exc)},
        )
        raise IntegrationError(
            f"openbb-sidecar unreachable for {symbol} {name}: {last_exc}"
        ) from last_exc

    @staticmethod
    def _sleep_for_attempt(attempt: int, *, name: str, exc: Exception) -> None:
        # Final attempt: don't sleep, let the caller raise.
        if attempt >= MAX_RETRY_ATTEMPTS:
            return
        delay = backoff_seconds(attempt - 1, with_jitter=True)
        logger.info(
            "research.openbb_sidecar.retry",
            extra={
                "endpoint": name,
                "attempt": attempt,
                "delay_seconds": delay,
                "error": str(exc),
            },
        )
        # Sleep imported lazily so tests can monkeypatch via the time module.
        import time

        time.sleep(delay)

    # ------------------------------------------------------------------
    # Payload → draft mapping
    # ------------------------------------------------------------------

    def _draft_from_payload(
        self,
        *,
        symbol: str,
        fact_kind: str,
        name: str,
        payload: dict[str, Any],
    ) -> ResearchFactDraft:
        retrieved_at = utc_now()
        # Per design D3: bitemporal `effective_from` = the upstream's
        # as-of date when present; fall back to retrieval time when the
        # endpoint does not surface one (sidecar's openbb wrappers may omit).
        as_of = payload.get("as_of_date")
        effective_from = _parse_as_of(as_of) or retrieved_at
        source_url = f"{self._base_url}/v1/equity/{name}/{symbol}"
        payload_bytes = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        draft = ResearchFactDraft(
            source_id=self.SOURCE_ID,
            fact_kind=fact_kind,
            effective_from=effective_from,
            recorded_from=retrieved_at,
            source_url=source_url,
            # The bitemporal CHECK constraint
            # `retrieval_method IN ('api','scrape','manual','llm')` rejects
            # `"http"` even though that's literally what we do — categorising
            # as 'api' fits the spirit (provider HTTP API behind the sidecar).
            retrieval_method="api",
            retrieved_at=retrieved_at,
            value_jsonb=payload,
            fact_metadata={
                "endpoint": name,
                "sidecar_url": self._base_url,
            },
        )
        return draft.with_payload(payload_bytes)


def _parse_as_of(value: Any) -> datetime | None:
    """Best-effort coerce the sidecar's ``as_of_date`` to a UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None
