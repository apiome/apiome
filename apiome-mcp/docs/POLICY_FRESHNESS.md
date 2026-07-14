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

## Implementation

On each authenticated `tools/call`, `CapabilityCallGateMiddleware`:

1. Reloads key grants via `validate_mcp_api_key` / `resolve_optional_mcp_auth`
   (MTG-1.3 columns on `mcp_api_keys`).
2. Reloads tenant ceiling / defaults via `load_tenant_mcp_policy_snapshot`
   (`tenant_mcp_policies` + `tenant_mcp_policy_tools`).
3. Runs the MTG-1.4 effective resolver.

Neither path may be memoized across calls for the same process.

Admin writes land through tenant MCP policy CRUD (MTG-3.1 / `#4775` when
shipped). Until that PUT exists, freshness is proven by mutating DB-backed
snapshots between sequential middleware calls in CI.

## Acceptance

After PUT (or equivalent) policy, the **next** `tools/call` within the lag
budget reflects the change without redeploy.

## Non-goals (this ticket)

- ≤30s TTL cache
- Version-column invalidate-on-write
- OpenAPI / REST changes
