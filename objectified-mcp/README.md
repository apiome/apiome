# objectified-mcp

Model Context Protocol server for Objectified. Ships the three primitive tools (`mcp.search`, `mcp.describe`, `mcp.execute`) on top of `@modelcontextprotocol/sdk`, with stdio as the first transport (Streamable HTTP arrives in MCP-1.2).

## Requirements

- Node.js 18+
- Yarn 4 (monorepo root)

## Build

From the repository root:

```bash
yarn workspace objectified-mcp build
```

Equivalent with pnpm:

```bash
pnpm --filter objectified-mcp build
```

## Run locally (stdio)

After a build:

```bash
node objectified-mcp/bin/objectified-mcp.js --transport stdio
```

Or via the workspace binary name once linked:

```bash
yarn workspace objectified-mcp start
```

The process speaks MCP over stdin/stdout; pair it with an MCP-aware client (Cursor, Claude Desktop, etc.) using a config that launches this command.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OBJECTIFIED_REST_URL` | Base URL for `objectified-rest` (default `http://127.0.0.1:8000`). All HTTP calls must go through `src/upstream/client.ts` — do not use raw `fetch` elsewhere. |
| `OBJECTIFIED_MCP_KEY` | API key for upstream auth (wired fully in MCP-1.3 / MCP-1.4). |

## Primitive tools (one-line examples)

- **mcp.search** — `{"q":"list tenants","category":"discovery"}` → returns matching actions from the in-process registry (empty until Epic 3 actions land).
- **mcp.describe** — `{"actionId":"tenant.list"}` → returns JSON Schemas for inputs/outputs when the action exists; otherwise an error payload.
- **mcp.execute** — `{"actionId":"tenant.list","arguments":{}}` → dispatches the action (bootstrap registry returns a stub until actions are registered).

## Tests

```bash
yarn workspace objectified-mcp test
```

## Layout

See issue MCP-1.1 / `docs/PLANNED_FEATURE_ROADMAP_MCP.md` for the full package tree (`registry/`, `upstream/`, `audit/`, `ratelimit/`, etc.).
