/**
 * Pure helpers mapping trade side/state to Badge variants — extracted
 * so the page Svelte file stays lean and the mapping is unit-testable
 * without a DOM environment.
 */

import type { BadgeVariant } from '$lib/components/Badge.svelte';

export function sideVariant(side: string): BadgeVariant {
  return side === 'buy' ? 'success' : 'destructive';
}

/**
 * Map Trade.state to a Badge variant.
 *
 * Slice ``u-next-2-trade-timeline``: ``closing`` and ``closed`` used to
 * share the ``mute`` variant, but the two states have radically
 * different risk profiles — a ``closing`` trade has an exit order in
 * flight (active broker-side risk), while ``closed`` is terminal. They
 * must look different in the UI.
 */
export function stateVariant(state: string): BadgeVariant {
  if (state === 'open') return 'accent';
  if (state === 'closing') return 'warning';
  return 'mute';
}

/**
 * Map Order.state to a Badge variant.
 *
 * Slice ``u-next-2-trade-timeline``: the trade-detail timeline renders
 * one row per Order (entry / stop / target / exit). The state palette
 * mirrors the trade-level palette but accounts for the broker-side
 * lifecycle (``new`` is pre-submit, ``submitted`` is acknowledged,
 * ``filled`` is terminal happy, ``canceled``/``rejected`` are terminal
 * unhappy).
 */
export function orderStateVariant(state: string): BadgeVariant {
  switch (state) {
    case 'new':
      return 'mute';
    case 'submitted':
    case 'partially_filled':
      return 'warning';
    case 'filled':
      return 'success';
    case 'canceled':
    case 'rejected':
      return 'destructive';
    default:
      return 'mute';
  }
}

/**
 * Categorise an Order into entry / stop / target / exit based on its
 * ``order_type`` + ``side`` relative to the parent trade's side.
 *
 * The Order rows don't carry an explicit role tag — the role is
 * inferred from the type:
 * - market on the same side as the trade → entry
 * - stop opposite to the trade side → stop-loss
 * - limit opposite to the trade side → target (take-profit)
 * - market opposite to the trade side → exit (manual / forced close)
 *
 * Returns ``unknown`` when no rule matches; the timeline still renders
 * the row but without a role label.
 */
export function orderRoleLabel(orderSide: string, orderType: string, tradeSide: string): string {
  const sameSide = orderSide === tradeSide;
  if (sameSide && orderType === 'market') return 'Entry';
  if (!sameSide && orderType === 'stop') return 'Stop';
  if (!sameSide && orderType === 'limit') return 'Target';
  if (!sameSide && orderType === 'market') return 'Exit';
  return orderType;
}
