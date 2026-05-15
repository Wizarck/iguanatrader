<script lang="ts">
  /**
   * (app) authenticated shell — slice W1.
   *
   * Renders Sidebar (left) + TopBar (top) + main content slot. The
   * cookie hook in `apps/web/src/hooks.server.ts` (slice 4 contract,
   * consumed unchanged) gates this route group: missing/invalid session
   * cookies 302 to `/login?redirect_to=<originating>` BEFORE this
   * layout renders.
   *
   * `data.user` is exposed by `+layout.server.ts` (slice 4); we hydrate
   * the auth store on mount so any descendant component reading
   * `authStore.user` sees the canonical value.
   */
  import PasswordAgeingBanner from '$lib/components/PasswordAgeingBanner.svelte';
  import Sidebar from '$lib/components/nav/Sidebar.svelte';
  import TopBar from '$lib/components/nav/TopBar.svelte';
  import { authStore } from '$lib/stores/auth.svelte';

  let { data, children } = $props();

  $effect(() => {
    authStore.user = data.user;
  });
</script>

<div class="shell">
  <Sidebar user={data.user} />
  <div class="shell__body">
    <TopBar user={data.user} />
    <main class="shell__main" id="main-content" tabindex="-1">
      {#if data.user && data.user.password_aging_state && data.user.password_aging_state !== 'fresh'}
        <PasswordAgeingBanner
          ageingState={data.user.password_aging_state}
          ageDays={data.user.password_age_days ?? null}
        />
      {/if}
      {@render children()}
    </main>
  </div>
</div>

<style>
  .shell {
    display: grid;
    grid-template-columns: auto 1fr;
    min-height: 100vh;
    background: var(--bg);
    color: var(--ink);
    font-family: var(--font-sans);
  }

  .shell__body {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .shell__main {
    flex: 1;
    padding: 24px 32px;
    overflow-x: auto;
  }

  .shell__main:focus {
    outline: none;
  }
</style>
