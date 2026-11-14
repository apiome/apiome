# MCP server generator (SDK-4.5, #4499)

`app.mcp_server_generator` turns a persisted `CanonicalApi` into a **runnable MCP server**: a
TypeScript project on `@modelcontextprotocol/sdk` (1.32.2) that an MCP client launches over stdio.
Its tools are the contract's operations, and a tool call is a real HTTP request to the API.

It is a pure function — no clock, no environment, no filesystem — called from `app.sdk_kit`, whose
archive carries the output under `mcp/` (see `public_sdk_kit.md`). The Agent Experience roadmap
(AGX-EPIC-2) hosts and governs this artifact type; this module only defines and generates it.

## Why it generates from the canonical model

SDK-4.5 was scoped to run under the generator SPI (SDK-1.2, #4482) and to wrap the SDK-2.1
TypeScript client (#4485). Both were closed **not-planned**, as was the SDK-1.4 compile-gate matrix
(#4484). Following the SDK-2.4 / 2.5 / 4.4 precedent, the generator reads the persisted canonical
model directly and rides the client kit, and it carries its own small call layer (`src/request.ts`)
in place of the TS client. The compile gate is this repository's own test
(`tests/test_mcp_server_generator.py`).

## Modules

| Module | Role |
| --- | --- |
| `app.mcp_tool_mapping.compile_mcp_tools` (AGX-1.1) | The operation → tool mapping: name, description, `inputSchema`. Shared with the managed MCP proxy and the MCP tool-definition export, so all three agree |
| `app.mcp_operation_binding.binding_for` | The way back: where each argument goes (path / query / header with its OpenAPI style, or a flat / nested body). Extracted from `apiome_mcp.agent_request_builder`, which now imports it |
| `app.terraform_provider_plan.plan_auth_settings` | Security schemes → credential settings, shared with the Terraform provider so both name a credential the same way |
| `app.mcp_server_generator` | Writes the per-contract `src/contract.ts`, `package.json`, `tsconfig.json`, `.env.example` and the README |
| `app.mcp_server_runtime` | The fixed TypeScript, embedded verbatim, plus the pinned dependency versions |

## The generated project

```
mcp/
├── package.json        ESM, `bin`, @modelcontextprotocol/sdk + zod, typescript + @types/node
├── tsconfig.json       strict, NodeNext
├── .env.example        every variable the server reads, credentials empty
├── README.md           install, configure, mcp.json registration, the tool table
└── src/
    ├── contract.ts     generated: SERVER, ENV, DEFAULT_BASE_URL, USER_AGENT, AUTH, TOOLS, PROVENANCE
    ├── types.ts        the schema subset, the binding, the tool and auth table shapes
    ├── validate.ts     JSON-Schema checks for the MCP keyword subset
    ├── request.ts      arguments → request (a port of agent_request_builder.build_request)
    ├── config.ts       base URL, extra headers and credentials from the environment
    ├── handlers.ts     listTools / callTool
    └── server.ts       the only file that imports the MCP SDK: a stdio Server over the handlers
```

Everything but `server.ts` imports nothing outside the project, so the gate compiles the core under
`--strict` and runs it with `node` — no SDK install, no network.

## A call

1. `tools/call` arrives with a tool name and arguments.
2. The arguments are checked against the tool's `inputSchema` (`validate.ts`). Any problem →
   `isError: true` with one line per problem, and **no request is sent**.
3. The binding builds the request: path parameters (`simple` / `label` / `matrix`), query
   parameters (`form`, `spaceDelimited`, `pipeDelimited`, `deepObject`), headers, and a JSON,
   form-encoded, multipart or text body. Every value is percent-encoded; a header argument may not
   set a framing or credential header.
4. The configured credentials, the extra headers and the `User-Agent` are added, and the request
   is sent with a 30 s timeout.
5. The response body becomes the tool result (JSON pretty-printed, cut at 100 000 characters). A
   status of 400 or more is `isError: true`, prefixed `HTTP <status> <reason>`.

## Configuration

| Variable | Holds |
| --- | --- |
| `<PREFIX>_BASE_URL` | The API's base URL. Defaults to the contract's first absolute server; required when there is none |
| `<PREFIX>_HEADERS` | Extra headers as a JSON object — e.g. `{"X-Mock-Session": "demo"}` for the SIM mock |
| `<PREFIX>_TOKEN` | Bearer, OAuth 2, OpenID Connect |
| `<PREFIX>_USERNAME`, `<PREFIX>_PASSWORD` | HTTP Basic |
| `<PREFIX>_API_KEY` | API key, sent in the header, query parameter or cookie the scheme names |

`<PREFIX>` is the project slug in upper snake case (`acme-widgets` → `ACME_WIDGETS`). When two
schemes would take the same name, the later one is prefixed with its scheme name, exactly as the
Terraform provider's settings are. A scheme whose variables are unset is not sent. Mutual TLS and
other schemes with no request representation are listed as unsupported in the README and in the
manifest's `mcp_server.unsupported_auth`.

## Names

- **Package** — `<name>-mcp-server`. A configured npm name is the tenant's *client* library, so
  only its scope is kept: `@acme/widgets` → `@acme/widgets-mcp-server`.
- **Server name** — the package name without its scope; it is what the server reports in
  `initialize` and the key in the README's `mcpServers` snippet.

## Guarantees

- **Deterministic** — the same revision and branding give byte-identical files.
- **No secrets** — the generated code names environment variables, never values.
- **Bounded** — at most 250 tools (`MAX_KIT_OPERATIONS`); the rest are listed under *Not included*.
- **Degrades, never fails the kit** — `app.sdk_kit.plan_mcp_server` turns a generator exception
  into `mcp_server.included: false` with the error.

## Verifying by hand

```bash
cd mcp && npm install && npm run build
SAMPLE_BASE_URL=http://127.0.0.1:8765 SAMPLE_HEADERS='{"X-Mock-Session":"demo"}' node dist/server.js
```

Or register `dist/server.js` with an MCP client. SDK-4.5 was verified this way against the SIM mock
(`apiome-mock run` serving the Petstore corpus fixture): five tools listed, a create / read / list /
delete cycle through the tools, and an out-of-range argument refused without a request.
