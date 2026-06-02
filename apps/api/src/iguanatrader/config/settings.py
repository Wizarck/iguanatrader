"""Boot-time configuration validators (slice-O1 carry-forward D9 item b).

Per design D9: the dev-only ``IGUANATRADER_DEV_INSECURE_COOKIE=1``
override (which drops the ``Secure`` flag from the session cookie —
gotcha #25) MUST NOT be active in production. The retro for slice 5
flagged the absence of a boot-time guard as a security gap. This
module plants the guard; the FastAPI app factory + the CLI both call
:func:`enforce_dev_insecure_cookie_prod_guard` early in their boot
sequences (current slice wires it into
:func:`iguanatrader.api.deps.is_secure_cookie` — the function is
called on every cookie write so the guard is enforced lazily on the
first request after boot).
"""

from __future__ import annotations

import os
from typing import ClassVar

from iguanatrader.shared.errors import IguanaError

#: Env-var that, when set to ``"1"``, drops the cookie ``Secure`` flag
#: (gotcha #25). Forbidden in production by this guard.
DEV_INSECURE_COOKIE_ENV: str = "IGUANATRADER_DEV_INSECURE_COOKIE"

#: Env-var declaring the operational environment.
ENV_VAR: str = "IGUANATRADER_ENV"


class ConfigError(IguanaError):
    """Raised when a boot-time configuration check fails (HTTP 500).

    These errors are unrecoverable startup conditions: the operator
    must set the env vars correctly before the app accepts traffic.
    Surfaced as RFC 7807 status 500 by the global handler chain.
    """

    type_uri: ClassVar[str] = "urn:iguanatrader:error:config"
    default_title: ClassVar[str] = "Configuration Error"
    default_status: ClassVar[int] = 500


#: Environments that serve real network traffic and therefore must carry
#: production-grade cookie security. ``paper`` is included: it is a
#: deployed, network-reachable environment (real IBKR paper account) — only
#: ``dev``/``test`` are exempt. Centralised so the set never drifts
#: between the cookie guard and other production-gated call sites.
_PRODUCTION_LIKE_ENVS: frozenset[str] = frozenset({"paper", "live", "production"})


def is_production_like(env: str | None) -> bool:
    """True for deployed environments (``paper``/``live``/``production``)."""
    return (env or "").strip().lower() in _PRODUCTION_LIKE_ENVS


def enforce_dev_insecure_cookie_prod_guard() -> None:
    """Refuse to boot when ``IGUANATRADER_DEV_INSECURE_COOKIE=1`` in a
    production-like env.

    Reads :data:`DEV_INSECURE_COOKIE_ENV` and :data:`ENV_VAR` from the
    process environment; raises :class:`ConfigError` when both
    conditions hold. Idempotent — call from FastAPI lifespan, CLI
    entrypoint, and the cookie-issuing path so any boot vector
    catches the misconfiguration.

    #10: previously this only fired for ``IGUANATRADER_ENV=production``,
    so ``paper`` and ``live`` deployments silently shipped insecure
    cookies. It now fires for every production-like env.
    """
    dev_insecure = os.getenv(DEV_INSECURE_COOKIE_ENV) == "1"
    env = os.getenv(ENV_VAR)
    if dev_insecure and is_production_like(env):
        raise ConfigError(
            detail=(
                f"{DEV_INSECURE_COOKIE_ENV}=1 is forbidden in a "
                f"production-like environment (IGUANATRADER_ENV={env!r}; "
                f"production-like = {sorted(_PRODUCTION_LIKE_ENVS)}). The "
                "dev-only flag drops the cookie Secure attribute (gotcha "
                "#25); shipping it exposes session cookies to MITM on plain "
                "HTTP. Unset the variable or run with IGUANATRADER_ENV=dev/test."
            ),
        )


__all__ = [
    "DEV_INSECURE_COOKIE_ENV",
    "ENV_VAR",
    "ConfigError",
    "enforce_dev_insecure_cookie_prod_guard",
    "is_production_like",
]
