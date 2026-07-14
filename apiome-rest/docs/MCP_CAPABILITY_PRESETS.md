# MCP capability profiles / presets (MTG-5.1)

Named packs let a tenant admin apply a **toolset enable matrix** to the draft
tenant MCP policy in one click. **Custom** remains available: any manual edit
that no longer matches a named pack is treated as Custom.

Source of truth: `app.mcp_capability_presets` (also exposed as
`GET /api-keys/mcp-capability-presets`).

## Documented matrix

Applying a named preset sets `in_ceiling` and `default_enabled` for every tool
in the enabled toolsets, and clears both flags for tools outside those sets.
`anonymous_enabled`, `default_mode`, and `allow_anonymous_mcp` are **not**
changed.

| Preset id | Label | Enabled toolsets |
|-----------|-------|------------------|
| `catalog_only` | Catalog only | `health`, `catalog` |
| `search_catalog` | Search + catalog | `health`, `catalog`, `search` |
| `full_read` | Full read | `health`, `catalog`, `search`, `document`, `structure` |
| `custom` | Custom | *(no matrix — current draft / non-matching state)* |

`health` stays on for every named preset so `ping` remains available.

Canonical toolsets (MTG-1.1): `health`, `catalog`, `search`, `document`,
`structure`.

## Runtime notes

- Preset selection updates the **draft** only; persistence is still the existing
  `PUT /v1/tenants/{tenant_slug}/mcp-policy` replace-all.
- The REST catalog returns named packs only (`custom` is a UI sentinel).
- Matching a loaded policy to a preset: every toolset is fully on or fully off;
  the enabled set must equal a named pack exactly. Any mixed toolset → Custom.

## Related

- `app.mcp_tool_registry` — toolset membership
- Tenants UI MCP Settings panel (MTG-4.2 toolset toggles)
