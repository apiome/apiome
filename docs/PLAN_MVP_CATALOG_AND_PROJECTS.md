# Plan — MVP focus on Catalog and Projects

_Drafted 2026-10-16 from the 1,094 open issues on `apiome/apiome`._

## 0. Decision

Until **Catalog** and **Projects** (including Versions, which is reached by drilling into a project)
are finished and hardened, nothing else gets new work. Six destinations that are not MVP-ready are
**held back**: they stay in the code but cannot be opened.

| Rail item (id) | Route | Why it is held back |
| --- | --- | --- |
| Primitives & types (`primitives`) | `/ade/dashboard/primitives` | Not MVP; HIVE-11.8 and the type-registry roadmap still open |
| MCP servers (`mcp`) — incl. Agent access | `/ade/dashboard/mcp/**` | MCP / agent roadmaps (AGX, AAU, MCP) are post-MVP |
| Export studio (`export-studio`) | `/ade/dashboard/export/studio` | Multi-format export (MFX) is post-MVP |
| SDK settings (`sdk-settings`) | `/ade/dashboard/sdk-settings` | SDK roadmaps are post-MVP |
| Style guides (`style-guides`) | `/ade/dashboard/style-guides/**` | Governance roadmap is post-MVP |
| Access audit (`audit`) | `/ade/dashboard/audit` | Governance roadmap is post-MVP |

Everything else stays enabled — Home, Projects, Catalog, Repositories, Published, Sunset timeline,
Lint posture, Members, Roles, API keys, Tenants — and is hardened as part of this plan before any
held-back feature is released.

### 0.1 How the gate works (`mvp/catalog-projects-focus`)

- **One list:** `apiome-ui/lib/feature-release.ts` → `UNRELEASED_FEATURE_IDS`.
- **Navigation:** `getPlatformNavGroups()` leaves those items out, so the rail, the command
  palette and the `G`-jumps (which all read it) do not list them at all.
- **Direct URLs:** each held-back route has a `layout.tsx` wrapping it in `UnreleasedFeatureGate`,
  which renders a locked “Not available yet” page with **Go to Projects**.
- **Cross-links from released pages:** removed while gated — the Home “Register an MCP server”
  quick action, the member drawer’s “Audit trail” link, the Lint posture MCP-finding link, the
  project facts card’s “Export studio” button, the version spec viewer’s export cards and the export
  dialog’s “Open in Export Studio”. Catalog’s **Export** (row menu and detail CTA) opens the in-place
  export dialog instead of the studio, so catalog items can still be exported.
- **Override:** `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES=all` (or a comma-separated id list) at build
  time re-opens features for development, e2e and docs screenshots.
- **Docs:** the guide pages for held-back features are backed up under `apiome-docs/unreleased/`
  (see its README) and removed from the site, its search and the in-app help catalog. Generated
  reference stays published: the REST/CLI/MCP reference and the three MCP lint-rule catalogs
  (`govern/mcp-*-rules.md`, written by `apiome-rest/scripts/generate_lint_rule_docs.py`).

**Releasing a feature** = remove its id from `UNRELEASED_FEATURE_IDS`, restore its docs pages,
screenshots and help-catalog entries (`apiome-docs/unreleased/README.md`), and add a release note.

---

## 1. Outstanding tickets — Catalog and Projects

Every ticket is a checkbox: tick it when the issue closes. Flags and area follow the dash.

### 1.1 Must finish (MVP hardening)

#### Phase A — Shared primitives

