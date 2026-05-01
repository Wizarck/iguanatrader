"""Unit tests for :mod:`iguanatrader.shared.heartbeat`."""

from __future__ import annotations

import asyncio

import pytest
from iguanatrader.shared.heartbeat import ConnectionState, HeartbeatMixin


class _RecordingAdapter(HeartbeatMixin):
    """Test double — counts callback invocations + can be made to fail."""

    def __init__(self, *, fail_n_heartbeats: int = 0) -> None:
        super().__init__()
        self.disconnect_callback_count = 0
        self.heartbeat_callback_count = 0
        self._heartbeats_to_fail = fail_n_heartbeats

    async def _send_heartbeat(self) -> None:
        self.heartbeat_callback_count += 1
        if self._heartbeats_to_fail > 0:
            self._heartbeats_to_fail -= 1
            raise RuntimeError("simulated network failure")

    async def _on_disconnect(self) -> None:
        self.disconnect_callback_count += 1


class TestAbstractEnforcement:
    def test_cannot_instantiate_without_overriding_abstract_methods(self) -> None:
        # Subclasses that omit one of the abstract hooks must not be
        # instantiable — caught at __init__ via ABC, not at the first
        # method call.
        class _Incomplete(HeartbeatMixin):
            async def _send_heartbeat(self) -> None:
                pass

            # _on_disconnect intentionally not implemented.

        with pytest.raises(TypeError, match="abstract"):
            _Incomplete()  # type: ignore[abstract]


class TestInitialState:
    def test_starts_disconnected(self) -> None:
        a = _RecordingAdapter()
        assert a.state == ConnectionState.DISCONNECTED


class TestIdempotentTransitions:
    def test_mark_connected_idempotent(self) -> None:
        a = _RecordingAdapter()
        a.mark_connected()
        a.mark_connected()
        assert a.state == ConnectionState.CONNECTED

    def test_mark_reconnecting_idempotent(self) -> None:
        a = _RecordingAdapter()
        a.mark_reconnecting()
        a.mark_reconnecting()
        assert a.state == ConnectionState.RECONNECTING

    async def test_mark_disconnected_callback_fires_once_per_real_transition(
        self,
    ) -> None:
        a = _RecordingAdapter()
        a.mark_connected()
        await a.mark_disconnected()
        await a.mark_disconnected()  # already DISCONNECTED — no-op
        assert a.disconnect_callback_count == 1

    async def test_mark_disconnected_from_disconnected_does_not_fire(self) -> None:
        a = _RecordingAdapter()
        # state is DISCONNECTED at construction.
        await a.mark_disconnected()
        assert a.disconnect_callback_count == 0


class TestStateMachine:
    async def test_connected_to_disconnected_to_connected(self) -> None:
        # mypy narrows ``a.state`` to a literal after each transition method,
        # which then triggers ``comparison-overlap`` on the next assertion
        # against a different literal. We compare on ``.value`` (str) here
        # to side-step the narrowing — same runtime semantics, different
        # static analysis.
        a = _RecordingAdapter()
        a.mark_connected()
        assert a.state.value == "connected"
        await a.mark_disconnected()
        assert a.state.value == "disconnected"
        assert a.disconnect_callback_count == 1
        a.mark_reconnecting()
        # mypy narrows a.state.value to Literal["disconnected"] from the
        # previous assert; it cannot follow the mark_*() mutation.
        assert a.state.value == "reconnecting"  # type: ignore[comparison-overlap]
        a.mark_connected()
        assert a.state.value == "connected"

    async def test_state_property_is_read_only(self) -> None:
        a = _RecordingAdapter()
        with pytest.raises(AttributeError):
            a.state = ConnectionState.CONNECTED  # type: ignore[misc]


class TestReconnectLoop:
    async def test_succeeds_on_first_attempt_marks_connected(self) -> None:
        a = _RecordingAdapter(fail_n_heartbeats=0)
        await a.reconnect_loop()
        assert a.state == ConnectionState.CONNECTED
        assert a.heartbeat_callback_count == 1

    async def test_uses_backoff_on_failures(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Speed up the test: stub out asyncio.sleep so backoff returns
        # immediately. We still verify that reconnect_loop calls sleep
        # the expected number of times.
        sleep_calls: list[float] = []

        async def fake_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)

        monkeypatch.setattr(asyncio, "sleep", fake_sleep)

        # Fail first 2 attempts, succeed on the 3rd.
        a = _RecordingAdapter(fail_n_heartbeats=2)
        await a.reconnect_loop()

        assert a.state == ConnectionState.CONNECTED
        assert a.heartbeat_callback_count == 3
        # Two sleeps before the successful 3rd attempt; each is a jittered
        # value within ±20% of the canonical sequence (3, 6).
        assert len(sleep_calls) == 2
        assert 3 * 0.8 <= sleep_calls[0] <= 3 * 1.2
        assert 6 * 0.8 <= sleep_calls[1] <= 6 * 1.2
