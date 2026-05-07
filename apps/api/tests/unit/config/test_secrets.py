"""Unit tests for SecretEnv (slice deployment-foundation §2).

Verifies that:

* Each required property reads from ``os.environ`` and raises
  :class:`MissingSecretError` when unset or blank.
* Optional properties (``ibkr_host``, ``ib_client_id``) fall back to
  documented defaults when unset.
* Integer-coerced properties (``tws_port``, ``ib_client_id``) raise
  :class:`MissingSecretError` (NOT ``ValueError``) on malformed input,
  so the boot path surfaces a single error type.
"""

from __future__ import annotations

import pytest

from iguanatrader.config.secrets import MissingSecretError, SecretEnv


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> SecretEnv:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fake")
    monkeypatch.setenv("IBKR_USERNAME", "fake-user")
    monkeypatch.setenv("IBKR_PASSWORD", "fake-pass")
    monkeypatch.setenv("TWS_PORT", "7497")
    monkeypatch.setenv("DATABASE_PATH", "/tmp/db.sqlite")
    return SecretEnv()


def test_required_properties_return_env_values(env: SecretEnv) -> None:
    assert env.anthropic_api_key == "sk-ant-fake"
    assert env.ibkr_username == "fake-user"
    assert env.ibkr_password == "fake-pass"
    assert env.tws_port == 7497
    assert env.database_path == "/tmp/db.sqlite"


@pytest.mark.parametrize(
    "missing_var",
    ["ANTHROPIC_API_KEY", "IBKR_USERNAME", "IBKR_PASSWORD", "TWS_PORT", "DATABASE_PATH"],
)
def test_missing_required_raises_missing_secret(
    env: SecretEnv, monkeypatch: pytest.MonkeyPatch, missing_var: str
) -> None:
    monkeypatch.delenv(missing_var, raising=False)
    prop_name = {
        "ANTHROPIC_API_KEY": "anthropic_api_key",
        "IBKR_USERNAME": "ibkr_username",
        "IBKR_PASSWORD": "ibkr_password",
        "TWS_PORT": "tws_port",
        "DATABASE_PATH": "database_path",
    }[missing_var]
    with pytest.raises(MissingSecretError) as exc_info:
        _ = getattr(env, prop_name)
    assert missing_var in str(exc_info.value)


def test_blank_value_treated_as_missing(
    env: SecretEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    with pytest.raises(MissingSecretError):
        _ = env.anthropic_api_key


def test_optional_ibkr_host_defaults_to_localhost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IBKR_HOST", raising=False)
    assert SecretEnv().ibkr_host == "127.0.0.1"


def test_optional_ib_client_id_defaults_to_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("IB_CLIENT_ID", raising=False)
    assert SecretEnv().ib_client_id == 1


def test_malformed_tws_port_raises_missing_secret(
    env: SecretEnv, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TWS_PORT", "not-a-number")
    with pytest.raises(MissingSecretError) as exc_info:
        _ = env.tws_port
    assert "integer" in str(exc_info.value)


def test_malformed_ib_client_id_raises_missing_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("IB_CLIENT_ID", "abc")
    with pytest.raises(MissingSecretError):
        _ = SecretEnv().ib_client_id