- [x] [#5597](https://github.com/apiome/apiome/issues/5597) HIVE-11.1 StatusStrip component — `mvp` · Shared (Versions)
- [x] [#5601](https://github.com/apiome/apiome/issues/5601) HIVE-11.5 FactsLine and DismissibleCallout primitives — `mvp` · Shared (Catalog)

#### Phase B — Projects / Versions

- [x] [#5598](https://github.com/apiome/apiome/issues/5598) HIVE-11.2 Versions — status strip replaces the three banners — `mvp` · Projects
- [x] [#5599](https://github.com/apiome/apiome/issues/5599) HIVE-11.3 Versions header — overflow menu and project switcher — `mvp` · Projects
- [x] [#5600](https://github.com/apiome/apiome/issues/5600) HIVE-11.4 Versions — one table toolbar — Projects

#### Phase C — Catalog

- [x] [#5602](https://github.com/apiome/apiome/issues/5602) HIVE-11.6 Catalog — quiet list page — `mvp` · Catalog
- [x] [#4122](https://github.com/apiome/apiome/issues/4122) MFI-28.6 Skeleton loading states for catalog list & detail — Catalog
- [x] [#4124](https://github.com/apiome/apiome/issues/4124) MFI-28.8 URL-synced detail tabs & accessibility pass — Catalog
- [x] [#4121](https://github.com/apiome/apiome/issues/4121) MFI-28.5 Bulk actions on the catalog list — Catalog
- [x] [#4093](https://github.com/apiome/apiome/issues/4093) MFI-25.8 Provenance tab enrichment — Catalog

#### Phase D — Conversion

- [x] [#4009](https://github.com/apiome/apiome/issues/4009) MFI-22.8 Per-format conversion packs + fixtures — XL · Catalog → Project conversion
- [x] [#3755](https://github.com/apiome/apiome/issues/3755) MFI-6.3 Catalog categorization — S · Catalog

#### Epics these close

- [x] [#4116](https://github.com/apiome/apiome/issues/4116) MFI-EPIC-28 Catalog UX & Look-and-Feel Improvements — after #4121, #4122, #4124
- [x] [#4078](https://github.com/apiome/apiome/issues/4078) MFI-EPIC-25 Catalog Detail View Parity — after #4093
- [x] [#4000](https://github.com/apiome/apiome/issues/4000) MFI-EPIC-22 Catalog → OpenAPI Conversion & Fidelity Preview — after #4009
- [ ] [#4001](https://github.com/apiome/apiome/issues/4001) MFI-EPIC-23 Catalog Screen & Non-Publishable Cataloged Items — all children done (last, #4021, closed); epic still open on GitHub

### 1.2 Should finish (Projects CLI parity)

The CLI is how CI drives Projects and Versions, so its gaps count against “finished”.

#### Phase E — `projects update / delete / export`

- [x] [#3205](https://github.com/apiome/apiome/issues/3205) CLI 3.4 — `apiome projects update <slug-or-id> (partial flags)`
- [x] [#3206](https://github.com/apiome/apiome/issues/3206) CLI 3.5 — `apiome projects delete <slug-or-id> (typed-confirmation)`
- [x] [#3207](https://github.com/apiome/apiome/issues/3207) CLI 3.6 — `apiome projects export <slug-or-id> (full project JSON dump)`

#### Phase E — `versions fork / unpublish / freeze / compatibility / delete`

- [x] [#3211](https://github.com/apiome/apiome/issues/3211) CLI 4.4 — `apiome versions fork <project> <source-version> --to <new-version>`
- [x] [#3213](https://github.com/apiome/apiome/issues/3213) CLI 4.6 — `apiome versions unpublish <project> <version>`
- [x] [#3214](https://github.com/apiome/apiome/issues/3214) CLI 4.7 — `apiome versions freeze <project> <version> (immutable schema snapshot)`
- [x] [#3215](https://github.com/apiome/apiome/issues/3215) CLI 4.8 — `apiome versions compatibility <project> --base v1 --head v2 (CI exit-code)`
- [x] [#3216](https://github.com/apiome/apiome/issues/3216) CLI 4.9 — `apiome versions delete <project> <version> (with confirmation)`

#### Phase E — `tags list / create / update / delete`

- [x] [#3263](https://github.com/apiome/apiome/issues/3263) CLI 11.4 — `apiome tags list <project> and tags show <project> <tag>`
- [x] [#3264](https://github.com/apiome/apiome/issues/3264) CLI 11.5 — `apiome tags create <project> <tag> --version <version>`
- [x] [#3265](https://github.com/apiome/apiome/issues/3265) CLI 11.6 — `apiome tags update <project> <tag> --version <new-version> (move tag)`
- [x] [#3266](https://github.com/apiome/apiome/issues/3266) CLI 11.7 — `apiome tags delete <project> <tag>`

#### Phase E (optional) — `properties`

- [x] [#3223](https://github.com/apiome/apiome/issues/3223) CLI 6.1 — `apiome properties list <project> (filter, search)`
- [x] [#3224](https://github.com/apiome/apiome/issues/3224) CLI 6.2 — `apiome properties show <project> <name-or-id>`
- [x] [#3225](https://github.com/apiome/apiome/issues/3225) CLI 6.3 — `apiome properties create <project> (interactive + --from-file)`
- [x] [#3226](https://github.com/apiome/apiome/issues/3226) CLI 6.4 — `apiome properties update <project> <name-or-id>`
- [x] [#3227](https://github.com/apiome/apiome/issues/3227) CLI 6.5 — `apiome properties delete <project> <name-or-id> (with usage check)`
- [x] [#3228](https://github.com/apiome/apiome/issues/3228) CLI 6.6 — `apiome properties copy <src-project> <name> --to <dst-project>`

#### Phase E (optional) — `classes`

- [x] [#3229](https://github.com/apiome/apiome/issues/3229) CLI 7.1 — `apiome classes list <project> <version> (--with-properties flag)`
- [x] [#3231](https://github.com/apiome/apiome/issues/3231) CLI 7.3 — `apiome classes create <project> <version> (interactive + --from-file)`

#### Phase E (optional) — `schema arazzo / json / diff`, `browse open`

- [x] [#3249](https://github.com/apiome/apiome/issues/3249) CLI 9.6 — `apiome schema arazzo <tenant>/<project>/<version> [--class X]`
- [x] [#3250](https://github.com/apiome/apiome/issues/3250) CLI 9.7 — `apiome schema json <tenant>/<project>/<version> [--class X] (JSON Schema)`
- [x] [#3251](https://github.com/apiome/apiome/issues/3251) CLI 9.8 — `apiome schema diff <tenant>/<project>/<v1> <v2> (text + machine-readable diff)`
- [x] [#3252](https://github.com/apiome/apiome/issues/3252) CLI 9.9 — `apiome browse open <tenant>/<project>/<version> (open browse URL in default browser)`

#### Epic this closes

- [x] [#3176](https://github.com/apiome/apiome/issues/3176) Projects (CLI) — after #3205, #3206, #3207

### 1.3 Catalog/Projects-related but deferred (new capability, not hardening)

These mention Catalog or Projects but add new features rather than finish existing ones.
Recommendation: leave them out of the MVP. None of them carries the `mvp` label any more (checked 2026-10-16).

#### Catalog Discovery Graph (CDG) — 34 tickets

Gateway connectors, ownership, dependency graph, registries.

- [x] [#5950](https://github.com/apiome/apiome/issues/5950) CDG Roadmap — Catalog Discovery Graph
- [x] [#5951](https://github.com/apiome/apiome/issues/5951) CDG-EPIC-1 Gateway and cloud connectors (absorbs RAR-EPIC-6 #3511)
- [x] [#5952](https://github.com/apiome/apiome/issues/5952) CDG-1.1 Refresh-source protocol and connector registry
- [x] [#5953](https://github.com/apiome/apiome/issues/5953) CDG-1.2 Kong connector (Konnect control planes and Admin API)
- [x] [#5954](https://github.com/apiome/apiome/issues/5954) CDG-1.3 AWS API Gateway connector
- [x] [#5955](https://github.com/apiome/apiome/issues/5955) CDG-1.4 Azure API Management connector
- [x] [#5956](https://github.com/apiome/apiome/issues/5956) CDG-1.5 Apigee connector
- [x] [#5957](https://github.com/apiome/apiome/issues/5957) CDG-1.6 Shadow-API report
- [x] [#5958](https://github.com/apiome/apiome/issues/5958) CDG-1.7 Connectors UI and CLI
- [x] [#5959](https://github.com/apiome/apiome/issues/5959) CDG-EPIC-2 Ownership and routing
- [x] [#5960](https://github.com/apiome/apiome/issues/5960) CDG-2.1 Teams model and RBAC resource
- [x] [#5961](https://github.com/apiome/apiome/issues/5961) CDG-2.2 Ownership on catalog entities
- [x] [#5962](https://github.com/apiome/apiome/issues/5962) CDG-2.3 Owner routing of findings
- [x] [#5963](https://github.com/apiome/apiome/issues/5963) CDG-2.4 Ownership surfaces
- [x] [#5964](https://github.com/apiome/apiome/issues/5964) CDG-2.5 Unowned-entity policy and ownership drift
- [x] [#5965](https://github.com/apiome/apiome/issues/5965) CDG-EPIC-3 Dependency and supply-chain graph
- [x] [#5966](https://github.com/apiome/apiome/issues/5966) CDG-3.1 Graph edge store and materializer
- [x] [#5967](https://github.com/apiome/apiome/issues/5967) CDG-3.2 Declared dependencies
- [x] [#5968](https://github.com/apiome/apiome/issues/5968) CDG-3.3 Blast-radius query
- [x] [#5969](https://github.com/apiome/apiome/issues/5969) CDG-3.4 Dependency graph UI
- [x] [#5970](https://github.com/apiome/apiome/issues/5970) CDG-3.5 Runtime-derived edges
- [x] [#5971](https://github.com/apiome/apiome/issues/5971) CDG-3.6 Graph export and diff-gate annotation
- [x] [#5972](https://github.com/apiome/apiome/issues/5972) CDG-EPIC-4 Registry endpoints
- [x] [#5973](https://github.com/apiome/apiome/issues/5973) CDG-4.1 MCP Registry API over the MCP server catalog
- [x] [#5974](https://github.com/apiome/apiome/issues/5974) CDG-4.2 Schema subject model
- [x] [#5975](https://github.com/apiome/apiome/issues/5975) CDG-4.3 Confluent-compatible subject REST API
- [x] [#5976](https://github.com/apiome/apiome/issues/5976) CDG-4.4 Upstream MCP registry connector
- [x] [#5977](https://github.com/apiome/apiome/issues/5977) CDG-4.5 Registry UI and CLI
- [x] [#5978](https://github.com/apiome/apiome/issues/5978) CDG-EPIC-5 Catalog entity kinds and scorecards
- [x] [#5979](https://github.com/apiome/apiome/issues/5979) CDG-5.1 Entity-kind registry and unified entity list
- [x] [#5980](https://github.com/apiome/apiome/issues/5980) CDG-5.2 Agent and model entities
- [x] [#5981](https://github.com/apiome/apiome/issues/5981) CDG-5.3 Gateway configs as entities
- [x] [#5982](https://github.com/apiome/apiome/issues/5982) CDG-5.4 Catalog facts for per-kind scorecards
- [x] [#5983](https://github.com/apiome/apiome/issues/5983) CDG-5.5 Backstage and Compass import

#### Security posture on catalog

Security score for catalog revisions.

- [x] [#5921](https://github.com/apiome/apiome/issues/5921) ASP-1.3 Security axis and 0–100 security score for catalog revisions

#### Designer view of catalog items

Designer is a commercial surface; non-MVP per its own body.

- [x] [#4021](https://github.com/apiome/apiome/issues/4021) MFI-23.12 Read-only Designer/Studio view of catalog items

#### Project / batch export

Depends on the Export studio.

- [x] [#4334](https://github.com/apiome/apiome/issues/4334) MFX-39.2 Project / batch export

#### Repository → project mapping

Multi-repo merge and PR-back sync.

- [x] [#2749](https://github.com/apiome/apiome/issues/2749) REPO-EPIC-5 Sync Pipeline & Project Mapping
- [x] [#2792](https://github.com/apiome/apiome/issues/2792) REPO-5.7 Multi-repo merge into single API surface
- [x] [#2793](https://github.com/apiome/apiome/issues/2793) REPO-5.8 PR-back sync (Apiome → repository)
- [x] [#2806](https://github.com/apiome/apiome/issues/2806) V2-REPO-8.2 Multi-repo federation (single project from N repos)

#### Agent / registry cataloging

Roadmap candidates.

- [ ] [#3970](https://github.com/apiome/apiome/issues/3970) MFI-EPIC-18 Agent Descriptor Cataloging (A2A / ACP / agentic-web)
- [ ] [#3978](https://github.com/apiome/apiome/issues/3978) MFI-18.5 Registry-as-source ingestion mode (crawl a catalog, not a doc)
- [ ] [#3980](https://github.com/apiome/apiome/issues/3980) MFI-19.2 CloudEvents + xRegistry (CNCF event catalog)

#### MCP catalog

MCP is held back.

- [ ] [#3637](https://github.com/apiome/apiome/issues/3637) V2-MCP External MCP Catalog (consume third-party MCP servers)
- [ ] [#3714](https://github.com/apiome/apiome/issues/3714) V2-MCP-27.4 Catalog analytics dashboard
- [x] [#5724](https://github.com/apiome/apiome/issues/5724) AAU-5.3 MCP Registry API endpoint over the MCP server catalog

#### Format-expansion catalog epics

More import formats.

- [ ] [#5406](https://github.com/apiome/apiome/issues/5406) FMT-EPIC-6 B2B / EDI / vertical depth
- [ ] [#5407](https://github.com/apiome/apiome/issues/5407) FMT-EPIC-7 Gateway & infrastructure route sources
- [ ] [#5408](https://github.com/apiome/apiome/issues/5408) FMT-EPIC-8 Code-first & type-system sources
- [ ] [#5409](https://github.com/apiome/apiome/issues/5409) FMT-EPIC-9 Industrial, IoT & semantic web
- [ ] [#5410](https://github.com/apiome/apiome/issues/5410) FMT-EPIC-10 Client workspace long tail
- [ ] [#5411](https://github.com/apiome/apiome/issues/5411) FMT-EPIC-11 Mainframe long tail
- [ ] [#5447](https://github.com/apiome/apiome/issues/5447) FMT-6.3 SWIFT MT import with MT↔MX projection notes
- [ ] [#5477](https://github.com/apiome/apiome/issues/5477) FMT-10.3 SoapUI / ReadyAPI project import
- [ ] [#5484](https://github.com/apiome/apiome/issues/5484) FMT-11.3 VSAM catalog and CICS BMS map import

#### Legacy v2 project ideas

Favourites, time tracking, heatmaps, archaeology.

- [ ] [#510](https://github.com/apiome/apiome/issues/510) Recently viewed projects
- [ ] [#513](https://github.com/apiome/apiome/issues/513) Pin favorite projects to the dashboard
- [ ] [#542](https://github.com/apiome/apiome/issues/542) Add favorite projects / quick access list
- [ ] [#544](https://github.com/apiome/apiome/issues/544) Add time spent per project breakdown
- [ ] [#560](https://github.com/apiome/apiome/issues/560) Heatmap visualization in versions screen
- [ ] [#771](https://github.com/apiome/apiome/issues/771) When copying versions, offer options to copy paths
- [ ] [#1023](https://github.com/apiome/apiome/issues/1023) Version Archaeology & Cross-Project Comparison
- [ ] [#1048](https://github.com/apiome/apiome/issues/1048) Service Catalog & Internal Marketplace
- [ ] [#2594](https://github.com/apiome/apiome/issues/2594) Project activity timeline correlated with schema revisions

#### Held-back features’ own tickets

These wait until their feature is next in line, along with the SDK, MFX, AGX and governance
roadmaps. #5609 re-homes SDK settings and should account for it being gated.

- [ ] [#5604](https://github.com/apiome/apiome/issues/5604) HIVE-11.8 Primitives & types — facts line over the registry
- [ ] [#5606](https://github.com/apiome/apiome/issues/5606) HIVE-11.10 Style guides, Sunset timeline, Lint posture — standing notes → links; lint stat rows → facts
- [ ] [#5609](https://github.com/apiome/apiome/issues/5609) HIVE-12.2 Re-home Tenants, Data browser · Migrations and SDK settings

---

## 2. Plan of action

| Phase | Work | Depends on | Exit check |
| --- | --- | --- | --- |
| **0. Gate** | Hold back the six features in nav, routes, cross-links and docs (this branch) | — | Rail omits the six; gated URLs show “Not available yet”; `yarn docs:check` passes |
| **A. Shared primitives** | #5597, #5601 | — | Components in the design-system gallery with tests |
| **B. Projects / Versions** | #5598 → #5599 → #5600 | A (#5597) | Versions page has one status strip, one header menu, one toolbar |
| **C. Catalog** | #5602, then #4122, #4124, #4121, #4093 in parallel | A (#5601) | Close #4116 and #4078 |
| **D. Conversion** | #4009, #3755 | — (rest-only, parallel with B/C) | Every importable format has a conversion pack + fixture; close #4000 |
| **E. CLI parity** | §1.2 | — (parallel) | `apiome projects/versions/tags` cover the UI’s verbs; close #3176 |
| **F. Hardening sweep** | See §3 | B, C, D | All §3 checks green |

Recommended order with two people: one on A → B, one on A → C; D and E as fill-in work.

## 3. Hardening checklist (Phase F)

Before **any** held-back feature is released, Catalog and Projects must meet all of these:

1. **End-to-end journey:** a Playwright journey covering import → catalog item → convert to project
   → edit → cut version → publish → unpublish → export, run in CI (extend the OLO journey suite).
2. **Accessibility:** every Catalog, Projects and Versions route passes the HIVE-10.2 axe gate with
   no route-ledger exemptions.
3. **Loading and error states:** skeletons (#4122) and `ErrorState` on every fetch on those pages;
   no blank screen on a slow or failed request.
4. **Export without the studio:** catalog and version export through the in-place dialog covers the
   formats the MVP promises; the dialog’s fidelity report is the only fidelity surface while the
   studio is held back.
5. **Permissions:** viewer / editor / owner matrices tested for every Catalog and Projects action
   (REST and UI), including bulk actions (#4121).
6. **Performance:** catalog list and versions table meet the HIVE-13.3 first-row budget with
   1,000 items.
7. **Docs:** every Catalog, Projects and Versions page in `apiome-docs/` is current, with fresh
   screenshots and no links into held-back features.
8. **Bug bar:** zero open bugs labelled `catalog`, `versions` or project-related at P0/P1.

## 4. Release order for held-back features (proposal)

Once §3 is green, release one at a time, each with its docs restored:
**Export studio** (closest to Catalog/Projects) → **Style guides** (Lint posture already depends on
it) → **Primitives & types** → **SDK settings** → **Access audit** → **MCP servers**.
