<script lang="ts">
  type Props = {
    name: string;
    label: string;
    value: string;
    type?: string;
    required?: boolean;
    pattern?: string;
    helpText?: string;
    error?: string;
    disabled?: boolean;
    placeholder?: string;
    autocomplete?: HTMLInputElement['autocomplete'];
  };

  let {
    name,
    label,
    value = $bindable(''),
    type = 'text',
    required = false,
    pattern,
    helpText,
    error,
    disabled = false,
    placeholder,
    autocomplete,
  }: Props = $props();

  const fieldId = `field-${name}`;
  const helpId = `${fieldId}-help`;
  const errorId = `${fieldId}-error`;
  const describedBy = $derived(
    [error ? errorId : null, helpText ? helpId : null].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="field" data-testid="text-input-{name}">
  <label class="field__label" for={fieldId}>{label}</label>
  <input
    id={fieldId}
    {name}
    {type}
    {pattern}
    {required}
    {disabled}
    {placeholder}
    {autocomplete}
    bind:value
    aria-invalid={error ? 'true' : undefined}
    aria-describedby={describedBy}
    class:has-error={!!error}
  />
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
  input {
    width: 100%;
    padding: 10px 12px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
  }
  input:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  input.has-error {
    border-color: var(--destructive);
  }
  input:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
</style>
