# Projects mockups

A polished, opinionated redesign of the **Projects** surface mounted at
[`/ade/dashboard/projects`](../../../src/app/ade/dashboard/page.tsx) in
the live app.

Today's production page is a flat table with create/edit dialogs and no
per-project home page. This set proposes:

| File                     | Maps to                                    | What's new                                                                                       |
| ------------------------ | ------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| `dashboard.html`         | `/ade/dashboard/projects`                  | KPI band · saved-view chips · card portfolio with quality/lint rings, contributors, status, domain pill · portfolio quality trend · activity feed |
| `detail.html`            | _new_ — `/ade/dashboard/projects/[id]`     | **Overview tab.** Gradient header, KPI band, About panel (full OpenAPI metadata), version pipeline funnel, largest-classes list, quality-history sparkline, contributors, activity timeline, danger zone preview |
| `detail-versions.html`   | _new_ — `…/[id]?tab=versions`              | **Versions tab.** Trajectory chart (quality across all 9 versions), release-lane timeline, filter chips, full table with diff stats, breaking-change indicators, selected-version drawer with reviewer state, channel/tag mapping (`latest` / `stable` / `next` / `lts`) |
| `detail-classes.html`    | _new_ — `…/[id]?tab=classes`               | **Classes tab.** Version selector, KPI strip (PII · regulated · most-changed), filter chips, two-pane layout — grouped class list (Money · People · Disputes · Reports · Webhook payloads) on the left, class detail on the right with property table, FK/PK/PII tags, references graph (inbound/outbound) |
| `detail-classes-graph.html` | _new_ — `…/[id]?tab=classes&view=graph` | **Classes tab · Graph view.** Force-directed class-reference visualization. Layout selector (Force / Circular / Hierarchical), grouping, filter chips (Hide orphans · Hide deprecated · Highlight PII · Min refs ≥ N), search-and-focus box, full-bleed grid-backed canvas with cluster halos (Money · Customer · Disputes · Reports · Webhook payloads), color-coded nodes sized by importance, curved arrowed edges with FK labels on highlighted paths, focused-node ring with cycle indicator, zoom/fit/re-layout overlay, legend, and a focused-class right rail (out/in refs · cycle warning · graph-health stats) |
| `detail-properties.html` | _new_ — `…/[id]?tab=properties`            | **Properties tab.** Project-wide property browser. KPI strip (218 properties · 17 unique types · 14 PII · 11 inconsistencies), type-distribution histogram, inconsistency callout (same name → different types), filter chips (Required · PII · FK · Computed · Deprecated · Inconsistent), cross-class table with usage counts, lint grades, drift indicators, selected-property usage drawer (definition + every class that uses it + consistency check), and a naming-convention adherence card |
| `detail-published.html`  | _new_ — `…/[id]?tab=published`             | **Published tab.** Channel & consumer view. KPI strip (4 channels · 7 consumers · downloads · sunset countdown), four channel cards (`latest` / `stable` / `next` / `lts-2024`) each showing pinned version, consumer avatars, 30-day download count and spec URL, consumer table (channel · pinned version · last fetch · health), deprecation timeline with sunset countdown for at-risk versions, recent publishes mini-list, and copyable spec endpoint URLs (yaml / json / sdk / changelog.rss) |
| `detail-activity.html`   | _new_ — `…/[id]?tab=activity`              | **Activity tab.** Full audit history. KPI strip (events · top actor · top event type · breaking changes), 30-day daily-volume bar chart with publish-day highlights, filter chips by event family (Publishes · Reviews · Schema · Settings · Integrations · Breaking) plus actor and date pickers, day-grouped sticky-headed timeline of color-coded events with deep links into Versions/Classes/Settings, top-actors leaderboard, event-type breakdown, and subscribe / export endpoints (rss / json / Slack) |
| `detail-settings.html`   | _new_ — `…/[id]?tab=settings`              | **Settings tab.** Section nav (General · OpenAPI metadata · Visibility &amp; access · Lifecycle · Notifications · Integrations · API tokens · Audit log · Danger zone), with working toggle switches, reviewer list, notifications matrix, integration cards (GitHub · webhook · Slack · CI), token table, audit timeline, and a four-action danger zone (transfer · disable · soft delete · permanent) |
| `wizard-path.html`       | _new_ — wizard step 1                                           | **Step 1 · Choose path.** Four large path cards (Manual / Import OpenAPI / Design with AI / From repository) with usage stats, supporting bullets, sub-options (file upload / URL / paste for OpenAPI; example prompt for AI; connected-repo list for repo scan), a "not sure?" help strip, and a disabled Back button |
| `wizard.html`            | _new_ — wizard step 2                                           | **Step 2 · Basics.** Path summary chip with "Change path" deep link, project basics form (name · slug with auto-derive · description with "Improve with AI" · domain category · visibility radio cards), and an inline preview of the path-picker and template grid |
| `wizard-template.html`   | _new_ — wizard step 3                                           | **Step 3 · Template &amp; metadata.** Template grid with one selected (Public REST API), full OpenAPI metadata form (`info.summary` · `info.version` · `info.license` · `info.contact` · `info.termsOfService` · `servers[]` with add/remove rows · advanced section), live `openapi.yaml#/info` preview pane, "Template seeded" checklist, lint-grade prediction |
| `wizard-review.html`     | _new_ — wizard step 4                                           | **Step 4 · Review &amp; create.** Per-step summary cards (Path · Basics · Template &amp; metadata) with inline Edit deep-links back to each step, pre-flight checks panel (5/5 passed), post-creation options checklist (open Overview · run lint · open AI · fire webhook), final preview card, full "What gets created" list, and a green primary CTA that lands on the Overview page |

