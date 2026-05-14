// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import type { EquitySnapshotOut } from '$lib/portfolio/types';

import EquitySparkline from './EquitySparkline.svelte';

function snapshot(equity: string, dayOffset: number): EquitySnapshotOut {
  return {
    id: `00000000-0000-0000-0000-${dayOffset.toString().padStart(12, '0')}`,
    tenant_id: '00000000-0000-0000-0000-0000000000aa',
    mode: 'paper',
    account_equity: equity,
    cash_balance: '50000.00',
    realized_pnl_today: '0.00',
    unrealized_pnl: '0.00',
    currency: 'USD',
    snapshot_kind: 'event',
    created_at: new Date(2026, 3, 1 + dayOffset).toISOString(),
  };
}

const meta: Meta = {
  title: 'Portfolio/EquitySparkline',
  component: EquitySparkline,
  tags: ['autodocs'],
  argTypes: {
    width: { control: 'number' },
    height: { control: 'number' },
    currency: { control: 'text' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Loaded: Story = {
  args: {
    snapshots: [
      snapshot('100000.00', 0),
      snapshot('100250.00', 1),
      snapshot('99800.00', 2),
      snapshot('100500.00', 3),
      snapshot('101200.00', 4),
      snapshot('100900.00', 5),
      snapshot('101800.00', 6),
    ],
    width: 240,
    height: 72,
    currency: 'USD',
  },
};

export const Empty: Story = {
  args: {
    snapshots: [],
    width: 240,
    height: 72,
    currency: 'USD',
  },
};

export const NegativeTrend: Story = {
  args: {
    snapshots: [
      snapshot('101000.00', 0),
      snapshot('100600.00', 1),
      snapshot('100300.00', 2),
      snapshot('99800.00', 3),
      snapshot('99100.00', 4),
    ],
    width: 240,
    height: 72,
    currency: 'USD',
  },
};
