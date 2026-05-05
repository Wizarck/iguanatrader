"""HTTP API package — slice 4 (auth-jwt-cookie) onward.

This package owns the FastAPI surface: app factory, routes, DTOs, and
auth primitives. Slice 4 plants the foundation (auth + minimal app
factory + slowapi limiter); slice 5 (``api-foundation-rfc7807``) layers
RFC 7807 exception handlers, dynamic-discovery via ``pkgutil``, and the
OpenAPI typegen pipeline on top.

This module exposes Argon2id parameter constants used by
:mod:`iguanatrader.api.auth`. Defaults follow OWASP 2024 minimum
recommendations + 2x memory headroom. Every parameter is overridable
via env var so operators can tune for constrained hosts (per design
decision D4 in the slice 4 ``design.md``).

Tuning guidance (per ``docs/gotchas.md`` #24): increasing
``ARGON2_MEMORY_KIB`` is forward-compatible — Argon2id encodes parameters
into the hash itself, so previously stored hashes verify regardless of
the live env. Decreasing parameters is also safe but reduces security
margin against future hardware.
"""

from __future__ import annotations

import os

ARGON2_TIME_COST: int = int(os.getenv("IGUANATRADER_ARGON2_TIME_COST", "3"))
"""Number of Argon2id iterations. Default 3 (OWASP 2024 minimum)."""

ARGON2_MEMORY_KIB: int = int(os.getenv("IGUANATRADER_ARGON2_MEMORY_KIB", "65536"))
"""Memory cost in KiB. Default 65536 = 64 MiB. Single-host MVP absorbs
~80 ms per verify on Arturo's hardware (see design.md D4)."""

ARGON2_PARALLELISM: int = int(os.getenv("IGUANATRADER_ARGON2_PARALLELISM", "4"))
"""Number of parallel lanes. Default 4."""

ARGON2_HASH_LEN: int = int(os.getenv("IGUANATRADER_ARGON2_HASH_LEN", "32"))
"""Output hash length in bytes. Default 32 (256-bit)."""

ARGON2_SALT_LEN: int = int(os.getenv("IGUANATRADER_ARGON2_SALT_LEN", "16"))
"""Salt length in bytes. Default 16 (128-bit)."""


__all__ = [
    "ARGON2_HASH_LEN",
    "ARGON2_MEMORY_KIB",
    "ARGON2_PARALLELISM",
    "ARGON2_SALT_LEN",
    "ARGON2_TIME_COST",
]
