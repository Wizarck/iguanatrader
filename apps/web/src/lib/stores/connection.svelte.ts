/**
 * Connection store — slice W1.
 *
 * Per-stream SSE connection state, with a `$derived` worst-case global
 * aggregate (closed > reconnecting > open). `useSSE` writes per-stream
 * state on connection lifecycle events; the TopBar's
 * `ConnectionIndicator` reads `global` for the visual variant.
 *
 * Per design D4: Svelte 5 runes singleton.
 */

export type StreamState = 'open' | 'reconnecting' | 'closed';

const PRIORITY: Record<StreamState, number> = {
  closed: 2,
  reconnecting: 1,
  open: 0,
};

class ConnectionStore {
  streams = $state<Record<string, StreamState>>({});

  /**
   * Worst-case state across all known streams. Empty stream set = `open`
   * (the indicator should show "Live" until something connects, NOT a
   * pessimistic "Disconnected" — there's nothing to disconnect from yet).
   */
  global = $derived.by<StreamState>(() => {
    const values = Object.values(this.streams);
    if (values.length === 0) return 'open';
    let worst: StreamState = 'open';
    for (const v of values) {
      if (PRIORITY[v] > PRIORITY[worst]) worst = v;
    }
    return worst;
  });

  /** Set the state of a stream by name. Used by `useSSE`. */
  setStream(name: string, state: StreamState): void {
    this.streams = { ...this.streams, [name]: state };
  }

  /** Drop a stream entirely (e.g., on graceful close). */
  removeStream(name: string): void {
    const { [name]: _, ...rest } = this.streams;
    void _;
    this.streams = rest;
  }
}

/** Singleton instance — import this everywhere. */
export const connectionStore = new ConnectionStore();
