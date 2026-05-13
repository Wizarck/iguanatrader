/**
 * Pure helpers mapping trade side/state to Badge variants — extracted
 * so the page Svelte file stays lean and the mapping is unit-testable
 * without a DOM environment.
 */

import type { BadgeVariant } from '$lib/components/Badge.svelte';

export function sideVariant(side: string): BadgeVariant {
  return side === 'buy' ? 'success' : 'destructive';
}

export function stateVariant(state: string): BadgeVariant {
  return state === 'open' ? 'accent' : 'mute';
}
