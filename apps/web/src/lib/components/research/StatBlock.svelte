<script lang="ts" module>
  /**
   * Trader KPI snapshot card (slice research-stat-block).
   *
   * Renders the data block Arturo asked for above the brief prose:
   * price + day chg + 52w range, vol, beta, valuation multiples,
   * RSI, MA position, relative strength vs SPY, analyst consensus.
   *
   * The component is value-only — formatting helpers are local so
   * the card stays self-contained. Each KPI gracefully renders as
   * "—" when the upstream source hasn't been ingested yet.
   */
</script>

<script lang="ts">
  export type BriefStats = {
    symbol: string;
    as_of: string | null;
    last_price: number | null;
    day_change_pct: number | null;
    high_52w: number | null;
    low_52w: number | null;
    position_in_52w_pct: number | null;
    avg_volume_20d: number | null;
    volatility_20d_annualized: number | null;
    beta_vs_spy_60d: number | null;
    forward_pe: number | null;
    pe_ratio: number | null;
    price_to_book: number | null;
    market_cap: number | null;
    rsi_14: number | null;
    sma_50: number | null;
    sma_200: number | null;
    pos_vs_sma_50_pct: number | null;
    pos_vs_sma_200_pct: number | null;
    return_3m_pct: number | null;
    return_12m_pct: number | null;
    relative_strength_vs_spy_3m_pct: number | null;
    relative_strength_vs_spy_12m_pct: number | null;
    analyst_target_price: number | null;
    analyst_count: number | null;
    upside_to_target_pct: number | null;
  };

  let { stats }: { stats: BriefStats } = $props();

  function fmt(value: number | null, opts: { digits?: number; suffix?: string } = {}): string {
    if (value === null || value === undefined) return '—';
    const { digits = 2, suffix = '' } = opts;
    return `${value.toFixed(digits)}${suffix}`;
  }

  function fmtPct(value: number | null, digits = 2): string {
    if (value === null || value === undefined) return '—';
    const sign = value > 0 ? '+' : '';
    return `${sign}${value.toFixed(digits)}%`;
  }

  function fmtCompact(value: number | null): string {
    if (value === null || value === undefined) return '—';
    const abs = Math.abs(value);
    if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
    if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
    if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
    if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
    return value.toFixed(0);
  }

  function signClass(value: number | null): string {
    if (value === null || value === undefined) return 'neutral';
    if (value > 0) return 'positive';
    if (value < 0) return 'negative';
    return 'neutral';
  }
</script>

