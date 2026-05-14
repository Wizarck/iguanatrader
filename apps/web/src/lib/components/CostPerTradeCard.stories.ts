// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import CostPerTradeCard from './CostPerTradeCard.svelte';

const TENANT_ID = '00000000-0000-0000-0000-0000000000aa';
const PERIOD_START = '2026-05-01T00:00:00Z';
const PERIOD_END = '2026-05-31T23:59:59Z';

const meta: Meta = {
  title: 'Costs/CostPerTradeCard',
  component: CostPerTradeCard,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {
  args: {
    perTrade: {
      tenant_id: TENANT_ID,
      period_start: PERIOD_START,
      period_end: PERIOD_END,
      total_llm_cost_usd: '0.00',
      closed_trades_count: 0,
      cost_per_trade_usd: null,
    },
  },
};

export const Typical: Story = {
  args: {
    perTrade: {
      tenant_id: TENANT_ID,
      period_start: PERIOD_START,
      period_end: PERIOD_END,
      total_llm_cost_usd: '12.45',
      closed_trades_count: 5,
      cost_per_trade_usd: '2.49',
    },
  },
};

export const OverBudget: Story = {
  args: {
    perTrade: {
      tenant_id: TENANT_ID,
      period_start: PERIOD_START,
      period_end: PERIOD_END,
      total_llm_cost_usd: '128.90',
      closed_trades_count: 18,
      cost_per_trade_usd: '7.16',
    },
  },
};
