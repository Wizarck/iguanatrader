"""HTTP-backed :class:`HindsightPort` (slice R6 production adapter).

Talks to the Hindsight memory bank service at
``IGUANATRADER_HINDSIGHT_URL`` via JSON POST. Two endpoints:

* ``POST {base}/recall`` body ``{"bank","query","limit","timeout_ms"}``
  -> response ``{"entries": [str, ...]}``.
* ``POST {base}/retain`` body ``{"bank","kind","content","metadata"}``
  -> response 200 (no body). Non-2xx raises
  :class:`HindsightWriteFailed`.

Failure modes per NFR-I8:

* Connection refused / DNS / network -> :class:`HindsightUnavailable`.
* Per-call deadline exceeded -> :class:`HindsightTimeout`.
* Non-2xx response -> :class:`HindsightWriteFailed` (retain) or
  :class:`HindsightUnavailable` (recall).

The adapter holds NO state across calls; every request constructs a
fresh :class:`httpx.AsyncClient` (cheap; HTTP/2 + connection pool
optimisations are out of scope for v1).
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from iguanatrader.contexts.research.hindsight import (
    HindsightTimeout,
    HindsightUnavailable,
    HindsightWriteFailed,
)
from iguanatrader.contexts.research.hindsight.in_memory import (
    InMemoryHindsightAdapter,
)
from iguanatrader.contexts.research.hindsight.port import HindsightPort

log = structlog.get_logger("iguanatrader.contexts.research.hindsight.http_adapter")


_DEFAULT_RETAIN_TIMEOUT_SECONDS = 5.0


class HttpHindsightAdapter:
    """JSON-over-HTTP client to a Hindsight memory bank service."""

    def __init__(
        self,
        *,
        base_url: str,
        retain_timeout_seconds: float = _DEFAULT_RETAIN_TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._retain_timeout = retain_timeout_seconds

    async def recall(
        self,
        *,
        bank: str,
        query: str,
        limit: int = 20,
        timeout_ms: int = 2000,
    ) -> list[str]:
        import httpx

        timeout_seconds = max(timeout_ms / 1000.0, 0.1)
        url = f"{self._base_url}/recall"
        payload: dict[str, Any] = {
            "bank": bank,
            "query": query,
            "limit": limit,
            "timeout_ms": timeout_ms,
        }
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise HindsightTimeout(detail=f"recall to {url} timed out") from exc
        except httpx.RequestError as exc:
            raise HindsightUnavailable(
                detail=f"recall to {url} failed: {exc}",
            ) from exc
        if response.status_code >= 400:
            raise HindsightUnavailable(
                detail=(
                    f"recall to {url} returned {response.status_code}: " f"{response.text[:200]}"
                ),
            )
        body = response.json()
        entries = body.get("entries", [])
        return [str(e) for e in entries][:limit]

    async def retain(
        self,
        *,
        bank: str,
        kind: str,
        content: str,
        metadata: dict[str, Any],
    ) -> None:
        import httpx

        url = f"{self._base_url}/retain"
        payload: dict[str, Any] = {
            "bank": bank,
            "kind": kind,
            "content": content,
            "metadata": metadata,
        }
        try:
            async with httpx.AsyncClient(timeout=self._retain_timeout) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise HindsightTimeout(detail=f"retain to {url} timed out") from exc
        except httpx.RequestError as exc:
            raise HindsightUnavailable(
                detail=f"retain to {url} failed: {exc}",
            ) from exc
        if response.status_code >= 400:
            raise HindsightWriteFailed(
                detail=(
                    f"retain to {url} returned {response.status_code}: " f"{response.text[:200]}"
                ),
            )


def build_hindsight_adapter_from_env() -> HindsightPort:
    """Construct the production Hindsight adapter (or InMemory fallback).

    If ``IGUANATRADER_HINDSIGHT_URL`` is unset OR empty, returns an
    :class:`InMemoryHindsightAdapter` so the daemon can boot in dev/CI
    without a real Hindsight backend (matches the
    Protocol+InTreeFake+DeferredProductionInstall pattern from
    ai-playbook v0.11).
    """
    url = os.environ.get("IGUANATRADER_HINDSIGHT_URL", "").strip()
    if not url:
        log.info(
            "hindsight.adapter.in_memory_fallback",
            reason="IGUANATRADER_HINDSIGHT_URL unset",
        )
        return InMemoryHindsightAdapter()
    log.info("hindsight.adapter.http_adapter", base_url=url)
    return HttpHindsightAdapter(base_url=url)


__all__ = ["HttpHindsightAdapter", "build_hindsight_adapter_from_env"]