<section class="stat-block" aria-label="Snapshot KPIs">
  <div class="row">
    <div class="block">
      <h3>Price</h3>
      <dl>
        <div>
          <dt>Last</dt>
          <dd>{fmt(stats.last_price)}</dd>
        </div>
        <div>
          <dt>Day chg</dt>
          <dd class={signClass(stats.day_change_pct)}>{fmtPct(stats.day_change_pct)}</dd>
        </div>
        <div>
          <dt>52w range</dt>
          <dd>{fmt(stats.low_52w)} — {fmt(stats.high_52w)}</dd>
        </div>
        <div>
          <dt>Pos in 52w</dt>
          <dd>{fmt(stats.position_in_52w_pct, { digits: 0, suffix: '%' })}</dd>
        </div>
        <div>
          <dt>Avg vol 20d</dt>
          <dd>{fmtCompact(stats.avg_volume_20d)}</dd>
        </div>
      </dl>
    </div>

    <div class="block">
      <h3>Risk</h3>
      <dl>
        <div>
          <dt>Vol 20d (ann)</dt>
          <dd>{fmt(stats.volatility_20d_annualized, { digits: 1, suffix: '%' })}</dd>
        </div>
        <div>
          <dt>Beta vs SPY</dt>
          <dd>{fmt(stats.beta_vs_spy_60d, { digits: 2 })}</dd>
        </div>
      </dl>
    </div>

    <div class="block">
      <h3>Valuation</h3>
      <dl>
        <div>
          <dt>Forward P/E</dt>
          <dd>{fmt(stats.forward_pe, { digits: 1 })}</dd>
        </div>
        <div>
          <dt>P/E</dt>
          <dd>{fmt(stats.pe_ratio, { digits: 1 })}</dd>
        </div>
        <div>
          <dt>P/B</dt>
          <dd>{fmt(stats.price_to_book, { digits: 1 })}</dd>
        </div>
        <div>
          <dt>Market cap</dt>
          <dd>{fmtCompact(stats.market_cap)}</dd>
        </div>
      </dl>
    </div>

    <div class="block">
      <h3>Momentum</h3>
      <dl>
        <div>
          <dt>RSI(14)</dt>
          <dd>{fmt(stats.rsi_14, { digits: 0 })}</dd>
        </div>
        <div>
          <dt>vs SMA50</dt>
          <dd class={signClass(stats.pos_vs_sma_50_pct)}>{fmtPct(stats.pos_vs_sma_50_pct, 1)}</dd>
        </div>
        <div>
          <dt>vs SMA200</dt>
          <dd class={signClass(stats.pos_vs_sma_200_pct)}>{fmtPct(stats.pos_vs_sma_200_pct, 1)}</dd>
        </div>
        <div>
          <dt>3m return</dt>
          <dd class={signClass(stats.return_3m_pct)}>{fmtPct(stats.return_3m_pct, 1)}</dd>
        </div>
        <div>
          <dt>12m return</dt>
          <dd class={signClass(stats.return_12m_pct)}>{fmtPct(stats.return_12m_pct, 1)}</dd>
        </div>
        <div>
          <dt>RS 3m vs SPY</dt>
          <dd class={signClass(stats.relative_strength_vs_spy_3m_pct)}
            >{fmtPct(stats.relative_strength_vs_spy_3m_pct, 1)}</dd
          >
        </div>
        <div>
          <dt>RS 12m vs SPY</dt>
          <dd class={signClass(stats.relative_strength_vs_spy_12m_pct)}
            >{fmtPct(stats.relative_strength_vs_spy_12m_pct, 1)}</dd
          >
        </div>
      </dl>
    </div>

    <div class="block">
      <h3>Analyst consensus</h3>
      <dl>
        <div>
          <dt>Mean target</dt>
          <dd>{fmt(stats.analyst_target_price, { digits: 2 })}</dd>
        </div>
        <div>
          <dt>Analysts</dt>
          <dd>{stats.analyst_count ?? '—'}</dd>
        </div>
        <div>
          <dt>Upside</dt>
          <dd class={signClass(stats.upside_to_target_pct)}
            >{fmtPct(stats.upside_to_target_pct, 1)}</dd
          >
        </div>
      </dl>
    </div>
  </div>

  {#if stats.as_of}
    <p class="as-of">Snapshot as of {stats.as_of}</p>
  {/if}
</section>

<style>
  .stat-block {
    background: var(--surface);
    border: 1px solid var(--mute);
    border-radius: 6px;
    padding: 16px 20px;
    margin-bottom: 16px;
  }
  .row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 24px 32px;
  }
  .block h3 {
    margin: 0 0 8px;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--mute);
  }
  dl {
    margin: 0;
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 4px 12px;
    font-size: 13px;
  }
  dl > div {
    display: contents;
  }
  dt {
    color: var(--mute);
  }
  dd {
    margin: 0;
    color: var(--ink);
    text-align: right;
    font-variant-numeric: tabular-nums;
    font-weight: 500;
  }
  dd.positive {
    color: var(--success, #2da44e);
  }
  dd.negative {
    color: var(--destructive, #cf222e);
  }
  dd.neutral {
    color: var(--ink);
  }
  .as-of {
    margin: 12px 0 0;
    font-size: 11px;
    color: var(--mute);
    text-align: right;
  }
</style>