## Open

```
open objectified-ui/public/mockups/projects/dashboard.html
```

Or, with the Next.js dev server running:

```
http://localhost:3000/mockups/projects/dashboard.html
```

## Anchors

- Top bar / sidebar / panel shells mirror
  [`mockups/repositories/`](../repositories/) — same gradient sidebar,
  280 px width, 48 px platform bar, indigo-500 active rail.
- Card body (quality/lint/trend rings + contributor stack) evolves the
  earlier exploration in
  [`mockups/dashboard/projects.html`](../dashboard/projects.html) but
  aligns to the production data model (slug, `domainCategory`, OpenAPI
  metadata, quality-history series).
- KPI cards reuse the conventions baked into
  [`dashboardScreenClasses.ts`](../../../src/app/components/ade/dashboard/dashboardScreenClasses.ts)
  (`repositoryKpiCardClass`, `repositoryKpiSparkToneClass`,
  `repositoryKpiSubtitleToneClass`).

## Visual language

- Status pills: `Enabled` = emerald, `Draft` = slate, `Review` = amber,
  `Published` = emerald, `Deprecated` = orange, `Attention` = amber
  (with rose ring on the card border).
- Score rings: ≥ 90 emerald, 75–89 indigo, 60–74 amber, &lt; 60 rose
  (matches `getNumericScoreTier` in production).
- Domain pill: violet (matches the existing chip used in the production
  table).
- PII / PCI / regulated-data pill: rose, uppercase, single-token.
- Project initials avatar: deterministic gradient (indigo→purple,
  emerald→cyan, amber→orange, rose→pink, purple→fuchsia, sky→cyan)
  derived from the slug.

## What's intentionally faked

- All projects, scores, contributors, versions, and activity events are
  hard-coded.
- Quality-trend SVGs are static — no live history queries.
- The wizard's "Continue" / "Back" / stepper-label / "Edit" links jump
  between the four step files, but no client-side state is preserved —
  every step renders the same hard-coded `billing-api` example.
- Theme toggle (persisted under `projects-mockup-theme`) and Lucide icon
  hydration are the only working JS.

## Out of scope

All seven detail tabs (Overview · Versions · Classes · Properties ·
Published · Activity · Settings) and all four wizard steps (Path ·
Basics · Template &amp; metadata · Review) are now designed. Remaining
gaps:

- The **Import** path's full sub-flow (drag-drop file upload, URL fetch,
  paste-text editor, parse-progress, schema-collision resolver) — only
  the path-picker entry on `wizard-path.html` is rendered.
- The **"Design with AI"** embedded chat — referenced from the wizard
  but the chat panel itself is reused from the existing production
  `LLMChatPanel` and not re-mocked here.
- The **selected-version drawer**, **selected-class drawer**, and
  **selected-property drawer** are each rendered for one example only;
  they're not parameterized across the lists.
- The graph (`detail-classes-graph.html`) shows a static SVG layout —
  no live force simulation, drag, pan, or hover-recompute.
