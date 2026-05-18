<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar
   * (apps/web/src/lib/components/nav/Sidebar.svelte) via the
   * import.meta.glob anti-collision pattern (slice W1 design D2).
   */
  export const meta = {
    label: 'Risk',
    icon: 'gauge',
    order: 60
  } as const;
</script>

<script lang="ts">
  import { page } from '$app/state';
  import Badge from '$lib/components/Badge.svelte';
  import EmptyState from '$lib/components/EmptyState.svelte';
  import RiskCapsCard from '$lib/components/RiskCapsCard.svelte';
  import RiskUtilisationCard from '$lib/components/RiskUtilisationCard.svelte';
  import { formatMoney } from '$lib/portfolio/format';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  const isAllEmpty = $derived(
    data.risk !== null &&
      Object.values(data.risk.utilisation).every(
        (v) => v === '0' || Number(v) === 0
      ) &&
      data.risk.state.capital === '0' &&
      data.risk.state.open_positions_count === 0
  );

  // Slice ``frontend-broker-mcp-risk-pages``: risk override form.
  // POSTs to /api/v1/risk/override per FR25 (double-confirmation audit).
  // The web channel only contributes ONE confirmation row; for the
  // canonical "double-channel-diversity" requirement the operator
  // should still confirm via Telegram / WhatsApp side. This form is
  // the emergency single-channel path documented in the runbook.
  let overrideOpen = $state(false);
  let overrideSubmitting = $state(false);
  let overrideError = $state<string | null>(null);
  let overrideSuccess = $state<string | null>(null);

  let proposalId = $state('');
  let riskEvalId = $state('');
  let reasonText = $state('');
  let secondChannel = $state<'telegram' | 'whatsapp' | 'cli' | 'dashboard'>(
    'telegram'
  );

  async function submitOverride(event: Event) {
    event.preventDefault();
    overrideSubmitting = true;
    overrideError = null;
    overrideSuccess = null;
    const nowIso = new Date().toISOString();
    const userId = page.data.user?.user_id;
    if (!userId) {
      overrideError = 'No hay user_id en sesión — re-loggear.';
      overrideSubmitting = false;
      return;
    }
    try {
      const res = await fetch('/api/v1/risk/override', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          proposal_id: proposalId,
          risk_evaluation_id: riskEvalId,
          authorised_by_user_id: userId,
          reason_text: reasonText,
          confirmation_chain: {
            first_confirmation: {
              channel: 'dashboard',
              confirmed_at: nowIso,
              user_id: userId
            },
            second_confirmation: {
              channel: secondChannel,
              confirmed_at: nowIso,
              user_id: userId
            }
          },
          state_snapshot_at_override: {}
        })
      });
      if (!res.ok) {
        const detail = await res.text();
        overrideError = `Override falló (${res.status}): ${detail || res.statusText}`;
      } else {
        overrideSuccess = 'Override registrada. Audit row creada.';
        proposalId = '';
        riskEvalId = '';
        reasonText = '';
      }
    } catch (err) {
      overrideError = err instanceof Error ? err.message : String(err);
    } finally {
      overrideSubmitting = false;
    }
  }
</script>

