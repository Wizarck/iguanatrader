<script lang="ts">
  type Props = {
    name: string;
    label: string;
    value: string;
    rows?: number;
    monospace?: boolean;
    error?: string;
    disabled?: boolean;
    helpText?: string;
    placeholder?: string;
  };

  let {
    name,
    label,
    value = $bindable(''),
    rows = 8,
    monospace = true,
    error,
    disabled = false,
    helpText,
    placeholder,
  }: Props = $props();

  const fieldId = `field-${name}`;
  const helpId = `${fieldId}-help`;
  const errorId = `${fieldId}-error`;
  const describedBy = $derived(
    [error ? errorId : null, helpText ? helpId : null].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="field" data-testid="textarea-{name}">
  <label class="field__label" for={fieldId}>{label}</label>
  <textarea
    id={fieldId}
    {name}
    {rows}
    {disabled}
    {placeholder}
    bind:value
    aria-invalid={error ? 'true' : undefined}
    aria-describedby={describedBy}
    class:has-error={!!error}
    class:monospace
  ></textarea>
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
  textarea {
    width: 100%;
    padding: 10px 12px;
    padding-bottom: 14px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    color: var(--ink);
    font-family: inherit;
    font-size: 14px;
    line-height: 1.5;
    resize: vertical;
  }
  textarea.monospace {
    font-family: var(--font-mono);
    font-size: 13px;
  }
  textarea:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 1px;
  }
  textarea.has-error {
    border-color: var(--destructive);
  }
  textarea:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
</style>
