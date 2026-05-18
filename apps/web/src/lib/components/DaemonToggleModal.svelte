<script lang="ts">
  /**
   * DaemonToggleModal — slice ``dual-daemon-mode-toggle-and-reconcile``.
   *
   * Opens from the chip click + (later) from the /settings page buttons.
   * Two variants:
   *   - paper: simple "activate/deactivate?" + optional reason
   *   - live: warning header + REQUIRED reason (>=20 chars) + REQUIRED
   *     password re-entry; server re-verifies via Argon2id
   *
   * On submit calls toggleDaemon(). On 403 (password-mismatch) the
   * modal stays open with "contraseña incorrecta" + the password field
   * cleared. On 200 the modal closes + refreshes the store.
   */
  import { isProblem } from '$lib/composables/useFetch';
  import { toggleDaemon } from '$lib/status/client';
  import type { DaemonMode } from '$lib/status/types';
  import { daemonStatusStore } from '$lib/stores/daemon-status.svelte';

  type Props = {
    mode: DaemonMode;
    open: boolean;
    onClose: () => void;
  };

  let { mode, open, onClose }: Props = $props();

  const currentRow = $derived(daemonStatusStore.status?.daemons.find((d) => d.mode === mode));
  const currentEnabled = $derived(currentRow?.enabled ?? false);
  const targetEnabled = $derived(!currentEnabled);
  const isLive = $derived(mode === 'live');

  let reason = $state('');
  let password = $state('');
  let submitting = $state(false);
  let error = $state<string | null>(null);

  let dialog: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!dialog) return;
    if (open && !dialog.open) {
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  });

  $effect(() => {
    if (!open) {
      // Reset on close so the next opening starts clean.
      reason = '';
      password = '';
      error = null;
      submitting = false;
    }
  });

  const reasonValid = $derived(!isLive || reason.trim().length >= 20);
  const passwordValid = $derived(!isLive || password.length > 0);
  const submitDisabled = $derived(submitting || !reasonValid || !passwordValid);

  async function handleSubmit(event: Event): Promise<void> {
    event.preventDefault();
    if (submitDisabled) return;
    submitting = true;
    error = null;
    try {
      const result = await toggleDaemon(mode, {
        enabled: targetEnabled,
        reason: reason || null,
        password_reconfirm: isLive ? password : null,
      });
      if (isProblem(result)) {
        if (result.type.includes('password-mismatch')) {
          error = 'Contraseña incorrecta.';
          password = '';
        } else if (result.type.includes('live-toggle-payload-invalid')) {
          error = result.detail ?? 'Datos inválidos. Revisa el motivo y la contraseña.';
        } else {
          error = result.detail ?? `Error ${result.status}: ${result.title}`;
        }
        return;
      }
      // Success — refresh the store so the chip reflects the new state
      // before the next 5s poll, then close.
      await daemonStatusStore.refresh();
      onClose();
    } catch (exc) {
      error = exc instanceof Error ? exc.message : String(exc);
    } finally {
      submitting = false;
    }
  }
</script>

<dialog
  bind:this={dialog}
  class="modal modal--{mode}"
  onclose={onClose}
  aria-labelledby="daemon-toggle-title"
>
  <form method="dialog" onsubmit={handleSubmit}>
    <header class="modal__header">
      <h2 id="daemon-toggle-title">
        {#if isLive}
          ⚠️ {targetEnabled ? 'ACTIVAR' : 'DESACTIVAR'} LIVE TRADING (dinero real)
        {:else}
          {targetEnabled ? 'Activar' : 'Desactivar'} paper trading
        {/if}
      </h2>
      {#if isLive}
        <p class="modal__warn">
          Estás a punto de {targetEnabled ? 'permitir' : 'bloquear'} la creación de
          órdenes con dinero real. Esto requiere reconfirmación de contraseña + un
          motivo claro para el audit log.
        </p>
      {/if}
    </header>

    <label class="field">
      <span class="field__label">
        Motivo {#if isLive}<em>(mínimo 20 caracteres)</em>{/if}
      </span>
      <textarea
        class="field__input"
        rows={3}
        bind:value={reason}
        placeholder={isLive
          ? 'Ej. promoting validated donchian strategy to live after 30 days of paper'
          : 'Opcional — anotación rápida para el audit log'}
        required={isLive}
        minlength={isLive ? 20 : 0}
      ></textarea>
    </label>

    {#if isLive}
      <label class="field">
        <span class="field__label">Contraseña</span>
        <input
          class="field__input"
          type="password"
          bind:value={password}
          autocomplete="current-password"
          required
        />
      </label>
    {/if}

    {#if error}
      <p class="modal__error" role="alert">{error}</p>
    {/if}

    <footer class="modal__footer">
      <button
        type="button"
        class="btn btn--ghost"
        onclick={onClose}
        disabled={submitting}
      >
        Cancelar
      </button>
      <button type="submit" class="btn btn--{mode}" disabled={submitDisabled}>
        {#if submitting}
          Enviando…
        {:else if targetEnabled}
          Activar {mode}
        {:else}
          Desactivar {mode}
        {/if}
      </button>
    </footer>
  </form>
</dialog>

<style>
  .modal {
    border: 1px solid var(--border);
    border-radius: var(--r-3);
    padding: 24px;
    min-width: 380px;
    max-width: 520px;
    background: var(--surface);
    color: var(--ink);
  }
  .modal::backdrop {
    background: oklch(15% 0.02 250 / 0.55);
  }
  .modal--live {
    border-color: oklch(64% 0.2 25 / 0.55);
  }
  .modal__header h2 {
    margin: 0 0 8px;
    font-size: 16px;
    font-weight: 700;
  }
  .modal--live .modal__header h2 {
    color: oklch(64% 0.2 25);
  }
  .modal__warn {
    margin: 0 0 16px;
    padding: 10px 12px;
    background: oklch(64% 0.2 25 / 0.1);
    border: 1px solid oklch(64% 0.2 25 / 0.35);
    border-radius: var(--r-2);
    color: oklch(64% 0.2 25);
    font-size: 13px;
    line-height: 1.45;
  }
  .field {
    display: block;
    margin-bottom: 14px;
  }
  .field__label {
    display: block;
    font-size: 12px;
    color: var(--mute);
    margin-bottom: 4px;
  }
  .field__label em {
    font-style: normal;
    color: oklch(82% 0.16 95);
  }
  .field__input {
    width: 100%;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--bg);
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
  }
  .modal__error {
    margin: 0 0 12px;
    padding: 8px 12px;
    background: oklch(64% 0.2 25 / 0.12);
    color: oklch(64% 0.2 25);
    border-radius: var(--r-2);
    font-size: 13px;
  }
  .modal__footer {
    display: flex;
    gap: 8px;
    justify-content: flex-end;
    margin-top: 8px;
  }
  .btn {
    padding: 8px 14px;
    border-radius: var(--r-2);
    border: 1px solid transparent;
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }
  .btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
  .btn--ghost {
    background: transparent;
    border-color: var(--border);
    color: var(--mute);
  }
  .btn--paper {
    background: oklch(82% 0.16 95 / 0.22);
    border-color: oklch(82% 0.16 95);
    color: oklch(82% 0.16 95);
  }
  .btn--live {
    background: oklch(64% 0.2 25 / 0.22);
    border-color: oklch(64% 0.2 25);
    color: oklch(64% 0.2 25);
  }
</style>
