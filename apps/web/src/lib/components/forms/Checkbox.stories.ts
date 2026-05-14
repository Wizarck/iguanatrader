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
    label: 'Enabled (genera señales)',
    checked: true,
    helpText: 'Si está desmarcado, la estrategia se guarda pero no propondrá trades.',
  },
};

export const WithError: Story = {
  args: {
    name: 'enabled',
    label: 'Enabled (genera señales)',
    checked: false,
    error: 'Debes habilitar la estrategia antes de guardar.',
  },
};

export const Disabled: Story = {
  args: {
    name: 'enabled',
    label: 'Enabled (genera señales)',
    checked: true,
    disabled: true,
  },
};
