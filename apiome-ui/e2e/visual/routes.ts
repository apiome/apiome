/**
 * What the visual-parity harness measures, and what it deliberately does not
 * (HIVE-10.1, #5337).
 *
 * ### The app side
 *
 * A parity test needs the app to render the page. Driving the real route would need a
 * session, a tenant and a database seeded to match what a designer typed into the mockup —
 * so every Hive page epic since HIVE-7.1 has instead had its jsdom suite **dump what it
 * rendered** into `e2e/fixtures/hive-<page>/`, and its browser suite mount that. Those dumps are
 * the real components' real output, kept honest by the jsdom suite that writes them, and
 * they are the same thing this harness mounts. See `e2e/visual/README.md`.
 *
 * ### Coverage is a ledger, not a sample
 *
 * {@link PARITY_ROUTES} names every mockup that *is* compared and
 * {@link UNCOVERED_MOCKUPS} names every mockup that is not, with the reason. Together they
 * must account for every page mockup in `docs/mockups/` — `tests/visual-parity-routes.test.ts`
 * fails if one is missing from both, so a new mockup cannot quietly slip past the harness.
 *
 * ### The first-row budget (HIVE-13.3, #5616)
 *
 * Parity says a page is built from the right tokens; it cannot say the page has piled standing
 * furniture above its data. So every pairing also either declares a {@link FirstRowBudget} —
 * how far down the page its first row of data may start — or is named in
 * {@link FIRST_ROW_EXEMPT} with the reason it has none. The same routes test enforces that.
 */

import { FIRST_DATA_ROW } from './landmarks';

/** Where the app side of a comparison comes from. */
export type ParitySubject =
  /** A committed fixture dump, mounted into a page that compiles the real `globals.css`. */
  | { kind: 'fixture'; dir: string; file: string }
  /** A live route on the dev server, for pages that need neither a session nor data. */
  | { kind: 'route'; path: string };

/** One mockup to app pairing the harness gates on. */
export interface ParityRoute {
  /** Short, stable id — used for the test title and the report file name. */
  id: string;
  /** The mockup, relative to `docs/mockups/`. It is read-only input. */
  mockup: string;
  /** The production route this pairing stands for, for the report. */
  route: string;
  /** Where the app side comes from. */
  subject: ParitySubject;
  /** The roadmap ticket that redesigned the route. */
  roadmapRef: string;
  /**
   * How far down the page the first row of data may start. Omitted only when the id is in
   * {@link FIRST_ROW_EXEMPT}.
   */
  firstRow?: FirstRowBudget;
}

/**
 * The first-row budgets `docs/mockups/PROPOSALS.md` sets, in CSS pixels at 1440 × 900
 * (comfortable density, `md` font scale).
 *
 * The review measured Published — header straight into the table — at ≈ 236 px and set it as
 * the bar; the quiet pass brought Catalog from ≈ 600 px to ≈ 345 px and Versions from ≈ 870 px
 * to ≈ 670 px. A budget is one of these three, never a number picked to fit a page.
 */
export const FIRST_ROW_BUDGET_PX = {
  /** A list page: facts line, one card, the rows. */
  list: 360,
  /** A detail page: a record's header and summary before its content. */
  detail: 560,
  /** Versions, which keeps a status strip and the artifacts card above its revisions. */
  versions: 700,
} as const;

/** Which of the three budgets a page is held to. */
export type FirstRowBudgetKind = keyof typeof FIRST_ROW_BUDGET_PX;

/**
 * A known overrun, allowed until the page's quiet pass lands.
 *
 * The gates in Epic 13 are introduced with allow-lists that only shrink. An allowance holds the
 * page at its ceiling — so it cannot get worse — and fails the run once the page comes back
 * within budget, so the entry is deleted rather than left to excuse a later regression.
 */
export interface FirstRowAllowance {
  /**
   * The furthest down the first row may start, in CSS pixels: today's measurement, rounded up
   * to the next multiple of ten above it, so a pixel of font rasterisation does not trip it.
   */
  ceilingPx: number;
  /** Why the page is over budget, and what brings it back. */
  reason: string;
}

