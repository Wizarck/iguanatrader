"""``IGUANATRADER_RESEARCH_CACHE_ROOT`` env override resolution.

The repository's hybrid-storage payload root defaults to
``data/research_cache`` (relative). Production deploys override via env
so the CLI doesn't need ``--workdir /data`` to avoid PermissionError
when ``app`` user tries to ``mkdir`` under ``/app/data/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from iguanatrader.contexts.research.repository import (
    DEFAULT_PAYLOAD_ROOT,
    ResearchRepository,
)


def test_default_payload_root_when_env_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("IGUANATRADER_RESEARCH_CACHE_ROOT", raising=False)
    repo = ResearchRepository()
    assert repo.payload_root == DEFAULT_PAYLOAD_ROOT


def test_env_override_wins_over_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_RESEARCH_CACHE_ROOT", "/data/research_cache")
    repo = ResearchRepository()
    assert repo.payload_root == Path("/data/research_cache")


def test_explicit_constructor_arg_wins_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests passing ``payload_root=tmp_path / "x"`` must not be shadowed by env."""
    monkeypatch.setenv("IGUANATRADER_RESEARCH_CACHE_ROOT", "/should/be/ignored")
    explicit = Path("/some/test/path")
    repo = ResearchRepository(payload_root=explicit)
    assert repo.payload_root == explicit


def test_empty_env_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """``IGUANATRADER_RESEARCH_CACHE_ROOT=`` (empty) falls back, not Path('')."""
    monkeypatch.setenv("IGUANATRADER_RESEARCH_CACHE_ROOT", "")
    repo = ResearchRepository()
    assert repo.payload_root == DEFAULT_PAYLOAD_ROOT
