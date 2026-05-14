// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import RiskUtilisationCard from './RiskUtilisationCard.svelte';

const STANDARD_CAPS = {
  per_trade_pct: '0.02',
  daily_loss_pct: '0.05',
  weekly_loss_pct: '0.10',
  max_open_positions: 5,
  max_drawdown_pct: '0.20',
};

const meta: Meta = {
  title: 'Risk/RiskUtilisationCard',
  component: RiskUtilisationCard,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle: Story = {
  args: {
    caps: STANDARD_CAPS,
    utilisation: {
      daily_loss: '0.005',
      weekly_loss: '0.012',
      max_drawdown: '0.03',
    },
  },
};

export const ApproachingCap: Story = {
  args: {
    caps: STANDARD_CAPS,
    utilisation: {
      daily_loss: '0.032',
      weekly_loss: '0.068',
      max_drawdown: '0.13',
    },
  },
};

export const KillSwitchTriggered: Story = {
  args: {
    caps: STANDARD_CAPS,
    utilisation: {
      daily_loss: '0.05',
      weekly_loss: '0.092',
      max_drawdown: '0.19',
    },
  },
};
