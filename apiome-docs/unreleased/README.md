# Unreleased guide pages

This folder keeps the user-guide pages of features that exist in the code but are **not released**.
They are withdrawn from the site — not built, routed, searched or listed — and kept here verbatim so
each one comes back unchanged when its feature ships.

## Why

The MVP is narrowed to **Catalog** and **Projects**. Until those are hardened, apiome-ui leaves six
rail destinations out of the navigation and gates their routes (`apiome-ui/lib/feature-release.ts`,
`UNRELEASED_FEATURE_IDS`). RC6 (`docs/RC6_OOE.md`) holds back more: the Catalog Discovery Graph
surfaces — Connectors, Shadow APIs, the Dependency graph, Teams and ownership, the Schema registry,
and the agent, model and component kinds with their Backstage/Compass import reports and scorecards
— and a project's consumer contracts. RC7 released the Catalog's import paths again —
`connectors`, `schema-registry` and `catalog-entities` — and their pages, fragments and screenshots
went back (release-notes post `2026-10-25-rc7-catalog-import`). One id still held back has no rail
item of its own: `consumers`; it gates a route and panels inside Projects. A guide page for a screen nobody can open would send readers to a dead
end, and the docs gate rejects `draft: true` and `unlisted: true` (orphan-page rule), so the pages
moved out of `docs/` instead.

Nothing in the build reads this folder: Docusaurus serves `docs/`, `release-notes/`, `src/pages/`
and `static/`; `yarn docs:check` (`scripts/check-docs.mjs`) reads `docs/`, `release-notes/`,
`screens.json`, `static/` and `sidebars.ts`; `yarn docs:screenshots` and the weekly refresh read
`screens.json`; and `scripts/check-loose-docs.sh` skips all of `apiome-docs/`. Keep it that way —
do not point any of them at `unreleased/`.

## What is here

| Page | Feature | Original path | Rail item id |
| --- | --- | --- | --- |
| Primitives and types | Primitives & types | `docs/build/primitives-and-types.mdx` | `primitives` |
| MCP servers | MCP servers | `docs/bring-in/mcp-servers.mdx` | `mcp` |
| Agent access | MCP servers (Agent access, `/ade/dashboard/mcp/agents`) | `docs/bring-in/agent-access.mdx` | `mcp` |
| Style guides | Style guides | `docs/govern/style-guides.mdx` | `style-guides` |
| Style-guide revisions and audit | Style guides | `docs/govern/style-guide-revisions.md` | `style-guides` |
| Access audit | Access audit | `docs/govern/access-audit.mdx` | `audit` |
| Export studio | Export studio | `docs/ship/export-studio.mdx` | `export-studio` |
| SDK settings | SDK settings | `docs/ship/sdk-settings.mdx` | `sdk-settings` |
| Shadow APIs | Shadow APIs | `docs/govern/shadow-apis.mdx` | `shadow-apis` |
| Dependency graph | Dependency graph (and the Dependencies tabs) | `docs/govern/dependency-graph.mdx` | `dependency-graph` |
| Teams | Teams and ownership | `docs/workspace/teams.mdx` | `teams` |

Each page sits at `unreleased/<original path>`.

**Fragments** — sections cut from pages that stayed on the site, each with a comment saying where it
goes back:

| Fragment | Goes back into | Rail item id |
| --- | --- | --- |
| `fragments/bring-in/import-wizard.add-mcp-server.mdx` | `docs/bring-in/import-wizard.mdx` — the **Add MCP server** row and note, the screenshot caption, and the **Postman Collection** and **MCP Server** sections | `mcp` |
| `fragments/ship/mock-try-out.test-drive-an-export.mdx` | `docs/ship/mock-try-out.mdx` — the **Test-drive an export** section, before **With the CLI or the API** (plus the third table row and “three ways” intro) | `export-studio` |
| `fragments/getting-started/browse-and-export.export-another-format.mdx` | `docs/getting-started/browse-and-export.mdx` — replaces the **Export another format** section | `export-studio` |
| `fragments/build/projects.consumers.mdx` | `docs/build/projects.mdx` — the **Consumers** menu row and section, the **Owner** section, and the `projects-table` alt text | `consumers`, `teams` |
| `fragments/build/versions.dependencies.mdx` | `docs/build/versions.mdx` — the **Dependencies** section, before **Conversion** | `dependency-graph` |
| `fragments/bring-in/catalog.entity-kinds-and-ownership.mdx` | `docs/bring-in/catalog.mdx` — the Teams link, owner column and owner filter in **Kinds**, the **Opens** column of **Home callouts**, the **Dependencies** tab row and tab id, the **Owner** section and **Assign owner** in the bulk bar (RC7 put back the rest) | `dependency-graph`, `teams`, `shadow-apis` |
| `fragments/bring-in/repositories.connectors-and-backstage.mdx` | `docs/bring-in/repositories.mdx` — the declared-dependency table and paragraph of **Backstage files** (RC7 put back the rest) | `dependency-graph` |
| `fragments/ship/published.owner.mdx` | `docs/ship/published.mdx` — the **Owner** column row and the owner filter sentence | `teams` |
| `fragments/workspace/tenants.ownership.mdx` | `docs/workspace/tenants.mdx` — the manage drawer's **Ownership** section and its mentions in the drawer intro | `teams` |

