// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import TextInput from './TextInput.svelte';

const meta: Meta = {
  title: 'Forms/TextInput',
  component: TextInput,
  tags: ['autodocs'],
  argTypes: {
    name: { control: 'text' },
    label: { control: 'text' },
    value: { control: 'text' },
    error: { control: 'text' },
    helpText: { control: 'text' },
    disabled: { control: 'boolean' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

export const Default: Story = {
  args: {
    name: 'symbol',
    label: 'Symbol',
    value: '',
    placeholder: 'SPY',
    helpText: 'Uppercase letters A-Z and digits 0-9, maximum 16 characters.',
  },
};

export const WithError: Story = {
  args: {
    name: 'symbol',
    label: 'Symbol',
    value: 'spy lower!',
    error: 'Invalid symbol: use A-Z and 0-9, maximum 16 characters.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'symbol',
    label: 'Symbol',
    value: 'SPY',
    disabled: true,
    helpText: 'Not editable in edit mode.',
  },
};
