"""Async dedupe wrapper for Tier-A source adapter inserts (slice R2).

Per slice R2 design D7: each adapter computes a deterministic
``dedupe_key`` per draft. The wrapper here does:

1. ``SELECT 1 FROM research_facts WHERE tenant_id = :tid AND dedupe_key = :key LIMIT 1``
2. Hit → emits ``research.<source_id>.skipped_duplicate`` and returns
   ``None`` (no insert; idempotent).
3. Miss → calls ``repository.insert_fact(draft)`` and returns the new
   :class:`ResearchFact`.

The ``tenant_id`` is read from the slice-3
:func:`iguanatrader.persistence.tenant.tenant_id_var` ContextVar — the
same source the slice-3 ``before_flush`` listener uses to stamp inserts.
The wrapper performs an explicit ``SELECT`` (not relying on the partial
unique-index ``IntegrityError``) because (a) two concurrent jobs both
hitting the index race uses repository-side error mapping that does not
distinguish dedupe from genuine constraint failures, and (b) the explicit
short-circuit lets us emit a structured log event instead of treating
the duplicate as a flush error. The partial unique index from migration
``0008_research_dedupe_index`` is the defence-in-depth backstop for
concurrent inserts that race past the SELECT.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import sqlalchemy as sa

from iguanatrader.shared.contextvars import tenant_id_var

if TYPE_CHECKING:
    from iguanatrader.contexts.research.models import ResearchFact
    from iguanatrader.contexts.research.ports import ResearchFactDraft
    from iguanatrader.contexts.research.repository import ResearchRepository

logger = logging.getLogger(__name__)


async def insert_with_dedupe(
    repository: ResearchRepository,
    draft: ResearchFactDraft,
) -> ResearchFact | None:
    """Insert ``draft`` unless ``draft.dedupe_key`` already exists for tenant.

    ``draft.dedupe_key`` MUST be set by the caller (the adapter computes
    the source-specific natural key — e.g. ``f"sec_edgar:{accession_no}"``).
    A draft with ``dedupe_key=None`` is rejected with :class:`ValueError` —
    use :meth:`ResearchRepository.insert_fact` directly for non-dedupe paths.
    """
    if draft.dedupe_key is None:
        raise ValueError(
            "insert_with_dedupe requires draft.dedupe_key to be set; "
            "use repository.insert_fact directly for non-dedupe inserts."
        )

    tenant_id = tenant_id_var.get()
    if tenant_id is None:
        raise RuntimeError(
            "insert_with_dedupe requires tenant_id_var to be set; "
            "the slice-3 ContextVar must be primed by the calling scheduler."
        )

    # SELECT 1 short-circuit — partial-index lookup is O(log n) on the
    # ``idx_research_facts_dedupe_key`` index from migration 0008.
    stmt = sa.text(
        "SELECT 1 FROM research_facts WHERE tenant_id = :tid AND dedupe_key = :key LIMIT 1"
    )
    result = await repository._session.execute(stmt, {"tid": tenant_id, "key": draft.dedupe_key})
    if result.scalar_one_or_none() is not None:
        logger.info(
            "research.%s.skipped_duplicate",
            draft.source_id,
            extra={"dedupe_key": draft.dedupe_key},
        )
        return None

    return await repository.insert_fact(draft)


__all__ = ["insert_with_dedupe"]
