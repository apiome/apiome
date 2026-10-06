# Agent key quotas & rate limits (AGX-3.2)

**Ticket:** AGX-3.2 ([#4538](https://github.com/apiome/apiome/issues/4538)). Schema: apiome-db
`V272__agent_key_quotas_agx_3_2.sql`. Code: [`apiome_mcp.agent_quotas`](../src/apiome_mcp/agent_quotas.py)
(enforcement), apiome-rest `app.agent_keys.get_agent_key_usage` (reporting).

An agent with no limits can retry in a tight loop and flood an upstream, and the tenant's bill,
within seconds. Every agent key gets two limits from the tenant's license tier.

## Limits per tier (`licenses.seats`)

| Tier | `agent_key_rps` (calls / second / key) | `agent_key_daily_calls` (calls / UTC day / key) |
|---|---|---|
| Free (and unlicensed tenants) | 2 | 1,000 |
| Paid | 20 | 100,000 |
| Sponsor | 100 | 1,000,000 |

- **RPS** is a token bucket per key, with a burst of one second's worth of calls (at least one).
  It works like the mock data plane's `mock_rps`. A fractional rate such as `0.5` is allowed.
- **Daily calls** resets at 00:00 UTC.
- **Zero or a negative value means unlimited.** A missing or non-numeric key gets the Free value.
  V272 seeds the values only where a key is absent, so a value an operator set is kept.
- The tier comes from the tenant's license (`tenant_licenses`). Change the license and the caps
  change within `APIOME_MCP_AGENT_QUOTA_LIMITS_CACHE_SECONDS` (default 60 s).

Both services read the caps through `apiome.agent_key_quota(tenant_id)`, which returns NULL for
an unlimited cap.

## One count of calls made

`apiome.agent_key_call_count(key_id, day)` counts the key's AGX-3.3 `agent_invocations` rows on
that UTC day, leaving out `quota_rejected` refusals (a refused call was never made). The AGX-3.3
rollups read the same rows, so for any key and day:

```
agent_key_call_count(key, day) = SUM(calls - quota_rejections)
                                 FROM agent_invocation_daily WHERE key_id = key AND day = day
```

apiome-rest reports exactly this number. The MCP guard caches it. It re-reads the count every
`APIOME_MCP_AGENT_QUOTA_USAGE_CACHE_SECONDS` (default 5 s) and adds the calls it admitted since.
It also never counts fewer than the calls this process admitted today, so the cap holds even
while invocation recording lags.

## Enforcement (MCP agent surface)

Add the middleware after `AgentAccessMiddleware`, so it runs inside it and sees the verified key:

```python
from apiome_mcp.agent_access import AgentAccessMiddleware
from apiome_mcp.agent_quotas import AgentQuotaGuard, AgentQuotaMiddleware
from apiome_mcp.settings import get_settings

agent_app.add_middleware(AgentAccessMiddleware())
agent_app.add_middleware(AgentQuotaMiddleware(guard=AgentQuotaGuard.from_settings(get_settings())))
```

- Only `tools/call` is limited. `tools/list` and the handshake are not calls.
- A call the access middleware refuses (unknown or non-permitted tool, bad key) never reaches the
  quota check and is not counted.
- The daily cap is checked first, so a key that is out of calls for the day does not use up RPS
  tokens. A refused call counts against neither limit.
- Without a verified key the middleware fails closed (`agent_key_missing`).
- The middleware belongs on the AGX runtime only. The catalog server never mounts it, and a test
  enforces this.

### The refusal

A refused call returns a `tools/call` **result** with `isError: true`. A raised error would lose
its data, because the MCP SDK turns any error raised during `tools/call` into a text-only result.
The text starts with the reason code and says when to retry:

```
agent_daily_cap_reached: this agent key has used its 1000 calls for today (UTC); retry after 3600 s (2026-10-07T00:00:00Z).
```

`structuredContent` carries the same details for agents that parse them. It follows 429
semantics, and `retryAfterSeconds` works like `Retry-After`:

```json
{
  "error": {"code": -32012, "reason": "agent_daily_cap_reached", "message": "…"},
  "reason": "agent_daily_cap_reached",
  "limit": "daily_calls",
  "cap": 1000,
  "used": 1000,
  "retryAfterSeconds": 3600,
  "retryAt": "2026-10-07T00:00:00Z",
  "httpStatus": 429
}
```

| `reason` | `limit` | `retryAfterSeconds` |
|---|---|---|
| `agent_rate_limited` | `rps` | until the bucket has a token (≥ 1) |
| `agent_daily_cap_reached` | `daily_calls` | until the next 00:00 UTC |

Code `-32012` sits next to AGX-3.1's `-32010` (key rejected) and `-32011` (toolset unavailable).
No refusal names the key, its prefix, the tenant or the toolset.

Each refusal is written as one `agent_invocations` row with outcome `quota_rejected` and the reason
as `error_code`, using the toolset's `target`. The rollups' `quota_rejections` therefore counts
them.

### When the database misbehaves

| Failure | Behaviour |
|---|---|
| Caps cannot be read | Last known caps for the tenant, else the Free caps |
| Count cannot be refreshed | Last count, plus calls admitted since |
| Refusal row cannot be written | Logged (`agent_invocation_record_failed`); the refusal is still returned |

## Reporting (key management API)

`GET /v1/tenants/{t}/agent-keys/{id}/usage` (`api_keys:view`) is the data for the AGX-3.4 UI:

```json
{
  "schemaVersion": "agx.agent-key-usage.v1",
  "keyId": "…",
  "licenseType": "free",
  "rps": {"cap": 2.0},
  "dailyCalls": {"day": "2026-10-06", "cap": 1000, "used": 240, "remaining": 760,
                 "resetsAt": "2026-10-07T00:00:00Z"},
  "asOf": "2026-10-06T12:00:00Z"
}
```

`null` caps are unlimited. Revoked keys are reported too.

## Known limits

- **Multiple instances.** The RPS bucket is per process, as on the mock data plane, so N MCP
  instances allow up to N × rps. Each instance sees calls admitted elsewhere only on its next
  count refresh, so a key can overshoot its daily cap by about
  (instances − 1) × rps × `APIOME_MCP_AGENT_QUOTA_USAGE_CACHE_SECONDS`. The usage API never
  reports a negative `remaining`.
- **Mock-target calls count.** Calls to a toolset with `target: mock` use the same caps as
  production calls, because they are invocations like any other.
- **The AGX-2.1 call path is not built yet.** Until it records invocations, the stored count stays
  at zero. The guard then enforces from the calls this process admitted.
