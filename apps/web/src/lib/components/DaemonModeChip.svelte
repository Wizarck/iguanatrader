<script lang="ts">
  /**
   * DaemonModeChip — slice ``dual-daemon-mode-toggle-and-reconcile``.
   *
   * Persistent header chip surfacing the per-mode daemon state. Click
   * opens DaemonToggleModal (wired in a follow-up slice — for now the
   * click is a no-op breadcrumb).
   *
   * Visual contract (design §D8):
   *   - paper → always YELLOW (warning); live → always RED (destructive)
   *   - dim/low-saturation when (enabled=false OR ib_connected=false)
   *   - full saturation + ON label when (enabled=true AND ib_connected=true)
   *   - pulse-dot when last_fill_at within last 60s
   *
   * The chip reads from the singleton daemon-status store; the layout
   * mounts the store + the two chips.
   */
  import DaemonToggleModal from '$lib/components/DaemonToggleModal.svelte';
  import { daemonStatusStore } from '$lib/stores/daemon-status.svelte';
  import type { DaemonMode } from '$lib/status/types';

  type Props = {
    mode: DaemonMode;
  };

  let { mode }: Props = $props();
  let modalOpen = $state(false);

  const row = $derived(daemonStatusStore.status?.daemons.find((d) => d.mode === mode) ?? null);
  const active = $derived(!!row && row.enabled && row.ib_connected);
  const recentlyFilled = $derived(() => {
    if (!row?.last_fill_at) return false;
    const fillMs = new Date(row.last_fill_at).getTime();
    return Date.now() - fillMs < 60_000;
  });

  const tone: 'paper' | 'live' = mode;
  const stateLabel = $derived(
    row === null ? '…' : active ? 'ON' : row.enabled ? 'OFF' : 'OFF',
  );
  const tooltip = $derived.by(() => {
    if (row === null) return `${mode.toUpperCase()} daemon status loading…`;
    if (!row.enabled) return `${mode.toUpperCase()} daemon is toggled OFF.`;
    if (!row.ib_connected) {
      return `${mode.toUpperCase()} daemon is enabled but the IB Gateway connection is down.`;
    }
    const pending = row.pending_proposals_count;
    return (
      `${mode.toUpperCase()} daemon is active. ` +
      `${pending} pending proposal${pending === 1 ? '' : 's'}.`
    );
  });

  function onclick(): void {
    modalOpen = true;
  }
</script>

<button
  type="button"
  class="chip chip--{tone}"
  class:chip--active={active}
  class:chip--dim={!active}
  class:chip--pulse={recentlyFilled}
  title={tooltip}
  aria-label={tooltip}
  {onclick}
>
  <span class="chip__dot" aria-hidden="true"></span>
  <span class="chip__label">{mode.toUpperCase()}</span>
  <span class="chip__state">{stateLabel}</span>
</button>

<DaemonToggleModal {mode} open={modalOpen} onClose={() => (modalOpen = false)} />

<style>
  .chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 10px;
    border-radius: var(--r-pill);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.04em;
    line-height: 1.4;
    border: 1px solid transparent;
    cursor: pointer;
    transition:
      background 120ms ease,
      border-color 120ms ease,
      filter 120ms ease;
  }

  .chip__dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: currentColor;
  }

  .chip__state {
    font-size: 10px;
    opacity: 0.85;
  }

  /* PAPER — always yellow (warning). Tone color is fixed; brightness
     varies with active state per design D8. */
  .chip--paper.chip--active {
    background: oklch(82% 0.16 95 / 0.22);
    color: oklch(82% 0.16 95);
    border-color: oklch(82% 0.16 95 / 0.55);
  }
  .chip--paper.chip--dim {
    background: oklch(82% 0.16 95 / 0.08);
    color: oklch(75% 0.12 95);
    border-color: oklch(82% 0.16 95 / 0.25);
    filter: saturate(0.7);
  }

  /* LIVE — always red (destructive). Red ≠ "down" — red conveys
     "real money is at risk". */
  .chip--live.chip--active {
    background: oklch(64% 0.2 25 / 0.22);
    color: oklch(64% 0.2 25);
    border-color: oklch(64% 0.2 25 / 0.55);
  }
  .chip--live.chip--dim {
    background: oklch(64% 0.2 25 / 0.08);
    color: oklch(60% 0.16 25);
    border-color: oklch(64% 0.2 25 / 0.25);
    filter: saturate(0.7);
  }

  .chip--pulse .chip__dot {
    animation: chip-pulse 1s ease-out;
  }

  @keyframes chip-pulse {
    0% {
      transform: scale(1);
      opacity: 1;
    }
    50% {
      transform: scale(1.6);
      opacity: 0.5;
    }
    100% {
      transform: scale(1);
      opacity: 1;
    }
  }
</style>
