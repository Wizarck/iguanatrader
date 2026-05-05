"""Research bounded context — bitemporal knowledge fabric.

Public surface (re-exported here for stable consumer imports):

* ORM models — :class:`ResearchSource`, :class:`SymbolUniverse`,
  :class:`WatchlistConfig`, :class:`ResearchFact`, :class:`ResearchBrief`,
  :class:`CorporateEvent`, :class:`AnalystRating`.
* Ports — :class:`SourcePort` Protocol + :class:`ResearchFactDraft` dataclass
  (consumed by R2/R3/R4 source adapters).
* Repository — :class:`ResearchRepository` (extends slice-2
  :class:`BaseRepository`; bitemporal :meth:`as_of` + provenance-validating
  :meth:`insert_fact`).
* Errors — :class:`MissingProvenanceError`, :class:`ResearchStubNotImplementedError`
  (slice-local 422 / 501 :class:`IguanaError` subclasses, declared here to
  avoid colliding with parallel slice T1/K1 edits to ``shared/errors.py``).
* Events — :class:`ResearchFactIngested`, :class:`ResearchBriefSynthesized`
  (in-process bus payloads; subscribers wired in R5/R6).

R1 ships the schema + repository contracts + DTO/route stubs. R2/R3/R4 wire
adapters that implement :class:`SourcePort` and call
:meth:`ResearchRepository.insert_fact`. R5 fills in the brief synthesis
pipeline + replaces route stubs with real handlers.
"""

from __future__ import annotations

from iguanatrader.contexts.research.errors import (
    MissingProvenanceError,
    ResearchStubNotImplementedError,
)
from iguanatrader.contexts.research.events import (
    ResearchBriefSynthesized,
    ResearchFactIngested,
)
from iguanatrader.contexts.research.models import (
    AnalystRating,
    CorporateEvent,
    ResearchBrief,
    ResearchFact,
    ResearchSource,
    SymbolUniverse,
    WatchlistConfig,
)
from iguanatrader.contexts.research.ports import ResearchFactDraft, SourcePort
from iguanatrader.contexts.research.repository import ResearchRepository

__all__ = [
    "AnalystRating",
    "CorporateEvent",
    "MissingProvenanceError",
    "ResearchBrief",
    "ResearchBriefSynthesized",
    "ResearchFact",
    "ResearchFactDraft",
    "ResearchFactIngested",
    "ResearchRepository",
    "ResearchSource",
    "ResearchStubNotImplementedError",
    "SourcePort",
    "SymbolUniverse",
    "WatchlistConfig",
]
