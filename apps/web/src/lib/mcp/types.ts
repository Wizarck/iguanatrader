/**
 * Frontend mirrors of the MCP tool catalogue DTOs in
 * ``apps/api/src/iguanatrader/api/routes/mcp_tools.py``.
 */

export type McpToolSpec = {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
};

export type McpToolList = {
  tools: McpToolSpec[];
};
