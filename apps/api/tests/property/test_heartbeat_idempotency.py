"""Property test: HeartbeatMixin transitions are idempotent.

For any sequence of ``mark_connected / mark_disconnected /
mark_reconnecting`` calls drawn from a state-machine grammar, the final
state matches the LAST call's intent and the ``_on_disconnect``
callback fires AT MOST ONCE per genuine ``CONNECTED → DISCONNECTED``
or ``RECONNECTING → DISCONNECTED`` transition (never on a duplicate
``mark_disconnected`` while already DISCONNECTED).
"""

from __future__ import annotations

import asyncio
import sys

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from iguanatrader.shared.heartbeat import ConnectionState, HeartbeatMixin

# On Windows asyncio defaults to ``ProactorEventLoop``; when Hypothesis
# spawns hundreds of ``asyncio.run`` calls, proactor loops leak FDs and
# emit ``ResourceWarning`` which our ``filterwarnings = ["error"]`` config
# turns into a failure. Selector loops are leak-free for this test's usage.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


class _RecordingAdapter(HeartbeatMixin):
    def __init__(self) -> None:
        super().__init__()
        self.disconnect_callback_count = 0

    async def _send_heartbeat(self) -> None:
        # Not exercised in this property test.
        pass

    async def _on_disconnect(self) -> None:
        self.disconnect_callback_count += 1


# Grammar: each step is one of three transition method names.
_STEP = st.sampled_from(["connected", "disconnected", "reconnecting"])
_SEQUENCES = st.lists(_STEP, min_size=1, max_size=50)


@given(steps=_SEQUENCES)
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_final_state_matches_last_step_and_callback_count_is_real_transitions(
    steps: list[str],
) -> None:
    """Final state matches last step's intent; callback count matches the
    number of *genuine* CONNECTED/RECONNECTING → DISCONNECTED transitions.
    """
    asyncio.run(_run(steps))


async def _run(steps: list[str]) -> None:
    a = _RecordingAdapter()

    expected_disconnect_callbacks = 0
    last_state = a.state  # initially DISCONNECTED

    for step in steps:
        if step == "connected":
            a.mark_connected()
            last_state = ConnectionState.CONNECTED
        elif step == "reconnecting":
            a.mark_reconnecting()
            last_state = ConnectionState.RECONNECTING
        elif step == "disconnected":
            if a.state is not ConnectionState.DISCONNECTED:
                expected_disconnect_callbacks += 1
            await a.mark_disconnected()
            last_state = ConnectionState.DISCONNECTED
        else:  # pragma: no cover - exhaustive
            pytest.fail(f"unexpected step {step!r}")

    assert a.state is last_state
    assert a.disconnect_callback_count == expected_disconnect_callbacks
