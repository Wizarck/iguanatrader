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
      } | null;
    }
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
