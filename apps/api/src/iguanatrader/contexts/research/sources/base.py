"""Sync ``TierASourceAdapter`` base class for slice R2 adapters.

Per slice R2 design D2 + risk note "async/sync mismatch deviation":

* ``SourcePort.fetch`` (R1) is **synchronous** (``Iterable[ResearchFactDraft]``).
  Tasks.md authored the base class as ``async`` — that draft was written
  before R1's archive resolved the contract; this implementation honours
  the actual sync Protocol. Mirror of slice R4's :class:`OpenBBSidecarSource`
  pattern (also sync httpx.Client).
* The base concentrates the four shared concerns: rate-limit governance
  (class-shared :class:`TokenBucket`), retry-on-transient + permanent-skip
  on 4xx (canonical ``backoff_seconds`` from slice 2), structlog event
  emission (``research.<source>.<action>``), and the ``tier='A'`` /
  ``retrieval_method='api'`` defaults via :meth:`_make_draft`.
* Each concrete adapter declares ``SOURCE_ID``, ``RATE_LIMIT_PER_SECOND``,
  and a class-shared ``_BUCKET`` initialised lazily so subclassing does
  not pay the bucket cost at module import.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from typing import Any, ClassVar

import httpx

from iguanatrader.contexts.research.errors import (
    ConfigError,
    SourceUnavailableError,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources._token_bucket import TokenBucket
from iguanatrader.shared.backoff import backoff_seconds
from iguanatrader.shared.time import now as utc_now

logger = logging.getLogger(__name__)


# Per design D8: 5 retries on transient 5xx + 429 + connection errors.
MAX_RETRY_ATTEMPTS = 5

# Per-request HTTP timeout. Tier-A APIs publish 5-30s p99 latency; allow
# headroom for cold caches without blocking the scheduler indefinitely.
DEFAULT_TIMEOUT_SECONDS = 60.0


class TierASourceAdapter:
    """Sync :class:`SourcePort` foundation for Tier-A native PiT sources.

    Subclasses MUST set:

    * ``SOURCE_ID`` — short identifier persisted as ``research_facts.source_id``
      and used in structlog event names.
    * ``RATE_LIMIT_PER_SECOND`` — replenish rate for the class-shared
      :class:`TokenBucket`. The base class instantiates the bucket lazily
      via :meth:`_get_bucket`.

    Subclasses MUST implement either :meth:`fetch` (symbol-based, e.g.
    SEC EDGAR) or a series-based variant (e.g. FRED's ``fetch_series``).
    The default :meth:`fetch` raises ``NotImplementedError``; the abstract
    constraint is contractual rather than enforced via :class:`abc.ABC`
    so subclasses with series-based public surfaces do not need a stub.
    """

    SOURCE_ID: ClassVar[str] = ""
    RATE_LIMIT_PER_SECOND: ClassVar[float] = 1.0

    # Populated lazily per subclass via :meth:`_get_bucket`. Storing on the
    # class — not the instance — gives multiple instances of the same
    # adapter type a shared budget (single-process scope; documented in
    # gotchas.md).
    _bucket: ClassVar[TokenBucket | None] = None

    def __init__(
        self,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not self.SOURCE_ID:
            raise ConfigError(
                detail=f"{type(self).__name__} must declare SOURCE_ID class attribute",
            )
        self._client = client or httpx.Client(timeout=timeout)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # ------------------------------------------------------------------
    # SourcePort contract (sync)
    # ------------------------------------------------------------------

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        raise NotImplementedError(
            f"{type(self).__name__} does not implement fetch(symbol, since); "
            "use the series-based variant if applicable."
        )

    # ------------------------------------------------------------------
    # Helpers for subclasses
    # ------------------------------------------------------------------

    @classmethod
    def _get_bucket(cls) -> TokenBucket:
        """Return the class-shared token bucket, creating it on first use."""
        if cls._bucket is None:
            cls._bucket = TokenBucket(rate=cls.RATE_LIMIT_PER_SECOND)
        return cls._bucket

    def _request_json(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_body: Any | None = None,
    ) -> dict[str, Any] | None:
        """Issue an HTTP request with rate-limit + retries; return parsed JSON.

        Returns ``None`` for permanent 4xx (excluding 429) — the caller is
        expected to skip that record and continue iteration. Raises
        :class:`SourceUnavailableError` if all retries on transient errors
        are exhausted.
        """
        bucket = type(self)._get_bucket()
        last_exc: Exception | None = None
        for attempt in range(1, MAX_RETRY_ATTEMPTS + 1):
            bucket.acquire()
            try:
                response = self._client.request(
                    method, url, headers=headers, params=params, json=json_body
                )
            except httpx.HTTPError as exc:
                last_exc = exc
                self._sleep_for_attempt(attempt, name=url, exc=exc)
                continue

            status = response.status_code
            if 200 <= status < 300:
                try:
                    parsed: dict[str, Any] = response.json()
                except json.JSONDecodeError as exc:
                    raise SourceUnavailableError(
                        detail=f"{self.SOURCE_ID} non-JSON response from {url}: {exc}",
                    ) from exc
                return parsed
            if status == 429:
                last_exc = SourceUnavailableError(
                    detail=f"{self.SOURCE_ID} rate-limited at {url}",
                )
                # Honour Retry-After if present; else fall through to backoff.
                retry_after = response.headers.get("Retry-After")
                if retry_after:
                    try:
                        wait = float(retry_after)
                    except ValueError:
                        wait = backoff_seconds(attempt - 1, with_jitter=True)
                    logger.info(
                        "research.%s.retry_after",
                        self.SOURCE_ID,
                        extra={"url": url, "wait_seconds": wait},
                    )
                    time.sleep(wait)
                    continue
                self._sleep_for_attempt(attempt, name=url, exc=last_exc)
                continue
            if 400 <= status < 500:
                # Permanent — log + skip; do not retry.
                logger.warning(
                    "research.%s.permanent_skip",
                    self.SOURCE_ID,
                    extra={"url": url, "status": status},
                )
                return None
            # 5xx — transient.
            last_exc = SourceUnavailableError(
                detail=f"{self.SOURCE_ID} HTTP {status} at {url}",
            )
            self._sleep_for_attempt(attempt, name=url, exc=last_exc)

        logger.error(
            "research.%s.gave_up",
            self.SOURCE_ID,
            extra={"url": url, "error": str(last_exc)},
        )
        raise SourceUnavailableError(
            detail=f"{self.SOURCE_ID} unreachable at {url}: {last_exc}",
        ) from last_exc

    @staticmethod
    def _sleep_for_attempt(attempt: int, *, name: str, exc: Exception) -> None:
        if attempt >= MAX_RETRY_ATTEMPTS:
            return
        delay = backoff_seconds(attempt - 1, with_jitter=True)
        logger.info(
            "research.tier_a.retry",
            extra={
                "url": name,
                "attempt": attempt,
                "delay_seconds": delay,
                "error": str(exc),
            },
        )
        time.sleep(delay)

    def _make_draft(
        self,
        *,
        fact_kind: str,
        effective_from: datetime,
        recorded_from: datetime | None = None,
        source_url: str,
        value_numeric: Any | None = None,
        value_text: str | None = None,
        value_jsonb: Any | None = None,
        unit: str | None = None,
        currency: str | None = None,
        effective_to: datetime | None = None,
        fact_metadata: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> ResearchFactDraft:
        """Build a :class:`ResearchFactDraft` with Tier-A defaults."""
        retrieved_at = utc_now()
        return ResearchFactDraft(
            source_id=self.SOURCE_ID,
            fact_kind=fact_kind,
            effective_from=effective_from,
            recorded_from=recorded_from or retrieved_at,
            source_url=source_url,
            retrieval_method="api",
            retrieved_at=retrieved_at,
            value_numeric=value_numeric,
            value_text=value_text,
            value_jsonb=value_jsonb,
            unit=unit,
            currency=currency,
            effective_to=effective_to,
            fact_metadata=fact_metadata,
            dedupe_key=dedupe_key,
        )


__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "MAX_RETRY_ATTEMPTS",
    "TierASourceAdapter",
]