/** How far down the page a route's first row of data may start. */
export interface FirstRowBudget {
  /**
   * The first row of data, read with `querySelector` inside the page region. Usually
   * {@link FIRST_DATA_ROW}; a page whose data is not a `DataTable` names its own.
   */
  selector: string;
  /** The budget, in CSS pixels below the page region's top edge: one of {@link FIRST_ROW_BUDGET_PX}. */
  budgetPx: number;
  /** A known overrun, when the page is over budget today. */
  allowance?: FirstRowAllowance;
}

/**
 * Build a route's first-row budget.
 *
 * @param kind Which budget the page is held to.
 * @param selector The first row of data; defaults to the first `DataTable` body row.
 * @param allowance A known overrun, when the page is over budget today.
 * @returns The budget to put on the route map entry.
 */
export function firstRowBudget(
  kind: FirstRowBudgetKind,
  selector: string = FIRST_DATA_ROW,
  allowance?: FirstRowAllowance
): FirstRowBudget {
  return allowance
    ? { selector, budgetPx: FIRST_ROW_BUDGET_PX[kind], allowance }
    : { selector, budgetPx: FIRST_ROW_BUDGET_PX[kind] };
}

/** Why a route carries no first-row budget. */
export type FirstRowExemptReason =
  /** The numbers are the page (PROPOSALS.md: Home and the Analytics pages keep full strips). */
  | 'analytics'
  /** The page is a form or a wizard: its controls come first by design, and its rows are a by-product. */
  | 'form-page';

/** What each exemption means, for the README and the routes test. */
export const FIRST_ROW_EXEMPT_REASONS: Record<FirstRowExemptReason, string> = {
  analytics:
    'an analytics page: its figures and charts are the data, so there is no row standing furniture could push down',
  'form-page':
    'a form or a wizard: the controls that edit the data come first by design',
};

/** Every route that carries no first-row budget, and why. */
export const FIRST_ROW_EXEMPT: Readonly<Record<string, FirstRowExemptReason>> = {
  'repository-telemetry': 'analytics',
  'mcp-analytics': 'analytics',
  'webhook-allowlist': 'form-page',
  'export-studio': 'form-page',
};

/** Why a mockup is not compared. */
export type UncoveredReason =
  /** Its redesign ticket has not landed, so there is no redesigned page to measure. */
  | 'awaiting-redesign'
  /** The surface is a dialog, drawer or wizard, not a page shell with page chrome. */
  | 'overlay-not-page'
  /** The surface uses the auth, launcher or foundations shell, not the app page shell. */
  | 'other-shell'
  /** The route is redesigned, but its suite mounts markup built in the spec, not a dump. */
  | 'no-page-fixture'
  /** A round-2 proposal replaced this mockup as the route's authority; the route compares to that. */
  | 'superseded';

/** What each reason means, for the report and the README. */
export const UNCOVERED_REASONS: Record<UncoveredReason, string> = {
  'awaiting-redesign':
    'the redesign ticket for this route has not landed, so there is no redesigned page to measure yet',
  'overlay-not-page':
    'the surface is a dialog, drawer or wizard rather than a page shell, so the page-chrome landmarks do not apply',
  'other-shell':
    'the surface uses the auth, launcher or foundations shell rather than the app page shell',
  'no-page-fixture':
    'the route is redesigned, but its browser suite builds its markup inline instead of dumping a fixture, so there is nothing committed to mount',
  superseded:
    'a round-2 proposal mockup replaced this one as the route’s authority, so the route is compared against the proposal instead',
};

/** A mockup the harness does not compare, and why. */
export interface UncoveredMockup {
  /** The mockup, relative to `docs/mockups/`. */
  mockup: string;
  /** Why it is not compared. */
  reason: UncoveredReason;
}

/**
 * Every mockup to app pairing the harness gates on.
 *
 * All eighteen are app-shell pages: a `.page` region with the HIVE-3.5 page chrome, which is
 * what the landmark table in `landmarks.ts` describes. Where a route has several committed
 * states, the pairing uses the state the mockup draws — the populated one — because an empty
 * state and a full table are different designs and comparing one to the other would measure
 * the fixture choice rather than the page.
 */
