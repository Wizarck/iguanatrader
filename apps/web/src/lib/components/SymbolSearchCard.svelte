<script lang="ts">
  /**
   * Symbol search card — slice `research-tab-ui`.
   *
   * Renders a `TextInput` with the canonical symbol pattern
   * (`^[A-Z0-9]{1,16}$`) + a submit button. On submit:
   *   1. Trim + uppercase the input.
   *   2. Validate against the pattern. Invalid → inline error, no
   *      navigation.
   *   3. Valid → call `onSubmit(symbol)` (defaults to
   *      `goto('/research/{symbol}')`).
   *
   * The default handler is overridable so this card can be reused for
   * any future symbol-keyed search (e.g., per-symbol portfolio drill-
   * down).
   */
  import { goto } from '$app/navigation';

  import { isValidSymbol } from '$lib/research/recent';

  import TextInput from './forms/TextInput.svelte';

  type Props = {
    onSubmit?: (symbol: string) => void;
    initialValue?: string;
  };

  let { onSubmit, initialValue = '' }: Props = $props();

  let value = $state(initialValue);
  let error = $state<string | null>(null);

  function handleSubmit(event: SubmitEvent): void {
    event.preventDefault();
    const normalized = value.trim().toUpperCase();
    if (!isValidSymbol(normalized)) {
      error = 'Symbol inválido. Usa 1-16 caracteres A-Z + dígitos.';
      return;
    }
    error = null;
    if (onSubmit) {
      onSubmit(normalized);
    } else {
      void goto(`/research/${encodeURIComponent(normalized)}`);
    }
  }
</script>

<form
  class="symbol-search-card"
  data-testid="symbol-search-card"
  onsubmit={handleSubmit}
  aria-label="Buscar brief de symbol"
>
  <TextInput
    name="symbol"
    label="Symbol"
    bind:value
    pattern="^[A-Z0-9]{'{1,16}'}$"
    placeholder="SPY"
    autocomplete="off"
    error={error ?? undefined}
    helpText="1-16 caracteres, mayúsculas y dígitos."
  />
  <button type="submit" class="submit">Buscar brief</button>
</form>

<style>
  .symbol-search-card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    padding: 24px;
    max-width: 480px;
    margin: 16px 0;
  }
  .submit {
    display: inline-block;
    padding: 10px 16px;
    background: var(--accent);
    color: var(--accent-fg, #000);
    border: 1px solid var(--accent);
    border-radius: var(--r-2);
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
  }
  .submit:hover {
    filter: brightness(1.08);
  }
  .submit:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
  }
</style>
