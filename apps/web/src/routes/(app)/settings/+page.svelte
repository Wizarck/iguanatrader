<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   *
   * Slice research-frontend-settings-page replaces the loading stub
   * with the feature-flag toggle UI. R6 hindsight-integration shipped
   * the GET/PUT backend; this slice consumes it.
   */
  export const meta = {
    label: 'Settings',
    icon: 'settings',
    order: 80
  } as const;
</script>

<script lang="ts">
  import DaemonToggleModal from '$lib/components/DaemonToggleModal.svelte';
  import { isProblem } from '$lib/composables/useFetch';
  import { reconcileDaemon } from '$lib/status/client';
  import type { DaemonMode } from '$lib/status/types';
  import { daemonStatusStore } from '$lib/stores/daemon-status.svelte';

  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  let hindsightEnabled = $state(data.flags.hindsight_recall_enabled);
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let savedAt = $state<string | null>(null);

  // Daemon-section state.
  let toggleModalMode = $state<DaemonMode | null>(null);
  let reconcileBusy = $state<DaemonMode | null>(null);
  let reconcileError = $state<string | null>(null);
  let reconcileMessage = $state<string | null>(null);

  const daemons = $derived(daemonStatusStore.status?.daemons ?? []);

  async function handleReconcile(mode: DaemonMode): Promise<void> {
    reconcileBusy = mode;
    reconcileError = null;
    reconcileMessage = null;
    try {
      const result = await reconcileDaemon(mode);
      if (isProblem(result)) {
        reconcileError = result.detail ?? `Error ${result.status}: ${result.title}`;
        return;
      }
      reconcileMessage = `Reconcile ${mode} aceptado · ${result.correlation_id.slice(0, 8)}`;
      await daemonStatusStore.refresh();
    } catch (exc) {
      reconcileError = exc instanceof Error ? exc.message : String(exc);
    } finally {
      reconcileBusy = null;
    }
  }

  function formatTimestamp(ts: string | null): string {
    if (!ts) return '—';
    return new Date(ts).toLocaleString('sv-SE'); // ISO-ish, locale-agnostic
  }

  async function toggleHindsight(next: boolean) {
    const previous = hindsightEnabled;
    hindsightEnabled = next; // optimistic
    saving = true;
    saveError = null;
    try {
      const res = await fetch('/api/v1/settings/feature-flags', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify({ hindsight_recall_enabled: next })
      });
      if (!res.ok) {
        const text = await res.text();
        saveError = `Save failed (${res.status}): ${text.slice(0, 200)}`;
        hindsightEnabled = previous; // rollback
        return;
      }
      const body = (await res.json()) as { hindsight_recall_enabled: boolean };
      hindsightEnabled = body.hindsight_recall_enabled;
      savedAt = new Date().toISOString();
    } catch (err) {
      saveError = err instanceof Error ? err.message : String(err);
      hindsightEnabled = previous;
    } finally {
      saving = false;
    }
  }
</script>

