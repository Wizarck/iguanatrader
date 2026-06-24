"""Unit tests for :class:`TelegramCallbackPoller` — tap-to-approve inbound.

Exercises ``_handle_callback`` directly (no live long-poll) with an httpx
``MockTransport`` capturing ``answerCallbackQuery`` / ``editMessageText`` and
fakes for the repository / service / session-scope so the real command
dispatcher runs end-to-end: owner gate, command routing, ack + card edit.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import httpx
import pytest
from iguanatrader.contexts.approval.channels.command_handler import reset_idempotency_cache
from iguanatrader.contexts.approval.channels.telegram_poller import TelegramCallbackPoller
from iguanatrader.contexts.approval.repository import ResolvedSender


@pytest.fixture(autouse=True)
def _reset_dedup() -> None:
    reset_idempotency_cache()


class _FakeSession:
    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...


class _FakeSessionCM:
    async def __aenter__(self) -> _FakeSession:
        return _FakeSession()

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _session_factory() -> _FakeSessionCM:
    return _FakeSessionCM()


class _FakeBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


class _FakeDecision:
    def __init__(self) -> None:
        self.id = uuid4()
        self.created_at = datetime.now(UTC)


class _FakeService:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, str]] = []

    async def record_decision(
        self,
        *,
        request_id: Any,
        outcome: str,
        decided_via_channel: str,
        decided_by_user_id: Any = None,
        decided_by_sender_id: Any = None,
        reason: Any = None,
    ) -> _FakeDecision:
        self.calls.append((request_id, outcome))
        return _FakeDecision()


class _FakeRepo:
    def __init__(self, *, authorized: bool) -> None:
        self._authorized = authorized

    async def resolve_enabled_sender(
        self, *, tenant_id: Any, channel: str, external_id: str
    ) -> ResolvedSender | None:
        if not self._authorized:
            return None
        return ResolvedSender(id=uuid4(), role="user")


def _client(captured: list[tuple[str, dict[str, Any]]]) -> httpx.AsyncClient:
    def _handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode() or "{}") if request.content else {}
        captured.append((str(request.url), body))
        return httpx.Response(200, json={"ok": True, "result": {}})

    return httpx.AsyncClient(transport=httpx.MockTransport(_handler))


def _callback(data: str, *, from_id: int = 4242) -> dict[str, Any]:
    return {
        "id": "cq-1",
        "data": data,
        "from": {"id": from_id},
        "message": {
            "message_id": 99,
            "chat": {"id": from_id},
            "text": "🟢 COMPRAR (LARGO) AAPL",
        },
    }


def _make_poller(
    *, authorized: bool, captured: list[tuple[str, dict[str, Any]]]
) -> tuple[TelegramCallbackPoller, _FakeService]:
    service = _FakeService()
    poller = TelegramCallbackPoller(
        bot_token="tok",
        tenant_id=uuid4(),
        service=service,
        message_bus=_FakeBus(),
        repository=_FakeRepo(authorized=authorized),
        session_factory=_session_factory,
        client=_client(captured),
    )
    return poller, service


@pytest.mark.asyncio
async def test_authorized_approve_records_and_edits() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    poller, service = _make_poller(authorized=True, captured=captured)
    rid = uuid4()

    await poller._handle_callback(_callback(f"approve:{rid}"))

    assert service.calls == [(rid, "granted")]
    urls = [u for u, _ in captured]
    assert any("answerCallbackQuery" in u for u in urls)
    edit = next(b for u, b in captured if "editMessageText" in u)
    assert "Aprobado" in edit["text"]


@pytest.mark.asyncio
async def test_authorized_reject_records_rejected() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    poller, service = _make_poller(authorized=True, captured=captured)
    rid = uuid4()

    await poller._handle_callback(_callback(f"reject:{rid}"))

    assert service.calls == [(rid, "rejected")]
    edit = next(b for u, b in captured if "editMessageText" in u)
    assert "Rechazado" in edit["text"]


@pytest.mark.asyncio
async def test_unauthorized_tap_records_nothing() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    poller, service = _make_poller(authorized=False, captured=captured)

    await poller._handle_callback(_callback(f"approve:{uuid4()}"))

    assert service.calls == []  # fail-closed: no decision recorded
    answer = next(b for u, b in captured if "answerCallbackQuery" in u)
    assert "autoriza" in answer["text"].lower()
    assert not any("editMessageText" in u for u, _ in captured)


@pytest.mark.asyncio
async def test_malformed_callback_data_is_ignored() -> None:
    captured: list[tuple[str, dict[str, Any]]] = []
    poller, service = _make_poller(authorized=True, captured=captured)

    await poller._handle_callback(_callback("garbage-without-colon"))

    assert service.calls == []
    answer = next(b for u, b in captured if "answerCallbackQuery" in u)
    assert "reconoc" in answer["text"].lower()
