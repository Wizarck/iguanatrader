"""In-process bus event declarations for the research bounded context.

Per design notes (R1 ships event classes only; subscribers wired in R5/R6):

* :class:`ResearchFactIngested` — fired by :class:`ResearchRepository` after
  a successful :meth:`insert_fact`. Carries the minimal payload needed by
  downstream consumers (R5 brief synthesis trigger, R6 Hindsight bridge,
  observability cost meter).
* :class:`ResearchBriefSynthesized` — fired by R5's brief service after a
  successful brief insert. Carries identifying fields + the partial flag
  so downstream consumers know whether to retry.

The :class:`Event` base class lives in :mod:`iguanatrader.shared.messagebus`
(slice 2). All event payloads are dataclasses (mutable not required;
serialisation happens at handler boundary).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from iguanatrader.shared.messagebus import Event


@dataclass
class ResearchFactIngested(Event):
    """Emitted after :meth:`ResearchRepository.insert_fact` succeeds.

    Subscribers (R5 brief synthesis kick-off, R6 Hindsight retain hook,
    observability slice cost meter) receive this in FIFO order per
    :class:`MessageBus` semantics. The event does not carry the full
    fact payload to keep the bus light; subscribers re-query by
    ``fact_id`` when they need detail.
    """

    tenant_id: UUID | None = None
    fact_id: UUID | None = None
    source_id: str = ""
    symbol_universe_id: UUID | None = None
    fact_kind: str = ""
    recorded_from: datetime | None = None


@dataclass
class ResearchBriefSynthesized(Event):
    """Emitted after :meth:`ResearchRepository.insert_brief` succeeds (R5).

    R1 declares the class; R5 emits + R6 subscribes (Hindsight bridge
    trigger). The ``partial=True`` case is observable so a follow-up
    refresh can be scheduled without waiting for the next cron tick.
    """

    tenant_id: UUID | None = None
    brief_id: UUID | None = None
    symbol_universe_id: UUID | None = None
    version: int = 0
    methodology: str = ""
    partial: bool = False


__all__ = [
    "ResearchBriefSynthesized",
    "ResearchFactIngested",
]
