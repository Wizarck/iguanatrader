// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import DataTable from './DataTable.svelte';

type TradeRow = {
  id: string;
  symbol: string;
  side: string;
  quantity: string;
  mode: string;
  state: string;
  opened_at: string;
};

const meta: Meta = {
  title: 'Common/DataTable',
  component: DataTable,
  tags: ['autodocs']
};

export default meta;
type Story = StoryObj<typeof meta>;

const TRADE_ROWS: TradeRow[] = [
  {
    id: '00000000-0000-0000-0000-000000000001',
    symbol: 'AAPL',
    side: 'buy',
    quantity: '10',
    mode: 'paper',
    state: 'open',
    opened_at: '2026-05-01T10:00:00Z'
  },
  {
    id: '00000000-0000-0000-0000-000000000002',
    symbol: 'MSFT',
    side: 'sell',
    quantity: '5',
    mode: 'paper',
    state: 'closed',
    opened_at: '2026-05-01T09:00:00Z'
  },
  {
    id: '00000000-0000-0000-0000-000000000003',
    symbol: 'SPY',
    side: 'buy',
    quantity: '100',
    mode: 'live',
    state: 'open',
    opened_at: '2026-05-02T08:00:00Z'
  }
];

const TRADE_COLUMNS = [
  { key: 'symbol', header: 'Symbol' },
  { key: 'side', header: 'Side' },
  { key: 'quantity', header: 'Qty' },
  { key: 'mode', header: 'Mode' },
  { key: 'state', header: 'State' },
  { key: 'opened_at', header: 'Opened' }
];

export const WithRows: Story = {
  args: {
    rows: TRADE_ROWS,
    columns: TRADE_COLUMNS,
    rowKey: (r: TradeRow) => r.id
  }
};

export const Clickable: Story = {
  args: {
    rows: TRADE_ROWS,
    columns: TRADE_COLUMNS,
    rowKey: (r: TradeRow) => r.id,
    onRowClick: (r: TradeRow) => console.log('row click', r.id)
  }
};

export const Empty: Story = {
  args: {
    rows: [],
    columns: TRADE_COLUMNS,
    rowKey: (r: TradeRow) => r.id,
    caption: 'No rows to display.'
  }
};
