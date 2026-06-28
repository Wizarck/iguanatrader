<script lang="ts">
  import { connectionStore } from '$lib/stores/connection.svelte';

  /**
   * ConnectionIndicator — slice W1.
   *
   * Reads `connectionStore.global` (worst-case aggregate across all SSE
   * streams). This is the DATA-stream connection — NOT the live-trading mode
   * (that is `DaemonModeChip`); labels deliberately avoid the word "Live".
   * Variants:
   *
   * - `idle` (no stream registered yet) → grey dot + "No data connection".
   * - `open` → green dot + "Live data".
   * - `reconnecting` → amber dot + "Reconnecting".
   * - `closed` → red dot + "No data" + tooltip with stream names. A
   *   persistent banner under the indicator surfaces if the drop exceeds 5s
   *   (slice 5 contract — the banner shows the streams that are closed).
   *
   * Per-stream detail surfaces via `title` attribute (HTML tooltip);
   * accessible via screen-reader through `aria-describedby` linkage.
   */

  // Stream summary string for the tooltip.
  const streamDetail = $derived(() => {
    const streams = connectionStore.streams;
    const entries = Object.entries(streams);
    if (entries.length === 0) return 'No active data streams';
    return entries.map(([name, state]) => `${name}: ${state}`).join(', ');
  });

  // When no SSE stream is registered yet, `connectionStore.global` optimistically
  // reports 'open' — which rendered a MISLEADING green "Live" while nothing was
  // actually connected (and clashed with the LIVE trading chip). Treat the empty
  // case as a distinct, neutral 'idle'. Labels are about the DATA connection, not
  // trading — deliberately NOT the word "Live" (that is the live-trading chip).
  const hasStreams = $derived(Object.keys(connectionStore.streams).length > 0);
  const variant = $derived(hasStreams ? connectionStore.global : 'idle');
  const label = $derived(
    variant === 'idle'
      ? 'No data connection'
      : variant === 'open'
        ? 'Live data'
        : variant === 'reconnecting'
          ? 'Reconnecting'
          : 'No data'
  );
</script>

<div
  class="indicator"
  data-variant={variant}
  role="status"
  aria-live="polite"
  aria-label="Data connection: {label}"
  title={streamDetail()}
>
  <span class="indicator__dot" aria-hidden="true"></span>
  <span class="indicator__label">{label}</span>
</div>

<style>
  .indicator {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-pill);
    font-size: 11px;
    color: var(--ink);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .indicator__dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--mute);
  }

  .indicator[data-variant='open'] .indicator__dot {
    background: var(--success);
    box-shadow: 0 0 6px oklch(72% 0.16 145 / 0.6);
  }
  .indicator[data-variant='reconnecting'] .indicator__dot {
    background: var(--warn-bg);
    animation: pulse 1.2s ease-in-out infinite;
  }
  .indicator[data-variant='closed'] .indicator__dot {
    background: var(--destructive);
  }

  @keyframes pulse {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.4;
    }
  }
</style>
