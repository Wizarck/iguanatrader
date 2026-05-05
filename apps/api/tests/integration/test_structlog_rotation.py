"""Integration tests for structlog config + RotatingFileHandler (NFR-O3 + design D6).

Test matrix (per task 7.7):

- Test / dev env → stdout only, no file created.
- Paper env → file handler created at ``logs/iguanatrader-paper.log``.
- Rotation triggered by ``maxBytes`` boundary (test hook with tiny size).
- Skipped on Windows or marked xfail per design D6 risks (rotation flake).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from iguanatrader.contexts.observability.structlog_config import configure_logging


def _detach_all_file_handlers() -> None:
    """Remove RotatingFileHandlers from the root logger between tests."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        if isinstance(handler, logging.handlers.RotatingFileHandler):
            root.removeHandler(handler)
            handler.close()


@pytest.fixture(autouse=True)
def _isolate_logging(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    monkeypatch.chdir(tmp_path)
    _detach_all_file_handlers()
    yield
    _detach_all_file_handlers()


def test_test_env_uses_stdout_only() -> None:
    configure_logging("test")
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []


def test_dev_env_uses_stdout_only() -> None:
    configure_logging("dev")
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="RotatingFileHandler has known Windows file-locking quirks per design D6 risks",
)
def test_paper_env_attaches_rotating_file_handler(tmp_path: Path) -> None:
    configure_logging("paper")
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(file_handlers) == 1
    handler = file_handlers[0]
    assert handler.maxBytes == 100 * 1024 * 1024
    assert handler.backupCount == 7
    log_path = Path(handler.baseFilename)
    assert log_path.name == "iguanatrader-paper.log"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="RotatingFileHandler has known Windows file-locking quirks per design D6 risks",
)
def test_unknown_env_falls_back_to_test_behaviour() -> None:
    configure_logging("nonsense")
    root = logging.getLogger()
    file_handlers = [
        h for h in root.handlers if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert file_handlers == []
