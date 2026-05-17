# syntax=docker/dockerfile:1.6
# Multi-stage Dockerfile for the openbb-sidecar.
# Per ADR-015 + R4 design D1: AGPL-3.0 isolation via separate container.
# The LICENSE file is preserved inside the runtime image as required by AGPL §13.

ARG PYTHON_VERSION=3.11

#
# Builder stage: resolve dependencies in an isolated venv.
#
FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    POETRY_VERSION=1.8.4 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_IN_PROJECT=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==${POETRY_VERSION}"

WORKDIR /build

COPY pyproject.toml poetry.lock* ./

RUN poetry install --only main --no-root --no-ansi

COPY src/ ./src/
COPY README.md LICENSE ./

RUN poetry install --only main --no-ansi

#
# Runtime stage: copy venv + source + LICENSE, drop build tooling.
#
FROM python:${PYTHON_VERSION}-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PATH="/app/.venv/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 sidecar

WORKDIR /app

# Copy the virtualenv with all resolved dependencies.
COPY --from=builder --chown=sidecar:sidecar /build/.venv /app/.venv
# Copy the sidecar source.
COPY --from=builder --chown=sidecar:sidecar /build/src /app/src
# Preserve LICENSE inside the image (AGPL §13 obligation).
COPY --from=builder --chown=sidecar:sidecar /build/LICENSE /app/LICENSE
COPY --from=builder --chown=sidecar:sidecar /build/README.md /app/README.md

ENV PYTHONPATH=/app/src

USER sidecar

EXPOSE 8765

HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=12 \
    CMD curl -fsS http://localhost:8765/health || exit 1

# Use `python -m uvicorn` instead of the `uvicorn` shell wrapper. The
# wrapper script in /app/.venv/bin/ has a shebang pointing at the
# builder stage's venv path (/build/.venv/bin/python) which doesn't
# exist in the runtime image — same gotcha as the api Dockerfile's
# alembic wrapper. python -m bypasses the shebang and uses the venv's
# python directly via PYTHONPATH.
CMD ["python", "-m", "uvicorn", "openbb_sidecar.main:app", "--host", "0.0.0.0", "--port", "8765"]
