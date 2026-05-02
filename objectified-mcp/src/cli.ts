import { parseArgs } from 'node:util';

import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';

import { ActionRegistry } from './registry/index.js';
import { createObjectifiedMcpServer } from './server.js';
import { RestClient } from './upstream/client.js';

async function main(): Promise<void> {
  const { values } = parseArgs({
    args: process.argv.slice(2),
    options: {
      transport: {
        type: 'string',
        default: 'stdio',
      },
    },
    strict: true,
    allowPositionals: false,
  });

  const transport = values.transport ?? 'stdio';
  if (transport !== 'stdio') {
    console.error(
      `Transport "${transport}" is not implemented yet. Only --transport stdio is supported (see MCP-1.2).`,
    );
    process.exitCode = 2;
    return;
  }

  const registry = ActionRegistry.instance();
  const upstream = RestClient.fromEnv();
  const server = createObjectifiedMcpServer(registry, upstream);

  await server.connect(new StdioServerTransport());
}

await main();
