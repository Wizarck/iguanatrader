// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import Textarea from './Textarea.svelte';

const meta: Meta = {
  title: 'Forms/Textarea',
  component: Textarea,
  tags: ['autodocs'],
  argTypes: {
    name: { control: 'text' },
    label: { control: 'text' },
    value: { control: 'text' },
    rows: { control: 'number' },
    monospace: { control: 'boolean' },
    error: { control: 'text' },
    disabled: { control: 'boolean' },
  },
};

export default meta;
type Story = StoryObj<typeof meta>;

const SAMPLE_PARAMS = JSON.stringify({ lookback: 20, atr_mult: 2.0 }, null, 2);

export const Default: Story = {
  args: {
    name: 'params',
    label: 'Params (JSON)',
    value: SAMPLE_PARAMS,
    rows: 8,
    monospace: true,
    helpText: 'Objeto JSON con los parámetros del kind.',
  },
};

export const WithError: Story = {
  args: {
    name: 'params',
    label: 'Params (JSON)',
    value: '{not-json',
    rows: 8,
    monospace: true,
    error: 'JSON inválido: Unexpected token n in JSON at position 1.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'params',
    label: 'Params (JSON)',
    value: SAMPLE_PARAMS,
    rows: 8,
    monospace: true,
    disabled: true,
  },
};
