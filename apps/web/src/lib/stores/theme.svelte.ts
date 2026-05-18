/**
 * Theme store — slice W1 + slice U6 light-theme activation.
 *
 * Reads `prefers-color-scheme` (system) + `localStorage['iguanatrader:theme']`
 * (user choice; latter wins). Applies `data-theme` attribute to `<html>`
 * via a `$effect`.
 *
 * Light-variant CSS vars landed with slice U6, so the toggle now has a
 * real visual effect — the previous "MVP constraint deferred" caveat
 * is gone.
 */

const STORAGE_KEY = 'iguanatrader:theme';

type ThemeName = 'dark' | 'light';

class ThemeStore {
  current = $state<ThemeName>('dark');

  constructor() {
    if (typeof window !== 'undefined') {
      // Hydrate: stored value > system preference > default 'dark'.
      let initial: ThemeName = 'dark';
      try {
        const stored = window.localStorage.getItem(STORAGE_KEY);
        if (stored === 'dark' || stored === 'light') {
          initial = stored;
        } else if (
          window.matchMedia &&
          window.matchMedia('(prefers-color-scheme: light)').matches
        ) {
          initial = 'light';
        }
      } catch {
        // localStorage / matchMedia unavailable; keep 'dark'.
      }
      this.current = initial;

      // Apply + persist on change.
      $effect.root(() => {
        $effect(() => {
          try {
            window.localStorage.setItem(STORAGE_KEY, this.current);
          } catch {
            // Ignore quota / disabled storage.
          }
          document.documentElement.setAttribute('data-theme', this.current);
        });
      });
    }
  }
}

/** Singleton instance — import this everywhere. */
export const themeStore = new ThemeStore();
