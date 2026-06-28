<script lang="ts">
  import { formatPercent } from '$lib/portfolio/format';
  import { utilisationBarColour, type UtilisationTier } from '$lib/risk/colour';
  import type { CapsDTO } from '$lib/risk/types';

  type Props = {
    utilisation: Record<string, string>;
    caps: CapsDTO;
  };

  let { utilisation, caps }: Props = $props();

  type Row = {
    key: 'daily_loss' | 'weekly_loss' | 'max_drawdown';
    label: string;
    capPct: string;
    valuePct: string | undefined;
    ratio: number;
    tier: UtilisationTier;
  };

  /**
   * Backend keys → display labels + their paired cap. The cap pairing
   * is enforced here (not in markup) so the bar's `aria-valuemax`
   * + the right-side ratio label stay consistent.
   */
  const ROW_DEFS: ReadonlyArray<{
    key: Row['key'];
    label: string;
    capKey: keyof CapsDTO;
  }> = [
    { key: 'daily_loss', label: 'Daily loss', capKey: 'daily_loss_pct' },
    { key: 'weekly_loss', label: 'Weekly loss', capKey: 'weekly_loss_pct' },
    { key: 'max_drawdown', label: 'Max drawdown', capKey: 'max_drawdown_pct' }
  ];

  function computeRatio(value: string | undefined, capPct: string): number {
    if (value === undefined) return 0;
    const v = Number(value);
    const c = Number(capPct);
    if (!Number.isFinite(v) || !Number.isFinite(c) || c <= 0) return 0;
    return Math.min(v / c, 1);
  }

  const rows = $derived<Row[]>(
    ROW_DEFS.map((def) => {
      const valuePct = utilisation[def.key];
      const capPct = String(caps[def.capKey]);
      const ratio = computeRatio(valuePct, capPct);
      return {
        key: def.key,
        label: def.label,
        capPct,
        valuePct,
        ratio,
        tier: utilisationBarColour(ratio)
      };
    })
  );
</script>

<dl class="utilisation-card" data-testid="risk-utilisation-card">
  {#each rows as row (row.key)}
    <div class="row" data-testid="utilisation-row-{row.key}">
      <dt class="row-label">{row.label}</dt>
      <dd class="row-body">
        <div
          class="bar bar--{row.tier}"
          role="progressbar"
          aria-label={row.label}
          aria-valuemin="0"
          aria-valuemax="1"
          aria-valuenow={row.ratio.toFixed(3)}
          data-tier={row.tier}
          data-testid="utilisation-bar-{row.key}"
        >
          <span
            class="bar-fill bar-fill--{row.tier}"
            style="width: {(row.ratio * 100).toFixed(1)}%"
          ></span>
        </div>
        <span class="value" data-testid="utilisation-value-{row.key}">
          {formatPercent(row.valuePct ?? null)} / {formatPercent(row.capPct)}
        </span>
      </dd>
    </div>
  {/each}
</dl>

<style>
  .utilisation-card {
    display: flex;
    flex-direction: column;
    gap: 16px;
    margin: 0;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .row {
    display: grid;
    grid-template-columns: minmax(160px, 200px) minmax(0, 1fr);
    gap: 16px;
    align-items: center;
  }
  .row-label {
    margin: 0;
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .row-body {
    margin: 0;
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(120px, auto);
    gap: 12px;
    align-items: center;
  }
  .bar {
    position: relative;
    height: 8px;
    background: oklch(70% 0.012 250 / 0.18);
    border-radius: var(--r-pill);
    overflow: hidden;
  }
  .bar-fill {
    display: block;
    height: 100%;
    border-radius: var(--r-pill);
    transition: width 200ms ease-out;
  }
  .bar-fill--success {
    background: oklch(72% 0.16 145 / 0.85);
  }
  .bar-fill--accent {
    background: oklch(72% 0.14 195 / 0.85);
  }
  .bar-fill--destructive {
    background: oklch(64% 0.2 25 / 0.85);
  }
  .value {
    color: var(--ink);
    font-size: 13px;
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    text-align: right;
    white-space: nowrap;
  }
  @media (max-width: 720px) {
    .row {
      grid-template-columns: minmax(0, 1fr);
      gap: 8px;
    }
  }
</style>
