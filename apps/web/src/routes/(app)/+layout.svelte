<script lang="ts">
  // (app) route group — gated by hooks.server.ts (cookie hook
  // redirects to /login on missing/invalid session). Slice W1 mounts
  // the dashboard skeleton + Sidebar + KillSwitchButton here.
  let { children } = $props();
</script>

{@render children()}
