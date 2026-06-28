// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import Checkbox from './Checkbox.svelte';

const meta: Meta = {
  title: 'Forms/Checkbox',
  component: Checkbox,
  tags: ['autodocs'],
  argTypes: {
    name: { control: 'text' },
    label: { control: 'text' },
    checked: { control: 'boolean' },
    error: { control: 'text' },
    disabled: { control: 'boolean' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    name: 'enabled',
    label: 'Enabled (generates signals)',
    checked: true,
    helpText: 'If unchecked, the strategy is saved but will not propose trades.',
  },
};

export const WithError: Story = {
  args: {
    name: 'enabled',
    label: 'Enabled (generates signals)',
    checked: false,
    error: 'You must enable the strategy before saving.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'enabled',
    label: 'Enabled (generates signals)',
    checked: true,
    disabled: true,
  },
};
