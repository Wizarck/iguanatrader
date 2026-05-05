"""Research-context error classes.

Per slice-5 design D9 precedent (:class:`BootstrapNotReadyError` plants new
:class:`IguanaError` subclasses inline as slices need them) AND per Wave-2
cross-slice anti-collision contract: parallel slices T1 + K1 also extend
:mod:`iguanatrader.shared.errors` in their own worktrees, so adding R1's
two subclasses to :mod:`shared.errors` would force a 3-way merge resolution
at Wave-2 fan-in. Instead, we declare the slice-local classes here. They
still inherit from :class:`IguanaError`, so the slice-5 global handler in
:mod:`iguanatrader.api.errors` renders them as RFC 7807 Problem Details —
status + canonical ``urn:iguanatrader:error:*`` ``type`` URI surface
identical to a class declared in ``shared/errors.py``.

The post-Wave-2 follow-up is to lift these into ``shared/errors.py`` once
T1/K1 are merged; that lift is purely a code-organisation change with zero
wire impact (classes preserve their ``type_uri`` and HTTP status).

Mirrors the pattern in :mod:`iguanatrader.persistence.errors` (slice 3 D9):
"persistence-specific errors live in the package that owns them, not in
``shared/`` which knows nothing about persistence per the slice-2 contract."
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IguanaError, ValidationError


class MissingProvenanceError(ValidationError):
    """Insert into ``research_facts`` lacked NOT NULL/CHECK provenance fields.

    Lifted from the SQLAlchemy driver's :class:`IntegrityError` at the
    :class:`ResearchRepository` boundary. The slice-5 global handler renders
    this as RFC 7807 422 with ``type=urn:iguanatrader:error:missing-provenance``.

    Subclasses :class:`ValidationError` (HTTP 400) but overrides
    :attr:`default_status` to 422 ("the request was well-formed but
    semantically incorrect") because the missing field is data-shape, not
    request-shape — the caller's HTTP body parsed fine but its semantics
    violated the database invariant.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:missing-provenance"
    default_title: ClassVar[str] = "Research Fact Missing Provenance"
    default_status: ClassVar[int] = 422


class ResearchStubNotImplementedError(IguanaError):
    """Slice-local 501 for research route stubs until R5.

    Mirrors slice 4's ``_problem_response`` precedent + slice 5 design D6:
    routes ``raise``, the global handler renders. Using a typed subclass
    (rather than ``raise NotImplementedError(...)``) preserves the canonical
    ``type`` URI in the rendered Problem body and gives operators a
    queryable structlog event when stubs fire.

    R5 (``research-brief-synthesis``) replaces every route handler that
    raises this with a real implementation; the class itself stays for
    any future stubs that may emerge mid-Wave-3.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:research-stub"
    default_title: ClassVar[str] = "Endpoint Not Yet Implemented"
    default_status: ClassVar[int] = 501


__all__ = [
    "MissingProvenanceError",
    "ResearchStubNotImplementedError",
]
