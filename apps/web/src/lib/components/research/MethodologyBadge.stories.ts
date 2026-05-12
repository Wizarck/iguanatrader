// Storybook 10 + Svelte 5: the `Meta<Component>` generic still references
// Svelte 4 component shape (`$on`/`$set`); using untyped `Meta` keeps
// stories working without `@ts-expect-error` clutter. Story args are
// validated at runtime via Storybook's Controls panel.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import MethodologyBadge from './MethodologyBadge.svelte';

const meta: Meta = {
  title: 'Research/MethodologyBadge',
  component: MethodologyBadge,
  tags: ['autodocs'],
  argTypes: {
    methodology: {
      control: 'select',
      options: ['three_pillar', 'canslim', 'magic_formula', 'qarp', 'multi_factor', 'unknown']
    },
    size: { control: 'inline-radio', options: ['sm', 'md'] },
    showLabel: { control: 'boolean' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const ThreePillar: Story = {
  args: { methodology: 'three_pillar', size: 'md', showLabel: true }
};

export const Canslim: Story = {
  args: { methodology: 'canslim', size: 'md', showLabel: true }
};

export const MagicFormula: Story = {
  args: { methodology: 'magic_formula', size: 'md', showLabel: true }
};

export const Qarp: Story = {
  args: { methodology: 'qarp', size: 'md', showLabel: true }
};

export const MultiFactor: Story = {
  args: { methodology: 'multi_factor', size: 'md', showLabel: true }
};

export const Unknown: Story = {
  args: { methodology: 'unknown', size: 'md', showLabel: true }
};

export const Small: Story = {
  args: { methodology: 'three_pillar', size: 'sm', showLabel: true }
};

export const IconOnly: Story = {
  args: { methodology: 'three_pillar', size: 'md', showLabel: false }
};
