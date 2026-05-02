import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as z from 'zod';

import type { ToolDeps } from './search.js';

export function registerDescribeTool(server: McpServer, deps: ToolDeps): void {
  server.registerTool(
    'mcp.describe',
    {
      description: 'Return the JSON Schema contract for a registered action.',
      inputSchema: z.object({
        actionId: z.string().describe('Registry action identifier'),
      }),
    },
    async ({ actionId }) => {
      const spec = deps.registry.describe(actionId, {});
      if (!spec) {
        return {
          content: [{ type: 'text', text: JSON.stringify({ error: 'unknown_action', actionId }) }],
          isError: true,
        };
      }
      return {
        content: [{ type: 'text', text: JSON.stringify(spec) }],
      };
    },
  );
}
