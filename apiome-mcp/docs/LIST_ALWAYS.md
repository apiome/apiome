# ADR — List-always invariant (MTG-2.1)

**Catalog MCP (`apiome-mcp`) always returns the full registered tool catalog on
`tools/list`**, regardless of tenant ceiling, tenant defaults, or per-key
enable-set. Governance may deny **`tools/call`** (MTG-2.2) but must never hide
tools from discovery. **Contrast AGX-3.1 (#4537):** agent keys intentionally
filter `tools/list` to the allowlist; reusing that pattern here would break the
product rule that services remain listed irrespective of settings.

Full architecture note (catalog MTG vs agent AGX, shared-code rules, CI guards):
**[AGX_COORDINATION.md](AGX_COORDINATION.md)** (MTG-5.5 / #4789).
