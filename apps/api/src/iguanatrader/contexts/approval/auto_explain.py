"""Auto-explain dispatcher wrapper — slice A1.

Adds an LLM-generated narrative to outbound approval-request messages
*before* they fan out to Hermes channels (Telegram / WhatsApp /
dashboard). Operators receive a 2-3 paragraph explanation of the
trade proposal alongside the raw "approve/reject" prompt — they no
longer have to context-switch to the dashboard to understand the
proposed entry / stop / risk-sizing rationale.

Architecture:

* Wraps any concrete :class:`ChannelDispatcher` (log-only, real
  Hermes adapter, future MCP-driven dispatch). The wrapper builds
  the narrative *in-process* (no extra HTTP) by calling an injected
  ``NarrativeProvider`` callable, then mutates the request's
  ``narrative`` field before delegating to the inner ``fanout``.
* Best-effort: any failure in narrative generation (LLM timeout,
  budget exceeded, parse error, network) is logged + swallowed; the
  inner dispatcher then sees an unenriched request and fanout
  proceeds with the legacy raw template.
* Budget guard sits inside :func:`route_llm` (slice R6) which the
  explainer calls internally; A0 cap hits surface here as the same
  swallowed-exception path above.

The wrapper does NOT mutate the underlying ``ApprovalRequestRow`` on
disk — narrative is attached to the *event payload only* via a new
``narrative`` attribute on the dataclass. Channels that don't know
about the attribute (older adapters) keep working unchanged.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from iguanatrader.contexts.approval.channels.types import ApprovalRequestRow
    from iguanatrader.contexts.approval.dispatcher import ChannelDispatcher

logger = logging.getLogger(__name__)


#: A NarrativeProvider takes the approval request and returns the
#: LLM-generated explanation. Composition root wires it up:
#:
#:     async def _provider(request):
#:         row = await proposal_repo.get(request.proposal_id)
#:         result = await explainer.explain(
#:             proposal_id=str(row.id),
#:             symbol=row.symbol,
#:             ...,
#:         )
#:         return result.narrative
#:
#: Tests inject a synchronous fake that returns canned text.
NarrativeProvider = Callable[["ApprovalRequestRow"], Awaitable[str]]


class AutoExplainEnrichingDispatcher:
    """Wraps a :class:`ChannelDispatcher` with a narrative pre-pass.

    The :meth:`fanout` signature matches the inner dispatcher exactly
    (Protocol-compatible), so the composition root can swap this in
    without touching upstream callers.
    """

    def __init__(
        self,
        *,
        inner: ChannelDispatcher,
        provider: NarrativeProvider,
    ) -> None:
        self._inner = inner
        self._provider = provider

    async def fanout(
        self,
        *,
        request: ApprovalRequestRow,
        channels: list[str],
    ) -> None:
        narrative = await self._safe_generate(request)
        if narrative:
            # Attach to the request payload so the inner dispatcher's
            # message builder picks it up. The frozen dataclass nature
            # of ApprovalRequestRow means we can't mutate it directly;
            # the channel adapter reads from `request.narrative` if
            # present (dynamic attr — older adapters ignore it).
            object.__setattr__(request, "narrative", narrative)
        await self._inner.fanout(request=request, channels=channels)

    async def _safe_generate(self, request: ApprovalRequestRow) -> str | None:
        try:
            narrative = await self._provider(request)
        except Exception as exc:  # best-effort by design
            logger.warning(
                "approval.auto_explain.failed",
                extra={
                    "request_id": str(request.id),
                    "proposal_id": str(request.proposal_id),
                    "error": f"{type(exc).__name__}: {exc}",
                },
            )
            return None
        if not narrative or not narrative.strip():
            logger.info(
                "approval.auto_explain.empty",
                extra={
                    "request_id": str(request.id),
                    "proposal_id": str(request.proposal_id),
                },
            )
            return None
        return narrative


__all__ = ["AutoExplainEnrichingDispatcher", "NarrativeProvider"]
