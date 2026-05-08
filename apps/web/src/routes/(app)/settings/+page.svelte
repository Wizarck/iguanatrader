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
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  let hindsightEnabled = $state(data.flags.hindsight_recall_enabled);
  let saving = $state(false);
  let saveError = $state<string | null>(null);
  let savedAt = $state<string | null>(null);

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
</style>
