// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import type { ApprovalRequest } from '$lib/approvals/types';

import ApprovalCard from './ApprovalCard.svelte';

const meta: Meta = {
  title: 'Approvals/ApprovalCard',
  component: ApprovalCard,
  tags: ['autodocs'],
};

export default meta;
type Story = StoryObj<typeof meta>;

// Frozen reference time for deterministic storybook rendering. Matches
// `apps/web/tests/countdown.test.ts` so the visual matches test fixtures.
const NOW = new Date('2026-05-14T12:00:00Z');

const BASE_APPROVAL: ApprovalRequest = {
  id: '11111111-1111-1111-1111-111111111111',
  tenant_id: '00000000-0000-0000-0000-0000000000aa',
  proposal_id: '22222222-2222-2222-2222-222222222222',
  delivered_to_channels: ['telegram', 'whatsapp'],
  timeout_seconds: 300,
  expires_at: '2026-05-14T12:05:00Z', // +5m from NOW
  created_at: '2026-05-14T12:00:00Z',
  delivery_failures: null,
};

export const PendingFresh: Story = {
  args: {
    approval: BASE_APPROVAL,
    initialNow: NOW,
  },
};

export const ExpiringSoon: Story = {
  args: {
    approval: {
      ...BASE_APPROVAL,
      id: '22222222-2222-2222-2222-222222222222',
      expires_at: '2026-05-14T12:00:30Z', // +30s
      timeout_seconds: 30,
    },
    initialNow: NOW,
  },
};

export const WithDeliveryFailures: Story = {
  args: {
    approval: {
      ...BASE_APPROVAL,
      id: '33333333-3333-3333-3333-333333333333',
      delivered_to_channels: ['dashboard'],
      delivery_failures: [
        { channel: 'telegram', error: 'timeout' },
        { channel: 'whatsapp', error: 'rate_limited' },
      ],
    },
    initialNow: NOW,
  },
};
