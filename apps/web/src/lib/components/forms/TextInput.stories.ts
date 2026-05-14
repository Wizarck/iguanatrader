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
    helpText: 'Letras mayúsculas A-Z y dígitos 0-9, máximo 16 caracteres.',
  },
};

export const WithError: Story = {
  args: {
    name: 'symbol',
    label: 'Symbol',
    value: 'spy lower!',
    error: 'Symbol inválido: usa A-Z y 0-9, máximo 16 caracteres.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'symbol',
    label: 'Symbol',
    value: 'SPY',
    disabled: true,
    helpText: 'No editable en modo edición.',
  },
};