export const PARITY_ROUTES: readonly ParityRoute[] = [
  {
    // HIVE-11.2 (#5598) re-dumped `timeline.html` with the status strip in place of the three
    // banners. The pairing stays on `build/versions.html` until HIVE-11.3/11.4 land the rest of
    // `proposals/versions-status-strip.html` and HIVE-13.4 promotes it.
    id: 'versions',
    mockup: 'build/versions.html',
    route: '/ade/dashboard/versions',
    subject: { kind: 'fixture', dir: 'hive-versions', file: 'timeline.html' },
    roadmapRef: 'HIVE-6.2',
    firstRow: firstRowBudget('versions', FIRST_DATA_ROW, {
      ceilingPx: 710,
      reason:
        'at the build/versions.html page width the first revision row lands at 702 px; HIVE-13.4 moves the pairing to proposals/versions-status-strip.html',
    }),
  },
  {
    // HIVE-11.8 (#5604) re-dumped `registry.html` with the quiet pass applied: the five-tile
    // strip folded into a facts line (the strip is behind Show stats) and the rail's `$ref`
    // card moved into a dialog. There is no primitives proposal mockup, so the pairing stays on
    // `build/primitives.html`; the facts line follows `proposals/catalog-quiet.html`.
    id: 'primitives',
    mockup: 'build/primitives.html',
    route: '/ade/dashboard/primitives',
    subject: { kind: 'fixture', dir: 'hive-primitives', file: 'registry.html' },
    roadmapRef: 'HIVE-6.5',
    firstRow: firstRowBudget('list'),
  },
  {
    id: 'primitive-detail',
    mockup: 'build/primitive-detail.html',
    route: '/ade/dashboard/primitives/[id]',
    subject: { kind: 'fixture', dir: 'hive-primitive-detail', file: 'detail.html' },
    roadmapRef: 'HIVE-6.5',
    // A detail page's data is the record itself: the schema card that opens the main column.
    firstRow: firstRowBudget('detail', '[data-testid="primitive-detail-schema"]'),
  },
  {
    id: 'catalog',
    // The quiet pass (HIVE-11.6) supersedes the top of `sources/catalog.html`: facts line,
    // header ghost link, one card for the list. The table fixture is a returning reader's page.
    mockup: 'proposals/catalog-quiet.html',
    route: '/ade/dashboard/catalog',
    subject: { kind: 'fixture', dir: 'hive-catalog', file: 'table.html' },
    roadmapRef: 'HIVE-11.6',
    firstRow: firstRowBudget('list', FIRST_DATA_ROW, {
      ceilingPx: 390,
      reason:
        'HIVE-11.6 brought the first row to 344 px; #3755 (categorization) then added a second toolbar row inside the card',
    }),
  },
  {
    id: 'catalog-item',
    mockup: 'sources/catalog-item.html',
    route: '/ade/dashboard/catalog/[id]',
    subject: { kind: 'fixture', dir: 'hive-catalog-item', file: 'overview.html' },
    roadmapRef: 'HIVE-7.2',
    // The overview pane is the record's content; the converted banner and related card precede it.
    firstRow: firstRowBudget('detail', '[data-testid="catalog-detail-pane-overview"]'),
  },
  {
    // HIVE-11.7 (#5603) re-dumped the fixtures with the quiet pass: the KPI strip folded into
    // a facts line (the strip is behind Show stats) and the Refresh activity panel became a
    // chip in it that opens a drawer. The facts line follows `proposals/catalog-quiet.html`.
    id: 'repositories',
    mockup: 'sources/repositories.html',
    route: '/ade/dashboard/repositories',
    subject: { kind: 'fixture', dir: 'hive-repositories', file: 'table.html' },
    roadmapRef: 'HIVE-7.3',
    firstRow: firstRowBudget('list'),
  },
  {
    // HIVE-11.7 (#5603): facts line under the title (strip behind Show stats); the filter form
    // collapsed behind Filters (n) in the table toolbar, with the preset left inline.
    id: 'repository-detail',
    mockup: 'sources/repository-detail.html',
    route: '/ade/dashboard/repositories/[id]',
    subject: { kind: 'fixture', dir: 'hive-repository-detail', file: 'files.html' },
    roadmapRef: 'HIVE-7.5',
    // The file tree is a plain table, so its rows carry no `data-row-id`.
    firstRow: firstRowBudget('detail', '.page-body tbody tr'),
  },
  {
    id: 'repository-catalog',
    mockup: 'sources/repository-catalog.html',
    route: '/ade/dashboard/repositories/[id]/catalog',
    subject: { kind: 'fixture', dir: 'hive-repository-bring-in', file: 'catalog.html' },
    roadmapRef: 'HIVE-7.6',
    firstRow: firstRowBudget('detail'),
  },
  {
    id: 'repository-telemetry',
    mockup: 'sources/repository-telemetry.html',
    route: '/ade/dashboard/repositories/[id]/telemetry',
    subject: { kind: 'fixture', dir: 'hive-repository-bring-in', file: 'telemetry.html' },
    roadmapRef: 'HIVE-7.6',
  },
  {
    id: 'webhook-allowlist',
    mockup: 'sources/webhook-allowlist.html',
    route: '/ade/dashboard/repositories/webhook-ip-allowlist',
    subject: { kind: 'fixture', dir: 'hive-repository-bring-in', file: 'allowlist.html' },
    roadmapRef: 'HIVE-7.6',
  },
  {
    id: 'mcp-servers',
    mockup: 'sources/mcp-servers.html',
    route: '/ade/dashboard/mcp',
    subject: { kind: 'fixture', dir: 'hive-mcp-catalog', file: 'catalog-list.html' },
    roadmapRef: 'HIVE-7.7',
    // The catalog groups servers by host; the first host section is the first row of data.
    firstRow: firstRowBudget('list', '.page-body section[data-testid^="mcp-host-"]', {
      ceilingPx: 520,
      reason:
        'no quiet pass yet: toolbar, owner filter, saved-search and collection strips, totals and the shadowed-names alert stand above the first host',
    }),
  },
  {
    id: 'mcp-endpoint',
    mockup: 'sources/mcp-endpoint.html',
    route: '/ade/dashboard/mcp/[endpointId]',
    subject: { kind: 'fixture', dir: 'hive-mcp-endpoint', file: 'versions.html' },
    roadmapRef: 'HIVE-7.8',
    // The versions panel is the endpoint's content; the stat grid and the notes card precede it.
    firstRow: firstRowBudget('detail', '[data-testid="mcp-endpoint-panel-versions"]', {
      ceilingPx: 590,
      reason:
        'no quiet pass yet: a four-tile stat grid and the notes card stand above the versions panel',
    }),
  },
  {
    id: 'mcp-capabilities',
    mockup: 'sources/mcp-capabilities.html',
    route: '/ade/dashboard/mcp/capabilities',
    subject: { kind: 'fixture', dir: 'hive-mcp-analytics', file: 'capabilities.html' },
    roadmapRef: 'HIVE-7.9',
    firstRow: firstRowBudget('list', FIRST_DATA_ROW, {
      ceilingPx: 420,
      reason: 'no quiet pass yet: the preset tiles stand above the capability table',
    }),
  },
  {
    id: 'mcp-analytics',
    mockup: 'sources/mcp-analytics.html',
    route: '/ade/dashboard/mcp/analytics',
    subject: { kind: 'fixture', dir: 'hive-mcp-analytics', file: 'dashboard.html' },
    roadmapRef: 'HIVE-7.9',
  },
  {
    id: 'mcp-compare',
    mockup: 'sources/mcp-compare.html',
    route: '/ade/dashboard/mcp/compare',
    subject: { kind: 'fixture', dir: 'hive-mcp-analytics', file: 'compare.html' },
    roadmapRef: 'HIVE-7.9',
    // The comparison opens on a section row, which carries no `data-row-id`.
    firstRow: firstRowBudget('list', '.page-body tbody tr'),
  },
  {
    id: 'published',
    mockup: 'ship/published.html',
    route: '/ade/dashboard/published',
    subject: { kind: 'fixture', dir: 'hive-published', file: 'table.html' },
    roadmapRef: 'HIVE-8.1',
    firstRow: firstRowBudget('list'),
  },
  {
    id: 'sunset-timeline',
    mockup: 'ship/sunset-timeline.html',
    route: '/ade/dashboard/versions/sunset-timeline',
    subject: { kind: 'fixture', dir: 'hive-sunset-timeline', file: 'timeline.html' },
    roadmapRef: 'HIVE-8.2',
    // The timeline plot is the page's data; the table under it repeats the same revisions.
    firstRow: firstRowBudget('list', '[data-testid="sunset-timeline-plot"]'),
  },
  {
    id: 'export-studio',
    mockup: 'ship/export-studio.html',
    route: '/ade/dashboard/export/studio',
    subject: { kind: 'fixture', dir: 'hive-export-studio', file: 'source.html' },
    roadmapRef: 'HIVE-8.3',
  },
];

