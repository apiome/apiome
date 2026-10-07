# Agent invocation proxy (AGX-2.1, rails AGX-2.3)

**Tickets:** AGX-2.1 ([#4533](https://github.com/apiome/apiome/issues/4533)), safety rails AGX-2.3 ([#4535](https://github.com/apiome/apiome/issues/4535), [`agent_safety_rails`](../src/apiome_mcp/agent_safety_rails.py)).
Endpoint: **`/agent/mcp`** on the streamable-HTTP server (`apiome-mcp serve --transport http`).
Code: [`agent_server`](../src/apiome_mcp/agent_server.py) (the app),
[`agent_toolset_source`](../src/apiome_mcp/agent_toolset_source.py) (what is served),
[`agent_invocation_proxy`](../src/apiome_mcp/agent_invocation_proxy.py) (the call path), with
[`agent_argument_validation`](../src/apiome_mcp/agent_argument_validation.py),
[`agent_request_builder`](../src/apiome_mcp/agent_request_builder.py),
[`agent_upstream_auth`](../src/apiome_mcp/agent_upstream_auth.py),
[`agent_upstream_client`](../src/apiome_mcp/agent_upstream_client.py) and
[`agent_result_mapping`](../src/apiome_mcp/agent_result_mapping.py).

An agent connects to Apiome's hosted MCP endpoint with an **agent key** (AGX-3.1), sees its
toolset's tools, and calls them. Each `tools/call` becomes one spec-faithful HTTP request to the
tenant's API (or to the SIM mock), with the tenant's upstream credential injected server-side,
and the answer comes back as an MCP result the agent can act on.

```mermaid
sequenceDiagram
  participant A as Agent (MCP client)
  participant E as /agent/mcp
  participant V as Validation
  participant C as Vault (AGX-2.2)
  participant U as Upstream API / SIM mock
  A->>E: tools/call {name, arguments} + Bearer agent key
  E->>E: AgentAccessMiddleware (key → toolset → permitted tools), AgentQuotaMiddleware
  E->>V: arguments vs inputSchema
  V-->>A: isError invalid_arguments (nothing sent)
  V->>C: build request; prod: open the bound credential
  C->>U: HTTP request, timeout / retry budget
  U-->>E: status + body (bounded)
  E-->>A: body (2xx) or isError + reason + hint
  E->>E: one agent_invocations row (AGX-3.3)
```

## One process, two endpoints

| Path | App | `tools/list` |
|---|---|---|
| `/mcp` | catalog server (MTG) | always the full catalog registry |
| `/agent/mcp` | agent runtime (AGX) | only the key's permitted tools |
| `/health` | liveness | — |

Both apps are mounted by [`http_app.build_http_app`](../src/apiome_mcp/http_app.py) and never
share a `tools/list` ([AGX_COORDINATION.md](AGX_COORDINATION.md)). The agent app runs, in order,
the bearer stash, `AgentAccessMiddleware` ([AGENT_ACCESS.md](AGENT_ACCESS.md)),
`AgentQuotaMiddleware` ([AGENT_QUOTAS.md](AGENT_QUOTAS.md)), and then the toolset provider.

## What is served

The tools are exactly apiome-rest's served view (`GET …/agent-toolsets/{id}/compiled`, AGX-1.3):
the version's canonical model rebuilt from its captured source, accepted description enrichments
written in, compiled by `compile_mcp_tools` over the toolset's enabled operations. Both services
call the same pure functions, so tool names match the stored `tool_name`s an allowlist holds.

- Every request reads one small manifest row (target, slugs, enabled operation keys, accepted
  descriptions, body-capture opt-in). The compile runs only when that changes, and is cached per
  toolset (`APIOME_MCP_AGENT_TOOLSET_CACHE_SIZE`). Enabling a tool, accepting a description or
  flipping `target` applies on the next request.
- A toolset that is missing, disabled, unpublished, or whose source no longer compiles fails
  closed with `agent_toolset_unavailable` (`-32011`).
- No `outputSchema` is declared (AGX-1.1); results carry `structuredContent` anyway.
- The MCP SDK's process-wide tool cache is switched off for this app: tools differ per key, and a
  cache miss would re-run `tools/list` (key verification included) inside every call.

## Per call

1. **Validate.** Arguments are checked against the tool's `inputSchema` (JSON Schema 2020-12).
   Unknown top-level arguments are refused unless the schema allows extras. A failure returns
   every problem and **never reaches the upstream**.
2. **Build the request.** The AGX-1.1 flattening is run backwards: path parameters fill the path
   template, query and header parameters are serialized by their OpenAPI `style` / `explode` /
   `allowReserved` (Swagger 2.0 `collectionFormat` too), and the body is either the remaining
   arguments (flat) or the `body` argument (nested), using the compiler's own rule. Bodies are
   encoded for their media type: JSON, `application/x-www-form-urlencoded`, `multipart/form-data`
   (text fields), text, or anything else as-is.
3. **Route** (AGX-2.4, [MOCK_TARGET.md](MOCK_TARGET.md)). `mock` → `{mock root}/{tenant}/{project}/{version}`
   + path; `prod` → the spec's first absolute `servers` entry (variables take their defaults) + path.
4. **Inject** (`prod` only). The AGX-2.2 credential bound to the exact request URL is opened and
   attached (header, query parameter, `Authorization: Bearer` or `Basic`), replacing any
   same-named header or parameter. No binding → the call goes out bare. A bound credential that
   cannot be opened → `upstream_credential_unavailable`, and nothing is sent.
5. **Call** within the budget (below). Redirects are not followed.
6. **Map** the answer (below) and write one AGX-3.3 invocation row.

### Request rails

| Refused as `invalid_arguments` | Why |
|---|---|
| empty path parameter, or one that serializes to `.` / `..` | would collapse or climb the path |
| header value with CR / LF / NUL | header injection |
| non-object body for a form media type | nothing to encode |

Header arguments that name `Host`, `Content-Length`, `Transfer-Encoding`, `Cookie`,
`Authorization` or any other header the HTTP client or the vault owns are dropped. Every value is
percent-encoded, so an argument cannot add a path segment or query pair.

### Safety rails (AGX-2.3)

[#4535](https://github.com/apiome/apiome/issues/4535), `apiome_mcp.agent_safety_rails`. Each rail
refuses **before anything is sent**, with its own hint-carrying result.

- **SSRF guard: resolve, check, then connect to the checked address.** Every `prod` connection
  opens through `GuardedNetworkBackend`, installed in the upstream client's connection pool. It
  resolves the host, refuses when **any** resolved address is private (RFC 1918), loopback,
  link-local (`169.254.0.0/16`, which covers the `169.254.169.254` metadata endpoint), CGNAT
  (`100.64.0.0/10`, Alibaba's `100.100.100.200`), unique-local (`fd00:ec2::254`), multicast,
  reserved or unspecified (IPv4-mapped and NAT64 IPv6 forms are judged by the IPv4 inside),
  then connects to an address it checked, never to the name. DNS rebinding (a public answer at
  check time, a private one at connect time) therefore cannot reach the socket. TLS still verifies
  the certificate against the host name. The address rule is apiome-rest's
  `app.ssrf_guard.is_disallowed_address`, the same rule as the SIM-3.2 Try It relay. A blocked
  call is not retried → `upstream_blocked`. An unresolvable host is `upstream_unreachable`.
  Resolution counts against the call's time budget.
- **Mock exemption.** The configured mock root (`APIOME_MCP_MOCK_INVOCATION_BASE_URL`, or the
  public root) is deployment infrastructure and is exempt, for requests to exactly its origin
  (scheme, host and port), as in SIM-3.2.
- **No redirects, no environment proxies.** A `3xx` is returned as is. `HTTP(S)_PROXY` is ignored,
  because a proxy would resolve the host outside the guard.
- **Declared method only.** The request must use the method the tool was compiled from, and no
  `X-HTTP-Method-Override` / `X-HTTP-Method` / `X-Method-Override` argument may name another one,
  so a tool compiled from a `GET` never sends anything else → `method_not_allowed`.
- **Request body cap.** `APIOME_MCP_AGENT_REQUEST_MAX_BYTES` (1 MiB) → `request_too_large`.
  Responses are cut at `APIOME_MCP_AGENT_RESPONSE_MAX_BYTES` and marked `[truncated: …]`
  (see Results).
- **Local development.** `APIOME_MCP_AGENT_UPSTREAM_ALLOW_PRIVATE=true` turns the address rule
  off so a `prod` toolset can call a private API. Never set it in a shared deployment.

### MCP annotations

Every served tool carries `annotations`, from the AGX-1.2 `write_op` flag stored for its operation:

| `write_op` | `readOnlyHint` | `destructiveHint` | `idempotentHint` | Description note |
|---|---|---|---|---|
| false | true | false | true | none |
| true, `PUT` / `DELETE` | false | true | true | *Changes data (PUT). Idempotent: … retrying after a failure is safe.* |
| true, `POST` / `PATCH` / other | false | true | false | *Changes data (POST). Not idempotent: … check the current state before retrying.* |

`openWorldHint` is always true. MCP clients can use these to ask for confirmation before
destructive tools.

### Timeout and retry budget

| Setting | Default | Meaning |
|---|---|---|
| `APIOME_MCP_AGENT_UPSTREAM_TIMEOUT_SECONDS` | 30 | one attempt, body read included |
| `APIOME_MCP_AGENT_UPSTREAM_CONNECT_TIMEOUT_SECONDS` | 5 | opening the connection |
| `APIOME_MCP_AGENT_UPSTREAM_MAX_RETRIES` | 2 | retries after the first attempt |
| `APIOME_MCP_AGENT_UPSTREAM_BUDGET_SECONDS` | 45 | all attempts and pauses together |
| `APIOME_MCP_AGENT_UPSTREAM_BACKOFF_SECONDS` | 0.2 | first pause; doubles each retry |
| `APIOME_MCP_AGENT_RESPONSE_MAX_BYTES` | 65536 | body bytes read and returned |

Idempotent methods (`GET`, `HEAD`, `OPTIONS`, `PUT`, `DELETE`, `TRACE`) are retried after a
timeout, a dropped connection, or a `502` / `503` / `504` (honouring `Retry-After` within the
budget). Other methods are retried only when the connection never opened, because only then was
the request certainly not sent.

## Results

**Success (`2xx`)** — the body as the upstream sent it in the first text block; a second
`[truncated: …]` block when it was cut; `structuredContent` = `{httpStatus, contentType, truncated,
body?}` (`body` when the whole response was JSON).

**Failure** — `isError: true`. The text starts with the reason and ends with `Hint: …`;
`structuredContent` carries:

```json
{
  "error": {"code": -32013, "reason": "upstream_not_found", "message": "The API found nothing at GET /pets/{petId} (HTTP 404)."},
  "reason": "upstream_not_found",
  "httpStatus": 404,
  "retryable": false,
  "hint": "Check the identifiers you passed (petId='99'); list or search the collection first to find a valid one. Retrying unchanged will not help.",
  "upstream": {"contentType": "application/json", "body": {"detail": "pet 99 not found"}}
}
```

| `reason` | When | `retryable` | Audit outcome |
|---|---|---|---|
| `invalid_arguments` (code `-32602`, plus `invalidArguments[]`) | refused before the upstream | no | `validation_failure` |
| `upstream_bad_request` | 400 / 422; the hint names the arguments the upstream pointed at | no | `upstream_error` |
| `upstream_unauthorized` / `upstream_forbidden` | 401 / 403; credentials are the tenant's to fix | no | `upstream_error` |
| `upstream_not_found` | 404 / 410; the hint names the path identifiers | no | `upstream_error` |
| `upstream_conflict` | 409 | no | `upstream_error` |
| `upstream_rate_limited` | 429 (`retryAfterSeconds` from `Retry-After`) | yes | `upstream_error` |
| `upstream_client_error` | other 4xx | no | `upstream_error` |
| `upstream_server_error` | 5xx (after safe retries) | yes | `upstream_error` |
| `upstream_redirect` | 3xx (not followed) | no | `upstream_error` |
| `upstream_timeout` | no answer within the budget | yes | `upstream_error` |
| `upstream_unreachable` | could not connect | yes | `upstream_error` |
| `upstream_not_configured` | `prod` and no absolute server URL | no | `internal_error` |
| `upstream_credential_unavailable` | bound credential cannot be opened | no | `internal_error` |
| `upstream_blocked` | the `prod` host resolves to a non-public address (SSRF guard) | no | `internal_error` |
| `method_not_allowed` | the request would use a method the tool does not declare | no | `validation_failure` |
| `request_too_large` | the request body is over `APIOME_MCP_AGENT_REQUEST_MAX_BYTES` | no | `validation_failure` |
| `tool_not_invocable` | the operation has no HTTP method/path | no | `internal_error` |
| `invocation_failed` | an unexpected error inside Apiome | — | `internal_error` |

A non-idempotent call that failed with a 5xx or a timeout adds: *may already have taken effect:
check the current state before calling again*. No result echoes request headers, and if the
upstream itself echoes the injected credential (a debug endpoint, an error page quoting
`Authorization`), every spelling of it in the response body and headers is replaced by
`[redacted]` before mapping, so an upstream credential never reaches the agent.

## Configuration

- **`APIOME_UPSTREAM_CREDENTIAL_ENCRYPTION_KEYS`** — the AGX-2.2 vault key map. It must be the
  same value apiome-rest uses, or `prod` calls with a bound credential fail closed.
- **`APIOME_MCP_MOCK_INVOCATION_BASE_URL`** — where this process reaches the SIM mock, when that
  differs from the public root (`http://mock:8775` inside docker compose). Unset = the public root.
- The table above, and `APIOME_MCP_AGENT_TOOLSET_CACHE_SIZE` (256). See
  [CONFIGURATION.md](CONFIGURATION.md).

## Performance

Overhead per call is one manifest read, the AGX-3.1 key/toolset reads (bcrypt included), the
AGX-3.2 quota check (cached), the audit insert, and request building. The compile is cached. The
acceptance test measures the whole round trip of 40 calls against an instant upstream (key
verification stubbed) and requires P95 < 100 ms; locally it is under 10 ms. A real key's bcrypt
verification (cost 10) is the largest remaining per-request cost and is not cached (AGX-3.1).
Each call logs `agent_invocation` with `latency_ms`, `upstream_ms` and `overhead_ms`.

## Tests

| File | Covers |
|---|---|
| `test_agent_request_builder.py` | the OpenAPI style table, Swagger `collectionFormat`, body modes and encodings, servers, request rails |
| `test_agent_argument_validation.py` | per-argument problems, unknown arguments, value-free messages |
| `test_agent_upstream_client.py` | retries only when safe, back-off, `Retry-After`, budget, truncation, no redirects |
| `test_agent_result_mapping.py` | success shape, truncation marker, one reason + hint per failure class |
| `test_agent_upstream_auth.py` | vault open with apiome-rest's cipher, ledger rows, fail-closed |
| `test_agent_toolset_source.py` | parity with the REST compiled view, enrichments, cache, fail-closed |
| `test_agent_invocation_proxy.py` | the call path: mock/prod routing, injection, validation never sent, audit rows |
| `test_agent_runtime_http.py` | acceptance over streamable HTTP: list + create pets, 400/404/500/timeout, P95, tool annotations |
| `test_agent_server.py` | middleware order, SDK cache off, settings, the guarded lifespan client |
| `test_agent_safety_rails.py` | AGX-2.3: resolve-check-connect, rebinding, real loopback refusal, exact mock-origin exemption, no retry on a block, method/size rails, annotations |
