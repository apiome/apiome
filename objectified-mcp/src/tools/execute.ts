import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as z from 'zod';

import type { ToolDeps } from './search.js';

export function registerExecuteTool(server: McpServer, deps: ToolDeps): void {
  server.registerTool(
    'mcp.execute',
    {
      description: 'Execute a registry action with validated arguments.',
      inputSchema: z.object({
        actionId: z.string(),
        arguments: z.record(z.string(), z.unknown()).optional(),
      }),
    },
    async ({ actionId, arguments: args }) => {
      const payload = deps.registry.execute(actionId, args ?? {}, {});
      return {
        content: [{ type: 'text', text: JSON.stringify(payload) }],
      };
    },
  );
}
