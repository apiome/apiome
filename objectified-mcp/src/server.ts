import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

import { packageVersion } from './package-info.js';
import type { ActionRegistry } from './registry/index.js';
import { registerPrimitiveTools } from './tools/index.js';
import type { RestClient } from './upstream/client.js';

export function createObjectifiedMcpServer(registry: ActionRegistry, upstream: RestClient): McpServer {
  const server = new McpServer(
    { name: 'objectified-mcp', version: packageVersion() },
    {
      capabilities: {
        tools: {},
        resources: {},
        prompts: {},
        logging: {},
      },
    },
  );

  registerPrimitiveTools(server, { registry, upstream });

  return server;
}
