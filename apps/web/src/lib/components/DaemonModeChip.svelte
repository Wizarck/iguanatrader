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
  // No row → either the first poll is still in flight ("…") or it settled with
  // no reachable status ("N/D", e.g. /api/v1/status failed). Either way the chip
  // must stay NEUTRAL GREY — never the red/yellow tone (red = real money armed,
  // not "unknown"), so a failed status read can't look like an armed live mode.
  const unknown = $derived(row === null && daemonStatusStore.loaded);
  const recentlyFilled = $derived(() => {
    if (!row?.last_fill_at) return false;
    const fillMs = new Date(row.last_fill_at).getTime();
    return Date.now() - fillMs < 60_000;
  });

  const tone: 'paper' | 'live' = mode;
  const stateLabel = $derived(row !== null ? (active ? 'ON' : 'OFF') : unknown ? 'N/D' : '…');
  const tooltip = $derived.by(() => {
    const M = mode.toUpperCase();
    // The LIVE chip is red on purpose — make clear it is a warning, not a fault.
    const realMoney = mode === 'live' ? ' Rojo = hay dinero real en riesgo, no es un error.' : '';
    if (row === null) {
      return unknown
        ? `No se pudo leer el estado del daemon ${M}.${realMoney}`
        : `Cargando estado del daemon ${M}…`;
    }
    if (!row.enabled) return `Daemon ${M} apagado (OFF).${realMoney}`;
    if (!row.ib_connected) {
      return `Daemon ${M} encendido, pero sin conexión con el IB Gateway.${realMoney}`;
    }
    const pending = row.pending_proposals_count;
    return `Daemon ${M} activo. ${pending} propuesta${pending === 1 ? '' : 's'} pendiente${pending === 1 ? '' : 's'}.${realMoney}`;
  });

  function onclick(): void {
    modalOpen = true;
  }
</script>

<button
  type="button"
  class="chip chip--{tone}"
  class:chip--active={active}
  class:chip--dim={!active && row !== null}
  class:chip--unknown={row === null}
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

  /* No status yet (loading) or unreachable status (N/D) → neutral grey, never
     the red/yellow tone. "Unknown" must not be mistaken for an armed live chip. */
  .chip--unknown {
    background: var(--surface-2);
    color: var(--mute);
    border-color: var(--border);
    filter: none;
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
