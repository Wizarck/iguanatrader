// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import EmptyState from './EmptyState.svelte';

const meta: Meta = {
  title: 'Common/EmptyState',
  component: EmptyState,
  tags: ['autodocs'],
  argTypes: {
    title: { control: 'text' },
    body: { control: 'text' },
    hint: { control: 'text' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const NoTrades: Story = {
  args: {
    title: 'No trades yet',
    body: 'Start the daemon to begin generating trades: `iguanatrader trading run --mode paper`.',
    hint: 'See docs/mvp-deploy.md for the deployment flow.'
  }
};

export const TitleAndBodyOnly: Story = {
  args: {
    title: 'No strategies configured',
    body: 'You have not configured any strategy for this tenant yet.'
  }
};

export const LongBody: Story = {
  args: {
    title: 'No equity snapshots',
    body: 'The snapshots cron runs every minute but requires the daemon to be running. If you waited more than 90 seconds and it is still empty, check the daemon logs.',
    hint: 'docs/runbook.md#equity-snapshots has the troubleshooting detail.'
  }
};
