# Apiome “Hive” — round-2 proposals (look & feel review of the shipped redesign)

> **Status:** proposal. Reviewed 2026-10-07 against `apiome-ui` 0.351.0 (HIVE-10.6 “Legacy
> cleanup” merged). Each proposal has a browser-openable mockup under `proposals/` built on the
> same `assets/hive.css` / `assets/hive.js` as the rest of this set, with **Notes** (route,
> problem, callouts, keeps, states) and **Callouts** (numbered annotations) in the mock bar.
> Nothing here changes routes, data or permissions; it is chrome, hierarchy and copy.

## 0. TL;DR

The redesign landed and it reads as designed: warm paper surfaces, one rail, azure accent,
status vocabulary, dark and high-contrast themes that hold up. The gaps that remain are not
token or component problems — they are **density and attention** problems that only show on
real pages at real viewport sizes:

| # | Finding | Where it shows | Proposal |
| --- | --- | --- | --- |
| 1 | **Standing furniture pushes data below the fold.** Stat strips, explanatory banners and stacked status banners open most list pages; at 1440 × 900 the first row of data lands 600–870 px down. | Versions, Catalog, Repositories, Primitives, Repository detail, MCP analytics, Members, Style guides, Sunset timeline | `proposals/versions-status-strip.html`, `proposals/catalog-quiet.html` — status strip, facts line, dismissible explainers, one card per list |
| 2 | **Header actions exceed the “one primary + secondaries + overflow” rule.** | Versions (6 controls), Catalog (toggle + primary) | overflow menu, project switcher in the breadcrumb |
| 3 | **The rail does not fit a 900 px-tall window.** 17 items + 5 group labels + 4 footer rows ≈ 1 030 px; Workspace scrolls behind a hidden scrollbar. | every `/ade/dashboard/**` page | `proposals/rail-compact.html` — Workspace collapsed by default, Tenants → workspace menu, SDK settings → Export studio tab, Notifications count |
| 4 | **Unopenable things take prime space.** Four “coming soon”/“planned” surfaces on the launcher (one of them stale: Access audit shipped), SSO/SCIM cards with dead buttons on Members, a gRPC “coming soon” tile in Import. | Launcher, Members, Import wizard | `proposals/launcher-focused.html` — one “Coming next” line, Recently shipped from What’s new; §10 rule |
| 5 | **Honey leaks out of brand moments.** Always-on honey pills (“Preview” in the rail, “gitlike” in headers), a honey-filled saved-search chip on MCP servers. | rail, Versions header, MCP servers | pill → dot (rail); saved searches use `.chip`; honey stays for brand, new, starred |
| 6 | **Three surfaces are still the old UI.** Admin console (`/admin/**`: slate login with a ⚠️ emoji, legacy sidebar), Data browser and Migrations. | `/admin/**`, `/ade/database`, `/ade/migration` | no new mockup — ship roadmap phase **P6** (`admin/*.html`, `tools/*.html` already exist) |

Everything else observed — login, onboarding, Preferences pane, dialogs, drawers, empty states,
tables, format pills, dark/high-contrast parity — matches `DESIGN.md` and needs no change.

## 1. How this was reviewed

* The app was run locally (`next dev`, signed-out routes) and every redesigned page was rendered
  at **1440 × 900** in light and dark from the committed fixture dumps in
  `apiome-ui/e2e/fixtures/hive-*/` — the same real-component output the parity and a11y gates
  mount — plus the live `/login`, `/design-system/**` and `/admin/dashboard` routes. Page
  fixtures were also composited into the shell fixture to judge rail + page together.
* Each mockup in this set was screenshotted beside its shipped page.
* Numbers below are measured on those renders (comfortable density, `md` font scale).

| Page | First row of data (y, 1440 × 900) | What precedes it |
| --- | --- | --- |
| Published | ≈ 236 px | header → table (the baseline the others should meet) |
| Catalog | ≈ 600 px | explainer banner · Supported formats row · 4-stat strip · 2 toolbar rows |
| Repositories | ≈ 600 px | 5-stat strip · Refresh activity panel · toolbar |
| Primitives | ≈ 460 px (collections), ≈ 815 px (types) | 5-stat strip · collections card + aside |
| Versions | ≈ 870 px | 3 stacked banners · artifacts + facts cards · Timeline filter bar · lifecycle toolbar |
| Repository detail | ≈ 650 px | 5-stat strip · branch bar · filter form · selection bar |
| Home | ≈ 400 px (continue cards) | checklist card · 6-stat strip (appropriate here) |

