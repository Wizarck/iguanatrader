/**
 * Server-side configuration loaded from `process.env`.
 *
 * Slice 4 ships these as plain `process.env` reads. Slice W1 may
 * migrate to SvelteKit's `$env/static/private` once the build pipeline
 * is wired (currently the `.svelte-kit` sync step that generates the
 * env modules requires a successful first build, which depends on
 * deps being installed via `pnpm install --frozen-lockfile`).
 */

/**
 * Base URL of the FastAPI backend. The SvelteKit form action and
 * `hooks.server.ts` proxy to this. Default points at the local dev
 * uvicorn (per `apps/api/src/iguanatrader/api/__main__.py`).
 */
export const API_BASE_URL: string =
  process.env.IGUANATRADER_API_BASE_URL ?? 'http://127.0.0.1:8000';

/** Session cookie name — MUST match `apps/api/src/iguanatrader/api/deps.py::COOKIE_NAME`. */
export const COOKIE_NAME = 'iguana_session';
