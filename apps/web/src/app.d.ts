// See https://svelte.dev/docs/kit/types#app
// for information about these interfaces

declare global {
  namespace App {
    // interface Error {}
    interface Locals {
      /** Authenticated user, populated by `hooks.server.ts` for `(app)` routes. */
      user: {
        user_id: string;
        tenant_id: string;
        email: string;
        role: 'tenant_user' | 'god_admin';
        created_at: string;
        /**
         * Slice `auth-change-password`: when true, every `(app)` route except
         * `/account/change-password` and `/logout` redirects to
         * `/account/change-password?required=1` via `hooks.server.ts`.
         */
        must_change_password: boolean;
        /**
         * Slice `auth-password-aging-warning`: days since the user last
         * rotated their password. `null` when `password_changed_at IS NULL`
         * (legacy users grandfathered in by the backend classifier).
         */
        password_age_days?: number | null;
        /**
         * Slice `auth-password-aging-warning`: classifier output the
         * `(app)/+layout.svelte` shell consults to decide whether to
         * mount `PasswordAgeingBanner`. Defaults to `'fresh'` on the
         * backend so older API consumers (and unmigrated rows) never
         * trip the banner.
         */
        password_aging_state?: 'fresh' | 'ageing' | 'stale';
      } | null;
    }
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
