// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import RiskCapsCard from './RiskCapsCard.svelte';

const meta: Meta = {
  title: 'Risk/RiskCapsCard',
  component: RiskCapsCard,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof meta>;

export const ConservativeDefaults: Story = {
  args: {
    caps: {
      per_trade_pct: '0.01',
      daily_loss_pct: '0.02',
      weekly_loss_pct: '0.05',
      max_open_positions: 3,
      max_drawdown_pct: '0.10',
    },
  },
};

export const StandardCaps: Story = {
  args: {
    caps: {
      per_trade_pct: '0.02',
      daily_loss_pct: '0.05',
      weekly_loss_pct: '0.10',
      max_open_positions: 5,
      max_drawdown_pct: '0.20',
    },
  },
};

export const AggressiveCaps: Story = {
  args: {
    caps: {
      per_trade_pct: '0.05',
      daily_loss_pct: '0.10',
      weekly_loss_pct: '0.20',
      max_open_positions: 10,
      max_drawdown_pct: '0.35',
    },
  },
};
