<script lang="ts">
  type Option = { value: string; label: string };

  type Props = {
    name: string;
    label: string;
    value: string;
    options: Option[];
    error?: string;
    disabled?: boolean;
    helpText?: string;
  };

  let {
    name,
    label,
    value = $bindable(''),
    options,
    error,
    disabled = false,
    helpText,
  }: Props = $props();

  const fieldId = `field-${name}`;
  const helpId = `${fieldId}-help`;
  const errorId = `${fieldId}-error`;
  const describedBy = $derived(
    [error ? errorId : null, helpText ? helpId : null].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="field" data-testid="select-{name}">
  <label class="field__label" for={fieldId}>{label}</label>
  <select
    id={fieldId}
    {name}
    {disabled}
    bind:value
    aria-invalid={error ? 'true' : undefined}
    aria-describedby={describedBy}
    class:has-error={!!error}
  >
    {#each options as opt (opt.value)}
      <option value={opt.value}>{opt.label}</option>
    {/each}
  </select>
  {#if helpText}
    <span class="field__hint" id={helpId}>{helpText}</span>
  {/if}
  {#if error}
    <span class="field__error" id={errorId} role="alert">{error}</span>
  {/if}
</div>

<style>
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
    font-weight: 600;
  }
  .field__hint {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    color: var(--mute);
  }
  .field__error {
    display: block;
    margin-top: 6px;
    font-size: 12px;
    color: var(--destructive);
    font-weight: 500;
  }
  select {
    width: 100%;
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
  }
  select:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  select.has-error {
    border-color: var(--destructive);
  }
  select:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
</style>
