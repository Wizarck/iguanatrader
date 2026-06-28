<script lang="ts">
  import { enhance } from '$app/forms';

  // The form action returns either a successful payload
  // (`{ submitted: true, message }`) or a `fail(...)` payload
  // (`{ alert_variant, message, retry_after? }`). The union below
  // narrows that without changing the server-side contract.
  type ForgotPasswordFormResult = {
    submitted?: boolean;
    message?: string;
    alert_variant?: 'destructive' | 'warn' | 'info';
    retry_after?: number;
  };

  let { form }: { form?: ForgotPasswordFormResult } = $props();
</script>

<svelte:head>
  <title>Reset password · iguanatrader</title>
</svelte:head>

<main>
  <div class="card">
    <div class="brand">
      <div class="brand__mark">i</div>
      <div class="brand__text">iguanatrader</div>
    </div>

    {#if form?.submitted}
      <div class="alert alert--info" role="status">
        {form.message ??
          'If the address is registered, you will receive instructions by email, Telegram, or WhatsApp within the next few minutes.'}
      </div>
      <p class="help">
        When the temporary password arrives, head back to
        <a href="/login">sign in</a> and enter it. On your first
        login we will ask you to change it for a new one.
      </p>
    {:else}
      <h1>Reset password</h1>
      <p class="help">
        Enter your email. We will send a temporary password through
        whichever channels you have configured (email, Telegram, WhatsApp).
      </p>

      {#if form?.alert_variant}
        <div class="alert alert--{form.alert_variant}" role="alert">
          {form.message}
        </div>
      {/if}

      <form method="POST" use:enhance>
        <label class="field">
          <span class="field__label">Email</span>
          <input
            name="email"
            type="email"
            autocomplete="email"
            required
            spellcheck="false"
            autocapitalize="off"
          />
        </label>

        <button type="submit">Send temporary password</button>
      </form>

      <p class="back">
        <a href="/login">Back to sign in</a>
      </p>
    {/if}
  </div>
</main>

<style>
  main {
    --bg: oklch(18% 0.02 250);
    --surface: oklch(22% 0.02 250);
    --surface-2: oklch(26% 0.02 250);
    --ink: oklch(95% 0.005 250);
    --mute: oklch(70% 0.012 250);
    --border: oklch(32% 0.02 250);
    --accent: oklch(72% 0.14 195);
    --accent-fg: oklch(15% 0.02 250);
    --accent-hover: oklch(76% 0.14 195);
    --destructive: oklch(64% 0.2 25);
    --info: oklch(72% 0.14 230);
    --r-1: 4px;
    --r-2: 8px;
    --r-3: 12px;
    --font-sans:
      'Inter Variable', system-ui, -apple-system, 'Segoe UI', sans-serif;
    background: var(--bg);
    color: var(--ink);
    font-family: var(--font-sans);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    margin: 0;
  }

  .card {
    width: 360px;
    padding: 32px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-3);
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 24px;
  }
  .brand__mark {
    width: 32px;
    height: 32px;
    background: var(--accent);
    border-radius: var(--r-2);
    display: inline-flex;
    align-items: center;
    justify-content: center;
    color: var(--accent-fg);
    font-weight: 700;
    font-size: 18px;
  }
  .brand__text {
    font-size: 18px;
    font-weight: 600;
  }

  h1 {
    font-size: 18px;
    margin: 0 0 8px;
  }

  .help {
    margin: 0 0 16px;
    font-size: 13px;
    color: var(--mute);
    line-height: 1.5;
  }
  .help a {
    color: var(--accent);
  }

  .alert {
    border-radius: var(--r-2);
    padding: 10px 12px;
    margin-bottom: 16px;
    font-size: 13px;
    border: 1px solid var(--border);
  }
  .alert--destructive {
    background: oklch(28% 0.06 25);
    border-color: var(--destructive);
    color: oklch(92% 0.05 25);
  }
  .alert--info {
    background: oklch(28% 0.04 230);
    border-color: var(--info);
    color: oklch(92% 0.04 230);
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
  input {
    width: 100%;
    padding: 10px 12px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
  }
  input:focus {
    outline: none;
    border-color: var(--accent);
    box-shadow: 0 0 0 2px oklch(72% 0.14 195 / 0.2);
  }

  button {
    width: 100%;
    padding: 10px 14px;
    background: var(--accent);
    color: var(--accent-fg);
    border: 0;
    border-radius: var(--r-2);
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    margin-top: 8px;
  }
  button:hover {
    background: var(--accent-hover);
  }

  .back {
    margin-top: 16px;
    font-size: 13px;
    text-align: center;
  }
  .back a {
    color: var(--accent);
  }
</style>
