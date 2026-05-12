// See MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import CitationLink from './CitationLink.svelte';

const meta: Meta = {
  title: 'Research/CitationLink',
  component: CitationLink,
  tags: ['autodocs'],
  argTypes: {
    factId: { control: 'text' },
    sourceLabel: { control: 'text' },
    sourceUrl: { control: 'text' },
    retrievedAt: { control: 'text' },
    method: {
      control: 'select',
      options: [null, 'api', 'scrape', 'manual', 'llm']
    }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const ResolvedWithUrl: Story = {
  args: {
    factId: '00000000-0000-0000-0000-00000000000a',
    sourceLabel: 'EDGAR 10-Q FY26 Q1',
    sourceUrl: 'https://www.sec.gov/edgar',
    retrievedAt: '2026-05-01T00:00:00Z',
    method: 'api'
  }
};

export const ScrapedSource: Story = {
  args: {
    factId: '00000000-0000-0000-0000-00000000000b',
    sourceLabel: 'Press release · Apple Newsroom',
    sourceUrl: 'https://www.apple.com/newsroom',
    retrievedAt: '2026-04-15T10:30:00Z',
    method: 'scrape'
  }
};

export const ManualEntry: Story = {
  args: {
    factId: '00000000-0000-0000-0000-00000000000c',
    sourceLabel: 'Manual analyst note',
    sourceUrl: null,
    retrievedAt: '2026-05-10T14:00:00Z',
    method: 'manual'
  }
};

export const LlmInferred: Story = {
  args: {
    factId: '00000000-0000-0000-0000-00000000000d',
    sourceLabel: 'LLM thesis synthesis',
    sourceUrl: null,
    retrievedAt: '2026-05-11T09:15:00Z',
    method: 'llm'
  }
};

export const BrokenCitation: Story = {
  args: {
    factId: 'ffffffff-ffff-ffff-ffff-ffffffffffff',
    sourceLabel: null,
    sourceUrl: null,
    retrievedAt: null,
    method: null
  }
};
