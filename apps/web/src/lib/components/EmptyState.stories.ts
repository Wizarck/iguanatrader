// See research/MethodologyBadge.stories.ts for the rationale on untyped `Meta`.
import type { Meta, StoryObj } from '@storybook/sveltekit';

import EmptyState from './EmptyState.svelte';

const meta: Meta = {
  title: 'Common/EmptyState',
  component: EmptyState,
  tags: ['autodocs'],
  argTypes: {
    title: { control: 'text' },
    body: { control: 'text' },
    hint: { control: 'text' }
  }
};

export default meta;
type Story = StoryObj<typeof meta>;

export const NoTrades: Story = {
  args: {
    title: 'No trades aún',
    body: 'Arranca el daemon para empezar a generar trades: `iguanatrader trading run --mode paper`.',
    hint: 'Consulta docs/mvp-deploy.md para el detalle del flujo de despliegue.'
  }
};

export const TitleAndBodyOnly: Story = {
  args: {
    title: 'Sin estrategias configuradas',
    body: 'Aún no has configurado ninguna estrategia para este tenant.'
  }
};

export const LongBody: Story = {
  args: {
    title: 'Sin snapshots de equity',
    body: 'El cron de snapshots se ejecuta cada minuto pero requiere que el daemon esté corriendo. Si esperaste más de 90 segundos y sigue vacío, revisa los logs del daemon.',
    hint: 'docs/runbook.md#equity-snapshots tiene el detalle de troubleshooting.'
  }
};
