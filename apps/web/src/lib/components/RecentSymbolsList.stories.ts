// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import RecentSymbolsList from './RecentSymbolsList.svelte';

/**
 * Storybook uses a real browser, so we seed `localStorage` per story
 * via a unique `storageKey` and a `beforeEach` hook. Each story gets
 * its own key to keep them deterministic.
 */
const meta: Meta = {
  title: 'Research/RecentSymbolsList',
  component: RecentSymbolsList,
  tags: ['autodocs'],
  argTypes: {
    storageKey: { control: 'text' },
    max: { control: 'number' },
    label: { control: 'text' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

const EMPTY_KEY = 'sb.research.recent.empty';
const SEEDED_KEY = 'sb.research.recent.seeded';
const FULL_KEY = 'sb.research.recent.full';

export const Empty: Story = {
  beforeEach: () => {
    if (typeof window !== 'undefined') {
      window.localStorage.removeItem(EMPTY_KEY);
    }
  },
  args: {
    storageKey: EMPTY_KEY
  }
};

export const WithThreeSymbols: Story = {
  beforeEach: () => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(SEEDED_KEY, JSON.stringify(['SPY', 'QQQ', 'TSLA']));
    }
  },
  args: {
    storageKey: SEEDED_KEY
  }
};

export const FullCapped: Story = {
  beforeEach: () => {
    if (typeof window !== 'undefined') {
      window.localStorage.setItem(
        FULL_KEY,
        JSON.stringify(['SPY', 'QQQ', 'TSLA', 'NVDA', 'AAPL', 'MSFT', 'GOOG', 'META'])
      );
    }
  },
  args: {
    storageKey: FULL_KEY
  }
};
