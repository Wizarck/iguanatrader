/**
 * Defensive local fallback for the RFC 7807 `Problem` shape.
 *
 * Slice 5 (`api-foundation-rfc7807`) ships the canonical Pydantic
 * `Problem` model on the backend; the typegen bot regenerates
 * `packages/shared-types/src/index.ts` (currently a placeholder
 * `export {};`) on the next backend push that touches DTOs. Until that
 * happens, importing
 * `import type { components } from '@iguanatrader/shared-types';`
 * resolves `components` as `unknown`, which would type-error in
 * `+error.svelte`.
 *
 * **This file is transient**: once the typegen bot lands real types,
 * this fallback becomes a structural alias for
 * `components['schemas']['Problem']` (TypeScript's structural type
 * system handles equivalence without explicit conditionals — both
 * shapes have the same fields).
 *
 * Mirrors slice 5 `apps/api/src/iguanatrader/api/problem.py` field-for-
 * field. Keep in sync if slice 5's schema changes; the typegen bot
 * eventually makes this file a no-op.
 *
 * See `docs/gotchas.md` entry #31.
 */

/** Single field-level validation error (slice 5 `ErrorDetail`). */
export interface ErrorDetail {
  /** Field path or pointer (e.g., `body.email`). */
  field?: string;
  /** Human-readable error message. */
  message: string;
  /** Machine-readable error code (e.g., `value_error.email`). */
  code?: string;
}

/**
 * RFC 7807 `application/problem+json` body shape.
 *
 * Mirror of slice 5 `Problem` Pydantic model. The `errors` array is
 * present on validation failures (e.g., 422 from a malformed login
 * payload); `correlation_id` is set by the FastAPI middleware on every
 * response so the user can copy it for support.
 */
export interface Problem {
  /** Type URI (e.g., `urn:iguanatrader:error:validation`). */
  type: string;
  /** Short human-readable summary. */
  title: string;
  /** HTTP status code. */
  status: number;
  /** Optional human-readable explanation. */
  detail?: string;
  /** Optional URI reference for the specific occurrence. */
  instance?: string;
  /** Optional per-field validation errors. */
  errors?: ErrorDetail[];
  /** Optional request correlation ID (set by middleware on every error). */
  correlation_id?: string;
}
