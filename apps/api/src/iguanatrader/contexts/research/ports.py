"""Ports + adapter input DTOs for the research bounded context.

Per design D7 (slice R1):

* :class:`SourcePort` — Protocol that R2/R3/R4 source adapters implement.
  Each adapter exposes ``fetch(symbol, since)`` returning an iterable of
  :class:`ResearchFactDraft` objects; the repository owns persistence.
* :class:`ResearchFactDraft` — frozen dataclass mirroring the
  :class:`ResearchFact` ORM columns the adapter populates. Excludes the
  surrogate ``id`` (repository assigns) and ``created_at`` (server
  default). Carries an optional ``payload_bytes`` for hybrid-storage
  dispatch — :meth:`with_payload` is the canonical factory adapters use.

R1 ships the contract + factory; the actual storage decisions
(inline JSONB vs filesystem path) live in :class:`ResearchRepository`.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from decimal import Decimal
from typing import Any, Protocol, runtime_checkable
from uuid import UUID

#: Hybrid payload size threshold (per design D3 + ADR-014 §7b.3). Strict ``<``,
#: NOT ``<=`` — matches the CHECK constraint on ``research_facts``. Documented
#: as gotcha #43.
PAYLOAD_INLINE_THRESHOLD: int = 16384


@dataclass(frozen=True, slots=True)
class ResearchFactDraft:
    """Adapter → repository hand-off shape for a fresh research fact insert.

    Mirrors :class:`iguanatrader.contexts.research.models.ResearchFact`
    columns the adapter is responsible for. The repository owns:

    * ``id`` — surrogate UUID assignment.
    * ``tenant_id`` — stamped by the slice-3 tenant listener.
    * ``created_at`` — server default.
    * Hybrid-storage dispatch — repository chooses inline vs filesystem
      based on ``payload_bytes`` length.

    Adapters SHOULD use :meth:`with_payload` to attach a raw bytes payload
    rather than setting ``raw_payload_*`` columns directly; the factory
    encapsulates the size-tier decision and sha256 computation.
    """

    source_id: str
    fact_kind: str
    effective_from: datetime
    recorded_from: datetime
    source_url: str
    retrieval_method: str
    retrieved_at: datetime
    symbol_universe_id: UUID | None = None
    value_numeric: Decimal | None = None
    value_text: str | None = None
    value_jsonb: Any | None = None
    unit: str | None = None
    currency: str | None = None
    effective_to: datetime | None = None
    confidence: Decimal | None = None
    fact_metadata: dict[str, Any] | None = None
    # Hybrid-payload dispatch fields. Adapters typically populate via
    # :meth:`with_payload` rather than touching these directly.
    raw_payload_inline: Any | None = None
    raw_payload_path: str | None = None
    raw_payload_sha256: str | None = None
    raw_payload_size_bytes: int | None = None
    payload_bytes: bytes | None = field(default=None, repr=False)

    def with_payload(self, payload_bytes: bytes) -> ResearchFactDraft:
        """Return a new draft with hybrid-storage tier columns populated.

        * If ``len(payload_bytes) < PAYLOAD_INLINE_THRESHOLD``: inline.
          Attempts ``json.loads`` first so structured payloads keep their
          JSONB queryability; falls back to UTF-8 text wrapped in a
          ``{"_raw": ...}`` envelope when the bytes don't decode as JSON.
        * If ``len(payload_bytes) >= PAYLOAD_INLINE_THRESHOLD``: leaves
          ``raw_payload_path=None`` (repository fills on insert) and
          stamps ``raw_payload_sha256`` + ``raw_payload_size_bytes`` so
          the repository can write the file under the canonical path.

        The XOR CHECK on ``research_facts`` enforces exactly-one-set; the
        repository's ``insert_fact`` method completes the path computation
        before flush.
        """
        size = len(payload_bytes)
        sha256 = hashlib.sha256(payload_bytes).hexdigest()

        if size < PAYLOAD_INLINE_THRESHOLD:
            try:
                inline_value: Any = json.loads(payload_bytes)
            except (json.JSONDecodeError, UnicodeDecodeError):
                inline_value = {"_raw": payload_bytes.decode("utf-8", errors="replace")}
            return replace(
                self,
                raw_payload_inline=inline_value,
                raw_payload_path=None,
                raw_payload_sha256=None,
                raw_payload_size_bytes=size,
                payload_bytes=None,
            )

        # Filesystem tier — repository fills raw_payload_path on insert.
        return replace(
            self,
            raw_payload_inline=None,
            raw_payload_path=None,
            raw_payload_sha256=sha256,
            raw_payload_size_bytes=size,
            payload_bytes=payload_bytes,
        )


@runtime_checkable
class SourcePort(Protocol):
    """Adapter-side contract for ingesting facts from an external source.

    Each Wave-3 source slice (R2 EDGAR/FRED, R3 news/catalysts, R4 OpenBB
    sidecar) ships at least one class implementing this Protocol. The
    R5 brief synthesis pipeline never touches adapters directly — it
    queries the repository, which is the sole writer of
    :class:`ResearchFact` rows.

    Contract:

    * ``fetch(symbol, since)`` returns an iterable (NOT necessarily a
      list — adapters may stream). ``since`` is the ``recorded_from``
      cursor — adapters return only facts whose underlying source data
      mutated after that timestamp; ``None`` means "full backfill".
    * Adapters MUST raise :class:`iguanatrader.shared.errors.IntegrationError`
      when the upstream is unreachable / rate-limited / responds with
      malformed data. The repository wrapping the call surfaces this as
      the canonical RFC 7807 502 Problem.
    * Adapters MUST NOT call :meth:`ResearchRepository.insert_fact`
      themselves — emitting :class:`ResearchFactDraft` is the contract;
      the repository owns the bitemporal supersession + provenance
      enforcement + payload-tier dispatch.
    """

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        """Yield :class:`ResearchFactDraft` objects newer than ``since``."""
        ...


__all__ = [
    "PAYLOAD_INLINE_THRESHOLD",
    "ResearchFactDraft",
    "SourcePort",
]
