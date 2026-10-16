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

### 1.1 Must finish (MVP hardening)

| Phase | Issue | Title | Flags | Area |
| --- | --- | --- | --- | --- |
| A | [#5597](https://github.com/apiome/apiome/issues/5597) | HIVE-11.1 StatusStrip component | mvp | Shared (Versions) |
| A | [#5601](https://github.com/apiome/apiome/issues/5601) | HIVE-11.5 FactsLine and DismissibleCallout primitives | mvp | Shared (Catalog) |
| B | [#5598](https://github.com/apiome/apiome/issues/5598) | HIVE-11.2 Versions — status strip replaces the three banners | mvp | Projects |
| B | [#5599](https://github.com/apiome/apiome/issues/5599) | HIVE-11.3 Versions header — overflow menu and project switcher | mvp | Projects |
| B | [#5600](https://github.com/apiome/apiome/issues/5600) | HIVE-11.4 Versions — one table toolbar | — | Projects |
| C | [#5602](https://github.com/apiome/apiome/issues/5602) | HIVE-11.6 Catalog — quiet list page | mvp | Catalog |
| C | [#4122](https://github.com/apiome/apiome/issues/4122) | MFI-28.6 Skeleton loading states for catalog list & detail | — | Catalog |
| C | [#4124](https://github.com/apiome/apiome/issues/4124) | MFI-28.8 URL-synced detail tabs & accessibility pass | — | Catalog |
| C | [#4121](https://github.com/apiome/apiome/issues/4121) | MFI-28.5 Bulk actions on the catalog list | — | Catalog |
| C | [#4093](https://github.com/apiome/apiome/issues/4093) | MFI-25.8 Provenance tab enrichment | — | Catalog |
| D | [#4009](https://github.com/apiome/apiome/issues/4009) | MFI-22.8 Per-format conversion packs + fixtures | XL | Catalog → Project conversion |
| D | [#3755](https://github.com/apiome/apiome/issues/3755) | MFI-6.3 Catalog categorization | S | Catalog |

Epics these close: [#4116](https://github.com/apiome/apiome/issues/4116) MFI-EPIC-28 (after #4121,
#4122, #4124), [#4078](https://github.com/apiome/apiome/issues/4078) MFI-EPIC-25 (after #4093),
[#4000](https://github.com/apiome/apiome/issues/4000) MFI-EPIC-22 (after #4009).
[#4001](https://github.com/apiome/apiome/issues/4001) MFI-EPIC-23 has one child left, #4021 (below).

### 1.2 Should finish (Projects CLI parity)

The CLI is how CI drives Projects and Versions, so its gaps count against “finished”.

| Phase | Issues | Scope |
| --- | --- | --- |
| E | [#3205](https://github.com/apiome/apiome/issues/3205), [#3206](https://github.com/apiome/apiome/issues/3206), [#3207](https://github.com/apiome/apiome/issues/3207) | `projects update / delete / export` — closes [#3176](https://github.com/apiome/apiome/issues/3176) |
| E | [#3211](https://github.com/apiome/apiome/issues/3211), [#3213](https://github.com/apiome/apiome/issues/3213)–[#3216](https://github.com/apiome/apiome/issues/3216) | `versions fork / unpublish / freeze / compatibility / delete` |
| E | [#3263](https://github.com/apiome/apiome/issues/3263)–[#3266](https://github.com/apiome/apiome/issues/3266) | `tags list / create / update / delete` |
| E (optional) | [#3223](https://github.com/apiome/apiome/issues/3223)–[#3228](https://github.com/apiome/apiome/issues/3228), [#3229](https://github.com/apiome/apiome/issues/3229), [#3231](https://github.com/apiome/apiome/issues/3231), [#3249](https://github.com/apiome/apiome/issues/3249)–[#3252](https://github.com/apiome/apiome/issues/3252) | `properties`, `classes`, `schema arazzo/json/diff`, `browse open` |

### 1.3 Catalog/Projects-related but deferred (new capability, not hardening)

These mention Catalog or Projects but add new features rather than finish existing ones.
Recommendation: leave them out of the MVP and **drop the `mvp` label** from those that carry it.

| Group | Issues | Note |
| --- | --- | --- |
| Catalog Discovery Graph (CDG) | [#5950](https://github.com/apiome/apiome/issues/5950)–[#5983](https://github.com/apiome/apiome/issues/5983) (34) | Gateway connectors, ownership, dependency graph, registries. 13 carry `mvp` — re-flag. |
| Security posture on catalog | [#5921](https://github.com/apiome/apiome/issues/5921) ASP-1.3 (`mvp`) | Security score for catalog revisions — re-flag |
| Designer view of catalog items | [#4021](https://github.com/apiome/apiome/issues/4021) MFI-23.12 | Designer is a commercial surface; non-MVP per its own body |
| Project / batch export | [#4334](https://github.com/apiome/apiome/issues/4334) MFX-39.2 | Depends on the Export studio |
| Repository → project mapping | [#2749](https://github.com/apiome/apiome/issues/2749) (`mvp`), [#2792](https://github.com/apiome/apiome/issues/2792), [#2793](https://github.com/apiome/apiome/issues/2793), [#2806](https://github.com/apiome/apiome/issues/2806) | Multi-repo merge and PR-back sync |
| Agent / registry cataloging | [#3970](https://github.com/apiome/apiome/issues/3970), [#3978](https://github.com/apiome/apiome/issues/3978), [#3980](https://github.com/apiome/apiome/issues/3980) | roadmap candidates |
| MCP catalog | [#3637](https://github.com/apiome/apiome/issues/3637), [#3714](https://github.com/apiome/apiome/issues/3714), [#5724](https://github.com/apiome/apiome/issues/5724) | MCP is held back |
| Format-expansion catalog epics | [#5406](https://github.com/apiome/apiome/issues/5406)–[#5411](https://github.com/apiome/apiome/issues/5411), [#5447](https://github.com/apiome/apiome/issues/5447), [#5477](https://github.com/apiome/apiome/issues/5477), [#5484](https://github.com/apiome/apiome/issues/5484) | More import formats |
| Legacy v2 project ideas | [#510](https://github.com/apiome/apiome/issues/510), [#513](https://github.com/apiome/apiome/issues/513), [#542](https://github.com/apiome/apiome/issues/542), [#544](https://github.com/apiome/apiome/issues/544), [#560](https://github.com/apiome/apiome/issues/560), [#771](https://github.com/apiome/apiome/issues/771), [#1023](https://github.com/apiome/apiome/issues/1023), [#1048](https://github.com/apiome/apiome/issues/1048), [#2594](https://github.com/apiome/apiome/issues/2594) | Favourites, time tracking, heatmaps, archaeology |

Held-back features’ own tickets — e.g. [#5604](https://github.com/apiome/apiome/issues/5604)
(Primitives facts line), [#5606](https://github.com/apiome/apiome/issues/5606) (Style guides notes),
the SDK, MFX, AGX and governance roadmaps — wait until their feature is next in line.
[#5609](https://github.com/apiome/apiome/issues/5609) (HIVE-12.2) re-homes SDK settings and should
account for it being gated.

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
