<script lang="ts">
  // Slice research-frontend-extras §4.5 — fixed colour + label per methodology.
  // OKLCH tokens declared inline pending the canonical DESIGN.md migration.

  type Methodology =
    | 'three_pillar'
    | 'canslim'
    | 'magic_formula'
    | 'qarp'
    | 'multi_factor';

  type Props = {
    methodology: string;
    size?: 'sm' | 'md';
    showLabel?: boolean;
  };

  let { methodology, size = 'md', showLabel = true }: Props = $props();

  const LABELS: Record<Methodology, string> = {
    three_pillar: '3-pillar',
    canslim: 'CANSLIM',
    magic_formula: 'Magic Formula',
    qarp: 'QARP',
    multi_factor: 'Multi-factor'
  };

  // OKLCH-ish hues (TBD in DESIGN.md). Each methodology gets a distinct hue.
  const COLOURS: Record<Methodology, string> = {
    three_pillar: 'oklch(70% 0.13 240)', // blue
    canslim: 'oklch(72% 0.14 30)',       // orange
    magic_formula: 'oklch(70% 0.13 140)',// green
    qarp: 'oklch(70% 0.14 320)',         // purple
    multi_factor: 'oklch(70% 0.11 60)'   // amber
  };

  function isKnown(m: string): m is Methodology {
    return Object.prototype.hasOwnProperty.call(LABELS, m);
  }

  let known = $derived(isKnown(methodology));
  let label = $derived(known ? LABELS[methodology as Methodology] : methodology);
  let bg = $derived(known ? COLOURS[methodology as Methodology] : 'var(--mute)');
</script>

<span
  class="badge"
  class:sm={size === 'sm'}
  style="--badge-bg: {bg}"
  aria-label={`Methodology: ${label}`}
  title={label}
>
  {#if showLabel}{label}{:else}●{/if}
</span>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    padding: 2px 8px;
    border-radius: 999px;
    background: var(--badge-bg);
    color: white;
    font-size: 12px;
    font-weight: 500;
    line-height: 1.4;
    white-space: nowrap;
  }
  .badge.sm {
    padding: 1px 6px;
    font-size: 11px;
  }
</style>
