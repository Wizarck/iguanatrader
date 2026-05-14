<script lang="ts" module>
  /**
   * Strategy edit/upsert form route (slice strategies-config-ui).
   * Hidden from the sidebar — reached from `/strategies` only.
   */
  export const meta = {
    label: 'Strategy form',
    icon: 'cpu',
    order: 999,
    hidden: true,
  } as const;
</script>

<script lang="ts">
  import { enhance } from '$app/forms';

  import Checkbox from '$lib/components/forms/Checkbox.svelte';
  import Select from '$lib/components/forms/Select.svelte';
  import Textarea from '$lib/components/forms/Textarea.svelte';
  import TextInput from '$lib/components/forms/TextInput.svelte';
  import {
    STRATEGY_KINDS,
    defaultParamsJson,
    type StrategyKind,
  } from '$lib/strategies/types';

  import type { ActionData, PageData } from './$types';

  type UpsertFailValues = {
    symbol: string;
    strategy_kind: string;
    params: string;
    enabled: boolean;
  };
  type FormShape = {
    formError?: string;
    fieldErrors?: Partial<Record<'symbol' | 'strategy_kind' | 'params', string>>;
    values?: UpsertFailValues;
    disableError?: string;
  };

  let { data, form }: { data: PageData; form?: ActionData } = $props();
  const formTyped = $derived(form as FormShape | undefined);

  const isNew = $derived(data.mode === 'new');

  // Initial values seed from server load OR from the most-recent failed
  // submit (so the user does not lose their edits on validation errors).
  const initialKind: StrategyKind = (formTyped?.values?.strategy_kind as StrategyKind | undefined) ??
    (data.strategy?.strategy_kind as StrategyKind | undefined) ??
    'donchian_atr';

  const initialParams: string = formTyped?.values?.params ??
    (data.strategy ? JSON.stringify(data.strategy.params, null, 2) : defaultParamsJson(initialKind));

  const initialSymbol: string = formTyped?.values?.symbol ?? data.strategy?.symbol ?? '';
  const initialEnabled: boolean = formTyped?.values?.enabled ?? data.strategy?.enabled ?? true;

  let symbolInput = $state(initialSymbol);
  let kindInput = $state<string>(initialKind);
  let paramsInput = $state(initialParams);
  let enabledInput = $state(initialEnabled);

  // Track the last kind-default we suggested. If the textarea still matches
  // it (or is empty), changing the dropdown overwrites with the new
  // kind-default. If the user has edited the textarea, preserve their work.
  let lastSuggestedDefault = $state(initialParams === defaultParamsJson(initialKind) ? initialParams : '');

  $effect(() => {
    if (!STRATEGY_KINDS.includes(kindInput as StrategyKind)) return;
    const suggested = defaultParamsJson(kindInput as StrategyKind);
    const textareaIsEmpty = paramsInput.trim() === '';
    const textareaMatchesPreviousSuggestion =
      lastSuggestedDefault !== '' && paramsInput === lastSuggestedDefault;
    if (textareaIsEmpty || textareaMatchesPreviousSuggestion) {
      paramsInput = suggested;
      lastSuggestedDefault = suggested;
    }
  });

  const kindOptions = STRATEGY_KINDS.map((k) => ({ value: k, label: k }));

  const titleText = $derived(
    isNew ? 'Nueva estrategia' : `Editar estrategia: ${data.strategy?.symbol ?? ''}`,
  );

  // Client-side JSON pre-check — saves a round-trip when the JSON is
  // obviously invalid. The server action re-validates regardless.
  let clientParamsError = $state<string | null>(null);
  function preflight(event: SubmitEvent) {
    clientParamsError = null;
    const raw = paramsInput.trim();
    if (!raw) {
      clientParamsError = 'Params es obligatorio (objeto JSON).';
      event.preventDefault();
      return;
    }
    try {
      const parsed: unknown = JSON.parse(raw);
      if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
        clientParamsError = 'Params debe ser un objeto JSON.';
        event.preventDefault();
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      clientParamsError = `JSON inválido: ${message}`;
      event.preventDefault();
    }
  }

  function confirmDisable(event: SubmitEvent) {
    const ok = confirm(
      `¿Deshabilitar la estrategia de ${data.strategy?.symbol ?? ''}? Esto pondrá la estrategia en estado disabled — no borra el config ni cierra posiciones abiertas.`,
    );
    if (!ok) event.preventDefault();
  }

  const showDisable = $derived(
    !isNew && data.strategy !== null && data.strategy.enabled === true,
  );
</script>

