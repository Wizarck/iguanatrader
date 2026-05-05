"""Auth primitives — Argon2id password hashing + JWT encode/decode + RBAC role.

Pure functions over module-level config. The HTTP route handlers in
:mod:`iguanatrader.api.routes.auth` and the FastAPI dependency
:func:`iguanatrader.api.deps.get_current_user` consume these primitives.

Design references:

* design D1 — HS256 with single rotating secret (``IGUANATRADER_JWT_SECRET``).
* design D3 — 24h JWT exp + 30-min auto-rotation threshold; cookie ceiling
  is enforced separately (in routes/deps using the ``login_at`` claim).
* design D4 — Argon2id parameters from :mod:`iguanatrader.api` constants;
  encoded into the hash so verify is forward-compatible across param bumps.
* design D10 — :class:`Role` enum gating ``/api/v1/*`` mutating endpoints.

Hard rules (per AGENTS.md §4):

* All structlog event names: ``auth.<entity>.<action>`` (context fixed to ``auth``).
* Email never logged in plaintext — :func:`hash_email_for_log` produces a
  truncated SHA-256 digest for safe attribution in logs.
"""

from __future__ import annotations

import enum
import hashlib
import os
import time
from typing import Any

import jwt
import structlog
from argon2 import PasswordHasher
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from iguanatrader.api import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_KIB,
    ARGON2_PARALLELISM,
    ARGON2_SALT_LEN,
    ARGON2_TIME_COST,
)

log = structlog.get_logger("iguanatrader.api.auth")

JWT_ALGORITHM: str = "HS256"
"""Symmetric signing algorithm (per design D1)."""

JWT_DEFAULT_EXP_SECONDS: int = 24 * 60 * 60
"""Default JWT lifetime — 24 hours (per design D3)."""

JWT_ROTATION_THRESHOLD_SECONDS: int = 30 * 60
"""Auto-rotate when expiry is within this window (per design D3 — 30 min)."""

COOKIE_CEILING_SECONDS: int = 7 * 24 * 60 * 60
"""Hard ceiling: 7 days from initial login. NOT extended by rotation."""

_JWT_SECRET_ENV: str = "IGUANATRADER_JWT_SECRET"
_JWT_SECRET_MIN_BYTES: int = 32

_password_hasher: PasswordHasher = PasswordHasher(
    time_cost=ARGON2_TIME_COST,
    memory_cost=ARGON2_MEMORY_KIB,
    parallelism=ARGON2_PARALLELISM,
    hash_len=ARGON2_HASH_LEN,
    salt_len=ARGON2_SALT_LEN,
)


class Role(enum.StrEnum):
    """RBAC role.

    Per ``docs/personas-jtbd.md`` §RBAC Matrix (refined 2026-05-05),
    iguanatrader uses a 2-level model:

    * :attr:`tenant_user` — single seat per tenant; full operational
      autonomy within that tenant.
    * :attr:`god_admin` — platform-level cross-tenant; impersonation
      tool for support / debugging. NOT exposed via the SvelteKit
      dashboard. In MVP, no User row carries ``role = god_admin``;
      god-admin auth is via separate (CLI / env-based) path. The role
      exists in this enum so :func:`requires_role` can gate future
      platform routes.
    """

    tenant_user = "tenant_user"
    god_admin = "god_admin"


def _get_jwt_secret() -> str:
    """Read the JWT secret from env. Raise on absent or too-short."""
    secret = os.getenv(_JWT_SECRET_ENV)
    if not secret:
        raise RuntimeError(
            f"{_JWT_SECRET_ENV} env var is not set. "
            "Generate a 32-byte hex secret and set it before booting."
        )
    if len(secret.encode("utf-8")) < _JWT_SECRET_MIN_BYTES:
        raise RuntimeError(f"{_JWT_SECRET_ENV} must be at least {_JWT_SECRET_MIN_BYTES} bytes.")
    return secret


def hash_password(plain: str) -> str:
    """Hash a plaintext password using Argon2id (returns the encoded string)."""
    return _password_hasher.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff ``plain`` verifies against ``hashed``.

    NEVER raises — all argon2-cffi exceptions become ``False``. This keeps
    call-sites clean and timing constant (callers can run a verify against
    a fixed dummy hash on the email-not-found branch without worrying
    about exception leakage).
    """
    try:
        return _password_hasher.verify(hashed, plain)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    except Exception:  # defensive — argon2 has odd unicode edges
        log.warning("auth.password.verify.unexpected_error", exc_info=True)
        return False


def encode_jwt(payload: dict[str, Any], exp_seconds: int = JWT_DEFAULT_EXP_SECONDS) -> str:
    """Encode ``payload`` as an HS256 JWT.

    Adds ``iat`` (issued at, unix seconds) and ``exp`` (= iat + ``exp_seconds``)
    claims to the payload. Caller-provided ``iat``/``exp`` values are overwritten.
    """
    now = int(time.time())
    claims: dict[str, Any] = {**payload, "iat": now, "exp": now + exp_seconds}
    return jwt.encode(claims, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_jwt(token: str) -> dict[str, Any] | None:
    """Decode + verify a JWT. Return claims dict on success, ``None`` on any failure.

    Emits a single structlog event per failure type so monitoring can
    distinguish brute-force probes (invalid signature) from natural expiry.
    Never raises.
    """
    try:
        return jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        log.info("auth.session.expired")
        return None
    except jwt.InvalidSignatureError:
        log.warning("auth.session.invalid_signature")
        return None
    except jwt.InvalidTokenError as exc:
        log.warning("auth.session.invalid_token", reason=str(exc))
        return None


def should_rotate(exp_unix: int, now_unix: int) -> bool:
    """Return True iff the JWT is within the rotation threshold of expiring.

    Boundary: at ``exp - now == JWT_ROTATION_THRESHOLD_SECONDS`` returns False
    (strict less-than). At ``exp - now == JWT_ROTATION_THRESHOLD_SECONDS - 1``
    returns True.
    """
    return (exp_unix - now_unix) < JWT_ROTATION_THRESHOLD_SECONDS


def hash_email_for_log(email: str) -> str:
    """Return a truncated SHA-256 hex digest of ``email`` for safe logging.

    Per AGENTS.md §4 hard rule: NEVER log raw PII (including email) in
    structlog events. The 16-hex-char digest gives enough collision
    resistance for incident attribution while not leaking the address.
    """
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:16]


__all__ = [
    "COOKIE_CEILING_SECONDS",
    "JWT_ALGORITHM",
    "JWT_DEFAULT_EXP_SECONDS",
    "JWT_ROTATION_THRESHOLD_SECONDS",
    "Role",
    "decode_jwt",
    "encode_jwt",
    "hash_email_for_log",
    "hash_password",
    "should_rotate",
    "verify_password",
]
