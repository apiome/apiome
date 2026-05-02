import type { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';

import type { ToolDeps } from './search.js';
import { registerDescribeTool } from './describe.js';
import { registerExecuteTool } from './execute.js';
import { registerSearchTool } from './search.js';

export type { ToolDeps } from './search.js';

export function registerPrimitiveTools(server: McpServer, deps: ToolDeps): void {
  registerSearchTool(server, deps);
  registerDescribeTool(server, deps);
  registerExecuteTool(server, deps);
}