<svelte:head>
  <title>{titleText} · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <h1>{titleText}</h1>

  {#if data.loadError}
    <div class="error" role="alert" data-testid="strategy-load-error">
      {data.loadError}
    </div>
  {:else}
    {#if formTyped?.formError}
      <div class="error" role="alert" data-testid="form-error">{formTyped.formError}</div>
    {/if}

    <form method="POST" action="?/upsert" use:enhance onsubmit={preflight} novalidate>
      <input type="hidden" name="mode" value={isNew ? 'new' : 'edit'} />

      {#if isNew}
        <TextInput
          name="symbol"
          label="Symbol"
          bind:value={symbolInput}
          required
          pattern="^[A-Z0-9]{'{1,16}'}$"
          helpText="Letras mayúsculas A-Z y dígitos 0-9, máximo 16 caracteres (convención IBKR)."
          error={formTyped?.fieldErrors?.symbol}
          placeholder="SPY"
          autocomplete="off"
        />
      {:else}
        <div class="static-field" data-testid="symbol-readonly">
          <span class="field__label">Symbol</span>
          <span class="field__value">{data.strategy?.symbol ?? ''}</span>
          <input type="hidden" name="symbol" value={data.strategy?.symbol ?? ''} />
        </div>
      {/if}

      <Select
        name="strategy_kind"
        label="Strategy kind"
        bind:value={kindInput}
        options={kindOptions}
        error={formTyped?.fieldErrors?.strategy_kind}
        helpText="Selecciona el tipo de estrategia. Cambiar el kind sugiere los parámetros por defecto si no has editado el textarea."
      />

      <Textarea
        name="params"
        label="Params (JSON)"
        bind:value={paramsInput}
        rows={10}
        monospace
        error={clientParamsError ?? formTyped?.fieldErrors?.params}
        helpText="Objeto JSON con los parámetros del kind. Ej: {`{ "lookback": 20, "atr_mult": 2.0 }`}."
      />

      <Checkbox
        name="enabled"
        label="Enabled (genera señales)"
        bind:checked={enabledInput}
        helpText="Si está desmarcado, la estrategia se guarda pero no propondrá trades."
      />

      <div class="actions">
        <button type="submit" class="btn btn--primary" data-testid="submit">Guardar</button>
        <a href="/strategies" class="btn btn--ghost" data-testid="cancel">Cancelar</a>
      </div>
    </form>

    {#if showDisable}
      <hr class="separator" />
      <div class="disable-section">
        <p class="disable-note">
          Esto pondrá la estrategia en estado disabled — no borra el config ni cierra posiciones
          abiertas.
        </p>
        <form method="POST" action="?/disable" use:enhance onsubmit={confirmDisable}>
          <button type="submit" class="btn btn--danger" data-testid="disable">Deshabilitar</button>
        </form>
        {#if formTyped?.disableError}
          <p class="error error--inline" role="alert" data-testid="disable-error">
            {formTyped.disableError}
          </p>
        {/if}
      </div>
    {/if}
  {/if}
</section>

<style>
  section {
    color: var(--ink);
    max-width: 640px;
  }
  h1 {
    font-size: 22px;
    font-weight: 600;
    margin: 0 0 16px;
  }
  .static-field {
    margin-bottom: 16px;
  }
  .field__label {
    display: block;
    font-size: 12px;
    color: var(--mute);
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }
  .field__value {
    display: inline-block;
    padding: 6px 0;
    color: var(--ink);
    font-size: 14px;
    font-family: var(--font-mono);
  }
  .actions {
    display: flex;
    gap: 12px;
    margin-top: 16px;
  }
  .btn {
    display: inline-block;
    padding: 10px 16px;
    border-radius: var(--r-2);
    font-family: inherit;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    border: 1px solid transparent;
    text-decoration: none;
    line-height: 1.4;
  }
  .btn--primary {
    background: var(--accent);
    color: var(--accent-fg);
  }
  .btn--primary:hover {
    background: var(--accent-hover);
  }
  .btn--ghost {
    background: transparent;
    color: var(--ink);
    border-color: var(--border);
  }
  .btn--ghost:hover {
    background: var(--surface-2);
  }
  .btn--danger {
    background: transparent;
    color: var(--destructive);
    border-color: oklch(64% 0.2 25 / 0.5);
  }
  .btn--danger:hover {
    background: oklch(64% 0.2 25 / 0.12);
  }
  .separator {
    margin: 28px 0 16px;
    border: 0;
    border-top: 1px solid var(--border);
  }
  .disable-section {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    padding: 16px 20px;
  }
  .disable-note {
    margin: 0 0 12px;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
  }
  .error {
    margin-top: 16px;
    margin-bottom: 16px;
    padding: 12px 16px;
    background: oklch(64% 0.2 25 / 0.14);
    border: 1px solid oklch(64% 0.2 25 / 0.4);
    border-radius: var(--r-2);
    color: var(--destructive);
    font-size: 14px;
  }
  .error--inline {
    margin: 12px 0 0;
    padding: 8px 12px;
    font-size: 13px;
  }
</style>
