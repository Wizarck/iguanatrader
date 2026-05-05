"""Research repository — bitemporal queries + provenance-validating inserts.

Per design D2 + D3 + D7 (slice R1):

* Inherits from slice-2 :class:`BaseRepository` (session via contextvar).
* :meth:`as_of` — bitemporal point-in-time query for a symbol.
* :meth:`insert_fact` — provenance-validating insert with hybrid-storage
  dispatch + driver-error lifting (``IntegrityError`` → :class:`MissingProvenanceError`).
* :meth:`supersede_fact` — narrow ``recorded_to: NULL → :ts`` UPDATE that
  passes the L2 trigger exception (per design D1).
* :meth:`latest_brief` — vigent brief lookup (``ORDER BY created_at DESC``).
* :meth:`insert_brief` — STUB; raises until R5 ships brief synthesis.

The filesystem cache directory (``data/research_cache/``) is provisioned on
first write by :meth:`_persist_payload_to_filesystem`. Per design risk
mitigation #2: NO pre-create in deploy scripts; first write does the
``mkdir(parents=True, exist_ok=True)`` (gotcha #41).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from iguanatrader.contexts.research.errors import (
    MissingProvenanceError,
    ResearchStubNotImplementedError,
)
from iguanatrader.contexts.research.models import ResearchBrief, ResearchFact
from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.shared.kernel import BaseRepository

#: Default filesystem root for hybrid-storage payload offload. Tests override
#: via :attr:`ResearchRepository.payload_root`. Production deploy resolves
#: against the project working directory; the directory is created on first
#: write (per gotcha #41).
DEFAULT_PAYLOAD_ROOT: Path = Path("data/research_cache")


class ResearchRepository(BaseRepository):
    """Persistence boundary for the research bounded context.

    Constructed with NO arguments per slice-2 contract — session resolved
    via :data:`session_var`. Tests that need to override the filesystem
    payload root pass ``payload_root=tmp_path / "cache"`` via the
    constructor; production callers leave the default.
    """

    payload_root: Path

    def __init__(self, *, payload_root: Path | None = None) -> None:
        self.payload_root = payload_root if payload_root is not None else DEFAULT_PAYLOAD_ROOT

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _session(self) -> AsyncSession:
        """Type-narrowed session accessor.

        :class:`BaseRepository.session` returns ``Any`` per slice-2
        contract (slice 2 doesn't depend on SQLAlchemy). We narrow at the
        repository boundary so mypy --strict catches misuse without
        requiring every call site to assert.
        """
        sess: Any = self.session
        return sess  # type: ignore[no-any-return]

    def _persist_payload_to_filesystem(
        self,
        *,
        source_id: str,
        recorded_from: datetime,
        sha256: str,
        payload_bytes: bytes,
    ) -> str:
        """Write ``payload_bytes`` under the canonical hybrid-storage path.

        Path scheme (per design D3 + ADR-014 §7b.3):
        ``<payload_root>/<source_id>/<yyyy-mm>/<sha256>.json``

        Parent directories are created on first write
        (``mkdir(parents=True, exist_ok=True)``). Returns the relative
        path stored on the row (relative to ``payload_root`` so a
        re-rooted deploy still resolves).

        Idempotent: if a file with the same ``sha256`` already exists,
        the bytes are NOT rewritten (sha256 collisions are
        cryptographically irrelevant for non-adversarial payloads, and
        skipping the write avoids a TOCTOU race on parallel ingests).
        """
        yyyy_mm = recorded_from.strftime("%Y-%m")
        rel_dir = Path(source_id) / yyyy_mm
        rel_path = rel_dir / f"{sha256}.json"
        abs_dir = self.payload_root / rel_dir
        abs_path = self.payload_root / rel_path

        abs_dir.mkdir(parents=True, exist_ok=True)
        if not abs_path.exists():
            abs_path.write_bytes(payload_bytes)

        return rel_path.as_posix()

    # ------------------------------------------------------------------
    # Bitemporal queries
    # ------------------------------------------------------------------

    async def as_of(self, symbol: str, at: datetime) -> list[ResearchFact]:
        """Return facts visible for ``symbol`` at point-in-time ``at``.

        Implements the dual-axis predicate from spec scenario "Point-in-
        time query returns only facts visible at the requested time":

        * ``effective_from <= at`` AND
          (``effective_to IS NULL`` OR ``effective_to > at``)
        * ``recorded_from <= at`` AND
          (``recorded_to IS NULL`` OR ``recorded_to > at``)

        ``symbol`` joins via :class:`SymbolUniverse` — a single tenant may
        have multiple universe rows for the same symbol on different
        exchanges; this query returns facts for ALL of them so the caller
        can disambiguate by exchange downstream.

        The slice-3 tenant listener auto-injects ``WHERE tenant_id =
        :ctx_tenant`` because :class:`ResearchFact` and
        :class:`SymbolUniverse` both have ``__tenant_scoped__ = True``
        (default). No explicit tenant filter needed here.
        """
        # Local import keeps the module-level import surface minimal +
        # avoids a circular dependency through models.py (which imports
        # nothing from this module but the listener-registry walk in
        # tenant_listener.py iterates ALL mappers; importing here keeps
        # the order explicit).
        from iguanatrader.contexts.research.models import SymbolUniverse

        sentinel = sa.literal(at)
        stmt = (
            sa.select(ResearchFact)
            .join(
                SymbolUniverse,
                ResearchFact.symbol_universe_id == SymbolUniverse.id,
            )
            .where(
                SymbolUniverse.symbol == symbol,
                ResearchFact.effective_from <= sentinel,
                sa.or_(
                    ResearchFact.effective_to.is_(None),
                    ResearchFact.effective_to > sentinel,
                ),
                ResearchFact.recorded_from <= sentinel,
                sa.or_(
                    ResearchFact.recorded_to.is_(None),
                    ResearchFact.recorded_to > sentinel,
                ),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    # ------------------------------------------------------------------
    # Inserts
    # ------------------------------------------------------------------

    async def insert_fact(self, draft: ResearchFactDraft) -> ResearchFact:
        """Insert a :class:`ResearchFact` from ``draft`` with provenance enforcement.

        Behaviour:

        1. Hybrid-storage dispatch — if ``draft.payload_bytes`` is set
           AND ``draft.raw_payload_path`` is None, write the bytes to
           filesystem under the canonical path and stamp
           ``raw_payload_path`` on the new row. (For inline payloads,
           :meth:`ResearchFactDraft.with_payload` already populated
           ``raw_payload_inline`` + ``raw_payload_size_bytes`` — we just
           pass them through.)
        2. Build the :class:`ResearchFact` instance. ``tenant_id`` is left
           unset; the slice-3 ``before_flush`` listener stamps it from
           ``tenant_id_var``.
        3. Flush — if the driver raises :class:`IntegrityError` (NOT NULL
           or CHECK violation), re-raise as :class:`MissingProvenanceError`.
        """
        raw_payload_path = draft.raw_payload_path
        if (
            draft.payload_bytes is not None
            and draft.raw_payload_path is None
            and draft.raw_payload_sha256 is not None
        ):
            raw_payload_path = self._persist_payload_to_filesystem(
                source_id=draft.source_id,
                recorded_from=draft.recorded_from,
                sha256=draft.raw_payload_sha256,
                payload_bytes=draft.payload_bytes,
            )

        # tenant_id is left as None so the slice-3 listener stamps it from
        # tenant_id_var. We pass placeholder None and rely on the listener
        # contract — explicit assignment would force callers to plumb
        # tenant_id through every adapter, defeating the slice-3 design.
        instance = ResearchFact(
            id=uuid4(),
            source_id=draft.source_id,
            symbol_universe_id=draft.symbol_universe_id,
            fact_kind=draft.fact_kind,
            value_numeric=draft.value_numeric,
            value_text=draft.value_text,
            value_jsonb=draft.value_jsonb,
            unit=draft.unit,
            currency=draft.currency,
            effective_from=draft.effective_from,
            effective_to=draft.effective_to,
            recorded_from=draft.recorded_from,
            recorded_to=None,
            source_url=draft.source_url,
            retrieval_method=draft.retrieval_method,
            retrieved_at=draft.retrieved_at,
            raw_payload_inline=draft.raw_payload_inline,
            raw_payload_path=raw_payload_path,
            raw_payload_sha256=draft.raw_payload_sha256,
            raw_payload_size_bytes=draft.raw_payload_size_bytes,
            confidence=draft.confidence,
            fact_metadata=draft.fact_metadata,
        )
        self._session.add(instance)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Pull the driver's message into ``detail`` so operators can
            # diagnose; the slice-5 global handler renders the canonical
            # ``urn:iguanatrader:error:missing-provenance`` ``type`` URI
            # regardless of the underlying CHECK / NOT NULL violation.
            raise MissingProvenanceError(
                detail=f"research_facts insert violated provenance/integrity: {exc.orig!s}",
            ) from exc
        return instance

    async def supersede_fact(self, old_id: UUID, at: datetime) -> None:
        """Set ``recorded_to`` on the fact identified by ``old_id`` to ``at``.

        Per design D1 + spec scenario "Narrow ``recorded_to`` supersession
        permitted": this is the only mutation allowed on
        :class:`ResearchFact` rows. The L2 trigger emitted by migration
        ``0003_research_tables`` permits the UPDATE when the only column
        changing is ``recorded_to`` going from NULL → non-NULL; every
        other UPDATE pattern aborts.

        Implementation uses raw SQL via :meth:`AsyncSession.execute` so
        the slice-3 ORM append-only listener (L1) does NOT see a dirty
        instance; the L2 trigger is the sole gatekeeper for this single
        supersession path. The ``WHERE recorded_to IS NULL`` clause makes
        the call idempotent — a second invocation against an already-
        superseded row updates zero rows (safe).
        """
        await self._session.execute(
            sa.text(
                "UPDATE research_facts "
                "SET recorded_to = :at "
                "WHERE id = :old_id AND recorded_to IS NULL"
            ),
            {"at": at, "old_id": old_id},
        )

    # ------------------------------------------------------------------
    # Brief queries (insert is stubbed until R5)
    # ------------------------------------------------------------------

    async def latest_brief(self, symbol: str) -> ResearchBrief | None:
        """Return the highest-version brief for ``symbol`` for the current tenant.

        Per spec scenario "Refreshed brief gets version N+1": orders by
        ``created_at DESC LIMIT 1``. The unique constraint on
        ``(tenant_id, symbol_universe_id, version)`` guarantees the
        ordering is well-defined.
        """
        from iguanatrader.contexts.research.models import SymbolUniverse

        stmt = (
            sa.select(ResearchBrief)
            .join(
                SymbolUniverse,
                ResearchBrief.symbol_universe_id == SymbolUniverse.id,
            )
            .where(SymbolUniverse.symbol == symbol)
            .order_by(ResearchBrief.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def insert_brief(self, *args: Any, **kwargs: Any) -> ResearchBrief:
        """STUB — ships in slice R5 (``research-brief-synthesis``)."""
        raise ResearchStubNotImplementedError(
            detail="ResearchRepository.insert_brief ships in slice R5",
        )


__all__ = [
    "DEFAULT_PAYLOAD_ROOT",
    "ResearchRepository",
]