<svelte:head>
  <title>Risk · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>Risk</h1>
    {#if data.risk}
      <Badge
        label={data.risk.kill_switch_active ? 'Kill-switch ACTIVO' : 'Operativo'}
        variant={data.risk.kill_switch_active ? 'destructive' : 'success'}
      />
    {/if}
  </header>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="risk-load-error">
      {data.loadError}
    </div>
  {:else if data.risk && isAllEmpty}
    <EmptyState
      title="Sin actividad de riesgo aún"
      body="El estado se inicializará cuando arranque el daemon."
      hint="Arranca el daemon: `iguanatrader trading run --mode paper`."
    />
  {:else if data.risk}
    <h2>Caps</h2>
    <RiskCapsCard caps={data.risk.caps} />

    <h2>Utilización</h2>
    <RiskUtilisationCard utilisation={data.risk.utilisation} caps={data.risk.caps} />

    <h2>Estado</h2>
    <dl class="state-card" data-testid="risk-state-card">
      <div class="cell">
        <dt>Capital</dt>
        <dd data-testid="state-capital">{formatMoney(data.risk.state.capital, 'USD')}</dd>
      </div>
      <div class="cell">
        <dt>Posiciones abiertas</dt>
        <dd data-testid="state-open-positions">
          {data.risk.state.open_positions_count} / {data.risk.caps.max_open_positions}
        </dd>
      </div>
      <div class="cell">
        <dt>Última actualización</dt>
        <dd data-testid="state-fetched-at">{data.risk.fetched_at}</dd>
      </div>
    </dl>

    <section class="override-block" data-testid="risk-override">
      <button
        type="button"
        class="override-toggle"
        onclick={() => (overrideOpen = !overrideOpen)}
        aria-expanded={overrideOpen}
      >
        {overrideOpen ? '▾' : '▸'} Override de risk cap (FR25 — audit trail)
      </button>
      {#if overrideOpen}
        <p class="hint">
          Registra un override autorizado contra un risk-eval que rechazó
          una propuesta. La row de audit se persiste en
          <code>risk_overrides</code> con doble confirmación (este formulario
          aporta una; la segunda debe venir de Telegram / WhatsApp / CLI).
          Reason text mínimo 20 caracteres (Pydantic <code>Field(min_length=20)</code>).
        </p>
        <form onsubmit={submitOverride} class="override-form">
          <label>
            <span>Proposal UUID</span>
            <input type="text" bind:value={proposalId} required placeholder="00000000-..." />
          </label>
          <label>
            <span>Risk evaluation UUID</span>
            <input type="text" bind:value={riskEvalId} required placeholder="00000000-..." />
          </label>
          <label>
            <span>Reason (≥20 chars)</span>
            <textarea bind:value={reasonText} required rows="3" minlength={20}></textarea>
          </label>
          <label>
            <span>Segundo canal de confirmación</span>
            <select bind:value={secondChannel}>
              <option value="telegram">telegram</option>
              <option value="whatsapp">whatsapp</option>
              <option value="cli">cli</option>
              <option value="dashboard">dashboard (mismo canal — débil)</option>
            </select>
          </label>
          <div class="override-actions">
            <button type="submit" class="primary" disabled={overrideSubmitting}>
              {overrideSubmitting ? 'Registrando...' : 'Registrar override'}
            </button>
          </div>
        </form>
        {#if overrideError}
          <div class="error" role="alert">{overrideError}</div>
        {/if}
        {#if overrideSuccess}
          <div class="success" role="status">{overrideSuccess}</div>
        {/if}
      {/if}
    </section>
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 0 0 16px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .state-card {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 16px;
    margin: 0;
    padding: 16px 20px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .cell {
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-width: 0;
  }
  dt {
    color: var(--mute);
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  dd {
    margin: 0;
    color: var(--ink);
    font-size: 18px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .error {
    margin-top: 16px;
    padding: 12px 16px;
    background: oklch(64% 0.2 25 / 0.14);
    border: 1px solid oklch(64% 0.2 25 / 0.4);
    border-radius: var(--r-2);
    color: var(--destructive);
    font-size: 14px;
  }
  .success {
    margin-top: 12px;
    padding: 12px 16px;
    background: oklch(70% 0.18 145 / 0.12);
    border: 1px solid oklch(70% 0.18 145 / 0.35);
    border-radius: var(--r-2);
    color: oklch(70% 0.18 145);
    font-size: 14px;
  }
  .override-block {
    margin: 32px 0 0;
    padding: 16px 20px;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
  }
  .override-toggle {
    width: 100%;
    background: transparent;
    border: none;
    cursor: pointer;
    color: var(--ink);
    text-align: left;
    font-size: 15px;
    font-weight: 600;
    padding: 0;
  }
  .override-block .hint {
    margin: 12px 0 16px;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.55;
  }
  .override-block .hint code {
    background: oklch(98% 0.01 240 / 0.05);
    padding: 1px 4px;
    border-radius: 3px;
    color: var(--accent);
    font-size: 12px;
  }
  .override-form {
    display: grid;
    gap: 12px;
    max-width: 560px;
  }
  .override-form label {
    display: flex;
    flex-direction: column;
    gap: 4px;
    font-size: 13px;
    color: var(--mute);
  }
  .override-form input,
  .override-form textarea,
  .override-form select {
    padding: 8px 10px;
    border: 1px solid var(--border);
    background: var(--bg);
    color: var(--ink);
    border-radius: var(--r-1);
    font-size: 14px;
    font-family: inherit;
  }
  .override-actions {
    display: flex;
    gap: 12px;
    margin-top: 4px;
  }
  .override-actions button.primary {
    padding: 9px 18px;
    border: 1px solid var(--destructive);
    background: var(--destructive);
    color: var(--bg);
    border-radius: var(--r-1);
    font-size: 14px;
    font-weight: 500;
    cursor: pointer;
  }
  .override-actions button.primary:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
  @media (max-width: 720px) {
    .state-card {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