<svelte:head>
  <title>Settings · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Settings</h1>

  {#if data.loadError}
    <div class="error" role="alert">
      {data.loadError}
    </div>
  {/if}

  <h2>Security</h2>
  <div class="security-row">
    <div class="security-row__copy">
      <p class="security-row__title">Password</p>
      <p class="security-row__help">
        Rotate your password. Required at first login for provisional
        credentials issued by an admin.
      </p>
    </div>
    <a class="security-row__action" href="/account/change-password">
      Change password
    </a>
  </div>

  <h2>Daemons</h2>
  <p class="daemons-help">
    Estado per-modo del trading daemon. Click en un chip del header (o
    el botón aquí) abre el modal de toggle. Reconcile dispara una
    sincronización forzada con IBKR (fills + equity snapshot).
  </p>
  {#if daemons.length === 0}
    <p class="status">Cargando estado…</p>
  {:else}
    <table class="daemons-table">
      <thead>
        <tr>
          <th>Modo</th>
          <th>Enabled</th>
          <th>IB conectado</th>
          <th>Última heartbeat</th>
          <th>Último fill</th>
          <th>Pending</th>
          <th>Acciones</th>
        </tr>
      </thead>
      <tbody>
        {#each daemons as daemon (daemon.mode)}
          <tr>
            <td class="daemons-table__mode daemons-table__mode--{daemon.mode}">
              {daemon.mode.toUpperCase()}
            </td>
            <td>{daemon.enabled ? '✓' : '—'}</td>
            <td>{daemon.ib_connected ? '✓' : '—'}</td>
            <td class="daemons-table__time">{formatTimestamp(daemon.last_heartbeat_at)}</td>
            <td class="daemons-table__time">{formatTimestamp(daemon.last_fill_at)}</td>
            <td>{daemon.pending_proposals_count}</td>
            <td class="daemons-table__actions">
              <button
                type="button"
                class="btn btn--ghost"
                onclick={() => (toggleModalMode = daemon.mode)}
              >
                Toggle
              </button>
              <button
                type="button"
                class="btn btn--ghost"
                disabled={reconcileBusy === daemon.mode}
                onclick={() => handleReconcile(daemon.mode)}
              >
                {reconcileBusy === daemon.mode ? '…' : 'Reconcile'}
              </button>
            </td>
          </tr>
        {/each}
      </tbody>
    </table>
  {/if}
  {#if reconcileError}
    <p class="error" role="alert">{reconcileError}</p>
  {/if}
  {#if reconcileMessage}
    <p class="status saved">{reconcileMessage}</p>
  {/if}

  <h2>Feature flags</h2>

  <div class="flag-row">
    <label class="flag-label">
      <input
        type="checkbox"
        checked={hindsightEnabled}
        disabled={saving}
        onchange={(e) => toggleHindsight((e.currentTarget as HTMLInputElement).checked)}
        aria-describedby="hindsight-help"
      />
      <span class="flag-name">Hindsight narrative recall</span>
    </label>
    <p id="hindsight-help" class="flag-help">
      FR81 — toggles narrative-context recall during research brief synthesis. Default
      OFF; recommended ON after ≥12 months of operation per ADR-016. Backend writes
      (FR80 retain) are always-on regardless of this toggle.
    </p>
  </div>

  {#if saving}
    <p class="status" aria-live="polite">Saving…</p>
  {/if}
  {#if saveError}
    <div class="error" role="alert">{saveError}</div>
  {/if}
  {#if savedAt && !saveError && !saving}
    <p class="status saved">Saved at {savedAt}</p>
  {/if}
</section>

{#if toggleModalMode !== null}
  <DaemonToggleModal
    mode={toggleModalMode}
    open={true}
    onClose={() => (toggleModalMode = null)}
  />
{/if}

<style>
  section {
    color: var(--ink);
    max-width: 720px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
    color: var(--ink);
  }
  .flag-row {
    border: 1px solid var(--mute);
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 12px;
    background: var(--surface);
  }
  .flag-label {
    display: flex;
    align-items: center;
    gap: 12px;
    cursor: pointer;
    font-weight: 500;
  }
  .flag-label input[type='checkbox'] {
    min-width: 20px;
    min-height: 20px;
    accent-color: var(--accent);
  }
  .flag-label input[type='checkbox']:disabled {
    opacity: 0.45;
    cursor: not-allowed;
  }
  .flag-name {
    color: var(--ink);
  }
  .flag-help {
    margin: 8px 0 0 32px;
    color: var(--mute);
    font-size: 14px;
    line-height: 1.45;
  }
  .status {
    color: var(--mute);
    margin: 8px 0 0;
    font-size: 14px;
  }
  .status.saved {
    color: var(--ok-fg, #2a7);
  }
  .error {
    color: var(--err-fg, #c00);
    background: var(--err-bg, #fee);
    padding: 0.5rem 0.75rem;
    border-radius: 4px;
    margin: 12px 0;
  }
  .security-row {
    border: 1px solid var(--mute);
    border-radius: 6px;
    padding: 16px;
    margin-bottom: 12px;
    background: var(--surface);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }
  .security-row__copy {
    flex: 1;
  }
  .security-row__title {
    margin: 0;
    font-weight: 500;
    color: var(--ink);
  }
  .security-row__help {
    margin: 4px 0 0;
    color: var(--mute);
    font-size: 14px;
    line-height: 1.45;
  }
  .security-row__action {
    padding: 8px 14px;
    background: var(--accent, oklch(72% 0.14 195));
    color: var(--accent-fg, oklch(15% 0.02 250));
    border-radius: 6px;
    font-size: 14px;
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;
  }
  .daemons-help {
    margin: 0 0 12px;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
  }
  .daemons-table {
    width: 100%;
    border-collapse: collapse;
    border: 1px solid var(--border);
    border-radius: 6px;
    overflow: hidden;
    margin-bottom: 12px;
    font-size: 13px;
  }
  .daemons-table th,
  .daemons-table td {
    padding: 8px 10px;
    text-align: left;
    border-bottom: 1px solid var(--border);
  }
  .daemons-table th {
    background: var(--surface-2);
    color: var(--mute);
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }
  .daemons-table tbody tr:last-child td {
    border-bottom: none;
  }
  .daemons-table__mode {
    font-weight: 700;
    letter-spacing: 0.04em;
  }
  .daemons-table__mode--paper {
    color: oklch(82% 0.16 95);
  }
  .daemons-table__mode--live {
    color: oklch(64% 0.2 25);
  }
  .daemons-table__time {
    color: var(--mute);
    font-variant-numeric: tabular-nums;
    font-size: 12px;
  }
  .daemons-table__actions {
    display: flex;
    gap: 6px;
  }
  .btn {
    padding: 4px 10px;
    border-radius: var(--r-2);
    border: 1px solid var(--border);
    font-size: 12px;
    cursor: pointer;
    background: transparent;
    color: var(--ink);
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn--ghost {
    background: transparent;
  }
  .btn--ghost:hover:not(:disabled) {
    background: var(--surface-2);
  }
</style>
