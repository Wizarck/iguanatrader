"""Registry contract test — exactly 17 canonical commands with valid metadata.

Per spec ``approval`` Requirement 7 + slice P1 task 6.5.
"""

from __future__ import annotations

from iguanatrader.contexts.approval.channels.commands import (
    CANONICAL_COMMAND_NAMES,
    COMMANDS,
    assert_canonical,
)


def test_registry_has_exactly_seventeen_commands() -> None:
    assert len(COMMANDS) == 17


def test_registry_names_match_canonical_set() -> None:
    assert frozenset(COMMANDS.keys()) == CANONICAL_COMMAND_NAMES


def test_assert_canonical_passes() -> None:
    assert_canonical()


def test_admin_role_assignment() -> None:
    """Per design D2 table: 6 admin commands; 11 user commands."""
    admin_commands = {
        name for name, spec in COMMANDS.items() if spec.required_role == "admin"
    }
    user_commands = {
        name for name, spec in COMMANDS.items() if spec.required_role == "user"
    }
    assert admin_commands == {
        "/halt",
        "/resume",
        "/override",
        "/budget",
        "/lock",
        "/unlock",
    }
    assert len(user_commands) == 11


def test_idempotency_key_source_assignment() -> None:
    """Per design D2: /approve, /reject keyed by request_id; admin
    commands keyed by payload; read-only by 'none'.
    """
    request_id_commands = {
        name
        for name, spec in COMMANDS.items()
        if spec.idempotency_key_source == "request_id"
    }
    payload_commands = {
        name
        for name, spec in COMMANDS.items()
        if spec.idempotency_key_source == "payload"
    }
    none_commands = {
        name
        for name, spec in COMMANDS.items()
        if spec.idempotency_key_source == "none"
    }
    assert request_id_commands == {"/approve", "/reject"}
    assert "/halt" in payload_commands
    assert "/resume" in payload_commands
    assert "/lock" in payload_commands
    assert "/unlock" in payload_commands
    assert "/help" in none_commands
    assert "/status" in none_commands


def test_every_handler_is_callable() -> None:
    for spec in COMMANDS.values():
        assert callable(spec.handler), f"{spec.name} handler is not callable"


def test_every_description_is_non_empty() -> None:
    for spec in COMMANDS.values():
        assert spec.description_md.strip(), f"{spec.name} has empty description"
