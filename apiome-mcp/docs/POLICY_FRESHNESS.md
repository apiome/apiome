# ADR — Policy freshness (MTG-2.5)

**Admins expect a capability disable (or enable) to take effect without
restarting the MCP process.** After a committed policy write, the next
authenticated `tools/call` must reflect that change within the lag budget —
no redeploy required.

## Contract

| Item | MVP value |
|------|-----------|
| Resolution | Postgres on **every** authenticated `tools/call` |
| Lag budget | **`0` seconds** (`POLICY_FRESHNESS_LAG_BUDGET_SECONDS`) |
| In-process cache | **None** (tenant policy + key grants) |

Any call that **starts after** the policy row’s commit must see the new value.
If a future optimization adds a TTL cache or write-time invalidation via a
version column, the lag budget must stay **≤ 30 seconds** and this document
must be updated.

## Decision (DBP-1.21 / #7204): keep `0`, fold the read into the key statement

DBP-1.21 cut the per-call database work. A policy cache (TTL or LISTEN/NOTIFY
invalidation) was considered and **not** adopted: the budget stays `0`. Instead
the catalog reads the key row, the tenant's `tenant_mcp_policies` row and the
**called tool's** `tenant_mcp_policy_tools` row in **one statement**
(`mcp_auth.KEY_AND_POLICY_COLUMNS`). The capability gate uses that prefetched
policy (`capability_policy.PrefetchedToolPolicy`) and runs no query of its own;
the resolvers only ever read the called tool's flags, so a one-tool snapshot
decides exactly like the full one. Fresh policy therefore costs no extra round
trip, and no invalidation channel is needed.

What *is* cached is only the bcrypt outcome of the key (`sha256(secret)` →
key id + hash, `APIOME_MCP_KEY_CACHE_SECONDS`): the key's own row — grants,
revocation, expiry — is still read on every call, in that same statement.

## Implementation

On each authenticated `tools/call`, `CapabilityCallGateMiddleware`:

1. Reloads key grants via `validate_mcp_api_key` / `resolve_optional_mcp_auth`
   (MTG-1.3 columns on `mcp_api_keys`).
2. Reloads tenant ceiling / defaults via `load_tenant_mcp_policy_snapshot`
   (`tenant_mcp_policies` + `tenant_mcp_policy_tools`).
3. Runs the MTG-1.4 effective resolver.

Neither path may be memoized across calls for the same process.

Admin writes land through tenant MCP policy CRUD (MTG-3.1 / `#4775`):
`PUT /v1/tenants/{tenant_slug}/mcp-policy`. After that committed write, the
next authenticated `tools/call` must see the change (lag `0`).

## Acceptance

After PUT (or equivalent) policy, the **next** `tools/call` within the lag
budget reflects the change without redeploy.

## Non-goals (this ticket)

- ≤30s TTL cache
- Version-column invalidate-on-write
- OpenAPI / REST changes
