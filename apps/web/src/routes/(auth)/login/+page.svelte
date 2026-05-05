<script lang="ts">
  import { onMount } from 'svelte';
  import { enhance } from '$app/forms';

  let { form } = $props();

  let countdown = $state<number>(form?.retry_after ?? 0);
  let interval: ReturnType<typeof setInterval> | null = null;

  /**
   * When the form action returns a 429 with `retry_after`, kick off a
   * 1Hz countdown so the disabled submit button label ticks down.
   * Cleans up on unmount or when the form rerenders without a
   * retry_after.
   */
  function startCountdown(seconds: number) {
    if (interval) clearInterval(interval);
    countdown = seconds;
    interval = setInterval(() => {
      countdown = Math.max(0, countdown - 1);
      if (countdown <= 0 && interval) {
        clearInterval(interval);
        interval = null;
      }
    }, 1000);
  }

  $effect(() => {
    if (form?.retry_after && form.retry_after > 0) {
      startCountdown(form.retry_after);
    }
  });

  onMount(() => {
    return () => {
      if (interval) clearInterval(interval);
    };
  });
</script>

<svelte:head>
  <title>Sign in · iguanatrader</title>
</svelte:head>

<main>
  <div class="login-card">
    <div class="brand">
      <div class="brand__mark">i</div>
      <div class="brand__text">iguanatrader</div>
    </div>

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

      <label class="field">
        <span class="field__label">Password</span>
        <input
          name="password"
          type="password"
          autocomplete="current-password"
          required
        />
      </label>

      <button type="submit" disabled={countdown > 0}>
        {#if countdown > 0}
          Wait {countdown}s
        {:else}
          Sign in
        {/if}
      </button>
    </form>

    <div class="login-help">
      <p>iguanatrader is a single-seat trading workstation. Need a tenant?
      Run <code>iguanatrader admin bootstrap-tenant</code> on the host.</p>
    </div>

    <footer>
      <span>v0.0.0 (slice 4)</span>
    </footer>
  </div>
</main>

<style>
  /* Inline OKLCH tokens — slice W1 will plant `tokens.css` and these
     custom properties move to a global stylesheet. */
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
    --warn-bg: oklch(78% 0.14 80);
    --info: oklch(72% 0.14 230);
    --r-1: 4px;
    --r-2: 8px;
    --r-3: 12px;
    --font-sans:
      'Inter Variable', system-ui, -apple-system, 'Segoe UI', sans-serif;
    --font-mono:
      'JetBrains Mono Variable', 'SF Mono', Consolas, monospace;

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

  .login-card {
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
  .alert--warn {
    background: oklch(28% 0.06 80);
    border-color: var(--warn-bg);
    color: oklch(92% 0.05 80);
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
  button:hover:not(:disabled) {
    background: var(--accent-hover);
  }
  button:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .login-help {
    margin-top: 24px;
    padding: 14px 16px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .login-help p {
    margin: 0;
    font-size: 12px;
    color: var(--mute);
    line-height: 1.5;
  }
  .login-help code {
    font-family: var(--font-mono);
    background: var(--bg);
    padding: 1px 4px;
    border-radius: var(--r-1);
    color: var(--accent);
  }

  footer {
    margin-top: 16px;
    font-size: 11px;
    color: var(--mute);
    text-align: center;
  }
</style>