## 2. Proposals

### 2.1 Versions — status strip (`proposals/versions-status-strip.html`)

* **Three banners → one `.status-strip`**: a row of status chips (Compatible · What’s new ·
  Deprecated · [gitlike] Server ahead). Exactly one detail opens at a time; the most severe
  tone opens on first paint; the choice persists for the session. A chip with nothing to say
  is not rendered; a single status renders already open.
* **Header: 6 controls → 4.** Project switcher becomes the last breadcrumb (typeahead menu).
  Compare · Import · ⋯ · **New version**; ⋯ holds Merge branches [gitlike], Sunset timeline,
  Published surface, Export studio, Copy link.
* **One toolbar** per table: search · lifecycle · “Any time” date popover · author menu ·
  state chips · sort. Filters stay in the URL.
* First revision row: ≈ 870 px → ≈ 670 px (≈ 610 px with the strip collapsed).

### 2.2 Catalog — quiet list page (`proposals/catalog-quiet.html`)

The rule, applied to one page so it can be copied to the other six:

* **Explanatory banners show once.** First visit: a dismissible `.callout--dismiss` with
  *Got it* (persists `hive.seen.<id>`) and *Learn more*. After that the same copy lives behind a
  ghost link in the page description (“How the catalog works” → dialog). Nothing is lost,
  nothing stands.
* **Stat strips fold into a facts line** (`.facts`): the same numbers as one tabular sentence
  under the header, with *Show stats* expanding the unchanged `.stat-grid` in place
  (persists per device). Home and the Analytics pages keep full strips — there the numbers
  *are* the page.
* **One card owns the list**: toolbar rows, view chips, view switch and the table.
* Supported formats move into the “How the catalog works” dialog and Import step 1.
* First catalog row: ≈ 600 px → ≈ 345 px.

Candidates for the same treatment: Repositories (stat strip + Refresh activity →
facts line + a “1 stale · 1 failed” chip that opens the panel), Primitives, Repository detail,
Members (seat meter → facts line “4 of 5 seats”; SSO/SCIM cards → one “Coming next” line),
Style guides (“Read-only for members” → ghost link), Sunset timeline (note → ghost link),
Lint posture (two stat rows → facts line + grades).

### 2.3 All apps — focused launcher (`proposals/launcher-focused.html`)

* Applications shows only openable tiles (Control Panel emphasised, Browser, host-injected
  commercial tiles). “Developer Suite — coming soon”, “Community — soon”, “Marketplace — soon”
  collapse into one “Coming next” line that links to What’s new.
* “On the roadmap: Audit — Planned” is stale (Access audit shipped) and becomes
  **Recently shipped** — the three latest What’s new entries, so the launcher cannot advertise
  something the rail already has.
* The build badge leaves the top row (DESIGN.md §5.1 retired it) and lives in the footer, still
  opening What’s new; the top row gains a What’s new icon with the honey unread dot.
* Eyebrow filler (“Jump into the tool you need right now”) is cut per §10.

### 2.4 Rail that fits 900 px (`proposals/rail-compact.html`)

* **Workspace group collapsed by default**, with a count on the label (collapse state already
  persists under `hive.navCollapsed`).
* **Tenants → workspace switcher menu** (“Manage workspaces…”); **SDK settings → Export studio
  tab**; **Data browser · Migrations → user menu** (they have no rail entry today).
* **Notifications shows a count** and leads the footer.
* **“Preview” pill → 6 px honey dot** with the word in the tooltip.
* Rail content ≈ 1 030 px → ≈ 860 px: nothing scrolls at 900 px.

### 2.5 Small things, no mockup needed

