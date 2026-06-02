"""Integration tests for the D9 boot-time prod cookie guard.

Per task 7.9: ``IGUANATRADER_ENV=production`` +
``IGUANATRADER_DEV_INSECURE_COOKIE=1`` → :class:`ConfigError` is
raised the moment any cookie write path runs (in this slice that is
:func:`iguanatrader.api.deps.is_secure_cookie`).
"""

from __future__ import annotations

import pytest
from iguanatrader.api.deps import is_secure_cookie
from iguanatrader.config.settings import (
    DEV_INSECURE_COOKIE_ENV,
    ENV_VAR,
    ConfigError,
    enforce_dev_insecure_cookie_prod_guard,
)


def test_guard_raises_when_dev_insecure_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "production")
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    with pytest.raises(ConfigError) as excinfo:
        enforce_dev_insecure_cookie_prod_guard()
    assert excinfo.value.status == 500
    assert "production" in (excinfo.value.detail or "")


def test_guard_passes_when_dev_insecure_in_dev_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "dev")
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    enforce_dev_insecure_cookie_prod_guard()  # no raise


@pytest.mark.parametrize("env", ["paper", "live", "production", "PAPER", " Live "])
def test_guard_raises_for_all_production_like_envs(
    env: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#10: the guard must fire for paper/live, not just production."""
    monkeypatch.setenv(ENV_VAR, env)
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    with pytest.raises(ConfigError):
        enforce_dev_insecure_cookie_prod_guard()


@pytest.mark.parametrize("env", ["dev", "test", "ci", ""])
def test_guard_passes_for_non_production_envs(env: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, env)
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    enforce_dev_insecure_cookie_prod_guard()  # no raise


def test_guard_passes_when_secure_cookie_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "production")
    monkeypatch.delenv(DEV_INSECURE_COOKIE_ENV, raising=False)
    enforce_dev_insecure_cookie_prod_guard()  # no raise


def test_is_secure_cookie_invokes_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ENV_VAR, "production")
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    with pytest.raises(ConfigError):
        is_secure_cookie()


def test_is_secure_cookie_returns_false_for_dev_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(ENV_VAR, "dev")
    monkeypatch.setenv(DEV_INSECURE_COOKIE_ENV, "1")
    assert is_secure_cookie() is False


def test_is_secure_cookie_default_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.delenv(DEV_INSECURE_COOKIE_ENV, raising=False)
    assert is_secure_cookie() is True
