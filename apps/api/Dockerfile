# syntax=docker/dockerfile:1.7
# Multi-stage build for the iguanatrader FastAPI monolith.
#
# - Stage `builder`: installs the workspace's Python deps (root pyproject)
#   into a self-contained venv with Poetry. Source code is NOT copied at
#   this stage so Docker can cache the deps layer across iterations.
# - Stage `runtime`: slim Python image with just the venv + source; runs
#   uvicorn on :8000 by default.
#
# Build context: the repo root (NOT apps/api/). The compose / CI invocation
# must pass `context: .` and `dockerfile: apps/api/Dockerfile`.

ARG PYTHON_VERSION=3.11

# ---------------------------------------------------------------------------
# Stage 1 — builder: Poetry + venv with all runtime deps.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=2.0.1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1 \
    PATH="/opt/venv/bin:${PATH}"

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /build

# Copy only the dep manifests first to maximise Docker layer caching.
COPY pyproject.toml poetry.lock README.md ./

# Install runtime deps into a project-local .venv. Skip dev deps.
RUN poetry install --no-root --without dev


# ---------------------------------------------------------------------------
# Stage 2 — runtime: slim image with venv + source.
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:${PATH}" \
    PYTHONPATH="/app/apps/api/src" \
    IGUANATRADER_API_HOST=0.0.0.0 \
    IGUANATRADER_API_PORT=8000

# curl: used by the compose healthcheck. libpq + sqlite3 client kept
# minimal — runtime drivers (asyncpg, aiosqlite) come from the venv.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash app

WORKDIR /app
COPY --from=builder --chown=app:app /build/.venv /opt/venv
COPY --chown=app:app apps/api ./apps/api
COPY --chown=app:app pyproject.toml poetry.lock README.md ./

# Root pyproject is `package-mode = false`, so Poetry does NOT install
# the project nor its `[tool.poetry.scripts]` entries. Install a thin
# shell wrapper that mirrors the documented `iguanatrader <subcommand>`
# operator UX.
RUN echo '#!/bin/sh' > /usr/local/bin/iguanatrader && echo 'exec python -m iguanatrader.cli "$@"' >> /usr/local/bin/iguanatrader && chmod +x /usr/local/bin/iguanatrader

# Boot-time migration runner. ENTRYPOINT below execs this before
# whatever CMD/command the container was launched with, so app and
# one-shot admin invocations both see an up-to-date schema. Set
# IGUANA_SKIP_MIGRATIONS=1 to bypass.
COPY --chown=root:root apps/api/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Pre-create /data with app ownership. Docker copies these perms onto
# a fresh named volume the first time it mounts, so the app user can
# write the SQLite file without an out-of-band chown step.
RUN mkdir -p /data && chown app:app /data

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -fsS http://localhost:8000/healthz || exit 1

# ENTRYPOINT runs alembic upgrade head before exec'ing CMD. The
# compose file overrides `command:` for one-shot init containers
# (e.g. `bootstrap-tenant`); migrations still run first via the
# entrypoint, which is intentional — bootstrap needs a current schema.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["python", "-m", "iguanatrader.api"]

# ---------------------------------------------------------------------------
# Profile aliases — the compose files (dev/test/paper/live) name distinct
# build targets so the resulting image tag is auditable, but the build
# itself is identical to `runtime`; profile divergence is env-only at run
# time (IBKR port, IGUANATRADER_PROFILE, secrets file). See compose
# headers for the AGENTS.md §4 rationale.
# ---------------------------------------------------------------------------
FROM runtime AS dev
FROM runtime AS test
FROM runtime AS paper
FROM runtime AS live
