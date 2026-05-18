<script lang="ts">
  export type BadgeVariant = 'success' | 'destructive' | 'accent' | 'mute' | 'warning';

  type Props = {
    label: string;
    variant: BadgeVariant;
  };

  let { label, variant }: Props = $props();
</script>

<span class="badge badge--{variant}" data-testid="badge" data-variant={variant}>
  {label}
</span>

<style>
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: var(--r-pill);
    font-size: 12px;
    font-weight: 600;
    line-height: 1.4;
    letter-spacing: 0.02em;
    text-transform: lowercase;
    border: 1px solid transparent;
  }
  .badge--success {
    background: oklch(72% 0.16 145 / 0.18);
    color: var(--success);
    border-color: oklch(72% 0.16 145 / 0.4);
  }
  .badge--destructive {
    background: oklch(64% 0.2 25 / 0.18);
    color: var(--destructive);
    border-color: oklch(64% 0.2 25 / 0.4);
  }
  .badge--accent {
    background: oklch(72% 0.14 195 / 0.18);
    color: var(--accent);
    border-color: oklch(72% 0.14 195 / 0.4);
  }
  .badge--mute {
    background: oklch(70% 0.012 250 / 0.14);
    color: var(--mute);
    border-color: var(--border);
  }
  .badge--warning {
    background: oklch(82% 0.16 95 / 0.18);
    color: oklch(82% 0.16 95);
    border-color: oklch(82% 0.16 95 / 0.4);
  }
</style>
