<script lang="ts">
  import { page } from '$app/state';

  import type { Problem } from '$lib/types/problem';

  /**
   * Global error boundary — slice W1.
   *
   * Reads `$page.error` (SvelteKit error context) and renders RFC 7807
   * `Problem`-shaped UI. Two render variants per `docs/ux/components.md` §2.3:
   *
   * - **recoverable** (status < 500): action hint based on `type` URI
   *   (auth → "Sign in", not-found → "Go home").
   * - **unrecoverable** (status ≥ 500): correlation ID + copy-to-
   *   clipboard button + "Try again" link.
   *
   * SvelteKit's `error()` thrown from a load function is surfaced via
   * `$page.error`; the shape is the project's `App.Error` extended with
   * the `Problem` fields when the backend response was a problem+json
   * (slice 5 contract). When only `{ message }` is present (transport
   * failure, unhandled JS error), we synthesise a minimal Problem.
   */

  /**
   * Best-effort coercion of `$page.error` to the `Problem` shape.
   *
   * SvelteKit's default `App.Error` is `{ message: string }`. Slice 4
   * declares `App.Error` as the default. Load functions that call
   * `error(status, problemBody)` propagate the body when the body is
   * an object (per SvelteKit's `error()` signature). We coerce
   * defensively so a transport failure (where `$page.error` is just
   * `{ message: 'Internal Error' }`) still renders something useful.
   */
  function coerceProblem(
    raw: unknown,
    status: number
  ): Problem {
    if (raw && typeof raw === 'object') {
      const obj = raw as Record<string, unknown>;
      const hasProblemShape =
        typeof obj.type === 'string' &&
        typeof obj.title === 'string' &&
        typeof obj.status === 'number';
      if (hasProblemShape) {
        return obj as unknown as Problem;
      }

      const message =
        typeof obj.message === 'string' ? obj.message : undefined;
      return {
        type:
          status >= 500
            ? 'urn:iguanatrader:error:internal'
            : 'urn:iguanatrader:error:client',
        title: defaultTitleFor(status),
        status,
        detail: message
      };
    }

    return {
      type: 'urn:iguanatrader:error:internal',
      title: defaultTitleFor(status),
      status
    };
  }

  function defaultTitleFor(status: number): string {
    if (status === 401) return 'Authentication Required';
    if (status === 403) return 'Forbidden';
    if (status === 404) return 'Not Found';
    if (status === 429) return 'Too Many Requests';
    if (status >= 500) return 'Internal Error';
    return 'Error';
  }

  function actionFor(problem: Problem): { href: string; label: string } | null {
    if (problem.status >= 500) {
      return { href: page.url.pathname, label: 'Try again' };
    }
    if (problem.type.includes('auth') || problem.status === 401) {
      const target = `/login?redirect_to=${encodeURIComponent(page.url.pathname + page.url.search)}`;
      return { href: target, label: 'Sign in' };
    }
    if (problem.type.includes('not-found') || problem.status === 404) {
      return { href: '/', label: 'Go home' };
    }
    return { href: '/', label: 'Go home' };
  }

  let problem = $derived<Problem>(
    coerceProblem(page.error, page.status)
  );
  let isUnrecoverable = $derived(problem.status >= 500);
  let action = $derived(actionFor(problem));
  let copied = $state(false);

  async function copyCorrelation(): Promise<void> {
    if (!problem.correlation_id) return;
    try {
      await navigator.clipboard.writeText(problem.correlation_id);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    } catch {
      // Clipboard API may be unavailable (insecure context); silently
      // fail — user can select the visible ID manually.
      copied = false;
    }
  }
</script>

<svelte:head>
  <title>{problem.title} · iguanatrader</title>
</svelte:head>

<section
  class="error-boundary"
  role="alert"
  aria-live="polite"
  aria-labelledby="error-title"
>
  <div class="error-card" data-variant={isUnrecoverable ? 'unrecoverable' : 'recoverable'}>
    <span class="badge" aria-label="Error type URI">{problem.type}</span>
    <h1 id="error-title">{problem.title}</h1>
    <p class="status">Status {problem.status}</p>

    {#if problem.detail}
      <p class="detail">{problem.detail}</p>
    {/if}

    {#if problem.errors && problem.errors.length > 0}
      <ul class="field-errors" aria-label="Validation errors">
        {#each problem.errors as err (`${err.field ?? 'global'}-${err.message}`)}
          <li>
            {#if err.field}
              <strong>{err.field}:</strong>
            {/if}
            {err.message}
          </li>
        {/each}
      </ul>
    {/if}

    {#if isUnrecoverable && problem.correlation_id}
      <div class="correlation">
        <span class="correlation__label">Correlation ID</span>
        <code class="correlation__id">{problem.correlation_id}</code>
        <button
          type="button"
          class="correlation__copy"
          onclick={copyCorrelation}
          aria-label="Copy correlation ID to clipboard"
        >
          {copied ? 'Copied!' : 'Copy'}
        </button>
      </div>
    {/if}

    {#if action}
      <a class="action" href={action.href}>{action.label}</a>
    {/if}
  </div>
</section>

<style>
  .error-boundary {
    min-height: 100vh;
    background: var(--bg);
    color: var(--ink);
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 32px;
    font-family: var(--font-sans);
  }

  .error-card {
    width: 100%;
    max-width: 520px;
    padding: 32px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-3);
  }

  .error-card[data-variant='unrecoverable'] {
    border-color: var(--destructive);
  }

  .badge {
    display: inline-block;
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--mute);
    background: var(--surface-2);
    padding: 4px 8px;
    border-radius: var(--r-pill);
    border: 1px solid var(--border);
    margin-bottom: 16px;
    word-break: break-all;
  }

  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 4px;
    color: var(--ink);
  }

  .status {
    font-size: 12px;
    color: var(--mute);
    margin: 0 0 16px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .detail {
    font-size: 14px;
    color: var(--ink);
    margin: 0 0 16px;
    line-height: 1.5;
  }

  .field-errors {
    list-style: none;
    padding: 12px 16px;
    margin: 0 0 16px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    font-size: 13px;
  }
  .field-errors li {
    margin-bottom: 4px;
  }
  .field-errors li:last-child {
    margin-bottom: 0;
  }
  .field-errors strong {
    color: var(--mute);
    font-weight: 500;
    margin-right: 6px;
  }

  .correlation {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 12px;
    background: var(--surface-2);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    margin-bottom: 16px;
    flex-wrap: wrap;
  }
  .correlation__label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--mute);
  }
  .correlation__id {
    font-family: var(--font-mono);
    font-size: 12px;
    color: var(--ink);
    flex: 1;
    overflow-wrap: anywhere;
  }
  .correlation__copy {
    background: var(--accent);
    color: var(--accent-fg);
    border: 0;
    border-radius: var(--r-2);
    padding: 6px 10px;
    font-size: 12px;
    font-weight: 600;
    cursor: pointer;
  }
  .correlation__copy:hover {
    background: var(--accent-hover);
  }

  .action {
    display: inline-block;
    background: var(--accent);
    color: var(--accent-fg);
    text-decoration: none;
    padding: 10px 16px;
    border-radius: var(--r-2);
    font-weight: 600;
    font-size: 14px;
  }
  .action:hover {
    background: var(--accent-hover);
  }
</style>
