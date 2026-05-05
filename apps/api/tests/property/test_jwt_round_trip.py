"""Property test: ``encode_jwt → decode_jwt`` preserves the payload.

For 100 randomly-generated ``(user_id, tenant_id, role)`` triples, an
encoded JWT decodes back to a payload whose ``sub``, ``tenant_id``, and
``role`` fields match the originals. ``iat`` and ``exp`` are stamped by
:func:`encode_jwt` (the caller's values, if any, are overwritten — see
:mod:`iguanatrader.api.auth` docstring), so we only assert their
relative shape.
"""

from __future__ import annotations

import os

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from iguanatrader.api.auth import (
    JWT_DEFAULT_EXP_SECONDS,
    Role,
    decode_jwt,
    encode_jwt,
)

# Hypothesis runs encode/decode 100 times per case; module-level setenv
# avoids fixture overhead inside the inner loop.
os.environ.setdefault("IGUANATRADER_JWT_SECRET", "x" * 64)


@pytest.mark.property
@given(
    user_id=st.uuids().map(str),
    tenant_id=st.uuids().map(str),
    role=st.sampled_from(list(Role)),
)
@settings(max_examples=100, deadline=None)
def test_jwt_encode_decode_preserves_payload(user_id: str, tenant_id: str, role: Role) -> None:
    payload = {
        "sub": user_id,
        "tenant_id": tenant_id,
        "role": role.value,
        "login_at": 1_700_000_000,
    }
    token = encode_jwt(payload, exp_seconds=JWT_DEFAULT_EXP_SECONDS)
    claims = decode_jwt(token)
    assert claims is not None

    # Caller-supplied keys round-trip identically.
    assert claims["sub"] == user_id
    assert claims["tenant_id"] == tenant_id
    assert claims["role"] == role.value
    assert claims["login_at"] == 1_700_000_000

    # Stamped keys carry the expected relative shape.
    assert claims["exp"] - claims["iat"] == JWT_DEFAULT_EXP_SECONDS
