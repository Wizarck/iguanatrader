<script lang="ts">
  /**
   * Soft "rotate your password" banner shown above the dashboard
   * tabs when `password_changed_at` crosses the ageing (60d default)
   * or stale (90d default) thresholds.
   *
   * Slice: `auth-password-aging-warning`. Mounts in
   * `apps/web/src/routes/(app)/+layout.svelte` so the warning travels
   * with every dashboard tab. The `getBannerVariant` helper carries
   * all branching so the markup stays declarative; vitest unit-tests
   * target the helper directly (`tests/password-ageing-banner.test.ts`).
   *
   * a11y:
   * - `role="status"` (polite) for the ageing variant — heads-up only.
   * - `role="alert"` (assertive) for the stale variant — action expected.
   * - Both variants use OKLCH tokens (`--accent` / `--destructive`)
   *   defined in `apps/web/src/app.css` so the dark theme cascade
   *   propagates without per-component overrides.
   */
  import {
    getBannerVariant,
    type PasswordAgeingState
  } from './password-ageing-banner';

  type Props = {
    ageingState: PasswordAgeingState;
    ageDays: number | null;
  };

  let { ageingState, ageDays }: Props = $props();

  const variant = $derived(getBannerVariant(ageingState, ageDays));
</script>

{#if variant}
  <div
    role={variant.role}
    class="banner banner--{variant.variant}"
    data-testid="password-ageing-banner"
  >
    <span class="banner__message">{variant.message}</span>
    <a class="banner__link" href={variant.link.href}>{variant.link.text}</a>
  </div>
{/if}

<style>
  .banner {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 12px;
    margin: 0 0 16px;
    padding: 12px 18px;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    color: var(--ink);
    font-size: 14px;
    line-height: 1.45;
  }

  .banner--warning {
    border-color: color-mix(in oklch, var(--accent) 60%, var(--border));
    background: color-mix(in oklch, var(--accent) 14%, var(--surface));
  }

  .banner--danger {
    border-color: color-mix(in oklch, var(--destructive) 60%, var(--border));
    background: color-mix(in oklch, var(--destructive) 14%, var(--surface));
  }

  .banner__message {
    flex: 1 1 auto;
    min-width: 0;
  }

  .banner__link {
    flex: 0 0 auto;
    color: var(--accent);
    font-weight: 600;
    text-decoration: none;
  }

  .banner__link:hover,
  .banner__link:focus-visible {
    text-decoration: underline;
  }

  .banner--danger .banner__link {
    color: var(--destructive);
  }
</style>
