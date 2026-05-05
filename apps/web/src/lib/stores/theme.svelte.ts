/**
 * Theme store — slice W1.
 *
 * Reads `prefers-color-scheme` (system) + `localStorage['iguanatrader:theme']`
 * (user choice; latter wins). Applies `data-theme` attribute to `<html>`
 * via a `$effect`.
 *
 * **MVP constraint** (per design D10 + gotcha entry): light-variant CSS
 * vars are NOT declared in `app.css`. This store may report `'light'`
 * based on stored preference, but the page renders dark until the light
 * vars land. The contract is preserved (attribute exists, system
 * preference is read) — only the user-facing visual difference is
 * deferred.
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
          // TODO(W1-followup): once light-variant CSS vars land,
          // remove the `'dark'` hard-coding here and let the attribute
          // reflect `this.current`. Today both stored values map to
          // dark CSS vars (see gotcha #34).
          document.documentElement.setAttribute('data-theme', this.current);
        });
      });
    }
  }
}

/** Singleton instance — import this everywhere. */
export const themeStore = new ThemeStore();
