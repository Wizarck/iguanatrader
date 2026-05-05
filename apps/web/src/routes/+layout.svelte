<script lang="ts">
  // Root layout — slice W1 will move tokens.css here. Until then,
  // each page renders its own inline style block (per the slice 4
  // design.md note: "renders inline `<style>` block with the locked
  // OKLCH tokens (W1 will plant `tokens.css` later — until then,
  // inline)").
  let { children } = $props();
</script>

{@render children()}