**Screenshots** — `unreleased/screens.json` holds the manifest entries (same `{"screens": [...]}`
shape as `../screens.json`) and `unreleased/static/img/screens/` their light and dark images:

| Rail item id | Screenshot ids |
| --- | --- |
| `primitives` | `primitives`, `primitives-how-resolution-works`, `primitives-namespaces`, `primitives-resolver`, `primitives-settings`, `primitives-import`, `primitives-editor`, `primitive-detail`, `primitive-testing` |
| `mcp` | `mcp-servers`, `mcp-servers-grid`, `mcp-endpoint-versions`, `mcp-endpoint-capabilities`, `mcp-endpoint-lint`, `mcp-endpoint-settings`, `mcp-analytics`, `mcp-capabilities`, `mcp-compare`, `import-wizard-mcp`, `agent-access`, `agent-access-keys`, `agent-access-usage` |
| `style-guides` | `style-guides`, `style-guides-readonly`, `style-guides-create-dialog`, `style-guides-assign-dialog`, `style-guides-policies`, `style-guides-verification-policy`, `style-guide-builtin`, `style-guide-rules`, `style-guide-custom-rule`, `style-guide-policy` |
| `audit` | `audit`, `audit-filtered`, `audit-drawer`, `audit-chain` |
| `export-studio` | `export-studio`, `export-studio-source`, `export-verify`, `export-studio-job`, `export-studio-failure`, `export-studio-gate`, `mock-test-drive` |
| `sdk-settings` | `sdk-settings` |
| `connectors` + `export-studio` | `export-studio-gateway` (Push back opening the Export studio; RC7 released Connectors with the Export dialog instead) |
| `shadow-apis` | `shadow-apis`, `shadow-apis-link` |
| `dependency-graph` | `dependency-graph`, `dependencies-tab`, `dependencies-runtime`, `blast-radius` |
| `teams` | `teams`, `team-detail`, `ownership-drift`, `catalog-owner-filter`, `tenant-ownership-policy` |
| `catalog-entities` + `mcp` | `scorecard-kind` (the Facts of an MCP server; RC7 released catalog facts, the Scorecards page uses `entity-facts`) |
| `consumers` | `project-consumers-bindings` |

**Not withdrawn**, on purpose: the MCP rule catalogs (`docs/govern/mcp-*-rules.md`, generated by
`apiome-rest/scripts/generate_lint_rule_docs.py`, linked from the generated MCP reference and
returned as `docs_page` by the REST rule endpoints), `getting-started/connect-an-mcp-host.mdx`,
`reference/mcp-quickstart.md`, `ship/export-fidelity.md` (it explains the Export dialog's fidelity
step too) and everything under `docs/reference/` — the REST, CLI and MCP surfaces still exist.

## Restore a feature

Do all of it in the pull request that releases the feature. `<id>` is its rail item id.

1. **Move its pages back**, keeping history:
   `git mv apiome-docs/unreleased/docs/<group>/<page> apiome-docs/docs/<group>/<page>`.
2. **Put back its fragments** (table above) where their comments say, then delete the fragment
   files.
3. **Restore its screenshots**: move each of its entries from `unreleased/screens.json` back into
   `../screens.json`, and `git mv` each `unreleased/static/img/screens/<id>.{light,dark}.png` back to
   `static/img/screens/`. Delete `unreleased/screens.json` once it is empty.
4. **Restore its help-catalog entries** in apiome-ui: move them from `UNRELEASED_GUIDE_ENTRIES` to
   `GUIDE_ENTRIES` in `apiome-ui/src/app/components/ade/help/helpCatalog.ts`
   (`apiome-ui/tests/help-catalog.test.ts` checks the catalog against `docs/`). Check
   `apiome-ui/src/app/utils/docsLinks.ts` too.
