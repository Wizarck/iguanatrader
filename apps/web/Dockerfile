# syntax=docker/dockerfile:1.7
# Multi-stage build for the iguanatrader SvelteKit frontend.
#
# - Stage `builder`: installs pnpm deps + runs `pnpm build` against
#   adapter-node, producing a self-contained `build/` directory.
# - Stage `runtime`: slim Node image that runs `node build/index.js`.
#
# Build context: the repo root (the workspace has a pnpm-lock.yaml at
# the root and `packages/shared-types` is a workspace dep).

ARG NODE_VERSION=20

# ---------------------------------------------------------------------------
# Stage 1 — builder: install pnpm deps + run vite build.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS builder

ENV PNPM_HOME=/pnpm \
    PATH="/pnpm:${PATH}" \
    COREPACK_ENABLE_DOWNLOAD_PROMPT=0

RUN corepack enable && corepack prepare pnpm@10 --activate

WORKDIR /build

# Copy the workspace manifests first for cache friendliness.
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY apps/web/package.json apps/web/
COPY packages/shared-types/package.json packages/shared-types/

RUN pnpm install --frozen-lockfile

# Now copy the rest of the workspace + build the web app.
COPY packages/shared-types ./packages/shared-types
COPY apps/web ./apps/web

# SvelteKit's `svelte-kit sync` step (run as part of `pnpm build`) needs
# the .svelte-kit directory writable.
RUN pnpm --filter @iguanatrader/web build


# ---------------------------------------------------------------------------
# Stage 2 — runtime: adapter-node output + minimal node deps.
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runtime

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=5173

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --create-home --shell /bin/bash app

WORKDIR /app

# Adapter-node output already bundles everything it needs except for
# devDeps not present in the bundle; copying node_modules of the web
# workspace is unnecessary because vite externalises adapter-node deps
# via its own bundle. The adapter-node entry is `build/index.js`.
COPY --from=builder --chown=app:app /build/apps/web/build ./build
COPY --from=builder --chown=app:app /build/apps/web/package.json ./package.json
COPY --from=builder --chown=app:app /build/node_modules ./node_modules

USER app
EXPOSE 5173

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -fsS http://localhost:5173/ || exit 1

CMD ["node", "build/index.js"]
