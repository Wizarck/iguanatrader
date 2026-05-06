/**
 * Auth store — slice W1.
 *
 * Singleton class with a `$state` rune holding the current user (or
 * `null` for unauthenticated). Hydrated from `(app)/+layout.server.ts`
 * `data.user` via a `$effect` in the layout's `<script>` block.
 *
 * Per design D4: stores are Svelte 5 runes (NOT `svelte/store`'s legacy
 * `writable`). The `.svelte.ts` extension is required for runes outside
 * `.svelte` files.
 */

class AuthStore {
  user = $state<App.Locals['user'] | null>(null);
}

/** Singleton instance — import this everywhere. */
export const authStore = new AuthStore();
