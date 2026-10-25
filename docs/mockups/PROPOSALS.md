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

## 5. Round 3 — colour & accent pass (2026-10-25)

> **Status:** proposal. Reviewed 2026-10-25 against `apiome-ui` 0.480 (the RC6 launch build) from the
> documentation screenshots at 1440 × 900 (`apiome-docs/static/img/screens/*.light|dark.png`). The hub
> with every before/after pair is **`proposals/accent-pass.html`**; each page has a live “after” under
> `proposals/accent-*.html` with a **Show before** bar (press `B`) that overlays the shipped screenshot;
> the whole delta is one stylesheet, `assets/hive-accent.css`, loaded after `hive.css`. Nothing here
> changes a route, a permission, a token *value*, a theme, a layout or a line of copy.

### 5.0 TL;DR

Round 2 fixed density and attention; Epics 11–13 shipped it. What is left is that the app is **calm
to the point of plain**: on most pages the navy primary is the only saturated element, the rail is a
grey list, headers are text, stats are a spreadsheet row, records are flat squares, and nothing
reacts to the pointer. This round spends colour where the eye needs an anchor and adds motion where
the hand expects a response — inside the token discipline DESIGN.md already sets.

| # | Finding | Where it shows | Proposal |
| --- | --- | --- | --- |
| 1 | **One hue does all the work.** Colour exists only inside table cells (format pills, badges, grade glyphs); the chrome around them is ink on paper. | every app page | area hues (5.2.1), stat tone (5.2.6), azure selection (5.2.4) |
| 2 | **The rail is a grey list.** Groups are collapsed by default (HIVE-12.1), so the rail is five uppercase labels with counts; every icon is `--fg-subtle`. | shell | hue dot per group, tinted icons, soft active item with a bar (5.2.2) |
| 3 | **Headers are text only.** The mockup index gives every area an icon tile in its hue; the shipped page headers dropped that identity. | Catalog, Projects, Versions, Members, Published, … | area icon tile, crumb dot, hairline (5.2.3) |
| 4 | **Stats are a spreadsheet row.** Label, number, caption; the deltas in `home/overview.html` did not ship. | Home | `Stat` tone, delta chip, sparkline, count-up (5.2.6) |
| 5 | **Records are flat squares.** The hexagon of §2 appears only in the workspace switcher; `build/projects.html` specified `.avatar--hex` for projects. | Projects, Catalog, Home, Versions, Published | `.avatar--record` hex in five identity hues; format edge on cards (5.2.7) |
| 6 | **Hover does nothing.** Cards do not lift, rows tint 2.5 %, the primary has no pressed state. | every list and card | card lift, azure row hover, pressed buttons, primary top-light (5.2.5) |
| 7 | **Selected is black.** Active chips and the tab underline use ink; §2 reserves azure for selected states. | list pages, Versions | chips and tabs select in azure (5.2.4) |
| 8 | **Home is not a landing.** Once the checklist is dismissed the first page after sign-in looks like any list page. | Home | hex pattern + glows behind the greeting, toned attention rows, action tiles (5.2.8–9) |

**Login, Sign-up and the All-apps launcher** already carry the brand (hex pattern, glows, format
pills, azure headline) and are not touched. Dialogs, drawers, the Preferences pane, empty states and
the status strip (HIVE-11.2) are unchanged.

### 5.1 How this was reviewed

* Every released RC6 page was read from the committed documentation screenshots (`yarn docs:screenshots`
  output, 1440 × 900, light and dark, page-only except the theme gallery which shows the shell).
* Five pages were rebuilt as live “after” mockups on the shipped layout — not on the older round-1
  mockups — so each pair differs only in colour, mark and motion: Home, Catalog (HIVE-11.6 layout),
  Projects, Versions (HIVE-11.2–11.4 layout), Members (HIVE-11.9 layout). The rail is compared 1 : 1.
* Every tint uses an existing `-soft` / `-fg` pair, so the contrast gate
  (`tests/a11y-token-contrast.test.ts`) already covers the text-on-tint combinations; the seven theme
  blocks need no new values.

