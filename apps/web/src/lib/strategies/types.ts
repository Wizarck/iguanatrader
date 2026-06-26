/**
 * Frontend mirrors of the FastAPI Pydantic DTOs in
 * `apps/api/src/iguanatrader/api/dtos/trades.py` (`StrategyConfigOut`,
 * `StrategyConfigIn`, `StrategyConfigListOut`) PLUS the per-kind
 * parameter catalogue consumed by the strategy form.
 *
 * The catalogue lives client-side until a `GET /strategies/catalogue`
 * endpoint exists (see U7 in `docs/roadmap-ui.md`). Defaults +
 * parameter names mirror the Python sources of truth at
 * `apps/api/src/iguanatrader/contexts/trading/strategies/*.py` —
 * changes there MUST be reflected here, and vice versa.
 */

export type StrategyConfigOut = {
  id: string;
  tenant_id: string;
  strategy_kind: string;
  symbol: string;
  params: Record<string, unknown>;
  enabled: boolean;
  version: number;
  created_at: string;
  updated_at: string;
};

export type StrategyConfigIn = {
  strategy_kind: string;
  params: Record<string, unknown>;
  enabled: boolean;
};

export type StrategyConfigListOut = {
  items: StrategyConfigOut[];
  total: number | null;
};

/**
 * Parameter input types — drive the form-field renderer + serialiser.
 *
 *   - `integer`          plain integer (lookback, periods).
 *   - `decimal`          plain decimal (atr_mult, num_std).
 *   - `percent`          decimal stored as a 0..1 fraction; displayed and
 *                        entered as 0..100 in the UI (risk_pct).
 *   - `optional-decimal` decimal that may be left blank → omitted from
 *                        the params payload (squeeze_threshold).
 *   - `optional-string`  string that may be left blank → omitted
 *                        (bias_filter).
 */
export type ParamType =
  | 'integer'
  | 'decimal'
  | 'percent'
  | 'optional-decimal'
  | 'optional-string';

export type ParamSpec = {
  name: string;
  label: string;
  type: ParamType;
  default: number | string | null;
  min?: number;
  max?: number;
  step?: number;
  help: string;
};

export type StrategySpec = {
  kind: string;
  displayName: string;
  description: string;
  params: ParamSpec[];
};

// Shared parameter blocks reused across strategies. Keeping them in
// one place ensures the help text + defaults stay consistent.
const ATR_PARAMS: ParamSpec[] = [
  {
    name: 'atr_period',
    label: 'ATR period (bars)',
    type: 'integer',
    default: 14,
    min: 2,
    max: 200,
    step: 1,
    help: 'Bars used by Wilder ATR. 14 is the textbook default; lower = tighter, jumpier stops.',
  },
  {
    name: 'atr_mult',
    label: 'ATR stop multiplier',
    type: 'decimal',
    default: 2.0,
    min: 0.5,
    max: 10,
    step: 0.1,
    help: 'Stop loss is placed at entry − atr_mult × ATR. 2.0 is a common middle ground; 1.0 is tight, 3.0 wide.',
  },
];

const RISK_PARAM: ParamSpec = {
  name: 'risk_pct',
  label: 'Risk per trade (%)',
  type: 'percent',
  default: 0.01,
  min: 0.001,
  max: 0.1,
  step: 0.001,
  help: 'Fraction of account equity to put at risk per trade. 1% is a common cap; NFR-R6 enforces a hard ceiling.',
};

// Position-sizing mode shared across every strategy. Mirrors the Python
// `_SIZING_PARAMS` in `strategies_catalogue.py`. "risk" (default, blank) sizes
// by risk_pct of equity; "cash" buys a fixed dollar amount (target_cash ÷
// price), the way orders are often placed by hand at IB. Both floor to whole
// shares. Null defaults → omitted from the params payload (risk is the default).
const SIZING_PARAMS: ParamSpec[] = [
  {
    name: 'sizing_mode',
    label: 'Position sizing mode',
    type: 'optional-string',
    default: null,
    help: 'How the share quantity is sized. Leave empty (or "risk") to size by risk-per-trade (risk_pct of equity); set to "cash" to buy a fixed dollar amount (target_cash ÷ price). Always floored to whole shares.',
  },
  {
    name: 'target_cash',
    label: 'Target cash per trade ($)',
    type: 'optional-decimal',
    default: null,
    min: 0,
    step: 50,
    help: 'Dollar amount to deploy per trade when sizing mode is "cash". Ignored in risk mode. Floored to whole shares at the entry price.',
  },
];

