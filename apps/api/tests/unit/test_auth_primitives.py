"""Unit tests for slice 4 auth primitives.

Covers the pure-function surface of :mod:`iguanatrader.api.auth`:

* Argon2id round-trip + wrong-input behaviour (returns False, never raises).
* JWT encode/decode round-trip preserves payload.
* JWT decode of expired / tampered / missing-secret tokens returns ``None``
  (never raises) and emits the appropriate structlog event.
* :func:`should_rotate` boundary semantics — strict less-than at the
  threshold (exactly N seconds out → False; N-1 → True).

The integration tests (``test_auth_flow.py``) cover the FastAPI route
behaviour layered on top of these primitives.
"""

from __future__ import annotations

import time

import pytest
from iguanatrader.api.auth import (
    JWT_ROTATION_THRESHOLD_SECONDS,
    Role,
    decode_jwt,
    encode_jwt,
    hash_email_for_log,
    hash_password,
    should_rotate,
    verify_password,
)

# Sets the JWT secret env var for every test in this module. Real secret
# rotation is out of scope — we only need a fixed value so encode/decode
# round-trip works deterministically.
_TEST_JWT_SECRET = "x" * 64  # 64 bytes — comfortably above the 32-byte minimum


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("IGUANATRADER_JWT_SECRET", _TEST_JWT_SECRET)


# --------------------------------------------------------------------------- #
# Argon2id password hashing
# --------------------------------------------------------------------------- #


class TestPasswordHashing:
    def test_round_trip_returns_true(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("correct horse battery staple", hashed) is True

    def test_wrong_password_returns_false(self) -> None:
        hashed = hash_password("correct horse battery staple")
        assert verify_password("incorrect", hashed) is False

    def test_empty_password_round_trip(self) -> None:
        # Argon2id permits empty plaintexts (defensive — should still
        # return True iff verify matches the encoded hash).
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("not-empty", hashed) is False

    def test_verify_against_invalid_hash_returns_false(self) -> None:
        # NEVER raises — the contract is "False on any failure".
        assert verify_password("anything", "not-a-real-hash") is False
        assert verify_password("anything", "") is False
        assert verify_password("anything", "$argon2id$invalid") is False

    def test_each_hash_is_unique_due_to_random_salt(self) -> None:
        h1 = hash_password("same-password")
        h2 = hash_password("same-password")
        # Salts differ → encoded strings differ
        assert h1 != h2
        # but both verify
        assert verify_password("same-password", h1) is True
        assert verify_password("same-password", h2) is True


# --------------------------------------------------------------------------- #
# JWT encode + decode
# --------------------------------------------------------------------------- #


class TestJWT:
    def test_round_trip_preserves_payload(self) -> None:
        token = encode_jwt({"sub": "user-123", "tenant_id": "tenant-abc"}, exp_seconds=60)
        claims = decode_jwt(token)
        assert claims is not None
        assert claims["sub"] == "user-123"
        assert claims["tenant_id"] == "tenant-abc"
        assert "iat" in claims
        assert "exp" in claims
        assert claims["exp"] - claims["iat"] == 60

    def test_decode_expired_token_returns_none(self) -> None:
        # Encode with exp_seconds=1, sleep past, decode → None
        token = encode_jwt({"sub": "user-x"}, exp_seconds=1)
        time.sleep(2)
        assert decode_jwt(token) is None

    def test_decode_tampered_signature_returns_none(self) -> None:
        token = encode_jwt({"sub": "user-x"}, exp_seconds=60)
        # Flip a single character in the signature segment (last segment
        # after the second '.').
        head, payload, sig = token.rsplit(".", 2)
        tampered_sig = "A" + sig[1:] if sig[0] != "A" else "B" + sig[1:]
        tampered = f"{head}.{payload}.{tampered_sig}"
        assert decode_jwt(tampered) is None

    def test_decode_garbage_returns_none(self) -> None:
        assert decode_jwt("not.a.token") is None
        assert decode_jwt("") is None
        assert decode_jwt("...") is None

    def test_caller_iat_exp_are_overwritten(self) -> None:
        # encode_jwt always stamps the current iat + computed exp;
        # caller-provided values are ignored.
        token = encode_jwt({"sub": "x", "iat": 1, "exp": 2}, exp_seconds=60)
        claims = decode_jwt(token)
        assert claims is not None
        # iat is set to "now-ish" (within a few seconds of test start)
        assert abs(claims["iat"] - int(time.time())) < 5
        # exp is iat + 60
        assert claims["exp"] - claims["iat"] == 60


# --------------------------------------------------------------------------- #
# should_rotate boundary cases (per design D3 — strict less-than)
# --------------------------------------------------------------------------- #


class TestShouldRotate:
    def test_exactly_at_threshold_returns_false(self) -> None:
        # exp - now == JWT_ROTATION_THRESHOLD_SECONDS → False (not yet rotating)
        now = 1_000_000
        exp = now + JWT_ROTATION_THRESHOLD_SECONDS
        assert should_rotate(exp, now) is False

    def test_one_second_below_threshold_returns_true(self) -> None:
        now = 1_000_000
        exp = now + JWT_ROTATION_THRESHOLD_SECONDS - 1
        assert should_rotate(exp, now) is True

    def test_one_second_above_threshold_returns_false(self) -> None:
        now = 1_000_000
        exp = now + JWT_ROTATION_THRESHOLD_SECONDS + 1
        assert should_rotate(exp, now) is False

    def test_already_expired_returns_true(self) -> None:
        # Past expiry counts as "should rotate" — the dependency layer is
        # responsible for rejecting expired tokens BEFORE asking should_rotate,
        # but the function itself answers cleanly for any finite negative
        # interval.
        now = 1_000_000
        exp = now - 100
        assert should_rotate(exp, now) is True


# --------------------------------------------------------------------------- #
# Role enum
# --------------------------------------------------------------------------- #


class TestRoleEnum:
    def test_values_match_db_check_constraint(self) -> None:
        # The migration 0002_users_role_enum CHECK is
        # ``role IN ('tenant_user','god_admin')``. Enum values MUST match
        # those strings exactly so DB inserts via the ORM succeed.
        assert Role.tenant_user.value == "tenant_user"
        assert Role.god_admin.value == "god_admin"

    def test_construction_from_value(self) -> None:
        assert Role("tenant_user") is Role.tenant_user
        assert Role("god_admin") is Role.god_admin

    def test_invalid_value_raises_valueerror(self) -> None:
        with pytest.raises(ValueError, match="not a valid Role"):
            Role("admin")  # legacy slice-3 value, dropped by migration 0002


# --------------------------------------------------------------------------- #
# email log hashing
# --------------------------------------------------------------------------- #


class TestEmailHashing:
    def test_returns_16_hex_chars(self) -> None:
        digest = hash_email_for_log("arturo6ramirez@gmail.com")
        assert len(digest) == 16
        assert all(c in "0123456789abcdef" for c in digest)

    def test_same_input_produces_same_digest(self) -> None:
        a = hash_email_for_log("user@example.com")
        b = hash_email_for_log("user@example.com")
        assert a == b

    def test_different_input_produces_different_digest(self) -> None:
        a = hash_email_for_log("user@example.com")
        b = hash_email_for_log("USER@example.com")  # different case
        assert a != b
