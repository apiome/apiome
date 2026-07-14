# ADR — Anonymous / unauthenticated call policy (MTG-2.3)

Anonymous MCP clients can still discover the full catalog via **`tools/list`**
(MTG-2.1). Whether they may **`tools/call`** is controlled by the **host
tenant’s** policy when the server is bound to that tenant via environment.

## Host tenant binding

| Setting | Behavior |
|---------|----------|
| `APIOME_MCP_ANONYMOUS_POLICY_TENANT_ID` **unset** | Anonymous `tools/call` is **legacy passthrough** (today’s public behavior). |
| **Set** to a tenant UUID | Load that tenant’s `tenant_mcp_policies` / `tenant_mcp_policy_tools` on **every** anonymous call (freshness lag `0`, same as MTG-2.5). |

Authenticated callers **never** consult anonymous fields; they use MTG-1.4 /
MTG-2.2 only.

## Policy fields

| Column | Table | Default | Meaning |
|--------|-------|---------|---------|
| `allow_anonymous_mcp` | `tenant_mcp_policies` | `true` | Kill switch: when `false`, deny **all** anonymous `tools/call`. |
| `anonymous_enabled` | `tenant_mcp_policy_tools` | `true` | Per-tool anonymous enable-set membership. |

Anonymous enable-set membership follows the same `default_mode` missing-row
rules as ceiling / defaults (`all` → full registry; `inherit_registry` /
`explicit` → row flags). It is **independent of key ceiling** for MVP.
Private-spec tools continue to require keys via `require_mcp_auth` at the tool
layer even when anonymously “enabled.”

Resolver: `app.mcp_effective_policy.resolve_tool_anonymous` (re-exported from
`apiome_mcp.effective_policy`).

## Matrix (auth × list / call)

| Caller | `tools/list` | `tools/call` |
|--------|--------------|--------------|
| Anonymous, env unset | Full catalog | Allow (legacy) |
| Anonymous, env set, `allow_anonymous_mcp=false` | Full catalog | Deny all (`capability_disabled`) |
| Anonymous, env set, tool not in anonymous set | Full catalog | Deny tool |
| Anonymous, env set, tool allowed | Full catalog | Allow (tool may still require key) |
| Authenticated key | Full catalog | MTG-1.4 / MTG-2.2 only — **anonymous fields ignored** |

Denials use stable message token `capability_disabled` with anonymous-specific
wording (never claims the caller presented a key). Anonymous denials are
**structlog only** — no `mcp_capability_denials` rows (MTG-2.4 remains
authenticated-only).

## Related

- Migration `V165__tenant_mcp_anonymous_policy_4772.sql`
- [`EFFECTIVE_POLICY.md`](EFFECTIVE_POLICY.md) — authenticated formula + call flow
- [`LIST_ALWAYS.md`](LIST_ALWAYS.md) — list is never filtered
- [`CONFIGURATION.md`](CONFIGURATION.md) — env variable reference
