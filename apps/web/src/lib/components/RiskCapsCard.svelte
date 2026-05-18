<script lang="ts">
  import { formatPercent } from '$lib/portfolio/format';
  import type { CapsDTO } from '$lib/risk/types';

  type Props = {
    caps: CapsDTO;
  };

  let { caps }: Props = $props();
</script>

<dl class="caps-card" data-testid="risk-caps-card">
  <div class="cell">
    <dt>Por trade</dt>
    <dd data-testid="cap-per-trade">{formatPercent(caps.per_trade_pct)}</dd>
  </div>
  <div class="cell">
    <dt>Daily loss</dt>
    <dd data-testid="cap-daily-loss">{formatPercent(caps.daily_loss_pct)}</dd>
  </div>
  <div class="cell">
    <dt>Weekly loss</dt>
    <dd data-testid="cap-weekly-loss">{formatPercent(caps.weekly_loss_pct)}</dd>
  </div>
  <div class="cell">
    <dt>Max positions</dt>
    <dd data-testid="cap-max-positions">{caps.max_open_positions}</dd>
  </div>
  <div class="cell">
    <dt>Max drawdown</dt>
    <dd data-testid="cap-max-drawdown">{formatPercent(caps.max_drawdown_pct)}</dd>
  </div>
</dl>

<style>
  .caps-card {
    display: grid;
    grid-template-columns: repeat(5, minmax(0, 1fr));
    gap: 16px;
    margin: 0;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  dt {
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  dd {
    margin: 0;
    color: var(--ink);
    font-size: 18px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  @media (max-width: 960px) {
    .caps-card {
      grid-template-columns: repeat(3, minmax(0, 1fr));
    }
  }
  @media (max-width: 560px) {
    .caps-card {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
