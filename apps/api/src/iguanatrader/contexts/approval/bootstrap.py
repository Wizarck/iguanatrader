"""Approval context bootstrap — wire :class:`ApprovalService` + :class:`MessageBus`.

The route layer + SSE stream + CLI all need access to the same
:class:`ApprovalService` instance + :class:`MessageBus` so events
emitted by REST writes are visible to SSE subscribers in the same
process. This module provides a process-wide lazy factory.

Thread-safety: FastAPI's request loop is single-threaded asyncio per
event-loop, so a module-level singleton is fine. Slice O1's
observability surface may swap this for an injected dependency once
the cross-context wiring matures.
"""

from __future__ import annotations

from functools import lru_cache

from iguanatrader.contexts.approval.repository import ApprovalRepository
from iguanatrader.contexts.approval.service import ApprovalService
from iguanatrader.shared.messagebus import MessageBus


@lru_cache(maxsize=1)
def get_message_bus() -> MessageBus:
    """Process-wide :class:`MessageBus` for cross-context events."""
    return MessageBus()


def make_repository() -> ApprovalRepository:
    """Per-request :class:`ApprovalRepository`. The session is read
    from :data:`session_var` lazily via :class:`BaseRepository`.
    """
    return ApprovalRepository()


def make_service() -> ApprovalService:
    """Construct an :class:`ApprovalService` bound to the shared bus."""
    return ApprovalService(
        repository=make_repository(),
        message_bus=get_message_bus(),
    )


__all__ = [
    "get_message_bus",
    "make_repository",
    "make_service",
]
