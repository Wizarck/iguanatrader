<script lang="ts">
  import { Moon, Sun } from 'lucide-svelte';

  import ConnectionIndicator from '$lib/components/nav/ConnectionIndicator.svelte';
  import DaemonModeChip from '$lib/components/DaemonModeChip.svelte';
  import { themeStore } from '$lib/stores/theme.svelte';

  /**
   * TopBar — slice W1.
   *
   * Hosts the global theme toggle, ConnectionIndicator, and a reserved
   * KillSwitchButton slot (`<div data-slot="kill-switch" />`). Slice K1
   * fills the slot in a follow-up PR; W1 ships the slot empty so K1's
   * landing PR is a single-component import with no TopBar churn.
   */

  type Props = {
    user: App.Locals['user'];
  };

  let { user }: Props = $props();

  function toggleTheme(): void {
    themeStore.current = themeStore.current === 'dark' ? 'light' : 'dark';
  }
</script>

<header class="topbar" aria-label="Top bar">
  <div class="topbar__title">
    <span class="topbar__welcome">
      {#if user}
        Signed in as <strong>{user.email}</strong>
      {:else}
        Dashboard
      {/if}
    </span>
  </div>

  <div class="topbar__actions">
    <!-- Slice ``dual-daemon-mode-toggle-and-reconcile``: persistent
         mode chips. Color is fixed (paper=yellow, live=red); brightness
         encodes whether the daemon is currently operating. -->
    <DaemonModeChip mode="paper" />
    <DaemonModeChip mode="live" />

    <ConnectionIndicator />

    <!-- K1 fills this slot with KillSwitchButton; W1 leaves it empty. -->
    <div class="topbar__kill-switch" data-slot="kill-switch"></div>

    <button
      type="button"
      class="topbar__theme-toggle"
      onclick={toggleTheme}
      aria-label={themeStore.current === 'dark'
        ? 'Switch to light theme'
        : 'Switch to dark theme'}
      aria-pressed={themeStore.current === 'light'}
    >
      {#if themeStore.current === 'dark'}
        <Moon size={16} strokeWidth={1.75} />
      {:else}
        <Sun size={16} strokeWidth={1.75} />
      {/if}
    </button>
  </div>
</header>

<style>
  .topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 24px;
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    color: var(--ink);
    min-height: 56px;
  }

  .topbar__title {
    display: flex;
    align-items: center;
    gap: 12px;
    font-size: 13px;
    color: var(--mute);
  }
  .topbar__welcome strong {
    color: var(--ink);
  }

  .topbar__actions {
    display: flex;
    align-items: center;
    gap: 12px;
  }

  /* Reserved slot for K1's KillSwitchButton. Empty in W1, hidden until
     K1 fills it (otherwise the slot would render as an empty zero-width
     div but still consume the gap). */
  .topbar__kill-switch:empty {
    display: none;
  }

  .topbar__theme-toggle {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--mute);
    border-radius: var(--r-2);
    width: 32px;
    height: 32px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    cursor: pointer;
  }
  .topbar__theme-toggle:hover {
    background: var(--surface-2);
    color: var(--ink);
  }
</style>