### 5.2 Proposals (numbered as the sections of `assets/hive-accent.css`)

1. **Area hues — six tokens, all pointers.** `--area-build` → `ok`, `--area-bring-in` → `violet`,
   `--area-ship` → `accent`, `--area-govern` → `warn`, `--area-workspace` → `rose`, `--area-tools` →
   `neutral`, each with `-soft` / `-fg`. This is the mapping `index.html` has used since round 1. A page
   declares `data-area` once on `<main>`; the rail declares it per group. Home has no area (it is the
   brand moment).
2. **Rail.** A 6 px hue dot on each group label (it survives the default-collapsed fold); icons tinted
   72 % toward the group hue; the active item becomes `--area-soft` with a 3 px `--area` bar instead of
   the raised white chip. Home keeps the chip. Text stays ink/muted.
3. **Page header.** A 34 px `.icon-tile--area` before the title (Versions puts the project’s hex mark
   there instead); a hue dot on the area crumb; an optional 2 px hairline under the sticky header
   fading out at 40 % width (`.page-header--area`).
4. **Selected = azure.** Tabs: underline, icon and count pill in `accent` / `accent-soft`. Chips:
   `accent-soft` + azure hairline instead of the black pill; hover previews the ring. Sorted column
   header in `accent-fg`. (§2 already says azure is “selected states”; this moves the shipped tabs and
   chips onto spec.)
5. **Alive on touch.** Cards: `card--hover` lifts 2 px with `--shadow-md` and an azure hairline,
   180 ms `--ease-out`; press settles. Rows: hover is azure at 5 % and the primary link underlines in
   `accent-fg`. Buttons: `:active` scales 0.99; the primary gets a top-light gradient
   (`color-mix(ink 86 %, white) → ink`) and a deeper hover shadow — same navy, same copy. Switch thumb
   eases with a small overshoot. All transforms are off under reduced motion.
6. **Stat tone.** `.stat[data-tone]` adds a 24 px icon tile in the tone, `.stat__delta--chip`
   (`+4` in `ok-soft`, `−2` in `danger-soft`) and an optional `.stat__spark`. The figure stays ink and
   counts up on first paint (skipped under reduced motion). Home keeps its full strip; list pages keep
   the facts line.
7. **Records.** `.avatar--record`: the hexagon in one of the five identity hues (`avatar--a…e`, hash of
   the id), so a project keeps its colour across Home, Projects, Versions, Catalog and the switcher.
   People keep the circle; the workspace keeps the brand gradient. `.card--edge` draws a 3 px gradient
   edge in the record’s format hue (`--fmt-openapi` …), the device the launcher tiles already use.
8. **Home band.** `.page-header--brand`: the launcher’s hex pattern plus a honey glow (top) and an azure
   glow (left) at about half the launcher’s intensity, behind the greeting only; the workspace name in
   the description takes the accent. Done checklist steps take the ok tint; the next step keeps the honey
   ring.
9. **Attention rows and action tiles.** `.list-row[data-tone]`: a 3 px tone rail and an icon tile per
   row (warn / danger / ok) instead of a 6 px dot. Quick actions become four `.qa-tile`s, each icon tile
   in the hue of the area it opens.

Per page, the delta is listed in each mockup’s **Notes → Callouts**. Members is deliberately the
smallest (it was already the most coloured list); Home is the largest.

### 5.3 What does not change

Routes, data, permissions, copy, layouts (every first-row budget in `e2e/visual/routes.ts` holds —
the tile sits in the header row, not above it), token *values*, the nine themes, dialogs, drawers,
wizards, the Preferences pane, empty states, the status strip, format pills and method chips, the
honey rule (§2 — honey still marks only brand, new, starred and the next checklist step).

### 5.4 DESIGN.md amendments these imply

