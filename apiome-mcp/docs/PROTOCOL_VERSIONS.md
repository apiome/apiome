# MCP protocol versions served by the agent runtime (AAU-4.1, #5714)

What `/agent/mcp` serves, to which clients, is a **pinned table** — not whatever the installed MCP SDK
happens to support. The table below is the contract; `src/apiome_mcp/protocol_versions.py` is the same
table as code and the only place a version is added or removed. The catalog server at `/mcp` is out of
scope here and keeps the SDK's defaults.

## Served-version matrix

| Version | Status on `/agent/mcp` | `initialize` offering it settles on | `MCP-Protocol-Version` header | Self-conformance gate |
|---|---|---|---|---|
| `2026-07-28` | **Served** — accepted per request; stateless requests and `server/discover` arrive with AAU-4.2, the `Mcp-Method`/`Mcp-Name` header plane with AAU-4.3 | `2025-11-25` (the revision has no handshake — see below) | Accepted; handed to the SDK as `2025-11-25`, recorded as `2026-07-28` | ✓ (`2026-07-28` → `2025-11-25`) |
| `2025-11-25` | **Served** | `2025-11-25` | Accepted | ✓ |
| `2025-06-18` | **Served** | `2025-06-18` | Accepted | ✓ |
| `2025-03-26` | **Legacy default** — what a request *without* the header is read as; a client may still negotiate it | `2025-03-26` | Accepted (and assumed when absent) | ✓ |
| `2024-11-05` | **Not served** — the HTTP+SSE era | `2025-11-25` (counter-offer; the client disconnects) | Refused `400` | — |
| anything else | **Not served** | `2025-11-25` (counter-offer) | Refused `400` | — |

**Transport.** `/agent/mcp` is Streamable HTTP only. The deprecated HTTP+SSE transport (`/sse` +
`/messages`) is never mounted on the agent runtime; `GET /agent/sse` is `404`.

**Why a 2026-07-28 `initialize` gets 2025-11-25.** 2026-07-28 drops the `initialize` handshake: every
request carries its own envelope. A server that answers `initialize` with `2026-07-28` claims a revision
it cannot be speaking on that connection — the `protocol.modern-version-via-handshake` conformance
rule. So the handshake counter-offers the newest handshake revision, which is the lifecycle's own
negotiation and exactly what a 2026-era client's auto mode falls back to when its `server/discover`
probe is not answered. Until AAU-4.2 serves `server/discover` and stateless `tools/call`, a 2026-07-28
client reaches the runtime through that fallback.

### Refusing an unsupported version

A request whose `MCP-Protocol-Version` header is not in the table (or that carries two different
values) is refused **before any body is read**, never served at another version:

```http
HTTP/1.1 400 Bad Request
Content-Type: application/json

{"jsonrpc": "2.0", "id": null,
 "error": {"code": -32022,
           "message": "Unsupported MCP-Protocol-Version '1999-01-01'; supported: 2026-07-28, 2025-11-25, 2025-06-18, 2025-03-26",
           "data": {"supported": ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26"], "requested": "1999-01-01"}}}
```

`-32022` is the 2026-07-28 unsupported-protocol-version code; it lies in JSON-RPC's
implementation-defined server-error band, so older clients read it as a server error. The requested
value is echoed back cut to 64 characters. Each refusal logs `mcp_protocol_version_refused`; each
counter-offered `initialize` logs `mcp_protocol_version_counter_offered`.

### The request's version, for middleware and audit

`apiome_mcp.protocol_version_gate.current_protocol_version()` returns the version of the message being
handled: the header's version (`2025-03-26` when absent; the real `2026-07-28` even though the SDK was
handed `2025-11-25`), or for `initialize` the version the handshake settles on. The same value is
bound to the structlog context as `protocol_version`, so every log line and audit event of the message
carries it. AAU-4.7 persists it on `agent_invocations`.

The gate stores the accepted version in the request's ASGI `state`
(`PROTOCOL_VERSION_STATE_KEY`), and `ProtocolVersionNegotiationMiddleware.on_message` reads it back per
message. A ContextVar set at the ASGI layer would not do: the SDK runs a session's messages in a task
started by the session's *first* request, so it would report that request's version forever.

## SDK posture decision: keep `mcp` 1.x + `fastmcp` 3.x, ship an ASGI shim

**Decision.** Keep the installed SDK and ship the shim in `apiome_mcp.http_app` /
`apiome_mcp.protocol_version_gate`. **uv.lock delta: none** — no dependency changes.

