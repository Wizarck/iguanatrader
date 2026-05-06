"""yfinance proxy adapter — routes through the OpenBB sidecar.

Per slice R4 design D7: ``yfinance`` is a runtime dependency of the
OpenBB Platform's default provider. iguanatrader does NOT import
``yfinance`` directly — the dependency lives only inside the sidecar
container (which carries the AGPL boundary). For symbols where yfinance
is the canonical source (e.g. ESG aggregates), we still want a dedicated
:class:`SourcePort` so the synthesis layer (R5) can reason about
``source_id="yfinance"`` distinctly from ``"openbb-sidecar"``.

Implementation is a thin re-skin of :class:`OpenBBSidecarSource` —
same HTTP endpoints, different ``SOURCE_ID`` so research_facts rows
are tagged correctly. Future slices can split this into a separate
sidecar microservice if yfinance's update cadence diverges from
openbb's.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from iguanatrader.contexts.research.ports import ResearchFactDraft
from iguanatrader.contexts.research.sources.openbb_sidecar import OpenBBSidecarSource

logger = logging.getLogger(__name__)


class YFinanceProxySource(OpenBBSidecarSource):
    """yfinance-tagged source backed by the OpenBB sidecar's openbb→yfinance path."""

    SOURCE_ID = "yfinance"

    def fetch(
        self,
        symbol: str,
        since: datetime | None,
    ) -> Iterable[ResearchFactDraft]:
        # Re-tag the parent's drafts with yfinance source_id. The sidecar
        # endpoint is shared; the distinction is bookkeeping only.
        for draft in super().fetch(symbol, since):
            yield ResearchFactDraft(
                source_id=self.SOURCE_ID,
                fact_kind=draft.fact_kind,
                effective_from=draft.effective_from,
                recorded_from=draft.recorded_from,
                source_url=draft.source_url,
                retrieval_method=draft.retrieval_method,
                retrieved_at=draft.retrieved_at,
                value_jsonb=draft.value_jsonb,
                fact_metadata={
                    **(draft.fact_metadata or {}),
                    "via": "openbb-sidecar",
                    "underlying_provider": "yfinance",
                },
                raw_payload_inline=draft.raw_payload_inline,
                raw_payload_path=draft.raw_payload_path,
                raw_payload_sha256=draft.raw_payload_sha256,
                raw_payload_size_bytes=draft.raw_payload_size_bytes,
            )
