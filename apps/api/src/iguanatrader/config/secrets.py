"""Boot-time secret-env loader for production adapters (slice deployment-foundation).

The 6 production adapters introduced by deployment-foundation (Anthropic,
IbAsync, APScheduler, Tier2Playwright, weekly_review_pdf, Helm/Fleet)
read their authentication material from process env populated by
SOPS-decryption at deploy time. This module centralises the read +
typed access; raising :class:`MissingSecretError` is the only failure
mode and it surfaces as RFC 7807 status 500 via the global handler chain.

Pattern: properties are evaluated lazily on access so a partially
configured environment can still boot the surfaces that don't need
the missing secret. The composition root constructs ``SecretEnv()``
once and passes it explicitly into each adapter — adapters never read
``os.environ`` directly (anti-pattern §3 in design.md).
"""

from __future__ import annotations

import os
from typing import ClassVar

from iguanatrader.shared.errors import IguanaError


class MissingSecretError(IguanaError):
    """Raised when a secret env var required by a production adapter is unset."""

    type_uri: ClassVar[str] = "urn:iguanatrader:error:missing-secret"
    default_title: ClassVar[str] = "Missing Secret"
    default_status: ClassVar[int] = 500


def _required(name: str) -> str:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        raise MissingSecretError(
            detail=(
                f"Environment variable {name!r} is required by a production "
                f"adapter but is unset (or empty). Verify the deploy-time "
                f"SOPS-decryption populated this variable in the pod env."
            ),
        )
    return value


class SecretEnv:
    """Typed accessor over the SOPS-decrypted secret env populated at deploy.

    Constructed once at the FastAPI composition root (or CLI entrypoint);
    each property raises :class:`MissingSecretError` on first access if
    the underlying env var is unset. Lazy-evaluation lets unrelated
    surfaces boot even when one adapter's secret is missing.
    """

    @property
    def anthropic_api_key(self) -> str:
        """``ANTHROPIC_API_KEY`` — consumed by ``AnthropicLLMClient`` (R5)."""
        return _required("ANTHROPIC_API_KEY")

    @property
    def ibkr_username(self) -> str:
        """``IBKR_USERNAME`` — consumed by ``IbAsyncIBClient`` (T2)."""
        return _required("IBKR_USERNAME")

    @property
    def ibkr_password(self) -> str:
        """``IBKR_PASSWORD`` — consumed by ``IbAsyncIBClient`` (T2)."""
        return _required("IBKR_PASSWORD")

    @property
    def tws_port(self) -> int:
        """``TWS_PORT`` — IBKR API listen port.

        Choose based on the IBKR client the operator runs:

        * **TWS desktop** (full client, with UI): paper ``7497`` / live ``7496``.
        * **IB Gateway** (headless, used by the docker sidecar shipped
          in slice ``ibkr-gateway-sidecar``): paper ``4002`` / live ``4001``.

        ``compose/ibgateway.yml`` defaults to ``4002`` (paper
        Gateway); operators flip both ``TRADING_MODE`` + ``TWS_PORT``
        when cutting over to live.
        """
        raw = _required("TWS_PORT")
        try:
            return int(raw)
        except ValueError as exc:
            raise MissingSecretError(
                detail=f"TWS_PORT must be an integer, got {raw!r}",
            ) from exc

    @property
    def ibkr_host(self) -> str:
        """``IBKR_HOST`` — TWS gateway host. Defaults to ``127.0.0.1`` if unset."""
        return os.environ.get("IBKR_HOST", "127.0.0.1")

    @property
    def ib_client_id(self) -> int:
        """``IB_CLIENT_ID`` — TWS connection client_id. Defaults to ``1`` if unset."""
        raw = os.environ.get("IB_CLIENT_ID", "1")
        try:
            return int(raw)
        except ValueError as exc:
            raise MissingSecretError(
                detail=f"IB_CLIENT_ID must be an integer, got {raw!r}",
            ) from exc

    @property
    def database_path(self) -> str:
        """``DATABASE_PATH`` — sqlite file path for ``APSchedulerAdapter`` jobstore."""
        return _required("DATABASE_PATH")

    # ------------------------------------------------------------------
    # Langfuse observability — slice ``llm-observability-and-signals``
    # ------------------------------------------------------------------
    # All three properties are *optional*: returning ``None`` is the
    # documented signal that Langfuse export is disabled, and the
    # client wrapper falls back to a no-op. Observability is opt-in
    # so dev / test / first-boot environments are not blocked on a
    # missing SOPS-decrypt of these vars.

    @property
    def langfuse_public_key(self) -> str | None:
        """``LANGFUSE_PUBLIC_KEY`` — None disables Langfuse export."""
        value = os.environ.get("LANGFUSE_PUBLIC_KEY")
        return value if value and value.strip() else None

    @property
    def langfuse_secret_key(self) -> str | None:
        """``LANGFUSE_SECRET_KEY`` — None disables Langfuse export."""
        value = os.environ.get("LANGFUSE_SECRET_KEY")
        return value if value and value.strip() else None

    @property
    def langfuse_host(self) -> str:
        """``LANGFUSE_HOST`` — defaults to Langfuse Cloud EU."""
        return os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")


__all__ = ["MissingSecretError", "SecretEnv"]