| Where | Today | Proposed |
| --- | --- | --- |
| MCP servers · Saved searches | `Public A/B servers` is a honey-filled chip | `.chip` (neutral); honey is brand/new/starred only (§2) |
| Versions / Change report | `gitlike` honey flag pill in header and tabs, always on | render only when `FEATURE_GITLIKE` is on, as `.badge--outline`; honey not for feature flags |
| Export studio header | icon tile above the title; breadcrumb reads “Ship › Back to Versions” | standard header: crumbs `Acme Corp › Ship › Export studio`, icon in the title row, “Back to Versions” as a ghost button |
| Import wizard, step 1 | fixed-height dialog leaves ≈ 450 px empty under eight source tiles; “Next →” uses a glyph | dialog height follows content (`--lg`, min-height for the stepper only); “Continue” per §8 Wizard; recent imports list fills step 1 when present |
| Members · Identity provider | SSO/SCIM cards with `Configure SSO` / `Enable SCIM` buttons that do nothing | one “Coming next” line (same component as the launcher) |
| Admin login | `/admin` still slate/indigo, ⚠️ emoji, “Super Admin” | ship `admin/login.html` (P6) |
| Profile page header | “Edit name” as the page’s one primary | fine — but the hero band gradient (honey → azure) is the only gradient surface in the app; make it `--bg-subtle` with the hex avatar |

## 3. DESIGN.md amendments these imply

| Section | Amendment |
| --- | --- |
| §2 Brand & tone | Honey is never a feature-flag or filter colour. Feature-flag markers are `.badge--outline`; saved searches and filters are `.chip`. |
| §5.1 / §5.2 Shell | Build string lives in the user-menu footer and launcher footer only. Groups may declare `defaultCollapsed`; collapsed labels show a count. Footer order: Notifications (count) · Help · Preferences · user. |
| §5.3 Page header | At most two secondary buttons beside the primary; the rest go to a ⋯ menu. A record switcher (project, repository, endpoint) is the last breadcrumb, not a header select. |
| §5.4 Overlays | New overlay-free pattern **status strip**: one row of status chips, one detail open at a time, most severe first. A page never stacks more than one banner. |
| §8 Patterns · List page | Header → **facts line** (stats folded, *Show stats* expands) → one `.table-wrap` with toolbar(s) → table. Explanatory copy is a dismissible first-visit callout plus a ghost link in the description. Stat strips stay only on Home and Analytics. |
| §10 Content & voice | Unreleased features appear once, as text (“Coming next: …”), never as disabled controls or dead buttons; roadmap copy is generated from What’s new, never hand-written. |
| §12 Roadmap | Add **P8 — Quiet pass**: 2.1–2.4 above plus the §2.2 candidates; depends on nothing, can run alongside P6. |

## 4. Tickets (RC6 milestone)

Planned in `docs/ROADMAP_HIVE_11_QUIET_PASS.md` and created in GitHub on 2026-10-07 as three
epics with 21 child issues, all on the **RC6** milestone.

| Epic | GitHub | Children | Mockup(s) |
| --- | --- | --- | --- |
| 11 — List-page density (“quiet pass”) | [#5594](https://github.com/apiome/apiome/issues/5594) | 11.1 `StatusStrip` #5597 · 11.2 Versions strip #5598 · 11.3 Versions header #5599 · 11.4 Versions toolbar #5600 · 11.5 `FactsLine` + `DismissibleCallout` #5601 · 11.6 Catalog #5602 · 11.7 Repositories #5603 · 11.8 Primitives #5604 · 11.9 Members #5605 · 11.10 Govern/Ship notes #5606 · 11.11 small chrome fixes #5607 | `versions-status-strip.html`, `catalog-quiet.html` |
| 12 — Shell & launcher fit | [#5595](https://github.com/apiome/apiome/issues/5595) | 12.1 default-collapsed groups #5608 · 12.2 re-home Tenants/Tools/SDK #5609 · 12.3 Notifications count #5610 · 12.4 Preview dot #5611 · 12.5 launcher tiles + `ComingNext` #5612 · 12.6 Recently shipped + footer #5613 | `rail-compact.html`, `launcher-focused.html` |
| 13 — Brand discipline, gates & docs | [#5596](https://github.com/apiome/apiome/issues/5596) | 13.1 honey audit + token gate #5614 · 13.2 header/banner/dead-control gates #5615 · 13.3 first-row budget in the parity harness #5616 · 13.4 DESIGN.md + mockups + ledger #5617 | — |
| P6 (existing) | [#5272](https://github.com/apiome/apiome/issues/5272) | HIVE-9.x — admin console; unchanged scope, now the most visible look-and-feel gap left | `admin/*.html`, `tools/*.html` |

Each issue inherits its mockup’s **Notes → Keeps / Callouts / States** as acceptance criteria,
exactly as the P0–P7 tickets did. The four proposal mockups are registered in
`apiome-ui/e2e/visual/routes.ts` as `awaiting-redesign`; HIVE-13.4 moves them into
`PARITY_ROUTES` with the re-dumped page fixtures.