/**
 * Per-kind catalogue. Order matters — first entry is the default in
 * the new-strategy form. Defaults are kept in sync with the Python
 * ``DEFAULT_*`` constants in
 * ``apps/api/src/iguanatrader/contexts/trading/strategies/*.py``.
 */
export const STRATEGY_CATALOGUE: readonly StrategySpec[] = [
  {
    kind: 'donchian_atr',
    displayName: 'Donchian breakout + ATR stop',
    description:
      'Long-only trend follower. Buys when price closes above the highest high of the prior N bars. Stop placed below entry at a multiple of Average True Range. Position sized to risk a fixed % of equity. Originated with the Turtle Traders.',
    params: [
      {
        name: 'lookback',
        label: 'Donchian channel lookback (bars)',
        type: 'integer',
        default: 20,
        min: 5,
        max: 200,
        step: 1,
        help: 'How many bars define the breakout high. 20 (Turtle S1) is reactive; 55 (Turtle S2) is slower but cleaner.',
      },
      ...ATR_PARAMS,
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
  {
    kind: 'sma_cross',
    displayName: 'Golden-cross SMA',
    description:
      'Long-only momentum strategy. Enters when the fast SMA crosses up through the slow SMA. Volatility-aware position sizing using a rolling stdev of returns. Classic 50/200 day combo is the "golden cross".',
    params: [
      {
        name: 'fast',
        label: 'Fast SMA period (bars)',
        type: 'integer',
        default: 50,
        min: 2,
        max: 200,
        step: 1,
        help: 'Short moving-average window. Smaller = more sensitive, more whipsaws.',
      },
      {
        name: 'slow',
        label: 'Slow SMA period (bars)',
        type: 'integer',
        default: 200,
        min: 10,
        max: 500,
        step: 1,
        help: 'Long moving-average window. Must be greater than fast.',
      },
      {
        name: 'vol_window',
        label: 'Volatility window (bars)',
        type: 'integer',
        default: 20,
        min: 5,
        max: 100,
        step: 1,
        help: 'Bars used to estimate return stdev for sizing.',
      },
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
  {
    kind: 'bollinger_breakout',
    displayName: 'Bollinger upper-band breakout',
    description:
      'Long-only volatility-adaptive trend follower. Buys when price closes above the upper Bollinger band (SMA + N stdev). Optional squeeze gate requires the bands to have been narrow before the break, which filters chop. ATR-based stop and risk-% sizing.',
    params: [
      {
        name: 'period',
        label: 'Bollinger period (bars)',
        type: 'integer',
        default: 20,
        min: 5,
        max: 200,
        step: 1,
        help: 'Bars used for the SMA + stdev. 20 is the canonical Bollinger setting.',
      },
      {
        name: 'num_std',
        label: 'Band width (× stdev)',
        type: 'decimal',
        default: 2.0,
        min: 0.5,
        max: 5,
        step: 0.1,
        help: 'How many standard deviations away the band sits. 2.0 is the classic default; higher = harder to trigger.',
      },
      {
        name: 'squeeze_threshold',
        label: 'Squeeze threshold (band width %)',
        type: 'optional-decimal',
        default: null,
        min: 0.001,
        max: 0.5,
        step: 0.001,
        help: 'Optional. When set, the break only counts if the prior squeeze-lookback bars had band width below this %. Leave empty to disable the gate.',
      },
      {
        name: 'squeeze_lookback',
        label: 'Squeeze lookback (bars)',
        type: 'integer',
        default: 6,
        min: 2,
        max: 50,
        step: 1,
        help: 'Bars over which the squeeze condition must hold. Ignored when squeeze threshold is empty.',
      },
      ...ATR_PARAMS,
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
  {
    kind: 'rsi_mean_reversion',
    displayName: 'RSI oversold mean-reversion',
    description:
      'Long-only counter-trend. Buys when Wilder RSI(14) crosses up from below the oversold threshold — i.e. the dip is starting to reverse. ATR stop and risk-% sizing keep losses bounded on the (frequent) failed reversals.',
    params: [
      {
        name: 'rsi_period',
        label: 'RSI period (bars)',
        type: 'integer',
        default: 14,
        min: 2,
        max: 100,
        step: 1,
        help: 'Wilder smoothing period. 14 is the textbook default.',
      },
      {
        name: 'oversold',
        label: 'Oversold threshold (0-100)',
        type: 'decimal',
        default: 30,
        min: 5,
        max: 50,
        step: 1,
        help: 'RSI level below which the strategy waits for a cross-up. 30 is conventional; 20 is more aggressive.',
      },
      {
        name: 'overbought',
        label: 'Overbought threshold (0-100)',
        type: 'decimal',
        default: 70,
        min: 50,
        max: 95,
        step: 1,
        help: 'Symmetric counterpart to oversold. Exposed for symmetry — long-only entries do not consume it directly.',
      },
      ...ATR_PARAMS,
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
  {
    kind: 'macd_cross',
    displayName: 'MACD signal-line cross',
    description:
      'Long-only momentum strategy. Buys when the MACD line crosses up through its signal line (Appel canonical 12/26/9). Optional bias filter — pass an SMA period in bias_filter to require price above SMA(period) before entry, filtering counter-trend signals.',
    params: [
      {
        name: 'fast',
        label: 'MACD fast EMA (bars)',
        type: 'integer',
        default: 12,
        min: 2,
        max: 100,
        step: 1,
        help: 'Short EMA in the MACD formula. 12 is the Appel default.',
      },
      {
        name: 'slow',
        label: 'MACD slow EMA (bars)',
        type: 'integer',
        default: 26,
        min: 5,
        max: 200,
        step: 1,
        help: 'Long EMA. Must be greater than fast.',
      },
      {
        name: 'signal',
        label: 'MACD signal EMA (bars)',
        type: 'integer',
        default: 9,
        min: 2,
        max: 50,
        step: 1,
        help: 'Smoothing EMA applied to the MACD line. 9 is the Appel default.',
      },
      {
        name: 'bias_filter',
        label: 'Bias filter (SMA period, optional)',
        type: 'optional-string',
        default: null,
        help: 'Optional trend filter — type an SMA period like "200" to require price above SMA(period). Leave empty to disable.',
      },
      ...ATR_PARAMS,
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
  {
    kind: 'volume_donchian',
    displayName: 'Donchian breakout + volume confirmation',
    description:
      'Long-only conviction-filtered Donchian variant. Same N-bar high breakout as the vanilla Donchian, but the breakout bar must also see volume above a multiple of the rolling average volume. Filters low-conviction breaks at the cost of fewer entries.',
    params: [
      {
        name: 'period',
        label: 'Donchian period (bars)',
        type: 'integer',
        default: 20,
        min: 5,
        max: 200,
        step: 1,
        help: 'Channel lookback. Same role as `lookback` in the vanilla Donchian strategy.',
      },
      {
        name: 'vol_window',
        label: 'Volume average window (bars)',
        type: 'integer',
        default: 20,
        min: 5,
        max: 200,
        step: 1,
        help: 'Bars used for the rolling average volume baseline.',
      },
      {
        name: 'volume_threshold',
        label: 'Volume multiple required',
        type: 'decimal',
        default: 1.5,
        min: 1.0,
        max: 10,
        step: 0.1,
        help: 'Breakout volume must be ≥ this multiple of the rolling avg. 1.5× is a moderate filter; 2.0× is strict.',
      },
      ...ATR_PARAMS,
      RISK_PARAM,
      ...SIZING_PARAMS,
    ],
  },
] as const;

export const STRATEGY_KINDS = STRATEGY_CATALOGUE.map((s) => s.kind);
export type StrategyKind = (typeof STRATEGY_CATALOGUE)[number]['kind'];

/** Lookup a strategy spec by kind. Returns undefined for unknown kinds. */
export function getStrategySpec(kind: string): StrategySpec | undefined {
  return STRATEGY_CATALOGUE.find((s) => s.kind === kind);
}

/** Default params object for a kind — used when seeding the form. */
export function defaultParams(kind: string): Record<string, unknown> {
  const spec = getStrategySpec(kind);
  if (!spec) return {};
  const out: Record<string, unknown> = {};
  for (const p of spec.params) {
    if (p.default === null) continue; // optional fields: leave omitted
    out[p.name] = p.default;
  }
  return out;
}

/** Pretty-printed JSON of the defaults; legacy helper, still used by tests. */
export function defaultParamsJson(kind: string): string {
  return JSON.stringify(defaultParams(kind), null, 2);
}

/**
 * Form-state value: every param spec maps to a string in the form (text
 * inputs serialise as strings). Optional fields default to empty string.
 */
export type ParamFormValues = Record<string, string>;

export function paramsToFormValues(
  spec: StrategySpec,
  params: Record<string, unknown>,
): ParamFormValues {
  const out: ParamFormValues = {};
  for (const p of spec.params) {
    const raw = params[p.name];
    if (raw === undefined || raw === null) {
      // Missing → show the default in the input (except for optional fields
      // which stay blank so the operator sees the catalogue's null-means-off semantics).
      if (p.default === null) {
        out[p.name] = '';
      } else {
        out[p.name] = formatDefault(p);
      }
      continue;
    }
    if (p.type === 'percent') {
      // Backend stores 0.01 = 1%. Display as 1.
      const num = typeof raw === 'number' ? raw : Number(raw);
      out[p.name] = Number.isFinite(num) ? String(num * 100) : '';
    } else {
      out[p.name] = String(raw);
    }
  }
  return out;
}

function formatDefault(p: ParamSpec): string {
  if (p.default === null) return '';
  if (p.type === 'percent') {
    return String(Number(p.default) * 100);
  }
  return String(p.default);
}

/** Validate + serialise the form back to a backend-shape params object.
 *
 * Returns either a populated params dict OR a map of per-field error
 * messages so the caller can surface them inline. Empty optional fields
 * are omitted from the output dict.
 */
export type ParamValidation =
  | { ok: true; params: Record<string, unknown> }
  | { ok: false; errors: Record<string, string> };

export function validateParamForm(
  spec: StrategySpec,
  values: ParamFormValues,
): ParamValidation {
  const params: Record<string, unknown> = {};
  const errors: Record<string, string> = {};
  for (const p of spec.params) {
    const raw = (values[p.name] ?? '').trim();
    if (raw === '') {
      if (p.type === 'optional-decimal' || p.type === 'optional-string') continue;
      errors[p.name] = `${p.label} is required.`;
      continue;
    }
    if (p.type === 'optional-string') {
      params[p.name] = raw;
      continue;
    }
    const num = Number(raw);
    if (!Number.isFinite(num)) {
      errors[p.name] = `${p.label} must be a number.`;
      continue;
    }
    if (p.type === 'integer' && !Number.isInteger(num)) {
      errors[p.name] = `${p.label} must be a whole number.`;
      continue;
    }
    if (p.type === 'percent') {
      // Bounds expressed as 0..1 in spec; we converted them via × 100 for display.
      const fraction = num / 100;
      if (p.min !== undefined && fraction < p.min) {
        errors[p.name] = `${p.label} must be at least ${p.min * 100}.`;
        continue;
      }
      if (p.max !== undefined && fraction > p.max) {
        errors[p.name] = `${p.label} must be at most ${p.max * 100}.`;
        continue;
      }
      params[p.name] = fraction;
      continue;
    }
    if (p.min !== undefined && num < p.min) {
      errors[p.name] = `${p.label} must be at least ${p.min}.`;
      continue;
    }
    if (p.max !== undefined && num > p.max) {
      errors[p.name] = `${p.label} must be at most ${p.max}.`;
      continue;
    }
    params[p.name] = num;
  }
  return Object.keys(errors).length === 0 ? { ok: true, params } : { ok: false, errors };
}

/** IBKR symbol convention — uppercase A-Z and digits, length 1..16. */
export const SYMBOL_PATTERN = /^[A-Z0-9]{1,16}$/;
