/**
 * Navigation store — slice W1.
 *
 * Holds Sidebar collapse state + active href cache. The collapsed flag
 * is persisted to `localStorage['iguanatrader:nav:collapsed']` so the
 * choice survives reloads.
 *
 * Per design D4: Svelte 5 runes singleton. SSR-safe — `localStorage`
 * access is gated on `typeof window !== 'undefined'`.
 */

const STORAGE_KEY = 'iguanatrader:nav:collapsed';

class NavStore {
  collapsed = $state(false);
  activeHref = $state<string>('/');

  /**
   * Mobile drawer open state. Deliberately NOT persisted (a drawer should
   * always start closed on load) and orthogonal to `collapsed` (which is the
   * desktop icon-rail toggle). Only consumed under the mobile breakpoint.
   */
  mobileOpen = $state(false);

  constructor() {
    // Hydrate from localStorage on browser-only mount.
    if (typeof window !== 'undefined') {
      try {
        const raw = window.localStorage.getItem(STORAGE_KEY);
        if (raw === 'true') this.collapsed = true;
      } catch {
        // localStorage may be unavailable (privacy mode); silently
        // default to collapsed=false.
      }

      // Persist on change. `$effect.root` so the effect outlives any
      // single component mount.
      $effect.root(() => {
        $effect(() => {
          try {
            window.localStorage.setItem(STORAGE_KEY, String(this.collapsed));
          } catch {
            // Ignore quota / disabled storage.
          }
        });
      });
    }
  }
}

/** Singleton instance — import this everywhere. */
export const navStore = new NavStore();
