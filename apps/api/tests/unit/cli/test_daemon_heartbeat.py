"""Daemon liveness heartbeat (container healthcheck source).

The daemon stamps a heartbeat file on its own event loop; the compose
healthcheck reads its freshness instead of curling a port the daemon does not
serve. A wedged daemon stops stamping → the file goes stale → the container is
restarted. These tests lock the path resolution + that the loop stamps a fresh
epoch and exits promptly when shutdown is signalled.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest
from iguanatrader.cli.trading import _heartbeat_loop, _heartbeat_path


def test_heartbeat_path_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IGUANATRADER_DAEMON_HEARTBEAT_PATH", raising=False)
    assert _heartbeat_path("paper") == "/data/daemon_heartbeat_paper"
    assert _heartbeat_path("live") == "/data/daemon_heartbeat_live"


def test_heartbeat_path_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_DAEMON_HEARTBEAT_PATH", "/custom/hb")
    assert _heartbeat_path("live") == "/custom/hb"


@pytest.mark.asyncio
async def test_heartbeat_writes_fresh_epoch_and_stops_on_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hb = tmp_path / "hb_paper"
    monkeypatch.setenv("IGUANATRADER_DAEMON_HEARTBEAT_PATH", str(hb))
    stop = asyncio.Event()
    task = asyncio.create_task(_heartbeat_loop("paper", stop, interval=0.05))
    await asyncio.sleep(0.12)  # at least one stamp written

    assert hb.exists()
    stamp = int(hb.read_text(encoding="utf-8"))
    assert abs(int(time.time()) - stamp) < 5  # fresh

    stop.set()
    await asyncio.wait_for(task, timeout=1.0)  # exits promptly on shutdown
    assert task.done()


@pytest.mark.asyncio
async def test_heartbeat_survives_unwritable_path(monkeypatch: pytest.MonkeyPatch) -> None:
    # A disk hiccup must not kill the loop (it logs + keeps ticking).
    monkeypatch.setenv("IGUANATRADER_DAEMON_HEARTBEAT_PATH", "/nonexistent-dir/hb")
    stop = asyncio.Event()
    task = asyncio.create_task(_heartbeat_loop("paper", stop, interval=0.05))
    await asyncio.sleep(0.12)
    assert not task.done()  # still running despite the write failures
    stop.set()
    await asyncio.wait_for(task, timeout=1.0)
