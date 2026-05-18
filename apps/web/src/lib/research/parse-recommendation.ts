/**
 * Extract the structured Recommendation section from a brief body
 * markdown string (slice U3).
 *
 * The `three_pillar` prompt emits a fixed-shape `## Recommendation`
 * block of four bolded lines:
 *
 *   ## Recommendation
 *
 *   **Action**: BUY | HOLD | AVOID
 *   **Target price**: $XXX.XX
 *   **Horizon**: 12 months
 *   **Key risks**:
 *   - risk one
 *   - risk two
 *
 * The parser is intentionally regex-based — the prompt's invariant
 * tests already lock the headings + key labels, so a higher-power
 * markdown AST would be over-engineering. When the section is
 * missing or malformed, individual fields fall back to ``null`` /
 * empty array so the card can still render a partial state.
 */

export type RecommendationAction = 'BUY' | 'HOLD' | 'AVOID';

export type ParsedRecommendation = {
  action: RecommendationAction | null;
  /** Free-form text after the colon (e.g. ``HOLD (low-confidence pending tier-A data)``). */
  actionSuffix: string;
  /** Numeric target price in USD when parseable; the original string otherwise. */
  targetPrice: number | null;
  targetPriceLabel: string | null;
  horizon: string | null;
  risks: string[];
  /** True when the action line declared ``low-confidence`` or the prose noted missing tier-A inputs. */
  lowConfidence: boolean;
};

const _ACTION_RE = /\*\*Action\*\*:\s*(?<value>[^\n]+)/i;
const _TARGET_RE = /\*\*Target\s*price\*\*:\s*(?<value>[^\n]+)/i;
const _HORIZON_RE = /\*\*Horizon\*\*:\s*(?<value>[^\n]+)/i;
const _RISKS_HEADER_RE = /\*\*Key\s*risks\*\*:\s*\n+(?<body>(?:\s*-\s+.+\n?)+)/i;
const _BULLET_RE = /^\s*-\s+(?<text>.+?)\s*$/;

export function parseRecommendation(body: string | null | undefined): ParsedRecommendation {
  if (!body) {
    return _empty();
  }
  // Restrict the search to the `## Recommendation` section so a stray
  // `**Action**:` reference inside a pillar can't bleed in.
  const section = _extractSection(body, 'Recommendation');
  const haystack = section ?? body;

  const actionMatch = _ACTION_RE.exec(haystack);
  const action = _coerceAction(actionMatch?.groups?.value ?? null);
  const actionSuffix = actionMatch?.groups?.value?.trim() ?? '';

  const targetMatch = _TARGET_RE.exec(haystack);
  const targetPriceLabel = targetMatch?.groups?.value?.trim() ?? null;
  const targetPrice = _coercePrice(targetPriceLabel);

  const horizonMatch = _HORIZON_RE.exec(haystack);
  const horizon = horizonMatch?.groups?.value?.trim() ?? null;

  const risksMatch = _RISKS_HEADER_RE.exec(haystack);
  const risks = risksMatch ? _extractBullets(risksMatch.groups?.body ?? '') : [];

  const lowConfidence =
    /low[-\s]?confidence/i.test(actionSuffix) ||
    /missing\s+tier[-\s]?A/i.test(haystack);

  return {
    action,
    actionSuffix,
    targetPrice,
    targetPriceLabel,
    horizon,
    risks,
    lowConfidence
  };
}

/**
 * Strip the `## Recommendation` block from a body string. Used by the
 * brief detail page to avoid duplicating the recommendation in the
 * card AND the prose.
 */
export function stripRecommendationSection(body: string | null | undefined): string {
  if (!body) return '';
  const headRe = /^##\s*Recommendation\s*\n/im;
  const headMatch = headRe.exec(body);
  if (!headMatch) return body;
  const start = headMatch.index;
  const after = body.slice(start + headMatch[0].length);
  const nextSection = /^##\s/m.exec(after);
  const end =
    start + headMatch[0].length + (nextSection ? nextSection.index : after.length);
  return (body.slice(0, start) + body.slice(end)).replace(/^\n+/, '');
}

function _empty(): ParsedRecommendation {
  return {
    action: null,
    actionSuffix: '',
    targetPrice: null,
    targetPriceLabel: null,
    horizon: null,
    risks: [],
    lowConfidence: false
  };
}

function _coerceAction(raw: string | null | undefined): RecommendationAction | null {
  if (!raw) return null;
  const upper = raw.trim().toUpperCase();
  if (upper.startsWith('BUY')) return 'BUY';
  if (upper.startsWith('HOLD')) return 'HOLD';
  if (upper.startsWith('AVOID')) return 'AVOID';
  return null;
}

function _coercePrice(raw: string | null): number | null {
  if (!raw) return null;
  // Capture the first decimal-looking number in the line — ``$174.50``
  // and ``174.50 USD`` and ``174`` all map to the same numeric.
  const match = /(-?\d+(?:\.\d+)?)/.exec(raw);
  if (!match) return null;
  const n = Number(match[1]);
  return Number.isFinite(n) ? n : null;
}

function _extractSection(body: string, heading: string): string | null {
  // Find the heading line, then slice to the next `## ` heading or EOF.
  // Avoids regex-based body capture so the JS engine's lack of `\Z` is
  // not a footgun.
  const headRe = new RegExp(`^##\\s*${heading}\\s*\\n`, 'mi');
  const headMatch = headRe.exec(body);
  if (!headMatch) return null;
  const start = headMatch.index + headMatch[0].length;
  const rest = body.slice(start);
  const endMatch = /^##\s/m.exec(rest);
  return endMatch ? rest.slice(0, endMatch.index) : rest;
}

function _extractBullets(body: string): string[] {
  const out: string[] = [];
  for (const line of body.split(/\r?\n/)) {
    const match = _BULLET_RE.exec(line);
    if (match) {
      const text = match.groups?.text?.trim();
      if (text) out.push(text);
    }
  }
  return out;
}
