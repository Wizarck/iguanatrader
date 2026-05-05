<script lang="ts">
  // Root layout — slice W1 plants the global stylesheet (Tailwind 4.x +
  // OKLCH tokens in `src/app.css`). All routes inherit dark theme via
  // `<html data-theme="dark">` declared in `src/app.html`.
  import '../app.css';

  let { children } = $props();
</script>

{@render children()}
