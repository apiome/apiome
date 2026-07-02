# MCP Catalog — design mockups

Static, self-contained design mockups for the **External MCP Catalog** feature
(the "consume third-party MCP servers" track folded into the V2-MCP roadmap —
epics **V2-MCP-EPIC-15…27**). Full plan: [`ROADMAP_MCP_CATALOGING.md`](../../../ROADMAP_MCP_CATALOGING.md).

These are **for design iteration only** — not production code, not wired to any API,
sample data is illustrative.

## Files

| File | What it is |
|------|------------|
| [`index.html`](./index.html) | Single-file, browser-openable mockup of the final-release UI (all screens via the left rail). No build, no deps. |

## How to view / iterate

```bash
# just open it
xdg-open docs/planning/mockups/mcp-catalog/index.html   # Linux
# or drag the file into a browser
```

Use the **left rail** to switch screens. On the endpoint-detail screen, use the
tab strip (Overview / Capabilities / Versions / Lint & Score / Test / Credentials /
Settings). The **+ Register MCP endpoint** button opens the registration wizard.

To propose a change, edit the HTML directly (the design tokens live in the `:root`
block at the top and mirror apiome-ui: brand indigo `#6366f1`, slate neutrals,
Aptos/Segoe type, 8/12px radii). Each screen ends with a **Design notes** callout
listing open questions to iterate on.

## Screens covered & roadmap mapping

| Screen | Purpose | Roadmap epic |
|--------|---------|--------------|
| **Sidebar** | Adopts apiome-ui's `DashboardSideNav` look (gradient rail, section headers + indigo dot, Lucide icons). **MCP lives under the "Specifications" catalog as "MCP Servers."** | — (UI shell) |
| **Catalog** (endpoint grid) | Reached via *Specifications › MCP Servers*. Grade-led cards, transport/visibility/auth badges, capability counts, health, recency; filter/group/sort. | EPIC-23 (Browse/Search), EPIC-24.1 |
| **Import dialog (MCP source)** | MCP is a **new source in apiome-ui's existing Import flow** (alongside File/URL/Clipboard/Git/SwaggerHub/Postman) — the source-card grid + numbered stepper, then MCP endpoint URL + transport + auth. On import it runs discovery and commits as catalog version 1 via the spec-import job pipeline. **Not** a standalone "register" action. | EPIC-17 (import-source plug-in / jobs), EPIC-24.1 |
| **Endpoint detail · Overview** | Identity header (name/host/grade/health), meta strip, server `instructions`, at-a-glance counts. | EPIC-24.2 |
| **· Capabilities** | Tools/resources/templates/prompts with descriptions, `inputSchema`, annotations; inline lint hints. | EPIC-16.4, EPIC-24.2 |
| **· Versions** | Date/time-tagged version timeline **+ a compare bar to diff any two versions** (base → target selectors, or tick two in the list). The diff panel re-renders per pair (added/removed/modified); non-adjacent pairs aggregate every change between them. | EPIC-18 (fingerprint/diff/tag), EPIC-24.3 |
| **· Lint & Score** | Grade gauge + category bars + findings split **MUST vs SHOULD**. | EPIC-21, EPIC-24.4 |
| **· Test** | Tool picker + schema-driven argument form + result/latency/`isError`, auth-aware, destructive-confirm. | EPIC-22, EPIC-24.5 |
| **· Credentials** | Auth type (None/Bearer/Header/OAuth 2.1), masked secrets, encryption note. | EPIC-20, EPIC-24.6 |
| **· Settings** | Name/URL/cadence/visibility, disable/delete. | EPIC-17.5, EPIC-24 |
| **Public browse** | Distinct public chrome (apiome-browse): search across public tools, browse-by-site, grade-ranked. | EPIC-23.6 |

## Design principles encoded here

1. **Grade-first.** The A–F service grade is the lead glyph everywhere — quality is a
   first-class catalog signal, not buried.
2. **One endpoint, one pipeline.** Every detail tab is a view onto the same
   discover → normalize → fingerprint → version → score → test flow.
3. **Version history is the spine.** MCP has no native capability versioning, so the
   date/time-tagged timeline + diff is a primary surface, not an afterthought.
4. **Secrets are never shown.** Credential fields are masked; the public surface reuses
   a credential-free read model.
5. **Ingestion = Import, not "register."** Adding an MCP server is a new **source** in
   the existing import flow, so it inherits the same wizard, job pipeline, options, and
   dry-run that OpenAPI/Swagger/Postman imports already use.
6. **Lives in the Specifications catalog.** Entry point is the sidebar's
   *Specifications › MCP Servers* item — MCP servers are catalogued specs, not a separate app.
7. **Consistent with apiome-ui** — sidebar chrome, import source-card grid, stepper,
   and tokens mirror `DashboardSideNav` / `ImportDialog` so it can graft onto ADE directly.

## Resolved design decisions

| Question | Decision |
|----------|----------|
| How are MCP servers added? | **Via the existing Import flow as a new "MCP Server" source** (not a bespoke register action). Ingests through the spec-import job pipeline. |
| Where does MCP live in the app? | **Sidebar › Specifications catalog › "MCP Servers"**, adopting `DashboardSideNav` look & feel. |
| Catalog layout & grouping | **Grade-led cards grouped by site/host** (default). Density toggle still open. |
| Lint & Score placement | **Dedicated tab + compact grade summary on Overview.** |
| Test access & destructive tools | **Test always available; tools with `destructiveHint` require an explicit confirm.** |
| Public browse ranking | **Grade-led** (highest service grade first). |

## Still-open questions

- Catalog: add a grid ↔ dense-list **density toggle**, and surface "changed since last view"?
- Public browse: when searching, switch to **relevance → grade** ordering (vs grade-led when idle)?
- **Dark-theme variant** (apiome-ui ships multiple themes) — add a toggle?
- Detail **tab order** — is Overview → Capabilities → Versions → Lint → Test → Credentials → Settings right?

> Next fidelity step (optional): a second mockup for the **periodic sweep / admin**
> view and the **registry import** flow, if those need design review before build.
