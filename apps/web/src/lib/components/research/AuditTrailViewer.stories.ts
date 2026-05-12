// See MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import AuditTrailViewer, {
  type AuditTrailEntry,
  type AuditTrailViewerFactRow
} from './AuditTrailViewer.svelte';

const meta: Meta = {
  title: 'Research/AuditTrailViewer',
  component: AuditTrailViewer,
  tags: ['autodocs'],
  argTypes: {
    deepLinkIndex: { control: 'number' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

const FACT_A = '00000000-0000-0000-0000-00000000f001';
const FACT_B = '00000000-0000-0000-0000-00000000f002';

const SAMPLE_ENTRIES: AuditTrailEntry[] = [
  {
    formula: 'pe_ratio = price / earnings',
    inputs: [
      { fact_id: FACT_A, value: '180.0' },
      { fact_id: FACT_B, value: '6.0' }
    ],
    intermediate_steps: ['180.0 / 6.0 = 30.0'],
    final_output: 30.0
  },
  {
    formula: 'revenue_growth = (revenue_current - revenue_prior) / revenue_prior',
    inputs: [
      { fact_id: '00000000-0000-0000-0000-00000000f003', value: '95.4' },
      { fact_id: '00000000-0000-0000-0000-00000000f004', value: '88.1' }
    ],
    intermediate_steps: ['(95.4 - 88.1) / 88.1 = 0.0829'],
    final_output: '8.29%'
  },
  {
    formula: 'pillar_score = weighted_avg([fundamentals, momentum, sentiment])',
    inputs: [
      { weight: 0.5, value: 0.82 },
      { weight: 0.3, value: 0.71 },
      { weight: 0.2, value: 0.65 }
    ],
    intermediate_steps: ['0.5 * 0.82 + 0.3 * 0.71 + 0.2 * 0.65 = 0.753'],
    final_output: 'Buy'
  }
];

const SAMPLE_FACT_BY_ID = new Map<string, AuditTrailViewerFactRow>([
  [FACT_A, { id: FACT_A, source_id: 'EDGAR 10-Q FY26 Q1', fact_kind: 'price' }],
  [FACT_B, { id: FACT_B, source_id: 'EDGAR 10-Q FY26 Q1', fact_kind: 'earnings' }]
]);

export const ThreeEntries: Story = {
  args: {
    entries: SAMPLE_ENTRIES,
    factById: SAMPLE_FACT_BY_ID,
    deepLinkIndex: null
  }
};

export const Empty: Story = {
  args: {
    entries: [],
    factById: null,
    deepLinkIndex: null
  }
};

export const DeepLinkSecondEntry: Story = {
  args: {
    entries: SAMPLE_ENTRIES,
    factById: SAMPLE_FACT_BY_ID,
    deepLinkIndex: 1
  }
};

export const NoFactLookup: Story = {
  args: {
    entries: SAMPLE_ENTRIES,
    factById: null,
    deepLinkIndex: null
  }
};
