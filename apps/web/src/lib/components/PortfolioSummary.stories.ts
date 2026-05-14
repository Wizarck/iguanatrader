// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import PortfolioSummary from './PortfolioSummary.svelte';

const meta: Meta = {
  title: 'Portfolio/PortfolioSummary',
  component: PortfolioSummary,
  tags: ['autodocs'],
  argTypes: {
    totalValue: { control: 'text' },
    dayPnlAbs: { control: 'text' },
    dayPnlPct: { control: 'text' },
    cash: { control: 'text' },
    positionCount: { control: 'number' },
    currency: { control: 'text' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Loaded: Story = {
  args: {
    totalValue: '100237.45',
    dayPnlAbs: '237.45',
    dayPnlPct: '0.00237',
    cash: '50000.00',
    positionCount: 3,
    currency: 'USD',
  },
};

export const NegativeDay: Story = {
  args: {
    totalValue: '99750.25',
    dayPnlAbs: '-249.75',
    dayPnlPct: '-0.00250',
    cash: '50000.00',
    positionCount: 2,
    currency: 'USD',
  },
};

export const NullDayPnl: Story = {
  args: {
    totalValue: '100000.00',
    dayPnlAbs: null,
    dayPnlPct: null,
    cash: '100000.00',
    positionCount: 0,
    currency: 'USD',
  },
};
