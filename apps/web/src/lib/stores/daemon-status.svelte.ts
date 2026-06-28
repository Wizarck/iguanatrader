/**
 * Daemon-status store — slice ``dual-daemon-mode-toggle-and-reconcile``.
 *
 * Polls `GET /api/v1/status` every 5s while the document is visible;
 * pauses on `visibilitychange` (hidden tab) and immediately refreshes
 * on resume. Exposes the latest `StatusResponse` + error state via
 * Svelte 5 `$state`.
 *
 * Per slice design D7: 5s cadence is the sweet spot between operator
 * perception (chip feels live) and server churn (~720 req/op/hour at
 * worst).
 *
 * Lifecycle: the (app) layout calls `start()` on mount and `stop()` on
 * unmount; HMR + route navigation transitions cycle through both.
 */

import { isProblem } from '$lib/composables/useFetch';
import { fetchStatus } from '$lib/status/client';
import type { StatusResponse } from '$lib/status/types';
import type { Problem } from '$lib/types/problem';

const POLL_INTERVAL_MS = 5_000;

class DaemonStatusStore {
  status = $state<StatusResponse | null>(null);
  error = $state<Problem | string | null>(null);
  /**
   * `true` once the first fetch has settled (success OR failure). Lets the
   * chips tell "still loading" (`status` null, never fetched → "…") apart from
   * "fetched but unreachable" (`status` null AND loaded → terminal "N/D"),
   * instead of spinning "…" forever when `/api/v1/status` fails.
   */
  loaded = $state(false);

  #intervalId: ReturnType<typeof setInterval> | null = null;
  #visibilityHandler: (() => void) | null = null;

  /** Begin polling. Idempotent — a second call is a no-op. */
  start(): void {
    if (this.#intervalId !== null) return;
    if (typeof document === 'undefined') return; // SSR guard

    void this.#refresh();
    this.#intervalId = setInterval(() => {
      if (document.visibilityState === 'visible') {
        void this.#refresh();
      }
    }, POLL_INTERVAL_MS);

    this.#visibilityHandler = () => {
      if (document.visibilityState === 'visible') {
        void this.#refresh();
      }
    };
    document.addEventListener('visibilitychange', this.#visibilityHandler);
  }

  /** Stop polling + remove listeners. Idempotent. */
  stop(): void {
    if (this.#intervalId !== null) {
      clearInterval(this.#intervalId);
      this.#intervalId = null;
    }
    if (this.#visibilityHandler !== null && typeof document !== 'undefined') {
      document.removeEventListener('visibilitychange', this.#visibilityHandler);
      this.#visibilityHandler = null;
    }
  }

  /** Force a one-off refresh (e.g. immediately after a toggle/reconcile). */
  async refresh(): Promise<void> {
    await this.#refresh();
  }

  async #refresh(): Promise<void> {
    try {
      const result = await fetchStatus();
      if (isProblem(result)) {
        this.error = result;
        return;
      }
      this.status = result;
      this.error = null;
    } catch (exc) {
      this.error = exc instanceof Error ? exc.message : String(exc);
    } finally {
      this.loaded = true;
    }
  }
}

export const daemonStatusStore = new DaemonStatusStore();
