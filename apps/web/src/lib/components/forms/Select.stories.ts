// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import Select from './Select.svelte';

const meta: Meta = {
  title: 'Forms/Select',
  component: Select,
  tags: ['autodocs'],
  argTypes: {
    name: { control: 'text' },
    label: { control: 'text' },
    value: { control: 'text' },
    error: { control: 'text' },
    disabled: { control: 'boolean' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

const KIND_OPTIONS = [
  { value: 'donchian_atr', label: 'donchian_atr' },
  { value: 'sma_cross', label: 'sma_cross' },
];

export const Default: Story = {
  args: {
    name: 'strategy_kind',
    label: 'Strategy kind',
    value: 'donchian_atr',
    options: KIND_OPTIONS,
    helpText: 'Selecciona el tipo de estrategia.',
  },
};

export const WithError: Story = {
  args: {
    name: 'strategy_kind',
    label: 'Strategy kind',
    value: 'donchian_atr',
    options: KIND_OPTIONS,
    error: 'Strategy kind inválido. Permitidos: donchian_atr, sma_cross.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'strategy_kind',
    label: 'Strategy kind',
    value: 'donchian_atr',
    options: KIND_OPTIONS,
    disabled: true,
  },
};