/**
 * Every page mockup the harness does not compare, and why.
 *
 * This list exists so that "not covered" is a decision on the record rather than an omission.
 * When a redesign ticket lands, its entry moves from here into {@link PARITY_ROUTES}; when a
 * new mockup is drawn, it has to appear in one of the two lists or the routes test fails.
 */
export const UNCOVERED_MOCKUPS: readonly UncoveredMockup[] = [
  { mockup: 'account/linked-accounts.html', reason: 'awaiting-redesign' },
  { mockup: 'account/profile.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/feature-flags.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/licenses.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/login.html', reason: 'other-shell' },
  { mockup: 'admin/overview.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/settings.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/templates.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/tenants.html', reason: 'awaiting-redesign' },
  { mockup: 'admin/users.html', reason: 'awaiting-redesign' },
  { mockup: 'auth/login.html', reason: 'other-shell' },
  { mockup: 'auth/onboarding.html', reason: 'other-shell' },
  { mockup: 'auth/signup-oauth.html', reason: 'other-shell' },
  { mockup: 'auth/two-factor.html', reason: 'other-shell' },
  { mockup: 'build/import-wizard.html', reason: 'overlay-not-page' },
  { mockup: 'build/projects.html', reason: 'awaiting-redesign' },
  { mockup: 'build/version-dialogs.html', reason: 'overlay-not-page' },
  { mockup: 'foundations/design-system.html', reason: 'other-shell' },
  { mockup: 'foundations/help.html', reason: 'no-page-fixture' },
  { mockup: 'foundations/settings-pane.html', reason: 'overlay-not-page' },
  { mockup: 'foundations/shell.html', reason: 'other-shell' },
  { mockup: 'govern/lint-posture.html', reason: 'no-page-fixture' },
  { mockup: 'govern/style-guide-detail.html', reason: 'no-page-fixture' },
  { mockup: 'govern/style-guides.html', reason: 'no-page-fixture' },
  { mockup: 'home/launcher.html', reason: 'other-shell' },
  { mockup: 'home/overview.html', reason: 'no-page-fixture' },
  // Round-3 proposals (docs/mockups/PROPOSALS.md §5, 2026-10-25): the colour & accent pass. Each
  // `accent-*` page is the shipped layout plus colour, mark and motion; it is compared once HIVE-14
  // lands and the page fixture is re-dumped. `accent-pass.html` is the before/after hub on the bare
  // shell, like the index, and is never a page to measure.
  { mockup: 'proposals/accent-catalog.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/accent-home.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/accent-members.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/accent-pass.html', reason: 'other-shell' },
  { mockup: 'proposals/accent-projects.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/accent-versions.html', reason: 'awaiting-redesign' },
  // Round-2 proposals (docs/mockups/PROPOSALS.md, 2026-10-07): each supersedes part of a shipped
  // page and is compared once its ticket lands and the page fixture is re-dumped.
  { mockup: 'proposals/launcher-focused.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/rail-compact.html', reason: 'awaiting-redesign' },
  { mockup: 'proposals/versions-status-strip.html', reason: 'awaiting-redesign' },
  { mockup: 'sources/catalog.html', reason: 'superseded' },
  { mockup: 'sources/repository-new.html', reason: 'overlay-not-page' },
  { mockup: 'tools/database.html', reason: 'awaiting-redesign' },
  { mockup: 'tools/migration.html', reason: 'awaiting-redesign' },
  { mockup: 'workspace/api-keys.html', reason: 'no-page-fixture' },
  { mockup: 'workspace/audit.html', reason: 'no-page-fixture' },
  { mockup: 'workspace/members.html', reason: 'no-page-fixture' },
  { mockup: 'workspace/roles.html', reason: 'no-page-fixture' },
  { mockup: 'workspace/tenants.html', reason: 'no-page-fixture' },
];

/**
 * The route map entry with a given id.
 *
 * @param id The entry's id.
 * @returns The entry.
 * @throws When no entry has that id, which is a typo in a spec rather than a parity failure.
 */
export function parityRoute(id: string): ParityRoute {
  const found = PARITY_ROUTES.find((route) => route.id === id);
  if (!found) throw new Error(`visual-parity: no route map entry with id "${id}"`);
  return found;
}
