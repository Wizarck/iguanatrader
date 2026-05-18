/**
 * MCP tools catalogue page loader (slice ``frontend-broker-mcp-risk-pages``).
 *
 * The MCP tool routes themselves require a bearer-token (Hermes-side
 * auth); the catalogue listing route at ``GET /api/v1/mcp/tools``
 * shares that requirement. This page therefore reads the token from
 * the deployment env (via a tiny passthrough) so the operator can
 * see what tools the server exposes WITHOUT shipping their token
 * down to the browser.
 *
 * If the token env var is unset on the api container, the route
 * returns 503 and we render a config-required message instead of
 * the catalogue.
 */

import { API_BASE_URL, COOKIE_NAME } from '$lib/config';
import { env as privateEnv } from '$env/dynamic/private';
import type { McpToolList } from '$lib/mcp/types';

import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ fetch, cookies }) => {
  const sessionCookie = cookies.get(COOKIE_NAME);
  const mcpToken = privateEnv.IGUANATRADER_MCP_TOKEN ?? '';

  const headers: Record<string, string> = sessionCookie
    ? { Cookie: `${COOKIE_NAME}=${sessionCookie}` }
    : {};
  if (mcpToken) {
    headers['Authorization'] = `Bearer ${mcpToken}`;
  }

  try {
    const res = await fetch(`${API_BASE_URL}/api/v1/mcp/tools`, { headers });
    if (res.status === 503) {
      return {
        tools: null as McpToolList | null,
        tokenConfigured: !!mcpToken,
        loadError:
          'MCP not configured. Set IGUANATRADER_MCP_TOKEN and IGUANATRADER_MCP_TENANT_SLUG on the api container.'
      };
    }
    if (res.status === 401) {
      return {
        tools: null as McpToolList | null,
        tokenConfigured: !!mcpToken,
        loadError:
          'MCP bearer mismatch — the web container is configured with a token that does not match the api container. Verify IGUANATRADER_MCP_TOKEN is identical on both services.'
      };
    }
    if (!res.ok) {
      return {
        tools: null as McpToolList | null,
        tokenConfigured: !!mcpToken,
        loadError: `No se pudo cargar el catálogo MCP: ${res.status} ${res.statusText}`
      };
    }
    const tools = (await res.json()) as McpToolList;
    return { tools, tokenConfigured: !!mcpToken, loadError: null };
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return {
      tools: null as McpToolList | null,
      tokenConfigured: !!mcpToken,
      loadError: `No se pudo cargar el catálogo MCP: ${message}`
    };
  }
};
