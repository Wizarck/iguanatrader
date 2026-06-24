/**
 * `@iguanatrader/shared-types` — shared TypeScript types between iguanatrader apps.
 *
 * Placeholder package. The pnpm workspace (`pnpm-workspace.yaml`), the lockfile
 * and `apps/web` (`"@iguanatrader/shared-types": "workspace:*"`) all reference
 * this package, and `apps/web/Dockerfile` copies it during the build — but the
 * package files themselves were never committed, which broke `docker build web`
 * at `COPY packages/shared-types/package.json` ("not found").
 *
 * Domain types currently live in `apps/web/src/lib/*/types.ts`. As they are
 * promoted to a single shared source of truth (e.g. generated from the API
 * OpenAPI schema), they re-export from here. Nothing imports this module yet,
 * so the empty export keeps it a valid, dependency-free workspace package.
 */
export {};
