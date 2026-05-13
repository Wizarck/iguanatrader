<script lang="ts" module>
  /**
   * Route metadata — consumed by the dynamic Sidebar (slice W1, design D2).
   * The change-password page is intentionally NOT in the sidebar — it
   * is reached via Settings or the "must change password" gate redirect.
   */
  export const meta = {
    label: 'Change password',
    icon: 'lock',
    order: 999,
    hidden: true
  } as const;
</script>

<script lang="ts">
  import { enhance } from '$app/forms';
  import type { ActionData, PageData } from './$types';

  let { data, form }: { data: PageData; form?: ActionData } = $props();

  let newPassword = $state('');
  let confirm = $state('');
  // Client-side mismatch surfaces immediately without round-tripping the
  // form action. The server-side action is still authoritative.
  let confirmMismatch = $derived(
    confirm.length > 0 && newPassword !== confirm
  );
</script>

<svelte:head>
  <title>Change password · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>Change password</h1>

  {#if data.required}
    <div class="alert alert--warn" role="alert">
      A password change is required before you can continue. Please set a new
      password to access the app.
    </div>
  {/if}

  {#if form?.alert_variant}
    <div class="alert alert--{form.alert_variant}" role="alert">
      {form.message}
    </div>
  {/if}

  <form method="POST" use:enhance>
    <label class="field">
      <span class="field__label">Current password</span>
      <input
        name="old_password"
        type="password"
        autocomplete="current-password"
        required
      />
    </label>

    <label class="field">
      <span class="field__label">New password</span>
      <input
        name="new_password"
        type="password"
        autocomplete="new-password"
        minlength="12"
        bind:value={newPassword}
        required
      />
      <span class="field__hint">
        At least 12 characters, with at least one digit or symbol.
      </span>
    </label>

    <label class="field">
      <span class="field__label">Confirm new password</span>
      <input
        name="confirm"
        type="password"
        autocomplete="new-password"
        minlength="12"
        bind:value={confirm}
        required
      />
      {#if confirmMismatch}
        <span class="field__hint field__hint--error">
          New password and confirmation do not match.
        </span>
      {/if}
    </label>

    <button type="submit" disabled={confirmMismatch}>Change password</button>
  </form>
</section>

<style>
  section {
    color: var(--ink);
    max-width: 480px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  .alert {
    border-radius: 8px;
    padding: 10px 12px;
    margin-bottom: 16px;
    font-size: 13px;
    border: 1px solid var(--mute);
  }
  .alert--warn {
    background: oklch(28% 0.06 80);
    border-color: oklch(78% 0.14 80);
    color: oklch(92% 0.05 80);
  }
  .alert--destructive {
    background: oklch(28% 0.06 25);
    border-color: oklch(64% 0.2 25);
    color: oklch(92% 0.05 25);
  }
  .field {
    display: block;
    margin-bottom: 16px;
  }
  .field__label {
    display: block;
    font-size: 12px;
    color: var(--mute);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }
  .field__hint {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    color: var(--mute);
  }
  .field__hint--error {
    color: oklch(64% 0.2 25);
  }
  input {
    width: 100%;
    padding: 10px 12px;
    background: var(--surface, oklch(22% 0.02 250));
    border: 1px solid var(--mute);
    border-radius: 6px;
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
  }
  button {
    padding: 10px 14px;
    background: var(--accent, oklch(72% 0.14 195));
    color: var(--accent-fg, oklch(15% 0.02 250));
    border: 0;
    border-radius: 6px;
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }
</style>
