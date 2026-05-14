<script lang="ts">
  type Props = {
    name: string;
    label: string;
    checked: boolean;
    disabled?: boolean;
    helpText?: string;
    error?: string;
  };

  let {
    name,
    label,
    checked = $bindable(false),
    disabled = false,
    helpText,
    error,
  }: Props = $props();

  const fieldId = `field-${name}`;
  const helpId = `${fieldId}-help`;
  const errorId = `${fieldId}-error`;
  const describedBy = $derived(
    [error ? errorId : null, helpText ? helpId : null].filter(Boolean).join(' ') || undefined,
  );
</script>

<div class="field" data-testid="checkbox-{name}">
  <label class="checkbox-row" for={fieldId}>
    <input
      id={fieldId}
      {name}
      type="checkbox"
      {disabled}
      bind:checked
      aria-invalid={error ? 'true' : undefined}
      aria-describedby={describedBy}
    />
    <span class="checkbox-label">{label}</span>
  </label>
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
  .checkbox-row {
    display: inline-flex;
    align-items: center;
    gap: 10px;
    cursor: pointer;
  }
  .checkbox-row input[type='checkbox'] {
    width: 16px;
    height: 16px;
    accent-color: var(--accent);
    cursor: pointer;
  }
  .checkbox-row input[type='checkbox']:disabled {
    opacity: 0.55;
    cursor: not-allowed;
  }
  .checkbox-label {
    color: var(--ink);
    font-size: 14px;
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
</style>