| Section | Amendment |
| --- | --- |
| §2 Brand & tone | Add **area hues**: each rail group owns one semantic hue (Build ok · Bring in violet · Ship accent · Govern warn · Workspace rose · Tools neutral), used for the group’s rail icons, the active item, the page-header tile and quick-action tiles — never for status. Home is a brand moment: hex pattern and glows behind the greeting. |
| §3.1 Tokens | `--area-*` (+`-soft`, `-fg`) as pointers; `--fmt-*` hues as tokens so an edge, a chart line and a pill agree. The five identity hues (`avatar--a…e`) join the fixed-hue allow-list beside `.fmt--*`. |
| §5.2 Rail | Group label carries the hue dot; active item = `--area-soft` + 3 px bar; icons tinted toward the hue. |
| §5.3 Page header | The title row starts with the area icon tile (or the record’s hex mark on a record page); the area crumb carries the dot; the 2 px hairline is optional. |
| §7 Components | `Stat` gains `tone`, `delta`, `spark`. `Avatar` gains `shape="hex"` + `hue` for records. `Card` gains `edge`. Tabs and chips select in azure. Buttons gain a pressed state; the primary gains the top-light. |
| §8 Patterns | “Alive on touch”: every card that opens something lifts; every row that opens something tints azure; every button presses; durations and easing from §3.4; reduced motion removes transforms. |
| §12 Roadmap | Add **P9 — Colour & accent pass** (HIVE-14): §5.2.1–4 are the shell and land first; 5–9 are per page and independent. Not RC6 — the first look-and-feel item for RC7. |

### 5.5 Production port

Every item maps onto what exists: `--area-*` aliases in the `:root` block of `globals.css` pointing at
`--color-ok/violet/accent/warn/rose/neutral`; an `area` field on `lib/platform-nav.ts` groups and an
`area` prop on `PageHeader`; the rail classes in `RailNav.tsx` / `railChrome.tsx`; `Tabs.tsx` /
`tabStyles.ts` and the `DataTable` filter chips; `Button.tsx`, `Card.tsx`, `Switch.tsx` and the row
hover rule; `.hive-stat` (`data-tone`, icon, delta chip) with the existing `.hive-sparkline`; `Avatar.tsx`
(`shape="hex"`, `hue` from a hash of the id) and the `hex-allow` fence; Home’s page for the band, tiles
and attention rows. Gates: `hive-design-tokens.test.ts`, `a11y-token-contrast.test.ts`, the axe gate, the
parity harness (re-dump the shell, Home, Projects, Catalog, Versions, Members fixtures), and the
`home` / `catalog` / `projects` / `versions` / `members` docs screenshots. The hub page carries the same
table (`proposals/accent-pass.html` → “Where it lands in apiome-ui”).

### 5.6 Tickets (proposed — not yet filed)

| Child | Scope | Mockup |
| --- | --- | --- |
| HIVE-14.1 | Area-hue tokens + rail (5.2.1–2) | every `proposals/accent-*.html` rail |
| HIVE-14.2 | Page-header tile, crumb dot, hairline (5.2.3) | `accent-catalog.html`, `accent-projects.html`, `accent-members.html`, `accent-versions.html` (title mark) |
| HIVE-14.3 | Selected = azure: tabs, chips, sorted header (5.2.4) | `accent-versions.html`, `accent-catalog.html` |
| HIVE-14.4 | Alive on touch: card lift, row hover, pressed buttons, primary top-light, switch easing (5.2.5) | `accent-pass.html` §5, `accent-projects.html` |
| HIVE-14.5 | Stat tone, delta chip, sparkline, count-up on Home (5.2.6) | `accent-home.html` |
| HIVE-14.6 | Record hex avatars with identity hues; card format edge (5.2.7) | `accent-home.html`, `accent-projects.html`, `accent-catalog.html`, `accent-versions.html` |
| HIVE-14.7 | Home band, action tiles, attention rows (5.2.8–9) | `accent-home.html` |
| HIVE-14.8 | Gates + docs: fence update, fixture re-dumps, screenshots, DESIGN.md §15 → body sections | — |

Each child inherits its mockup’s **Notes → Keeps / Callouts / States** as acceptance criteria, as the
round-2 tickets did.
