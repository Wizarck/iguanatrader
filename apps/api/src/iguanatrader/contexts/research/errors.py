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

from iguanatrader.shared.errors import (
    IguanaError,
    IntegrationError,
    RateLimitError,
    ValidationError,
)


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


class SourceUnavailableError(IntegrationError):
    """Tier-A adapter exhausted retries against an upstream API (slice R2).

    Distinct ``type`` URI from :class:`IntegrationError` so operators can
    pattern-match on "this specific Tier-A source is unavailable" vs the
    generic 502 lift used elsewhere. Default 503 (we *know* it is down for
    now; an IBKR transient is 502 because we cannot tell).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:source-unavailable"
    default_title: ClassVar[str] = "Research Source Unavailable"
    default_status: ClassVar[int] = 503


class RateLimitedError(RateLimitError):
    """Adapter response indicated the source rate-limited us (slice R2).

    BLS' "200 OK + status=REQUEST_NOT_PROCESSED" is the canonical example.
    Subclass of :class:`RateLimitError` so the slice-5 global handler still
    surfaces 429; distinct ``type`` URI for source-side observability.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:research-rate-limited"
    default_title: ClassVar[str] = "Research Source Rate Limited"


class InvalidCitationError(IguanaError):
    """LLM emitted a ``[fact:<uuid>]`` marker not present in the input bundle (R5).

    Per design D3 step 6 + D10: every citation marker MUST resolve to a
    fact id provided in the synthesizer's prompt context. An invented
    UUID raises this error and the synthesis aborts (no brief persisted).
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:invalid-citation"
    default_title: ClassVar[str] = "Invalid Citation"
    default_status: ClassVar[int] = 502


class BriefSynthesisShortError(IguanaError):
    """Synthesised brief body is too short — likely LLM degenerated (R5 design Q3).

    Pragmatic 100-word floor — adjustable in v1.5 based on observed
    corpora. Surfaces as 502 because the synthesiser produced output
    but the output is not usable.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:brief-too-short"
    default_title: ClassVar[str] = "Brief Synthesis Too Short"
    default_status: ClassVar[int] = 502


class InsufficientPriceDataError(ValidationError):
    """Synthesis blocked because close_price is missing from the feature bundle.

    The LLM cannot produce a coherent recommendation without a current-price
    anchor. Callers should ingest price bars before retrying.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:insufficient-price-data"
    default_title: ClassVar[str] = "Insufficient Price Data"
    default_status: ClassVar[int] = 422


class ConfigError(IguanaError):
    """Adapter failed init due to missing/malformed configuration (slice R2).

    Raised at :meth:`__init__` of every Tier-A adapter when its required
    env var (``SEC_EDGAR_USER_AGENT``, ``FRED_API_KEY``, ``BLS_API_KEY``,
    ``BEA_API_KEY``) is unset or fails format validation. Surfaces as RFC
    7807 500 — operators must fix the env, not the caller.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:config"
    default_title: ClassVar[str] = "Configuration Error"
    default_status: ClassVar[int] = 500


__all__ = [
    "BriefSynthesisShortError",
    "ConfigError",
    "InsufficientPriceDataError",
    "InvalidCitationError",
    "MissingProvenanceError",
    "RateLimitedError",
    "ResearchStubNotImplementedError",
    "SourceUnavailableError",
]
