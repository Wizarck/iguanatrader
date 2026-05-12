// See MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import BriefHeader from './BriefHeader.svelte';

const meta: Meta = {
  title: 'Research/BriefHeader',
  component: BriefHeader,
  tags: ['autodocs'],
  argTypes: {
    symbol: { control: 'text' },
    methodology: {
      control: 'select',
      options: ['three_pillar', 'canslim', 'magic_formula', 'qarp', 'multi_factor']
    },
    version: { control: 'number' },
    synthesizedAt: { control: 'text' },
    refreshing: { control: 'boolean' },
    refreshError: { control: 'text' },
    refreshDisabled: { control: 'boolean' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

const NOOP = async () => undefined;

export const Default: Story = {
  args: {
    symbol: 'AAPL',
    methodology: 'three_pillar',
    version: 3,
    synthesizedAt: '2026-05-11T08:00:00Z',
    refreshing: false,
    refreshError: null,
    onRefresh: NOOP,
    refreshDisabled: false
  }
};

export const Refreshing: Story = {
  args: {
    symbol: 'AAPL',
    methodology: 'three_pillar',
    version: 3,
    synthesizedAt: '2026-05-11T08:00:00Z',
    refreshing: true,
    refreshError: null,
    onRefresh: NOOP,
    refreshDisabled: false
  }
};

export const RefreshError: Story = {
  args: {
    symbol: 'AAPL',
    methodology: 'three_pillar',
    version: 3,
    synthesizedAt: '2026-05-11T08:00:00Z',
    refreshing: false,
    refreshError: 'Refresh failed (503): EDGAR ingest temporarily unavailable',
    onRefresh: NOOP,
    refreshDisabled: false
  }
};

export const ReadOnly: Story = {
  args: {
    symbol: 'AAPL',
    methodology: 'qarp',
    version: 1,
    synthesizedAt: '2026-04-30T08:00:00Z',
    refreshing: false,
    refreshError: null,
    onRefresh: NOOP,
    refreshDisabled: true
  }
};