| | Installed (kept) | Implements 2026-07-28 |
|---|---|---|
| `mcp` | 1.27.0 — `LATEST_PROTOCOL_VERSION = "2025-11-25"`, `DEFAULT_NEGOTIATED_VERSION = "2025-03-26"`, serves `2024-11-05` | 2.3.0 (2026-10-02) — `server/discover`, per-request envelope, `resultType` |
| `fastmcp` | 3.2.4 | 4.2.0 (requires `mcp` 2.x and the new `mcp-types` 2.x) |

**What the upgrade would cost (measured on this branch, then reverted).** Raising `fastmcp>=4.2.0`
re-locks to `mcp` 2.3.0 + `mcp-types` 2.3.0 and, among others, `starlette` 1.0.0 → 1.10.0, `joserfc`
1.6.4 → 1.8.0, `openapi-pydantic` 0.5.1 → 0.6.0, `py-key-value-aio` 0.4.4 → 0.4.6 and `uncalled-for`
0.3.1 → 0.6.1; it adds `truststore` 0.10.5 and drops `keyring` with its transitive packages
(`jaraco-*`, `jeepney`, `secretstorage`, `more-itertools`, `pywin32-ctypes`).
It breaks the code: `mypy` reports 17 errors in 6 modules and the test suite fails at collection.
The model classes moved to snake_case fields (`ToolAnnotations(read_only_hint=…)`,
`CallToolResult(structured_content=…, is_error=…)`), `mcp.McpError` became `MCPError`, and the
low-level server lost the `_tool_cache` that `agent_server._disable_sdk_tool_cache` switches off —
the guard that keeps one tenant's tool definitions from serving another's. 37 modules (source and
tests) import `mcp` directly, and 92 lines use one of the renamed names.

**Why the shim.** The pieces 2026-07-28 needs first — accepting the header, refusing what is not
served, recording the version per request — sit at the HTTP boundary and need no SDK support. Porting
the security-relevant tool-cache guard and the access/quota middleware to a six-week-old SDK major is
not a spike; it belongs with the work that needs the new SDK's message plane. The shim keeps the
whole stack's behaviour byte-identical for every client that worked yesterday.

**Revisit when** AAU-4.2 (stateless requests, `server/discover`) starts: that is the first piece that
needs a 2026-07-28 message plane rather than a header plane. Re-measure the upgrade then; if it is
taken, `SDK_WIRE_VERSION` and the header rewrite go away, the table here stays.

**Drift guards.** `tests/test_protocol_versions.py` fails if the SDK stops speaking a served handshake
revision, and if this document stops listing an accepted version.

## The self-conformance gate

The catalog's own conformance engine judges the agent runtime, once per version in the table — the
FMT-5.5 pattern of holding Apiome to the rules it publishes.

* **What runs.** `tests/test_agent_self_conformance.py` serves the real HTTP app (Uvicorn, the agent
  runtime at `/agent/mcp`) and discovers it with the catalog's MCP client (`app.mcp_client`) with a
  transcript recorder attached — the same session discovery records for a registered endpoint — then
  runs the `mcp-protocol` profile with `failOn=error`: what `apiome mcp conformance <endpoint>
  --profile mcp-protocol --fail-on error` computes for a snapshot, without the round trip through a
  database.
* **What fails it.** A changed negotiation for any column (`SELF_GATE_NEGOTIATION`), any protocol
  `error` finding, or a skipped rule (every protocol rule must be evaluated, none assumed to pass).
  A version added to `SERVED_PROTOCOL_VERSIONS` without a gate column fails too.
* **Where.** The *Apiome MCP* workflow runs it as its own step, **MCP protocol self-conformance gate**,
  before the full suite, so a regression is named in the check list.
* **Rules for 2026-07-28** (`app.mcp_conformance_rules`, spec version `2026-07-28`):
  `protocol.modern-version-via-handshake` (error), `protocol.result-type-missing` (error) and
  `protocol.deprecated-capability-declared` (info). `protocol.unsupported-protocol-version` now
  recognises `2025-11-25` and `2026-07-28`.

Today every column grades **A** with info findings only: the SDK declares the `logging` capability
(deprecated by 2026-07-28) and an `extensions` key outside the 2025-06-18 vocabulary, and declares
`prompts`/`resources` with nothing in them; the `2026-07-28` column also notes the downgrade to
`2025-11-25`.
