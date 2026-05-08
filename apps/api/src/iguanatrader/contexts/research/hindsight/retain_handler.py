"""HindsightRetainHandler - bus-bridge follow-up #5 (slice R6).

Subscribes to :class:`ResearchBriefSynthesized` events emitted by R5's
:class:`BriefService.refresh`. On each emission, loads the brief by id,
composes a narrative chunk, and calls :meth:`HindsightPort.retain`.

Failures (Hindsight unavailable / timeout / write-failed / repository
lookup miss) are logged + swallowed - FR80 says always-on but
non-blocking (no retain failure should impact the brief synthesis
path).

Pattern: same shape as K1.RiskService.register_subscriptions
(PR #103) and P1.ApprovalService.register_subscriptions (PR #104).
Fifth canonical instance of bus-bridge follow-up; promote to
ai-playbook v0.11.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

from iguanatrader.contexts.research.hindsight import (
    HindsightTimeout,
    HindsightUnavailable,
    HindsightWriteFailed,
)

if TYPE_CHECKING:
    from iguanatrader.contexts.research.events import ResearchBriefSynthesized
    from iguanatrader.contexts.research.hindsight.port import HindsightPort
    from iguanatrader.contexts.research.repository import ResearchRepository
    from iguanatrader.shared.messagebus import MessageBus


log = structlog.get_logger("iguanatrader.contexts.research.hindsight.retain_handler")


class HindsightRetainHandler:
    """Always-on retain bridge (FR80) on ResearchBriefSynthesized event."""

    def __init__(
        self,
        *,
        hindsight: HindsightPort,
        repository: ResearchRepository,
    ) -> None:
        self._hindsight = hindsight
        self._repository = repository

    def register_subscriptions(self, bus: MessageBus) -> None:
        """Register the bus subscription (idempotent)."""
        from iguanatrader.contexts.research.events import (
            ResearchBriefSynthesized,
        )

        bus.subscribe(
            ResearchBriefSynthesized,
            self._on_brief_synthesized,
            idempotent=True,
        )

    async def _on_brief_synthesized(
        self,
        event: ResearchBriefSynthesized,
    ) -> None:
        """Handler: load brief + compose narrative + call retain."""
        if event.brief_id is None or event.tenant_id is None:
            log.warning(
                "research.hindsight.retain_skipped_no_ids",
                brief_id=str(event.brief_id),
                tenant_id=str(event.tenant_id),
            )
            return

        try:
            brief = await self._repository.get_brief_by_id(event.brief_id)
        except Exception as exc:
            log.warning(
                "research.hindsight.retain_lookup_failed",
                brief_id=str(event.brief_id),
                error=str(exc),
            )
            return

        if brief is None:
            log.warning(
                "research.hindsight.retain_brief_not_found",
                brief_id=str(event.brief_id),
            )
            return

        bank = f"iguanatrader-research-{event.tenant_id}"
        thesis = getattr(brief, "thesis_text", None) or ""
        if not thesis.strip():
            log.warning(
                "research.hindsight.retain_skipped_empty_thesis",
                brief_id=str(event.brief_id),
            )
            return
        metadata: dict[str, Any] = {
            "brief_id": str(event.brief_id),
            "tenant_id": str(event.tenant_id),
            "version": int(getattr(brief, "version", 0) or 0),
            "methodology": str(getattr(brief, "methodology", "") or ""),
        }

        try:
            await self._hindsight.retain(
                bank=bank,
                kind="brief_summary",
                content=thesis,
                metadata=metadata,
            )
        except (HindsightUnavailable, HindsightTimeout, HindsightWriteFailed) as exc:
            log.warning(
                "research.hindsight.retain_failed",
                brief_id=str(event.brief_id),
                error=str(exc),
            )
            return
        except Exception as exc:
            log.warning(
                "research.hindsight.retain_unexpected_error",
                brief_id=str(event.brief_id),
                error=str(exc),
            )
            return

        log.info(
            "research.hindsight.retain_ok",
            brief_id=str(event.brief_id),
            bank=bank,
            content_length=len(thesis),
        )


__all__ = ["HindsightRetainHandler"]
