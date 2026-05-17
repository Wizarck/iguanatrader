<script lang="ts" module>
  /**
   * Strategy create/edit form route (slice strategies-form-rewrite-english).
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
  import TextInput from '$lib/components/forms/TextInput.svelte';
  import {
    STRATEGY_CATALOGUE,
    getStrategySpec,
    paramsToFormValues,
    validateParamForm,
    type ParamFormValues,
    type ParamSpec,
    type StrategySpec,
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

  // Seed: server load > most-recent failed submit > catalogue default.
  const initialKind: string =
    (formTyped?.values?.strategy_kind as string | undefined) ??
    (data.strategy?.strategy_kind as string | undefined) ??
    STRATEGY_CATALOGUE[0].kind;
  const initialSymbol: string = formTyped?.values?.symbol ?? data.strategy?.symbol ?? '';
  const initialEnabled: boolean = formTyped?.values?.enabled ?? data.strategy?.enabled ?? true;

  // Hydrate the param form values from either the previously-failed submit's
  // raw JSON OR the loaded strategy's params dict OR the catalogue defaults.
  function initialParamValues(kind: string): ParamFormValues {
    const spec = getStrategySpec(kind);
    if (!spec) return {};
    // 1. Failed submit → try to parse the previous JSON and replay.
    if (formTyped?.values?.params) {
      try {
        const parsed = JSON.parse(formTyped.values.params) as Record<string, unknown>;
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          return paramsToFormValues(spec, parsed);
        }
      } catch {
        // Fall through to next source.
      }
    }
    // 2. Loaded strategy on edit mode.
    if (data.strategy?.strategy_kind === kind && data.strategy?.params) {
      return paramsToFormValues(spec, data.strategy.params);
    }
    // 3. Catalogue defaults.
    return paramsToFormValues(spec, {});
  }

  let symbolInput = $state(initialSymbol);
  let kindInput = $state<string>(initialKind);
  let paramValues = $state<ParamFormValues>(initialParamValues(initialKind));
  let enabledInput = $state(initialEnabled);

  // Per-field client-side errors surfaced on submit attempt.
  let paramErrors = $state<Record<string, string>>({});
  let formError = $state<string | null>(null);

  let currentSpec = $derived<StrategySpec | undefined>(getStrategySpec(kindInput));

  // When the kind changes, swap the param values to the new kind's defaults.
  // We do NOT preserve old values across kinds (parameters are not portable).
  let lastKindSeen = $state(initialKind);
  $effect(() => {
    if (kindInput === lastKindSeen) return;
    paramValues = initialParamValues(kindInput);
    paramErrors = {};
    lastKindSeen = kindInput;
  });

  const kindOptions = STRATEGY_CATALOGUE.map((s) => ({
    value: s.kind,
    label: `${s.displayName} (${s.kind})`,
  }));

  const titleText = $derived(
    isNew ? 'New strategy' : `Edit strategy: ${data.strategy?.symbol ?? ''}`,
  );

  // Hidden field holds the serialised JSON we send to the server action.
  // Driven by the param values + currently-selected spec.
  let paramsJsonHidden = $state(initialJsonForKind(initialKind));

  function initialJsonForKind(kind: string): string {
    const spec = getStrategySpec(kind);
    if (!spec) return '{}';
    const validation = validateParamForm(spec, initialParamValues(kind));
    if (validation.ok) {
      return JSON.stringify(validation.params);
    }
    return '{}';
  }

  function preflight(event: SubmitEvent) {
    formError = null;
    paramErrors = {};
    if (!currentSpec) {
      formError = 'Pick a strategy type before saving.';
      event.preventDefault();
      return;
    }
    const validation = validateParamForm(currentSpec, paramValues);
    if (!validation.ok) {
      paramErrors = validation.errors;
      formError = 'Some parameters need attention — see the messages below.';
      event.preventDefault();
      return;
    }
    paramsJsonHidden = JSON.stringify(validation.params);
  }

  function confirmDisable(event: SubmitEvent) {
    const ok = confirm(
      `Disable the strategy for ${data.strategy?.symbol ?? ''}? It stays in the database with enabled=false. Open positions are not closed.`,
    );
    if (!ok) event.preventDefault();
  }

  const showDisable = $derived(
    !isNew && data.strategy !== null && data.strategy.enabled === true,
  );

  function displayValueFor(p: ParamSpec): string {
    return paramValues[p.name] ?? '';
  }

  function setParamValue(p: ParamSpec, value: string): void {
    paramValues = { ...paramValues, [p.name]: value };
  }

  function inputModeFor(p: ParamSpec): 'numeric' | 'decimal' | 'text' {
    if (p.type === 'integer') return 'numeric';
    if (p.type === 'decimal' || p.type === 'percent' || p.type === 'optional-decimal') {
      return 'decimal';
    }
    return 'text';
  }

  function placeholderFor(p: ParamSpec): string {
    if (p.default === null) return 'optional';
    if (p.type === 'percent') return String(Number(p.default) * 100);
    return String(p.default);
  }
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
    {:else if formError}
      <div class="error" role="alert" data-testid="client-error">{formError}</div>
    {/if}

    <form method="POST" action="?/upsert" use:enhance onsubmit={preflight} novalidate>
      <input type="hidden" name="mode" value={isNew ? 'new' : 'edit'} />
      <input type="hidden" name="params" value={paramsJsonHidden} />

      {#if isNew}
        <TextInput
          name="symbol"
          label="Symbol"
          bind:value={symbolInput}
          required
          pattern="^[A-Z0-9]{'{1,16}'}$"
          helpText="Uppercase letters A-Z and digits 0-9, max 16 characters (IBKR convention)."
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
        label="Strategy type"
        bind:value={kindInput}
        options={kindOptions}
        error={formTyped?.fieldErrors?.strategy_kind}
        helpText="Each type runs a different signal-generation algorithm. Switching types resets the parameter values to that type's defaults."
      />

      {#if currentSpec}
        <div class="kind-description" data-testid="kind-description">
          {currentSpec.description}
        </div>

        <fieldset class="params" aria-label="Strategy parameters">
          <legend>Parameters</legend>
          {#each currentSpec.params as paramSpec (paramSpec.name)}
            <div class="param-field">
              <label class="param-label" for={`param-${paramSpec.name}`}>
                {paramSpec.label}
              </label>
              <input
                id={`param-${paramSpec.name}`}
                class="param-input"
                type="text"
                inputmode={inputModeFor(paramSpec)}
                value={displayValueFor(paramSpec)}
                placeholder={placeholderFor(paramSpec)}
                aria-invalid={paramErrors[paramSpec.name] ? 'true' : undefined}
                aria-describedby={`help-${paramSpec.name}`}
                data-testid={`param-${paramSpec.name}`}
                oninput={(e) =>
                  setParamValue(paramSpec, (e.currentTarget as HTMLInputElement).value)}
              />
              <p class="param-help" id={`help-${paramSpec.name}`}>{paramSpec.help}</p>
              {#if paramErrors[paramSpec.name]}
                <p
                  class="param-error"
                  role="alert"
                  data-testid={`param-error-${paramSpec.name}`}
                >
                  {paramErrors[paramSpec.name]}
                </p>
              {/if}
            </div>
          {/each}
        </fieldset>
      {/if}

      <Checkbox
        name="enabled"
        label="Enabled (generates signals)"
        bind:checked={enabledInput}
        helpText="If unchecked, the strategy config is saved but no proposals are emitted."
      />

      <div class="actions">
        <button type="submit" class="btn btn--primary" data-testid="submit">Save</button>
        <a href="/strategies" class="btn btn--ghost" data-testid="cancel">Cancel</a>
      </div>
    </form>

    {#if showDisable}
      <hr class="separator" />
      <div class="disable-section">
        <p class="disable-note">
          Soft-disables the strategy. Config row stays in the database; no proposals are
          generated. Open positions are NOT closed.
        </p>
        <form method="POST" action="?/disable" use:enhance onsubmit={confirmDisable}>
          <button type="submit" class="btn btn--danger" data-testid="disable">Disable</button>
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
    max-width: 720px;
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
  .kind-description {
    margin: 0 0 16px;
    padding: 12px 16px;
    border-left: 3px solid var(--accent);
    background: var(--surface);
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
    border-radius: 0 var(--r-2) var(--r-2) 0;
  }
  .params {
    margin: 16px 0;
    padding: 16px 20px;
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
  }
  .params legend {
    padding: 0 8px;
    font-size: 12px;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--mute);
  }
  .param-field {
    margin: 0 0 14px;
  }
  .param-field:last-of-type {
    margin-bottom: 0;
  }
  .param-label {
    display: block;
    font-size: 12px;
    color: var(--ink);
    margin-bottom: 4px;
    font-weight: 500;
  }
  .param-input {
    width: 100%;
    padding: 8px 10px;
    font-family: var(--font-mono);
    font-size: 13px;
    background: var(--bg);
    color: var(--ink);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
  }
  .param-input:focus {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  .param-input[aria-invalid='true'] {
    border-color: var(--destructive);
  }
  .param-help {
    margin: 4px 0 0;
    font-size: 11px;
    color: var(--mute);
    line-height: 1.4;
  }
  .param-error {
    margin: 6px 0 0;
    font-size: 12px;
    color: var(--destructive);
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
