// See MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import FactTimeline, { type FactTimelineRow } from './FactTimeline.svelte';

const meta: Meta = {
  title: 'Research/FactTimeline',
  component: FactTimeline,
  tags: ['autodocs'],
  argTypes: {
    maxItems: { control: 'number' },
    highlightFactId: { control: 'text' },
    asOf: { control: 'text' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

const SAMPLE_FACTS: FactTimelineRow[] = [
  {
    id: '00000000-0000-0000-0000-00000000f001',
    source_id: 'EDGAR 10-Q FY26 Q1',
    source_url: 'https://www.sec.gov/edgar',
    retrieval_method: 'api',
    retrieved_at: '2026-05-01T00:00:00Z',
    fact_kind: 'revenue',
    value_numeric: '95.4',
    value_text: null,
    effective_from: '2026-05-01T00:00:00Z'
  },
  {
    id: '00000000-0000-0000-0000-00000000f002',
    source_id: 'EDGAR 10-Q FY26 Q1',
    source_url: 'https://www.sec.gov/edgar',
    retrieval_method: 'api',
    retrieved_at: '2026-05-01T00:00:00Z',
    fact_kind: 'earnings',
    value_numeric: '24.1',
    value_text: null,
    effective_from: '2026-05-01T00:00:00Z'
  },
  {
    id: '00000000-0000-0000-0000-00000000f003',
    source_id: 'Apple Newsroom · 2026-04-15',
    source_url: 'https://www.apple.com/newsroom',
    retrieval_method: 'scrape',
    retrieved_at: '2026-04-15T10:30:00Z',
    fact_kind: 'product_launch',
    value_numeric: null,
    value_text: 'iPhone 17 Pro',
    effective_from: '2026-04-15T10:30:00Z'
  },
  {
    id: '00000000-0000-0000-0000-00000000f004',
    source_id: 'Manual analyst note',
    source_url: null,
    retrieval_method: 'manual',
    retrieved_at: '2026-04-10T14:00:00Z',
    fact_kind: 'analyst_note',
    value_numeric: null,
    value_text: 'Margin guidance unchanged',
    effective_from: '2026-04-10T14:00:00Z'
  }
];

export const FourFacts: Story = {
  args: { facts: SAMPLE_FACTS }
};

export const Empty: Story = {
  args: { facts: [] }
};

export const AsOfMode: Story = {
  args: {
    facts: SAMPLE_FACTS.slice(0, 2),
    asOf: '2026-05-01T00:00:00Z'
  }
};

export const Highlighted: Story = {
  args: {
    facts: SAMPLE_FACTS,
    highlightFactId: '00000000-0000-0000-0000-00000000f002'
  }
};

export const TruncatedByMaxItems: Story = {
  args: {
    facts: SAMPLE_FACTS,
    maxItems: 2
  }
};
