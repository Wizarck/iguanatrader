"""Hindsight integration (slice R6).

Hindsight is the narrative-recall complement to the SQL bitemporal
:class:`ResearchFact` store:

* :func:`HindsightPort.retain` — always-on write (FR80) of brief
  summaries to a per-tenant memory bank
  ``iguanatrader-research-<tenant_id>``.
* :func:`HindsightPort.recall` — togglable per-tenant read (FR81),
  gated by ``tenants.feature_flags.hindsight_recall_enabled`` (default
  OFF; recommended ON after >=12 months of operation).

The SQL bitemporal facts remain source-of-truth for citation chain
(NFR-O8) + provenance + audit reproducibility - Hindsight does NOT
replace, it complements with semantic narrative.

Three error classes for graceful degradation per NFR-I8:

* :class:`HindsightUnavailable` - connection/transport failure.
* :class:`HindsightTimeout` - request exceeded the per-call deadline
  (default 2s on recall, 5s on retain).
* :class:`HindsightWriteFailed` - non-2xx response on retain.
"""

from __future__ import annotations

from typing import ClassVar

from iguanatrader.shared.errors import IguanaError


class HindsightUnavailable(IguanaError):
    """Hindsight backend unreachable (connection / transport)."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:hindsight-unavailable"
    default_title: ClassVar[str] = "Hindsight Unavailable"
    default_status: ClassVar[int] = 503


class HindsightTimeout(IguanaError):
    """Hindsight request exceeded its per-call deadline."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:hindsight-timeout"
    default_title: ClassVar[str] = "Hindsight Timeout"
    default_status: ClassVar[int] = 504


class HindsightWriteFailed(IguanaError):
    """Hindsight retain returned a non-2xx response."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:hindsight-write-failed"
    default_title: ClassVar[str] = "Hindsight Write Failed"
    default_status: ClassVar[int] = 502


__all__ = [
    "HindsightTimeout",
    "HindsightUnavailable",
    "HindsightWriteFailed",
]
