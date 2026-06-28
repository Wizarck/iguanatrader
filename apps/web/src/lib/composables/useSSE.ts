/**
 * `useSSE` composable — slice W1.
 *
 * Wraps `EventSource` against `${API_BASE_URL}/api/v1/stream/<name>`
 * with reconnect-on-drop using the canonical backoff sequence
 * `[3, 6, 12, 24, 48]` seconds — exact mirror of slice 2's
 * `HeartbeatMixin` backoff. After exhausting the sequence, the
 * connection is marked `'closed'` and no further automatic reconnect
 * fires (caller may instantiate a fresh `useSSE` to start over).
 *
 * Per-stream connection state is written to the `connection` store so
 * the TopBar `ConnectionIndicator` reads aggregate health.
 *
 * The composable returns `{ close }` — the caller MUST call `close()`
 * on component unmount (typically inside an `$effect` cleanup function)
 * to avoid leaking the EventSource.
 *
 * Per design D5 + D6. Reconnect contract aligned with j1.md §3 step 1
 * ("After 5s of disconnect: red + persistent banner").
 */

import type { Problem } from '$lib/types/problem';

import { API_BASE_URL } from '$lib/config';
import { connectionStore } from '$lib/stores/connection.svelte';

/** Canonical backoff — mirror of slice 2 `HeartbeatMixin`. */
export const SSE_BACKOFF_SECONDS = [3, 6, 12, 24, 48] as const;

export type SSEHandle = {
  /** Close the connection and stop reconnects. Idempotent. */
  close: () => void;
};

export type SSEOptions = {
  /** Fired on every `MessageEvent`. */
  onMessage?: (event: MessageEvent) => void;
  /**
   * Fired when the server returns a Problem on the initial connect or
   * on reconnect (HTTP 4xx/5xx with problem+json). EventSource itself
   * doesn't expose response bodies; this hook is invoked when the
   * underlying `fetch` preflight (where supported) receives a Problem.
   * For the basic browser EventSource, this is a no-op — connection
   * failures fire `onerror` only. Implementations may layer a fetch
   * preflight in a follow-up.
   */
  onProblem?: (problem: Problem) => void;
  /** Fired when the connection moves to `'open'` (initial or after reconnect). */
  onOpen?: () => void;
};

/**
 * Resolve the SSE URL for a given stream name.
 *
 * Same-origin in the browser (empty base) so `EventSource` connects through the
 * SvelteKit `/api/v1/[...path]` proxy — which forwards the session cookie and
 * streams `text/event-stream` straight back. `useSSE` only runs in the browser
 * (EventSource is browser-only), but the guard mirrors `useFetch` for symmetry.
 * Resolving against `API_BASE_URL` here pointed EventSource at the bundle
 * default (`http://127.0.0.1:8000`) and never connected.
 */
function streamUrl(name: string): string {
  const base = typeof window === 'undefined' ? API_BASE_URL : '';
  return `${base}/api/v1/stream/${encodeURIComponent(name)}`;
}

export function useSSE(name: string, opts: SSEOptions = {}): SSEHandle {
  // SSR / non-browser guard — `EventSource` is browser-only. The handle
  // is a no-op; caller's effect cleanup just calls `close()`.
  if (typeof EventSource === 'undefined') {
    return { close: () => {} };
  }

  let attempt = 0;
  let source: EventSource | null = null;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closed = false;

  const setState = (state: 'open' | 'reconnecting' | 'closed'): void => {
    connectionStore.setStream(name, state);
  };

  const connect = (): void => {
    if (closed) return;

    source = new EventSource(streamUrl(name), {
      withCredentials: true,
    });

    source.onopen = () => {
      attempt = 0;
      setState('open');
      opts.onOpen?.();
    };

    source.onmessage = (event) => {
      opts.onMessage?.(event);
    };

    source.onerror = () => {
      // EventSource reconnects natively, but we want our canonical
      // backoff sequence (slice 2 mirror). Force-close the native
      // connection and schedule the next attempt.
      source?.close();
      source = null;

      if (closed) return;

      if (attempt >= SSE_BACKOFF_SECONDS.length) {
        setState('closed');
        return;
      }

      const delay = SSE_BACKOFF_SECONDS[attempt] * 1000;
      attempt += 1;
      setState('reconnecting');
      reconnectTimer = setTimeout(connect, delay);
    };
  };

  const close = (): void => {
    closed = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    source?.close();
    source = null;
    setState('closed');
    connectionStore.removeStream(name);
  };

  // Kick off the first connection synchronously.
  connect();

  return { close };
}
