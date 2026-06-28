<script module lang="ts">
  export const meta = {
    label: 'MCP tools',
    icon: 'arrow-up-right-from-square',
    order: 85
  } as const;
</script>

<script lang="ts">
  import type { PageData } from './$types';

  let { data }: { data: PageData } = $props();

  function pretty(schema: Record<string, unknown>): string {
    return JSON.stringify(schema, null, 2);
  }
</script>

<svelte:head>
  <title>MCP tools · iguanatrader</title>
</svelte:head>

<section aria-live="polite">
  <header class="page-header">
    <h1>MCP server — tool catalogue</h1>
    <p class="hint">
      List of tools the daemon exposes under
      <code>/api/v1/mcp/tools/*</code> for Hermes / Telegram. Each tool
      is a POST authenticated with a bearer token
      (<code>IGUANATRADER_MCP_TOKEN</code>). The equivalent actions
      are also available via session-auth from
      <code>/proposals/{'{'}id{'}'}</code>, <code>/trades/{'{'}id{'}'}</code> and
      <code>/research/{'{'}symbol{'}'}</code> — the MCP endpoint is the
      layer for external integrations.
    </p>
  </header>

  <section class="status-card" data-testid="mcp-status">
    <h2>Server status</h2>
    <dl>
      <dt>Token configured in web</dt>
      <dd>
        {#if data.tokenConfigured}
          <span class="ok">✓ yes</span>
        {:else}
          <span class="bad">✗ no — set <code>IGUANATRADER_MCP_TOKEN</code> in the web container</span>
        {/if}
      </dd>
      <dt>Catalogue accessible</dt>
      <dd>
        {#if data.tools}
          <span class="ok">✓ {data.tools.tools.length} tools registered</span>
        {:else}
          <span class="bad">✗ no — see error below</span>
        {/if}
      </dd>
    </dl>
  </section>

  {#if data.loadError}
    <div class="error" role="alert">{data.loadError}</div>
  {/if}

  {#if data.tools}
    <h2>Tools</h2>
    <ul class="tools">
      {#each data.tools.tools as tool (tool.name)}
        <li class="tool">
          <header>
            <h3><code>{tool.name}</code></h3>
            <span class="endpoint">POST /api/v1/mcp/tools/{tool.name}</span>
          </header>
          <p>{tool.description}</p>
          <details>
            <summary>Input schema</summary>
            <pre><code>{pretty(tool.input_schema)}</code></pre>
          </details>
        </li>
      {/each}
    </ul>

    <section class="hermes-howto">
      <h2>Configure Hermes / Telegram</h2>
      <p>
        On the Hermes host, register the MCP server pointing to the api container:
      </p>
      <pre><code># eligia-core/mcp-servers.yaml (SOPS-encrypted)
servers:
  iguanatrader:
    url: https://iguana.geeplo.com/api/v1/mcp
    auth:
      type: bearer
      token: $&#123;IGUANATRADER_MCP_TOKEN&#125;
    tools_path: /tools</code></pre>
      <p class="hint-small">
        The token must be identical to the one you set in
        <code>/opt/iguanatrader/.env</code> (variable
        <code>IGUANATRADER_MCP_TOKEN</code>) + the tenant slug in
        <code>IGUANATRADER_MCP_TENANT_SLUG</code>.
      </p>
    </section>
  {/if}
</section>

<style>
  section {
    color: var(--ink);
  }
  .page-header { margin-bottom: 16px; }
  .page-header h1 { font-size: 22px; font-weight: 600; margin: 0 0 8px; }
  .page-header .hint {
    margin: 0;
    color: var(--mute);
    font-size: 13px;
    line-height: 1.5;
    max-width: 760px;
  }
  h2 {
    font-size: 16px;
    font-weight: 600;
    margin: 24px 0 12px;
  }
  h3 {
    font-size: 14px;
    font-weight: 600;
    margin: 0;
  }
  code {
    background: oklch(98% 0.01 240 / 0.05);
    padding: 1px 4px;
    border-radius: 3px;
    font-size: 12px;
    color: var(--accent);
    font-family: var(--font-mono);
  }
  .status-card,
  .tool,
  .hermes-howto {
    border: 1px solid var(--border);
    border-radius: var(--r-2);
    background: var(--surface);
    padding: 16px 20px;
    margin: 12px 0;
  }
  .status-card dl {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 8px 16px;
    margin: 0;
    font-size: 14px;
  }
  .status-card dt {
    color: var(--mute);
    font-weight: 500;
  }
  .status-card dd {
    margin: 0;
    color: var(--ink);
  }
  .ok { color: oklch(70% 0.18 145); }
  .bad { color: var(--destructive); }
  .tools {
    list-style: none;
    padding: 0;
    margin: 0;
  }
  .tool header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 8px;
    gap: 12px;
    flex-wrap: wrap;
  }
  .tool .endpoint {
    font-family: var(--font-mono);
    font-size: 11px;
    color: var(--mute);
  }
  .tool p {
    margin: 0 0 12px;
    color: var(--ink);
    font-size: 13px;
    line-height: 1.55;
  }
  details summary {
    cursor: pointer;
    color: var(--accent);
    font-size: 13px;
  }
  details pre {
    margin: 8px 0 0;
    padding: 12px;
    background: oklch(98% 0.01 240 / 0.03);
    border: 1px solid var(--border);
    border-radius: var(--r-1);
    font-size: 12px;
    overflow-x: auto;
    color: var(--ink);
  }
  .hermes-howto pre {
    background: oklch(98% 0.01 240 / 0.03);
    border: 1px solid var(--border);
    border-radius: var(--r-1);
    padding: 12px 14px;
    font-size: 12px;
    line-height: 1.45;
    overflow-x: auto;
    color: var(--ink);
  }
  .hint-small {
    margin: 8px 0 0;
    font-size: 12px;
    color: var(--mute);
    line-height: 1.5;
  }
  .error {
    margin-top: 16px;
    padding: 12px 16px;
    background: oklch(64% 0.2 25 / 0.14);
    border: 1px solid oklch(64% 0.2 25 / 0.4);
    border-radius: var(--r-2);
    color: var(--destructive);
    font-size: 14px;
  }
</style>