5. **Release it in the UI**: remove `<id>` from `UNRELEASED_FEATURE_IDS` in
   `apiome-ui/lib/feature-release.ts`.
6. **Re-add the links** the withdrawal took out. The pages edited were the section indexes
   (`build/`, `bring-in/`, `ship/`, `govern/` `index.mdx`), `getting-started/index.mdx`,
   `getting-started/launcher-and-home.mdx` (the coming-soon sentence and the *Register an MCP server*
   quick action), `getting-started/browse-and-export.mdx`, `build/versions.mdx`,
   `build/version-dialogs.mdx`, `build/lint-and-quality.md`, `bring-in/import-wizard.mdx`,
   `bring-in/import-a-spec.md`, `ship/mock-try-out.mdx`, `ship/export-a-spec.md`,
   `ship/export-fidelity.md`, `govern/reviews.mdx`, `govern/lint-posture.mdx`,
   `workspace/index.mdx`, `workspace/members.mdx`, `workspace/roles.mdx`, `workspace/api-keys.mdx`,
   `workspace/tenants.mdx`, `workspace/help.mdx`, and the 2026-10-07 release-notes posts for Build,
   Bring in, Ship and Govern.
   The RC6 withdrawal (`connectors` … `consumers`) also edited `build/projects.mdx`,
   `bring-in/catalog.mdx`, `bring-in/repositories.mdx`, `bring-in/index.mdx`, `ship/index.mdx`,
   `ship/published.mdx`, `ship/publish-a-version.md`, `govern/index.mdx`, `workspace/index.mdx` and
   `getting-started/index.mdx` by hand, and pointed links into withdrawn pages at their REST
   reference instead (`reference/rest/connectors.md`, `graph.md`, `teams.md`, `owners.md`,
   `schema-registry.md`, `catalog-agents.md`, `catalog-migrations.md`, `catalog-entities.md`,
   `consumer-contracts.md`) in the format-import pages, `govern/lint-posture.mdx`,
   `govern/runtime-usage.mdx`, `ship/export-fidelity.md`, `ship/export-to-a-gateway.md`,
   `ship/sunset-timeline.mdx`, `workspace/api-keys.mdx`, `workspace/notifications.mdx`,
   `workspace/roles.mdx` and the 2026-10-17 … 2026-10-20 release-notes posts. Point them back at the
   guide page (and its anchor) that the restored feature brings back. `git log -p --follow` on any of them shows what changed;
   `grep -rn "not yet available" apiome-docs/docs` finds the placeholders.
   RC7 (`connectors`, `schema-registry`, `catalog-entities`) restored its pages with the parts that
   lean on still-gated features rewritten: `bring-in/connectors.mdx`, `bring-in/agents-and-models.mdx`,
   `bring-in/migrate-from-backstage-or-compass.mdx` and `govern/scorecards.mdx` link to
   `reference/rest/graph.md`, `owners.md`, `teams.md` and `connectors.md` (shadow report) instead
   of the Dependency graph, Teams and Shadow APIs pages, and leave out the **Owner** and **Graph**
   sections of entity pages, the agent page's **Usage** link and the component page's **Open the
   dependency graph** link. `bring-in/catalog.mdx` **Home callouts** says the Unowned and Shadow
   pages are not available yet. Put those back with `teams`, `dependency-graph` and `shadow-apis`.
   For `primitives` and `mcp`, also point the legacy-docs area rules back at the restored page:
   the `PRIMITIVE|…` and `MCP` entries of `AREA_PAGES` in `scripts/legacy_docs_inventory.py` (now
   `build/edit-classes-and-properties` and `getting-started/connect-an-mcp-host`), and the matching
   links in `docs/archive/INVENTORY.md`; `python3 -m unittest scripts/tests/test_loose_docs.py`
   fails if a rule names a page that is not on the site.
7. **Recapture its screenshots** — the route is gated, so re-open it for the run:
   `NEXT_PUBLIC_APIOME_PREVIEW_FEATURES=<id> yarn docs:screenshots -- --id <screenshot-id>` (or
   without the variable once step 5 is in the build), and update any copy that changed meanwhile.
8. **Add a release-notes post** under `release-notes/` saying the feature and its guide are back.
9. **Run `yarn docs:check`** from the repository root.
