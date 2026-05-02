import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import * as z from 'zod';

import type { ActionRegistry } from '../registry/index.js';
import type { RestClient } from '../upstream/client.js';

export type ToolDeps = {
  registry: ActionRegistry;
  upstream: RestClient;
};

export function registerSearchTool(server: McpServer, deps: ToolDeps): void {
  server.registerTool(
    'mcp.search',
    {
      description: 'Find an action by keyword, category, or resource.',
      inputSchema: z.object({
        q: z.string().describe('Keyword or phrase to match'),
        category: z.string().optional().describe('Optional category filter'),
        resource: z.string().optional().describe('Optional resource filter'),
      }),
    },
    async ({ q, category, resource }) => {
      void deps.upstream;
      const hits = deps.registry.search(q, {});
      const filtered = hits.filter((h) => {
        if (category && h.category !== category) return false;
        if (resource && h.resource !== resource) return false;
        return true;
      });
      return {
        content: [{ type: 'text', text: JSON.stringify({ actions: filtered }) }],
      };
    },
  );
}
