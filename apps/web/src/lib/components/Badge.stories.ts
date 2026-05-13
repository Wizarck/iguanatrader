// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import Badge from './Badge.svelte';

const meta: Meta = {
  title: 'Common/Badge',
  component: Badge,
  tags: ['autodocs'],
  argTypes: {
    label: { control: 'text' },
    variant: {
      control: 'inline-radio',
      options: ['success', 'destructive', 'accent', 'mute']
    }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Success: Story = {
  args: { label: 'buy', variant: 'success' }
};

export const Destructive: Story = {
  args: { label: 'sell', variant: 'destructive' }
};

export const Accent: Story = {
  args: { label: 'open', variant: 'accent' }
};

export const Mute: Story = {
  args: { label: 'closed', variant: 'mute' }
};
