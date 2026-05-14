// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import SymbolSearchCard from './SymbolSearchCard.svelte';

const meta: Meta = {
  title: 'Research/SymbolSearchCard',
  component: SymbolSearchCard,
  tags: ['autodocs'],
  argTypes: {
    initialValue: { control: 'text' },
    onSubmit: { action: 'submit' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    initialValue: ''
  }
};

export const Prefilled: Story = {
  args: {
    initialValue: 'SPY'
  }
};

export const InvalidPrefill: Story = {
  args: {
    initialValue: 'lower-case-bad'
  }
};
