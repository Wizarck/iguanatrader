<script lang="ts">
  type Props = {
    title: string;
    body: string;
    hint?: string;
  };

  let { title, body, hint }: Props = $props();
</script>

<div class="empty-state" data-testid="empty-state">
  <p class="empty-title">{title}</p>
  <p class="empty-body">{body}</p>
  {#if hint}
    <p class="empty-hint">{hint}</p>
  {/if}
</div>

<style>
  .empty-state {
    margin-top: 16px;
    padding: 20px 24px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    max-width: 640px;
  }
  .empty-title {
    margin: 0 0 8px;
    color: var(--ink);
    font-size: 15px;
    font-weight: 600;
  }
  .empty-body {
    margin: 0;
    color: var(--mute);
    font-size: 14px;
    line-height: 1.5;
  }
  .empty-hint {
    margin: 8px 0 0;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.45;
    font-style: italic;
  }
</style>
