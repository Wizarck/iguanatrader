"""Env-aware structlog configuration (per design D6 + NFR-O3).

Replaces the slice-5 placeholder
:func:`iguanatrader.api.app._configure_structlog` (which configured
JSON-to-stdout only). The slice-O1 :func:`configure_logging` is the
authoritative entry point; ``app.py::_configure_structlog`` becomes a
one-liner delegate (per design D6).

Behaviour by environment:

- ``IGUANATRADER_ENV=test`` (default in tests) → JSON to stdout only;
  no file handler. Matches the slice-5 baseline so existing tests
  don't observe behaviour drift.
- ``IGUANATRADER_ENV=dev`` → JSON to stdout (no pretty-printer in MVP;
  the dev-tty branch was descoped to keep the diff small).
- ``IGUANATRADER_ENV=paper`` / ``live`` → JSON to stdout +
  :class:`logging.handlers.RotatingFileHandler` writing to
  ``logs/iguanatrader-{env}.log`` with ``maxBytes = 100*1024*1024``
  (100 MB per NFR-O3) and ``backupCount = 7``.

Risk mitigation: the file handler is wrapped in try/except; any
:class:`OSError` during handler init (Windows file-locking, missing
``logs/`` perms, etc.) emits a stderr breadcrumb + falls back to
stdout-only. This matches the design-D6 risks section ("Windows
RotatingFileHandler may fail mid-rotation").
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path

import structlog

#: Env-var name resolved by :func:`get_env`. Default ``test`` so importing
#: this module from an unconfigured shell does not silently land a real
#: file handler in CWD.
ENV_VAR: str = "IGUANATRADER_ENV"

#: Recognised environment names. Anything else falls back to ``test``.
_KNOWN_ENVS: set[str] = {"test", "dev", "paper", "live"}

#: NFR-O3 rotation limits — 100 MB per file, 7 backups (~7 days at
#: typical log volume; precise retention depends on volume, documented
#: as "100 MB rotation, retain 7 backups").
LOG_FILE_MAX_BYTES: int = 100 * 1024 * 1024
LOG_FILE_BACKUP_COUNT: int = 7


def get_env() -> str:
    """Resolve the current env from :data:`ENV_VAR`; ``test`` if unknown."""
    raw = os.getenv(ENV_VAR, "test").strip().lower()
    return raw if raw in _KNOWN_ENVS else "test"


def _structlog_processors() -> list[structlog.types.Processor]:
    """Project-canonical processor chain (matches slice-5 baseline)."""
    return [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]


def _maybe_attach_file_handler(env: str) -> None:
    """Attach a :class:`RotatingFileHandler` for paper / live envs.

    Best-effort: any :class:`OSError` during handler init writes a
    breadcrumb to stderr + leaves stdout-only logging intact.
    """
    if env not in {"paper", "live"}:
        return

    log_dir = Path("logs")
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            filename=str(log_dir / f"iguanatrader-{env}.log"),
            maxBytes=LOG_FILE_MAX_BYTES,
            backupCount=LOG_FILE_BACKUP_COUNT,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logging.getLogger().addHandler(handler)
    except OSError as exc:  # pragma: no cover — Windows-only path
        sys.stderr.write(
            f"[observability.structlog_config] RotatingFileHandler init failed for "
            f"env={env!r}: {exc!r}; logs will write stdout-only this session.\n"
        )


def configure_logging(env: str | None = None) -> None:
    """Configure stdlib logging + structlog for ``env``.

    Idempotent — calling twice replaces the existing config (structlog
    + stdlib :func:`logging.basicConfig` both treat re-config calls
    consistently).
    """
    resolved = (env or get_env()).strip().lower()
    if resolved not in _KNOWN_ENVS:
        resolved = "test"

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.INFO,
        force=True,
    )

    _maybe_attach_file_handler(resolved)

    structlog.configure(
        processors=_structlog_processors(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.INFO),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


__all__ = [
    "ENV_VAR",
    "LOG_FILE_BACKUP_COUNT",
    "LOG_FILE_MAX_BYTES",
    "configure_logging",
    "get_env",
]
