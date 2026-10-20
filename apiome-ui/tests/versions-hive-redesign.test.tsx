/**
 * The Versions redesign, rendered (HIVE-6.2, #5313).
 *
 * `versions-model.test.ts` holds the decisions and `versions-css.test.ts` pins the
 * declarations; this holds the screen that makes them — the whole `page.tsx`, mounted against
 * mocked `/api/projects`, `/api/versions` and the dozen smaller reads it makes, with the mockup's
 * six revisions of *Payments API*. What it pins is the ticket's five acceptance criteria and
 * the mockup's **Notes → Keeps (1:1)** list:
 *
 *   1. **Every current column, filter, row action and dialog is present and behaves
 *      identically.** The seven columns are read off the rows; the lifecycle, tag and timeline
 *      filters narrow; the sort menu and the headers sort; the row menu offers every action;
 *      New / Edit / Sunset / Publish / spec viewer open and submit through the same routes.
 *   2. **The lint badge still reads the stored report** — no `/lint` request is made to draw
 *      the list (#5259).
 *   3. **Publish gates block and allow exactly as before, including force-publish with a
 *      reason.** A style-guide error blocks; force + reason unblocks; the POST carries
 *      `skipPublishChecks` and the reason.
 *   4. **The mock cell's switch, URL copy and scenario link work for published and draft
 *      states.** The PUT, the clipboard and the label are all read.
 *   5. **`FEATURE_GITLIKE` behaviour is unchanged in production builds** — pinned in the model
 *      tests; here the non-production rule is checked: git-like items are drawn, marked and
 *      inert rather than absent.
 *
 * Plus the status strip (HIVE-11.2), the project facts, the related artifacts panel and the four empty
 * states.
 */

import * as fs from 'fs';
import * as path from 'path';
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

const mockConfirm = jest.fn<Promise<boolean>, [unknown]>(() => Promise.resolve(true));
const mockAlert = jest.fn<Promise<void>, [unknown]>(() => Promise.resolve());
/**
 * The address bar, as the mocked router keeps it. The toolbar's filters are URL state
 * (HIVE-11.4), so `replace` has to land in `useSearchParams` for a chip or a menu to narrow.
 */
let mockSearch = new URLSearchParams();
const mockSearchListeners = new Set<() => void>();
const mockReplace = jest.fn((href: string) => {
  mockSearch = new URLSearchParams(href.split('?')[1] ?? '');
  mockSearchListeners.forEach((listener) => listener());
});

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io', is_tenant_admin: true } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('next/navigation', () => {
  const { useSyncExternalStore } = jest.requireActual<typeof import('react')>('react');
  const subscribe = (listener: () => void) => {
    mockSearchListeners.add(listener);
    return () => mockSearchListeners.delete(listener);
  };
  return {
    useRouter: () => ({ push: jest.fn(), replace: mockReplace }),
    useSearchParams: () => useSyncExternalStore(subscribe, () => mockSearch),
    usePathname: () => '/ade/dashboard/versions',
  };
});

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({
    confirm: (options: unknown) => mockConfirm(options),
    alert: (options: unknown) => mockAlert(options),
    prompt: jest.fn(),
  }),
}));

jest.mock('@/app/providers/PushConflictBannerProvider', () => ({
  usePushConflictBanner: () => ({
    conflict: null,
    setPushConflictFrom409: jest.fn(),
    clearPushConflict: jest.fn(),
  }),
}));

const mockDeleteVersion = jest.fn(async () => JSON.stringify({ success: true }));
const mockBuildSpec = jest.fn(async () =>
  JSON.stringify({ openapi: '3.1.0', info: { title: 'Payments API', version: '2.3.1' }, paths: {} }, null, 2)
);

jest.mock('@lib/db/helper', () => ({
  deleteVersion: (...args: unknown[]) => mockDeleteVersion(...(args as [])),
  buildOpenApiSpecJsonForVersion: (...args: unknown[]) => mockBuildSpec(...(args as [])),
  getClassesForVersion: async () => '[]',
  getPropertiesForClass: async () => '[]',
  getTenantsAdministratedByUser: async () => '[]',
}));

/** Whole screens of their own, not under test. */
jest.mock('@/app/components/ade/dashboard/ImportDialog', () => ({
  __esModule: true,
  default: ({ open }: { open: boolean }) => (open ? <div data-testid="import-dialog">import wizard</div> : null),
}));
jest.mock('@/app/components/ade/dashboard/export/ExportDialog', () => ({
  __esModule: true,
  default: ({ open }: { open: boolean }) => (open ? <div data-testid="export-dialog">export</div> : null),
}));
jest.mock('@/app/components/ade/dashboard/export/VersionExportPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="version-export-panel">export cards</div>,
}));
jest.mock('@/app/components/ade/dashboard/MockScenarioEditor', () => ({
  MockScenarioEditor: ({ open }: { open: boolean }) => (open ? <div data-testid="scenario-editor">scenarios</div> : null),
}));
jest.mock('@/app/components/ade/dashboard/test-bench/SchemaTestBench', () => ({
  SchemaTestBench: () => <div data-testid="schema-test-bench">test bench</div>,
}));
jest.mock('@/app/components/ade/dashboard/SuiteRegressionBadge', () => ({
  SuiteRegressionBadge: () => null,
}));
jest.mock('@/app/ade/dashboard/versions/RelationshipGraphDialog', () => ({
  __esModule: true,
  default: () => null,
}));
jest.mock('@/app/ade/dashboard/versions/VersionHistoryGraphPanel', () => ({
  __esModule: true,
  default: () => <div data-testid="history-graph">graph</div>,
}));
jest.mock('@/app/ade/dashboard/versions/VersionCanvasCompare', () => ({
  __esModule: true,
  default: () => <div data-testid="canvas-compare">canvas</div>,
}));
jest.mock('@monaco-editor/react', () => ({
  __esModule: true,
  default: ({ value, language }: { value: string; language: string }) => (
    <div data-testid="mock-monaco" data-language={language}>
      {value}
    </div>
  ),
}));
jest.mock('@/app/hooks/useMockUsage', () => ({
  useMockUsage: () => ({
    seriesByVersion: new Map([['payments-api::2.3.1', [1, 2, 3, 4, 5]]]),
    loading: false,
    error: null,
  }),
}));
jest.mock('@/app/utils/mock-usage-series', () => ({
  mockUsageSeriesKey: (slug: string, label: string) => `${slug}::${label}`,
  MOCK_USAGE_WINDOW_DAYS: 30,
}));
jest.mock('@/app/components/ade/dashboard/catalog/useConversionHistory', () => ({
  useConversionHistory: () => ({ rows: [], loading: false, error: null, retry: jest.fn() }),
}));

import Versions from '../src/app/ade/dashboard/versions/page';

// ---------------------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------------------

const PROJECT_ID = '8f2a1c00-0000-4000-8000-000000000001';

const PROJECTS = [
  { id: PROJECT_ID, name: 'Payments API', slug: 'payments-api', publishable: true },
  { id: '3b91de00-0000-4000-8000-000000000002', name: 'Orders Service', slug: 'orders-service', publishable: true },
  { id: 'c0ffee00-0000-4000-8000-000000000004', name: 'Avro Contracts', slug: 'avro-contracts', publishable: false },
];

const BASE = {
  project_id: PROJECT_ID,
  creator_id: 'u-ada',
  shortMessage: null as string | null,
  changelog: null as string | null,
  enabled: true,
  published: false,
  deleted_at: null,
  updated_at: '2026-01-01T00:00:00.000Z',
  published_at: null as string | null,
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
};

const HEAD_ID = '9d3f7a21-0000-4000-8000-000000000001';
const V231_ID = '4c8e1b09-0000-4000-8000-000000000002';
const V230_ID = '77ab0c5e-0000-4000-8000-000000000003';
const V220_ID = 'ded00000-0000-4000-8000-000000000004';
const V210_ID = '1f0e9d88-0000-4000-8000-000000000005';
const BETA_ID = 'b3d1e6a0-0000-4000-8000-000000000006';

const VERSIONS = [
  {
    ...BASE,
    id: HEAD_ID,
    version_id: '2.4.0',
    shortMessage: 'Add refund reasons and payout webhooks',
    changelog: '- added: RefundReason enum · - added: payout.settled event',
    created_at: '2026-08-15T09:12:00.000Z',
    qualityScore: 88,
    qualityGrade: 'B',
  },
  {
    ...BASE,
    id: V231_ID,
    version_id: '2.3.1',
    shortMessage: 'Patch: fix Refund.amount minimum',
    changelog: '- fixed: Refund.amount minimum 0.01',
    published: true,
    published_at: '2026-08-03T10:00:00.000Z',
    created_at: '2026-08-02T16:40:00.000Z',
    creator_id: 'u-grace',
    creator_name: 'Grace Hopper',
    creator_email: 'grace@example.com',
    qualityScore: 94,
    qualityGrade: 'A',
    mockEnabled: true,
    mockBaseUrl: 'https://mock.apiome.dev/acme/payments-api/2.3.1',
  },
  {
    ...BASE,
    id: V230_ID,
    version_id: '2.3.0',
    shortMessage: 'Payouts resource + settlement reports',
    published: true,
    published_at: '2026-07-22T00:00:00.000Z',
    created_at: '2026-07-21T11:30:00.000Z',
    enabled: false,
    creator_id: 'u-linus',
    creator_name: 'Linus Torvalds',
    creator_email: 'linus@example.com',
    qualityScore: 71,
    qualityGrade: 'C',
  },
  {
    ...BASE,
    id: V220_ID,
    version_id: '2.2.0',
    shortMessage: 'Card tokenisation + 3DS challenge flow',
    published: true,
    published_at: '2026-06-11T00:00:00.000Z',
    created_at: '2026-06-10T14:15:00.000Z',
    lifecycle: 'deprecated',
    metadata: {
      sunsetAt: '2026-09-30T00:00:00.000Z',
      successorRevisionId: V231_ID,
      deprecationMessage: 'Migrate to /payment-intents before sunset.',
    },
    forkedFromRevisionId: 'ffff0000-0000-4000-8000-000000000009',
    forkSourceVersionLabel: '1.9.0',
    forkSourceProjectName: 'Orders Service',
    qualityScore: 82,
    qualityGrade: 'B',
  },
  {
    ...BASE,
    id: V210_ID,
    version_id: '2.1.0',
    shortMessage: 'Initial public release',
    published: true,
    published_at: '2026-03-02T10:00:00.000Z',
    created_at: '2026-03-02T10:00:00.000Z',
    lifecycle: 'archived',
    revisionLocked: true,
  },
  {
    ...BASE,
    id: BETA_ID,
    version_id: '2.0.0-beta.1',
    shortMessage: 'Experimental: instant payouts',
    changelog: 'Spike for instant payouts; not for release.',
    created_at: '2026-02-14T15:48:00.000Z',
    lifecycle: 'beta',
    creator_id: 'u-linus',
    creator_name: 'Linus Torvalds',
    creator_email: 'linus@example.com',
    mockEnabled: true,
    mockPrivate: true,
    mockBaseUrl: 'https://mock.apiome.dev/acme/payments-api/2.0.0-beta.1',
  },
];

const CHANGELOGS = [
  {
    publishedRevisionId: V231_ID,
    versionLabel: '2.3.1',
    publishedAt: '2026-08-03T10:00:00.000Z',
    baselineRevisionId: V230_ID,
    baselineVersionLabel: '2.3.0',
    status: 'ready',
    maxSeverity: 'non-breaking',
    counts: { 'non-breaking': 2, 'docs-only': 1 },
  },
];

const RELATED = [
  { projectId: 'g1', name: 'payments-api.graphql', sourceFormat: 'graphql', protocol: 'http', linkSource: 'converted', deleted: false },
  { projectId: 'g2', name: 'payments-legacy.wsdl', sourceFormat: 'wsdl', protocol: null, linkSource: 'manual', deleted: true },
];

/** A lint report with one error — the case that blocks Publish. */
const LINT_REPORT_BLOCKING = {
  projectId: PROJECT_ID,
  versionRecordId: HEAD_ID,
  versionId: '2.4.0',
  score: 88,
  grade: 'B',
  findings: [
    { id: 'f1', path: 'paths./payouts.post', category: 'ops', rule: 'operation-4xx-response', severity: 'error', message: 'Missing 4xx response' },
  ],
  ruleHits: {},
  severityCounts: { error: 1, warning: 3, info: 2 },
  reportFingerprint: 'fp',
  baseRevisionId: null,
  compatibilityOverall: 'safe',
  guideName: 'Acme REST',
};

const GUARDRAIL_QUIET = {
  policy: 'block',
  status: 'ok',
  triggered: false,
  blocked: false,
  breaking: false,
  majorBumped: null,
  fromVersion: '2.3.1',
  toVersion: '2.4.0',
  baselineRevisionId: V231_ID,
  breakingChanges: [],
  breakingCount: 0,
  truncated: false,
  counts: {},
  maxSeverity: null,
  recommendedVersion: null,
  detail: null,
  message: 'No breaking changes.',
};

const DECISION_PASSED = {
  passed: true,
  enforcement: 'block',
  skipped: false,
  evaluationId: 'eval_5c1a',
  evidenceRunIds: ['run_88a2'],
  gateResults: [{ gate: 'contract-tests', passed: true }],
  warnings: [],
};

// ---------------------------------------------------------------------------------------
// The fetch router
// ---------------------------------------------------------------------------------------

type Route = { method?: string; test: RegExp; reply: (url: string, init?: RequestInit) => unknown; status?: number };

let routes: Route[] = [];
const calls: Array<{ url: string; method: string; body: unknown }> = [];

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function installFetch(extra: Route[] = []) {
  routes = [
    { test: /^\/api\/projects\?include_catalog=true$/, reply: () => ({ success: true, projects: PROJECTS }) },
    { test: /^\/api\/versions\?projectId=/, reply: () => ({ success: true, versions: VERSIONS }) },
    { test: /\/version-branches$/, reply: () => ({ success: true, branches: [] }) },
    { test: /\/version-tags$/, reply: () => ({ success: true, tags: [] }) },
    { test: /\/has-class-schema/, reply: () => ({ success: true, map: {} }) },
    { test: /\/changelogs$/, reply: () => ({ success: true, changelogs: CHANGELOGS }) },
    {
      test: new RegExp(`^/api/projects/${PROJECT_ID}$`),
      reply: () => ({ success: true, project: { identityGroupId: 'grp-1', relatedArtifacts: RELATED } }),
    },
    { test: /\/lint$/, reply: () => LINT_REPORT_BLOCKING },
    { test: /\/breaking-publish-guardrail$/, reply: () => ({ success: true, ...GUARDRAIL_QUIET }) },
    { method: 'POST', test: /^\/api\/verification-policy\/evaluate$/, reply: () => ({ success: true, data: DECISION_PASSED }) },
    { method: 'PUT', test: /\/mock$/, reply: (url, init) => {
        const enabled = Boolean((JSON.parse(String(init?.body ?? '{}')) as { enabled?: boolean }).enabled);
        return { success: true, version: { mockEnabled: enabled, mockBaseUrl: enabled ? 'https://mock.apiome.dev/x' : null, mockPrivate: false } };
      } },
    { method: 'POST', test: /\/publish$/, reply: () => ({ success: true }) },
    { method: 'POST', test: /\/unpublish$/, reply: () => ({ success: true }) },
    { method: 'PUT', test: /^\/api\/versions\/[^/?]+$/, reply: () => ({ success: true }) },
    { method: 'POST', test: /^\/api\/versions$/, reply: () => ({ success: true, version: { copied_classes: 3 } }) },
    ...extra,
  ];
  calls.length = 0;
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const method = (init?.method ?? 'GET').toUpperCase();
    let body: unknown = null;
    try {
      body = init?.body ? JSON.parse(String(init.body)) : null;
    } catch {
      body = init?.body;
    }
    calls.push({ url, method, body });
    for (const route of [...routes].reverse()) {
      if ((route.method ?? 'GET') === method && route.test.test(url)) {
        return jsonResponse(route.reply(url, init), route.status);
      }
    }
    return jsonResponse({ success: false, error: `unrouted ${method} ${url}` }, 404);
  }) as unknown as typeof fetch;
}

// ---------------------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------------------

/**
 * The table's data rows — the `<tr data-row-id>`s. The mock cell's sparkline draws a hidden data
 * table of its own (`ChartFrame`), so a bare `getAllByRole('row')` would count its points too.
 */
function dataRows(): HTMLElement[] {
  return within(screen.getByTestId('versions-table'))
    .getAllByRole('row')
    .filter((row) => row.hasAttribute('data-row-id'));
}

/** Radix `DropdownMenu.Trigger` opens on `pointerdown`, which jsdom does not synthesise from a click. */
function openRowMenu(versionId: string) {
  fireEvent.keyDown(screen.getByTestId(`versions-row-menu-${versionId}`), { key: 'Enter' });
  return screen.findByTestId(`versions-row-menu-content-${versionId}`);
}

async function renderVersions() {
  const view = render(<Versions />);
  await screen.findByTestId('versions-table');
  await waitFor(() => expect(screen.getByTestId(`versions-cell-${HEAD_ID}`)).toBeInTheDocument());
  return view;
}

beforeAll(() => {
  // jsdom has no ResizeObserver, which Radix's popper measures with.
  (global as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(navigator, 'clipboard', {
    value: { writeText: jest.fn(async () => undefined) },
    configurable: true,
  });
});

beforeEach(() => {
  installFetch();
  mockSearch = new URLSearchParams();
  // The status strip remembers its open chip per project for the session.
  window.sessionStorage.clear();
  mockConfirm.mockClear();
  mockAlert.mockClear();
  mockDeleteVersion.mockClear();
  (navigator.clipboard.writeText as jest.Mock).mockClear();
});

// ---------------------------------------------------------------------------------------
// The header
// ---------------------------------------------------------------------------------------

describe('the header', () => {
  it('titles the page with the project and badges the head and its stored quality', async () => {
    await renderVersions();
    const header = screen.getByTestId('page-header');
    expect(within(header).getByRole('heading', { level: 1 })).toHaveTextContent('Payments API');
    expect(within(header).getByTestId('format-pill')).toHaveTextContent('OpenAPI');
    expect(screen.getByTestId('versions-head-badge')).toHaveTextContent('v2.4.0 draft');
    expect(screen.getByTestId('versions-head-quality')).toHaveTextContent('B · 88');
    expect(within(header).getByRole('link', { name: 'Sunset timeline (EOL schedule)' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions/sunset-timeline'
    );
    // Breadcrumb: Home › Build › Projects › Payments API
    const crumbs = within(header).getByTestId('page-breadcrumb');
    expect(crumbs).toHaveTextContent('Home');
    expect(crumbs).toHaveTextContent('Projects');
    expect(crumbs).toHaveTextContent('Payments API');
  });

  it('keeps Compare › Import › ⋯ › New version, one primary action, and nothing else in the cluster', async () => {
    await renderVersions();
    const actions = screen.getByTestId('page-header-actions');
    const names = within(actions)
      .getAllByRole('button')
      .map((b) => b.getAttribute('data-testid') ?? b.textContent?.trim());
    expect(names).toEqual([
      'versions-compare-button',
      'versions-import-button',
      'page-header-overflow',
      'versions-new-button',
    ]);
    expect(screen.getByTestId('versions-import-button')).toBeEnabled();
    expect(screen.getByTestId('versions-compare-button')).toBeEnabled();
    expect(screen.getByTestId('page-header-overflow')).toHaveAccessibleName('More actions');
    // The honey flag has left the header's action cluster (HIVE-11.3).
    expect(within(actions).queryByTestId('gitlike-flag')).not.toBeInTheDocument();
  });

  it('moves the project switcher into the breadcrumb, excluding catalog items', async () => {
    mockReplace.mockClear();
    await renderVersions();
    const trigger = within(screen.getByTestId('page-breadcrumb')).getByTestId('versions-project-switch');
    expect(trigger).toHaveAttribute('aria-haspopup', 'menu');
    expect(trigger).toHaveTextContent('Payments API');
    fireEvent.click(trigger);

    const menu = await screen.findByRole('menu', { name: 'Projects' });
    // The selector never offers a catalog item (#4587); the current project is checked.
    const options = within(menu).getAllByRole('menuitemradio');
    expect(options.map((o) => o.textContent)).toEqual(['OpenAPIPayments API', 'OpenAPIOrders Service']);
    expect(options[0]).toHaveAttribute('aria-checked', 'true');
    expect(within(menu).getByRole('menuitem', { name: 'All projects' })).toHaveAttribute('href', '/ade/dashboard/projects');

    // Typeahead: the filter is focused, and Enter switches to the first match.
    const search = screen.getByRole('searchbox', { name: 'Jump to project' });
    expect(search).toHaveFocus();
    fireEvent.change(search, { target: { value: 'orders' } });
    fireEvent.keyDown(search, { key: 'Enter' });
    expect(mockReplace).toHaveBeenCalledWith(
      expect.stringContaining('projectId=3b91de00-0000-4000-8000-000000000002'),
      { scroll: false }
    );
    expect(screen.queryByRole('menu', { name: 'Projects' })).not.toBeInTheDocument();
    expect(trigger).toHaveFocus();
  });

  it('holds Merge branches, Sunset timeline, Published surface and Copy link in the ⋯ menu', async () => {
    await renderVersions();
    fireEvent.keyDown(screen.getByTestId('page-header-overflow'), { key: 'Enter' });
    const menu = await screen.findByTestId('page-header-overflow-menu');
    expect(menu).toHaveTextContent('This project');

    // Unavailable, not removed: the row stays reachable and states why.
    const merge = within(menu).getByTestId('page-header-overflow-merge');
    expect(merge).toHaveAttribute('aria-disabled', 'true');
    expect(merge).toHaveAttribute('title', 'Compiled but hidden today (FEATURE_GITLIKE=false)');
    expect(merge).toHaveTextContent('gitlike');
    expect(within(merge).queryByTestId('gitlike-flag')).not.toBeInTheDocument();

    expect(within(menu).getByTestId('page-header-overflow-sunset-timeline')).toHaveAttribute(
      'href',
      '/ade/dashboard/versions/sunset-timeline'
    );
    expect(within(menu).getByTestId('page-header-overflow-published')).toHaveAttribute('href', '/ade/dashboard/published');
    // Export studio waits for its release, exactly as the facts card's link does.
    expect(within(menu).queryByTestId('page-header-overflow-export-studio')).not.toBeInTheDocument();

    const copy = within(menu).getByTestId('page-header-overflow-copy-link');
    expect(copy).toHaveAttribute('aria-keyshortcuts', 'Meta+Shift+C Control+Shift+C');
    fireEvent.click(copy);
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        `${window.location.origin}/ade/dashboard/versions?projectId=${PROJECT_ID}`
      )
    );
  });

  it('copies the project link with ⌘⇧C', async () => {
    await renderVersions();
    fireEvent.keyDown(window, { key: 'C', metaKey: true, shiftKey: true });
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(
        `${window.location.origin}/ade/dashboard/versions?projectId=${PROJECT_ID}`
      )
    );
  });

  it('draws the git-like Change report tab inert with the flag, in this build', async () => {
    await renderVersions();
    const tab = screen.getByTestId('versions-tab-change-report');
    expect(tab).toBeDisabled();
    expect(within(tab).getByTestId('gitlike-flag')).toHaveTextContent('gitlike');
  });

  it('counts the tabs — Timeline 6, Changes 4 — and switches to the Changes tab', async () => {
    await renderVersions();
    expect(screen.getByTestId('versions-tab-timeline')).toHaveTextContent('6');
    expect(screen.getByTestId('versions-tab-changes')).toHaveTextContent('4');
    expect(screen.getByTestId('versions-tab-test-bench')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('versions-tab-changes'));
    await waitFor(() => expect(screen.queryByTestId('versions-table')).not.toBeInTheDocument());
    fireEvent.click(screen.getByTestId('versions-tab-timeline'));
    await screen.findByTestId('versions-table');
  });

  it('opens the project\'s Dependencies tab (CDG-3.4)', async () => {
    installFetch([
      {
        test: /^\/api\/graph\/edges\/project\/[^/]+\?direction=(in|out)&limit=500$/,
        reply: () => ({ edges: [], total: 0, truncated: false, limit: 500, offset: 0 }),
      },
    ]);
    await renderVersions();
    const tab = screen.getByTestId('versions-tab-dependencies');
    fireEvent.click(tab);
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(await screen.findByText('Nothing depends on this yet')).toBeInTheDocument();
    expect(calls.filter((c) => c.url.startsWith('/api/graph/edges/project/'))).toHaveLength(2);
    expect(screen.queryByTestId('versions-table')).not.toBeInTheDocument();
  });

  it('counts unresolved threads on the Discussion tab and opens the project discussion (COL-1.3)', async () => {
    installFetch([
      {
        test: /\/comment-threads\?status=open&limit=1&offset=0$/,
        reply: () => ({ success: true, threads: [], count: 0, total: 3, limit: 1, offset: 0 }),
      },
      {
        test: /\/comment-threads\?status=open&limit=50&offset=0$/,
        reply: () => ({ success: true, threads: [], count: 0, total: 0, limit: 50, offset: 0 }),
      },
      {
        test: /\/comment-threads\/summary$/,
        reply: () => ({
          success: true,
          statusTotals: { open: 2, resolved: 0, orphaned: 0 },
          unresolvedTotal: 2,
          unresolvedByAnchor: {},
          truncated: false,
        }),
      },
    ]);
    await renderVersions();
    const tab = screen.getByTestId('versions-tab-discussion');
    await waitFor(() => expect(within(tab).getByTestId('versions-tab-discussion-count')).toHaveTextContent('3'));
    expect(tab).toHaveAttribute('title', '3 unresolved comment threads');

    fireEvent.click(tab);
    expect(await screen.findByTestId('project-discussion-panel')).toBeInTheDocument();
    expect(tab).toHaveAttribute('aria-selected', 'true');
    expect(screen.queryByTestId('versions-table')).not.toBeInTheDocument();
    // The panel's summary is fresher than the tab's first read, and replaces it.
    await waitFor(() => expect(within(tab).getByTestId('versions-tab-discussion-count')).toHaveTextContent('2'));
  });
});

// ---------------------------------------------------------------------------------------
// The status strip, the overview and the facts
// ---------------------------------------------------------------------------------------

/** The status strip's chip group. */
const statusChips = () => screen.findByRole('group', { name: 'Project status' });

/** The strip's one detail row. */
const statusDetail = () => document.querySelector('.status-strip__detail') as HTMLElement;

describe('the status strip and the overview', () => {
  it('folds the compatibility, what’s-new and deprecation statuses into one strip, the most severe open', async () => {
    await renderVersions();
    const chips = await statusChips();
    const compat = within(chips).getByRole('button', { name: /Compatible/ });
    expect(compat).toHaveTextContent('v2.3.0 → v2.3.1');
    const whatsNew = within(chips).getByRole('button', { name: /What’s new/ });
    expect(whatsNew).toHaveTextContent('v2.4.0 draft');
    const deprecated = within(chips).getByRole('button', { name: /v2\.2\.0 deprecated/ });
    expect(deprecated).toHaveTextContent('· sunset 30 Sep 2026');
    // No stacked banners any more.
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();

    // `warn` outranks `accent` and `ok`, so the deprecation detail is open on first paint.
    expect(deprecated).toHaveAttribute('aria-expanded', 'true');
    expect(compat).toHaveAttribute('aria-expanded', 'false');
    const detail = statusDetail();
    expect(detail).toBeVisible();
    expect(detail).toHaveTextContent('v2.2.0 is deprecated — sunset 30 Sep 2026 00:00 UTC.');
    expect(detail).toHaveTextContent('Successor v2.3.1');
    expect(detail).toHaveTextContent('Consumers see the same warning on compatibility checks (#507).');
    expect(within(detail).getByRole('link', { name: 'Sunset timeline' })).toHaveAttribute(
      'href',
      '/ade/dashboard/versions/sunset-timeline'
    );
    expect(within(detail).getByRole('link', { name: 'Migration guide' })).toHaveAttribute('target', '_blank');
  });

  it('keeps every banner action — “View report” and “Open changes” open the Changes tab', async () => {
    await renderVersions();
    const chips = await statusChips();
    fireEvent.click(within(chips).getByRole('button', { name: /Compatible/ }));
    expect(statusDetail()).toHaveTextContent('Compatible.');
    expect(statusDetail()).toHaveTextContent('v2.3.0 → v2.3.1 has');
    fireEvent.click(within(statusDetail()).getByRole('button', { name: 'View report' }));
    await waitFor(() => expect(screen.getByTestId('versions-tab-changes')).toHaveAttribute('aria-selected', 'true'));
    // The timeline's three statuses stay with the timeline.
    expect(screen.queryByRole('group', { name: 'Project status' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByTestId('versions-tab-timeline'));
    fireEvent.click(within(await statusChips()).getByRole('button', { name: /What’s new/ }));
    expect(statusDetail()).toHaveTextContent('What’s new in v2.4.0 (draft).');
    fireEvent.click(within(statusDetail()).getByRole('button', { name: 'Open changes' }));
    await waitFor(() => expect(screen.getByTestId('versions-tab-changes')).toHaveAttribute('aria-selected', 'true'));
  });

  it('remembers the open chip per project for the session, and collapses', async () => {
    await renderVersions();
    const chips = await statusChips();
    fireEvent.click(within(chips).getByRole('button', { name: /Compatible/ }));
    expect(window.sessionStorage.getItem(`hive.versions.status.${PROJECT_ID}`)).toBe('"compat"');

    fireEvent.click(screen.getByRole('button', { name: /Collapse/ }));
    expect(statusDetail()).not.toBeVisible();
    expect(window.sessionStorage.getItem(`hive.versions.status.${PROJECT_ID}`)).toBe('null');
    for (const chip of within(chips).getAllByRole('button')) expect(chip).toHaveAttribute('aria-expanded', 'false');
  });

  it('draws the related artifacts panel and the project facts', async () => {
    await renderVersions();
    const related = await screen.findByTestId('catalog-detail-related-artifacts');
    expect(within(related).getByRole('link', { name: 'payments-api.graphql' })).toBeInTheDocument();
    expect(within(related).getByText('payments-legacy.wsdl')).toHaveClass('rart__name-deleted');
    expect(within(related).getByTestId('catalog-show-all-representations')).toBeInTheDocument();
    expect(within(related).getByTestId('catalog-load-suggestions')).toBeInTheDocument();

    const facts = screen.getByTestId('versions-project-facts');
    expect(facts).toHaveTextContent('payments-api');
    expect(facts).toHaveTextContent('v2.4.0 · 9d3f7a21');
    expect(facts).toHaveTextContent('v2.3.1');
    expect(facts).toHaveTextContent('Yes (not a catalog item)');
    expect(within(facts).getByRole('link', { name: 'Published surface' })).toHaveAttribute('href', '/ade/dashboard/published');
    // The Export studio link waits for the studio's release (`lib/feature-release.ts`).
    expect(within(facts).queryByRole('link', { name: 'Export studio' })).not.toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------------------
// The table
// ---------------------------------------------------------------------------------------

describe('the table', () => {
  it('draws the seven columns and the six rows, newest first', async () => {
    await renderVersions();
    const table = screen.getByTestId('versions-table');
    const headers = within(table).getAllByRole('columnheader').map((th) => th.textContent?.trim());
    expect(headers).toEqual(['Version', 'Revision / changelog', 'Status', 'Mock', 'Created by', 'Created', 'Actions']);
    const rows = dataRows();
    expect(rows).toHaveLength(6);
    expect(rows[0]).toHaveTextContent('v2.4.0');
    expect(rows[5]).toHaveTextContent('v2.0.0-beta.1');
    expect(screen.getByTestId('versions-table-foot')).toHaveTextContent('6 revisions · sorted by created ↓ · lifecycle filter: all');
    expect(screen.getByTestId('versions-table-foot-head')).toHaveTextContent('Head v2.4.0 · last published v2.3.1');
  });

  it('draws the version cell: link, lifecycle, HEAD, published lock, locked shield, fork box, id, and the stored lint badge without a lint request', async () => {
    await renderVersions();
    const head = screen.getByTestId(`versions-cell-${HEAD_ID}`);
    expect(within(head).getByRole('button', { name: 'v2.4.0' })).toHaveAttribute('title', 'View spec');
    expect(within(head).getByText('Stable')).toHaveAttribute('data-status', 'stable');
    expect(within(head).getByText('HEAD')).toBeInTheDocument();
    expect(within(head).getByTestId('version-lint-badge')).toHaveTextContent('B · 88');
    expect(within(head).getByText('9d3f7a21')).toBeInTheDocument();

    const published = screen.getByTestId(`versions-cell-${V231_ID}`);
    expect(within(published).getByTestId(`versions-published-chip-${V231_ID}`)).toHaveTextContent('Published');

    const locked = screen.getByTestId(`versions-cell-${V210_ID}`);
    expect(within(locked).getByText('Locked')).toBeInTheDocument();
    expect(within(locked).getByText('Archived')).toHaveAttribute('data-status', 'archived');
    expect(within(locked).getByTestId('version-lint-badge-unscored')).toHaveTextContent('Lint —');

    const forked = screen.getByTestId(`versions-fork-${V220_ID}`);
    expect(forked).toHaveTextContent('Fork · from v1.9.0 (Orders Service)');
    expect(within(screen.getByTestId(`versions-cell-${V220_ID}`)).getByText('Deprecated')).toHaveAttribute('data-status', 'deprecated');

    // #5259: the list is drawn from the stored score — no `/lint` GET was made.
    expect(calls.filter((c) => /\/lint$/.test(c.url))).toHaveLength(0);
  });

  it('draws status, creator and created — with Disabled and the green published date', async () => {
    await renderVersions();
    expect(screen.getByTestId(`versions-status-${V231_ID}`)).toHaveTextContent('Published');
    expect(screen.getByTestId(`versions-status-${HEAD_ID}`)).toHaveTextContent('Draft');
    const disabledRow = screen.getByTestId(`versions-status-${V230_ID}`).closest('tr') as HTMLElement;
    expect(within(disabledRow).getByText('Disabled')).toHaveAttribute('data-status', 'disabled');
    expect(within(disabledRow).getByText('Linus Torvalds')).toBeInTheDocument();
    expect(within(disabledRow).getByText('linus@example.com')).toBeInTheDocument();
    expect(screen.getByTestId(`versions-published-at-${V231_ID}`)).toHaveTextContent(/^Published \d{2}\/\d{2}\/\d{2}$/);
    expect(screen.queryByTestId(`versions-published-at-${HEAD_ID}`)).not.toBeInTheDocument();
  });

  it('narrows with the quick chips and says so in the foot', async () => {
    await renderVersions();
    expect(screen.getByTestId('versions-facet-drafts')).toHaveTextContent('2');
    expect(screen.getByTestId('versions-facet-published')).toHaveTextContent('4');
    fireEvent.click(screen.getByTestId('versions-facet-drafts'));
    await waitFor(() => expect(dataRows()).toHaveLength(2));
    expect(screen.getByTestId('versions-table-foot')).toHaveTextContent('2 revisions');
    expect(screen.getByTestId('versions-facet-drafts')).toHaveAttribute('aria-pressed', 'true');
  });

  it('sorts from the menu and toggles from a header without ever unsorting', async () => {
    await renderVersions();
    const firstVersion = () => dataRows()[0].textContent ?? '';
    expect(firstVersion()).toContain('v2.4.0');
    fireEvent.keyDown(screen.getByTestId('versions-sort-menu'), { key: 'Enter' });
    fireEvent.click(await screen.findByTestId('versions-sort-version'));
    await waitFor(() => expect(firstVersion()).toContain('v2.0.0-beta.1'));
    expect(screen.getByTestId('versions-sort-menu')).toHaveTextContent('Sorted by version ↑');
    // The header cycles asc → desc → (the primitive's null, read as a flip back to asc).
    const versionHeader = within(screen.getByTestId('versions-table')).getByRole('button', { name: /Version/ });
    fireEvent.click(versionHeader);
    await waitFor(() => expect(firstVersion()).toContain('v2.4.0'));
    fireEvent.click(versionHeader);
    await waitFor(() => expect(firstVersion()).toContain('v2.0.0-beta.1'));
    expect(screen.getByTestId('versions-table-foot')).toHaveTextContent('sorted by version ↑');
  });

  it('narrows with the toolbar search and clears it with the Clear filters chip', async () => {
    await renderVersions();
    // One toolbar for the table: the Timeline card is gone (HIVE-11.4).
    expect(screen.queryByTestId('versions-timeline-filters')).not.toBeInTheDocument();
    const toolbar = screen.getByTestId('versions-table-toolbar');
    expect(within(toolbar).getByLabelText('Search revisions')).toBeInTheDocument();
    // No filter, no chip.
    expect(screen.queryByTestId('versions-clear-filters')).not.toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search revisions'), { target: { value: 'payout' } });
    await waitFor(() => expect(dataRows()).toHaveLength(3));
    // The search is URL state, under the REST list's own `q`, beside the project id.
    expect(mockSearch.get('q')).toBe('payout');
    const clear = screen.getByTestId('versions-clear-filters');
    expect(clear).toHaveTextContent('Clear filters (1)');
    fireEvent.click(clear);
    await waitFor(() => expect(dataRows()).toHaveLength(6));
    expect(mockSearch.get('q')).toBeNull();
    expect(screen.getByLabelText('Search revisions')).toHaveValue('');
    expect(screen.queryByTestId('versions-clear-filters')).not.toBeInTheDocument();
    // Nothing matches → the timeline empty state, with its reset.
    fireEvent.change(screen.getByLabelText('Search revisions'), { target: { value: 'zzz-nothing' } });
    await screen.findByTestId('versions-empty-timeline');
    fireEvent.click(screen.getByRole('button', { name: 'Reset timeline filters' }));
    await waitFor(() => expect(screen.queryByTestId('versions-empty-timeline')).not.toBeInTheDocument());
  });

  it('applies a date range from the Any time popover, and restores focus on Escape', async () => {
    await renderVersions();
    const trigger = screen.getByTestId('versions-date-filter');
    expect(trigger).toHaveTextContent('Any time');
    expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');

    fireEvent.click(trigger);
    const popover = await screen.findByRole('dialog', { name: 'Created between' });
    fireEvent.change(within(popover).getByLabelText('From date'), { target: { value: '2026-07-01' } });
    fireEvent.change(within(popover).getByLabelText('To date'), { target: { value: '2026-08-31' } });
    fireEvent.click(within(popover).getByTestId('versions-date-filter-apply'));
    await waitFor(() => expect(dataRows()).toHaveLength(3));
    expect(mockSearch.get('createdAfter')).toBe('2026-07-01');
    expect(mockSearch.get('createdBefore')).toBe('2026-08-31');
    expect(trigger).toHaveTextContent('Jul 1, 2026 – Aug 31, 2026');
    expect(screen.queryByRole('dialog', { name: 'Created between' })).not.toBeInTheDocument();
    // Both dates are one filter each.
    expect(screen.getByTestId('versions-clear-filters')).toHaveTextContent('Clear filters (2)');

    // An inverted draft cannot be applied; Escape discards it and hands focus back.
    fireEvent.click(trigger);
    const again = await screen.findByRole('dialog', { name: 'Created between' });
    expect(within(again).getByLabelText('From date')).toHaveValue('2026-07-01');
    fireEvent.change(within(again).getByLabelText('From date'), { target: { value: '2026-09-30' } });
    expect(within(again).getByRole('alert')).toHaveTextContent('From must be on or before To.');
    expect(within(again).getByTestId('versions-date-filter-apply')).toBeDisabled();
    fireEvent.keyDown(again, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog', { name: 'Created between' })).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(mockSearch.get('createdAfter')).toBe('2026-07-01');

    // Clear inside the popover empties both.
    fireEvent.click(trigger);
    fireEvent.click(within(await screen.findByRole('dialog', { name: 'Created between' })).getByTestId('versions-date-filter-clear'));
    await waitFor(() => expect(dataRows()).toHaveLength(6));
    expect(trigger).toHaveTextContent('Any time');
  });

  it('fills the draft from a quick range chip', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId('versions-date-filter'));
    const popover = await screen.findByRole('dialog', { name: 'Created between' });
    const chip = within(popover).getByTestId('versions-date-preset-last30');
    expect(chip).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(chip);
    expect(chip).toHaveAttribute('aria-pressed', 'true');
    expect(within(popover).getByLabelText('From date')).not.toHaveValue('');
    fireEvent.click(within(popover).getByTestId('versions-date-filter-apply'));
    await waitFor(() => expect(screen.getByTestId('versions-date-filter')).toHaveTextContent('Last 30 days'));
  });

  it('narrows by author from the All authors menu, with avatars, and restores focus', async () => {
    await renderVersions();
    const trigger = screen.getByTestId('versions-author-filter');
    expect(trigger).toHaveTextContent('All authors');
    fireEvent.keyDown(trigger, { key: 'Enter' });
    // Radix names the menu after its trigger.
    const menu = await screen.findByRole('menu', { name: 'All authors' });
    const items = within(menu).getAllByRole('menuitemradio');
    expect(items.map((item) => item.textContent)).toEqual([
      'All authors',
      'ALAda Lovelace',
      'GHGrace Hopper',
      'LTLinus Torvalds',
    ]);
    expect(items[0]).toHaveAttribute('aria-checked', 'true');
    fireEvent.click(items[3]);
    await waitFor(() => expect(dataRows()).toHaveLength(2));
    expect(mockSearch.get('creatorId')).toBe('u-linus');
    expect(trigger).toHaveTextContent('Linus Torvalds');
    expect(screen.queryByTestId('versions-author-filter-menu')).not.toBeInTheDocument();
    await waitFor(() => expect(trigger).toHaveFocus());

    // Escape closes without changing the filter.
    fireEvent.keyDown(trigger, { key: 'Enter' });
    const again = await screen.findByTestId('versions-author-filter-menu');
    expect(within(again).getByTestId('versions-author-u-linus')).toHaveAttribute('aria-checked', 'true');
    fireEvent.keyDown(again, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('versions-author-filter-menu')).not.toBeInTheDocument());
    expect(trigger).toHaveFocus();
    expect(mockSearch.get('creatorId')).toBe('u-linus');
  });

  it('reads every toolbar filter from a shared link and keeps the params it does not own', async () => {
    mockSearch = new URLSearchParams(
      `projectId=${PROJECT_ID}&q=payout&creatorId=u-ada&createdAfter=2026-01-01&createdBefore=2026-12-31&state=drafts`
    );
    render(<Versions />);
    await screen.findByTestId('versions-table');
    await waitFor(() => expect(screen.getByLabelText('Search revisions')).toHaveValue('payout'));
    expect(screen.getByTestId('versions-author-filter')).toHaveTextContent(/Ada Lovelace|1 author/);
    expect(screen.getByTestId('versions-facet-drafts')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('versions-clear-filters')).toHaveTextContent('Clear filters (5)');
    fireEvent.click(screen.getByTestId('versions-clear-filters'));
    await waitFor(() => expect(dataRows()).toHaveLength(6));
    // Every filter dropped; the project stays.
    expect(mockSearch.toString()).toBe(`projectId=${PROJECT_ID}`);
  });

  it('re-reads the list with the lifecycle filter and offers to clear it when nothing matches', async () => {
    installFetch([
      { test: /^\/api\/versions\?projectId=.*&lifecycle=beta$/, reply: () => ({ success: true, versions: [] }) },
    ]);
    await renderVersions();
    fireEvent.keyDown(screen.getByTestId('versions-lifecycle-filter'), { key: 'Enter' });
    fireEvent.click(await screen.findByRole('option', { name: 'Beta' }));
    await screen.findByTestId('versions-empty-lifecycle');
    expect(calls.some((c) => c.url.includes('lifecycle=beta'))).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: 'Clear lifecycle filter' }));
    await waitFor(() => expect(screen.queryByTestId('versions-empty-lifecycle')).not.toBeInTheDocument());
  });
});

// ---------------------------------------------------------------------------------------
// The mock cell
// ---------------------------------------------------------------------------------------

describe('the mock cell', () => {
  it('shows the four states, the URL with its copy button, the scenarios link and the sparkline', async () => {
    await renderVersions();
    const published = screen.getByTestId(`version-mock-cell-${V231_ID}`);
    expect(published).toHaveTextContent('Mock on');
    expect(within(published).getByRole('switch', { name: 'Mock for version 2.3.1' })).toBeChecked();
    expect(within(published).getByText('https://mock.apiome.dev/acme/payments-api/2.3.1')).toBeInTheDocument();
    expect(within(published).getByRole('button', { name: 'Edit mock scenarios for version 2.3.1' })).toBeInTheDocument();
    expect(within(published).getByRole('img', { name: /^Mock requests for v2\.3\.1, last 30 days/ })).toBeInTheDocument();

    const draftPrivate = screen.getByTestId(`version-mock-cell-${BETA_ID}`);
    expect(draftPrivate).toHaveTextContent('Private mock on');
    expect(within(draftPrivate).getByText('Private')).toHaveAttribute('data-status', 'private');
    expect(within(draftPrivate).getByText('No requests yet')).toBeInTheDocument();

    expect(screen.getByTestId(`version-mock-cell-${HEAD_ID}`)).toHaveTextContent('Draft mock off');
    expect(screen.getByTestId(`version-mock-cell-${V230_ID}`)).toHaveTextContent('Mock off');
  });

  it('copies the URL and toggles a draft mock through the PUT route', async () => {
    await renderVersions();
    fireEvent.click(screen.getByRole('button', { name: 'Copy mock URL for version 2.3.1' }));
    await waitFor(() =>
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith('https://mock.apiome.dev/acme/payments-api/2.3.1')
    );
    fireEvent.click(screen.getByRole('switch', { name: 'Mock for version 2.4.0' }));
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT' && c.url === `/api/versions/${HEAD_ID}/mock`);
      expect(put?.body).toEqual({ projectId: PROJECT_ID, enabled: true });
    });
    await waitFor(() => expect(screen.getByTestId(`version-mock-cell-${HEAD_ID}`)).toHaveTextContent('Mock on'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit mock scenarios for version 2.4.0' }));
    await screen.findByTestId('scenario-editor');
  });
});

// ---------------------------------------------------------------------------------------
// The row actions and the menu
// ---------------------------------------------------------------------------------------

describe('the row menu', () => {
  it('lists every action, with the git-like ones drawn, flagged and inert in this build — Delete included', async () => {
    await renderVersions();
    const menu = await openRowMenu(HEAD_ID);
    const items = within(menu).getAllByRole('menuitem').map((item) => item.getAttribute('data-testid'));
    expect(items).toEqual([
      'versions-row-action-view',
      'versions-row-action-export',
      'versions-row-action-compareWithCurrent',
      'versions-row-action-relationshipGraph',
      'versions-row-action-branchFrom',
      'versions-row-action-forkToProject',
      'versions-row-action-tagFrom',
      'versions-row-action-scheduleSunset',
      'versions-row-action-edit',
      'versions-row-action-publish',
      'versions-row-action-freezeSchema',
      'versions-row-action-toggleLock',
      'versions-row-action-delete',
    ]);
    const del = within(menu).getByTestId('versions-row-action-delete');
    expect(del).toHaveAttribute('aria-disabled', 'true');
    expect(del).toHaveAttribute('title', 'Compiled but hidden today (FEATURE_GITLIKE=false)');
    expect(within(del).getByTestId('gitlike-flag')).toBeInTheDocument();
    // The plain items are not flagged and not disabled.
    const publish = within(menu).getByTestId('versions-row-action-publish');
    expect(publish).not.toHaveAttribute('aria-disabled');
    expect(within(publish).queryByTestId('gitlike-flag')).not.toBeInTheDocument();
    // Seven git-like verbs plus Lock revision (the session is a tenant admin).
    expect(within(menu).getAllByTestId('gitlike-flag')).toHaveLength(8);
  });

  it('opens the spec viewer from the version link, and copies the spec', async () => {
    await renderVersions();
    fireEvent.click(within(screen.getByTestId(`versions-cell-${V231_ID}`)).getByRole('button', { name: 'v2.3.1' }));
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(within(dialog).getByRole('heading', { name: 'OpenAPI 3.1.0 specification' })).toBeInTheDocument();
    expect(dialog).toHaveTextContent('Payments API — v2.3.1');
    await within(dialog).findByTestId('mock-monaco');
    // The export cards deep-link into the Export studio, so they wait for its release.
    expect(within(dialog).queryByTestId('version-export-panel')).not.toBeInTheDocument();
    expect(within(dialog).getByTestId('spec-viewer-download')).toHaveTextContent('payments-api-2-3-1-openapi.json');
    fireEvent.click(within(dialog).getByTestId('spec-format-tab-yaml'));
    await waitFor(() => expect(within(dialog).getByTestId('spec-viewer-download')).toHaveTextContent('payments-api-2-3-1-openapi.yaml'));
    fireEvent.click(within(dialog).getByTestId('spec-viewer-copy'));
    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalledWith(expect.stringContaining('openapi: 3.1.0')));
  });

  it('opens the export dialog from the menu', async () => {
    await renderVersions();
    const menu = await openRowMenu(V231_ID);
    fireEvent.click(within(menu).getByTestId('versions-row-action-export'));
    await screen.findByTestId('export-dialog');
  });

  it('confirms an unpublish with the version named, then POSTs the unpublish route', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId(`versions-quick-unpublish-${V231_ID}`));
    await waitFor(() => expect(mockConfirm).toHaveBeenCalled());
    expect(mockConfirm.mock.calls[0][0]).toMatchObject({
      title: 'Unpublish "v2.3.1"?',
      variant: 'danger',
      confirmLabel: 'Unpublish',
    });
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'POST' && c.url === `/api/versions/${V231_ID}/unpublish`)).toBe(true)
    );
  });
});

// ---------------------------------------------------------------------------------------
// The dialogs
// ---------------------------------------------------------------------------------------

describe('the dialogs', () => {
  it('opens New version with the bump preview and creates through POST /api/versions', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId('versions-new-button'));
    const dialog = await screen.findByTestId('new-version-dialog');
    expect(within(dialog).getByTestId('new-version-preview')).toHaveTextContent('Version 2.5.0 will be created');
    expect(within(dialog).getByTestId('new-version-submit')).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId('new-version-message'), { target: { value: 'Add payout limits' } });
    await waitFor(() => expect(within(dialog).getByTestId('new-version-submit')).toBeEnabled());
    fireEvent.click(within(dialog).getByTestId('new-version-submit'));
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.url === '/api/versions');
      expect(post?.body).toMatchObject({ projectId: PROJECT_ID, shortMessage: 'Add payout limits', bump_strategy: 'minor' });
    });
    await waitFor(() => expect(screen.queryByTestId('new-version-dialog')).not.toBeInTheDocument());
  });

  it('opens Edit on a draft with its note, and saves through PUT', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId(`versions-quick-edit-${HEAD_ID}`));
    const dialog = await screen.findByTestId('edit-version-dialog');
    expect(within(dialog).getByTestId('edit-version-note')).toHaveValue('Add refund reasons and payout webhooks');
    fireEvent.change(within(dialog).getByTestId('edit-version-note'), { target: { value: 'Refund reasons' } });
    fireEvent.click(within(dialog).getByTestId('edit-version-submit'));
    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT' && c.url === `/api/versions/${HEAD_ID}`);
      expect(put?.body).toMatchObject({ projectId: PROJECT_ID, shortMessage: 'Refund reasons' });
    });
  });

  it('freezes the notes for a published revision an admin edits', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId(`versions-quick-edit-${V231_ID}`));
    const dialog = await screen.findByTestId('edit-version-dialog');
    expect(within(dialog).getByTestId('edit-version-published-note')).toBeInTheDocument();
    expect(within(dialog).getByTestId('edit-version-note')).toBeDisabled();
  });

  it('opens Schedule sunset from the menu, requires the instant, and saves lifecycle + sunset', async () => {
    await renderVersions();
    const menu = await openRowMenu(HEAD_ID);
    fireEvent.click(within(menu).getByTestId('versions-row-action-scheduleSunset'));
    const dialog = await screen.findByTestId('sunset-schedule-dialog');
    expect(within(dialog).getByTestId('sunset-schedule-submit')).toBeDisabled();
    fireEvent.change(within(dialog).getByTestId('sunset-schedule-local'), { target: { value: '2026-09-30T02:00' } });
    await waitFor(() => expect(within(dialog).getByTestId('sunset-schedule-submit')).toBeEnabled());
    // Lifecycle is still Stable → the save is refused with the same sentence as before.
    fireEvent.click(within(dialog).getByTestId('sunset-schedule-submit'));
    await within(dialog).findByText('Set lifecycle to Deprecated when scheduling a sunset.');
    expect(calls.some((c) => c.method === 'PUT' && c.url === `/api/versions/${HEAD_ID}`)).toBe(false);
  });

  it('publish: a style-guide error blocks, force + reason unblocks, and the POST carries both', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId(`versions-quick-publish-${HEAD_ID}`));
    const dialog = await screen.findByTestId('publish-version-dialog');
    expect(within(dialog).getByRole('heading', { name: 'Publish v2.4.0' })).toBeInTheDocument();
    // The three gates load through the same routes.
    await within(dialog).findByTestId('publish-guide-violations-panel');
    await within(dialog).findByTestId('verification-policy-panel');
    await waitFor(() => expect(within(dialog).getByTestId('publish-submit')).toBeDisabled());
    expect(within(dialog).getByTestId('publish-blocked-note')).toHaveTextContent(
      'Resolve style-guide error violations or enable force publish with a reason.'
    );
    expect(within(dialog).getByTestId('publish-guide-violations-panel')).toHaveTextContent('1 error');
    // The quiet guardrail says nothing; the policy passed.
    expect(within(dialog).queryByTestId('breaking-publish-guardrail-panel')).not.toBeInTheDocument();
    await waitFor(() => expect(within(dialog).getByTestId('verification-policy-panel')).toHaveTextContent('Passed'));
    // In this build the change report is drawn inert with its flag.
    expect(within(dialog).getByTestId('publish-change-report-inert')).toBeInTheDocument();

    fireEvent.click(within(dialog).getByTestId('publish-force'));
    await within(dialog).findByTestId('publish-force-reason');
    expect(within(dialog).getByTestId('publish-submit')).toBeDisabled();
    expect(within(dialog).getByTestId('publish-blocked-note')).toHaveTextContent('Enter a reason for force publishing');
    fireEvent.change(within(dialog).getByTestId('publish-force-reason'), { target: { value: 'Hotfix under change ticket 42' } });
    await waitFor(() => expect(within(dialog).getByTestId('publish-submit')).toBeEnabled());
    fireEvent.click(within(dialog).getByTestId('publish-visibility-public'));
    fireEvent.click(within(dialog).getByTestId('publish-submit'));
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.url === `/api/versions/${HEAD_ID}/publish`);
      expect(post?.body).toMatchObject({
        projectId: PROJECT_ID,
        visibility: 'public',
        shortMessage: 'Add refund reasons and payout webhooks',
        skipPublishChecks: true,
        forcePublishReason: 'Hotfix under change ticket 42',
      });
    });
    await waitFor(() => expect(screen.queryByTestId('publish-version-dialog')).not.toBeInTheDocument());
  });

  it('publish: with no gate tripped the button is live and the POST carries no override', async () => {
    installFetch([{ test: /\/lint$/, reply: () => ({ ...LINT_REPORT_BLOCKING, findings: [], severityCounts: { warning: 1 } }) }]);
    await renderVersions();
    fireEvent.click(screen.getByTestId(`versions-quick-publish-${HEAD_ID}`));
    const dialog = await screen.findByTestId('publish-version-dialog');
    await within(dialog).findByTestId('publish-guide-violations-panel');
    await within(dialog).findByTestId('verification-policy-panel');
    await waitFor(() => expect(within(dialog).getByTestId('publish-submit')).toBeEnabled());
    expect(within(dialog).queryByTestId('publish-blocked-note')).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByTestId('publish-submit'));
    await waitFor(() => {
      const post = calls.find((c) => c.method === 'POST' && c.url === `/api/versions/${HEAD_ID}/publish`);
      expect(post?.body).toMatchObject({ visibility: 'private' });
      expect(post?.body).not.toHaveProperty('skipPublishChecks');
    });
  });
});

// ---------------------------------------------------------------------------------------
// The empty and gated states
// ---------------------------------------------------------------------------------------

describe('the states', () => {
  it('shows the no-versions state with New version and Import', async () => {
    installFetch([{ test: /^\/api\/versions\?projectId=/, reply: () => ({ success: true, versions: [] }) }]);
    render(<Versions />);
    const empty = await screen.findByTestId('versions-empty');
    expect(empty).toHaveTextContent('No versions yet');
    expect(within(empty).getByRole('button', { name: 'New version' })).toBeInTheDocument();
    expect(within(empty).getByRole('button', { name: 'Import' })).toBeInTheDocument();
    expect(screen.queryByTestId('versions-table')).not.toBeInTheDocument();
  });

  it('shows the no-projects state', async () => {
    installFetch([{ test: /^\/api\/projects\?include_catalog=true$/, reply: () => ({ success: true, projects: [] }) }]);
    render(<Versions />);
    await screen.findByTestId('versions-no-projects');
    expect(screen.getByRole('link', { name: 'Go to Projects' })).toHaveAttribute('href', '/ade/dashboard/projects');
  });

  it('opens the shared importer from the header', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId('versions-import-button'));
    await screen.findByTestId('import-dialog');
  });
});

// ---------------------------------------------------------------------------------------
// The browser fixtures
// ---------------------------------------------------------------------------------------

/**
 * `e2e/hive-versions.spec.ts` measures this screen in a real browser — no horizontal document
 * scroll, the column widths, axe — against markup the components actually render. That markup
 * is written here, from the very render this suite pins, into `e2e/fixtures/hive-versions/`
 * when `VERSIONS_FIXTURE_DUMP=1` is set:
 *
 *     VERSIONS_FIXTURE_DUMP=1 npx jest -c jest.config.ts tests/versions-hive-redesign.test.tsx -t fixtures
 *
 * Without the variable the test still runs — it renders every surface and checks each is
 * there — so a change to a component that would leave the fixtures stale fails loudly here
 * before it fails quietly in the browser.
 */
/** The Sources tab's reply for the docs fixture: two service repositories merged into one surface. */
const SOURCES_SOURCE = (id: string, name: string, precedence: number, classes: number, paths: number) => ({
  id,
  repository_id: `repo-${id}`,
  repository_full_name: name,
  provider: 'github',
  branch: 'main',
  path: 'openapi.yaml',
  precedence,
  first_version_id: HEAD_ID,
  last_version_id: HEAD_ID,
  last_version_label: '2.4.0',
  last_blob_sha: null,
  class_count: classes,
  path_count: paths,
  created_at: '2026-10-19T12:00:00Z',
  updated_at: '2026-10-19T12:00:00Z',
});
const SOURCES_PROV = (id: string, name: string, carried: boolean) => ({
  source_id: id,
  repository_id: `repo-${id}`,
  repository_full_name: name,
  branch: 'main',
  path: 'openapi.yaml',
  blob_sha: null,
  carried_from_version_id: carried ? V231_ID : null,
});
const SOURCES_REPLY = {
  project_id: 'project-1',
  sources: [
    SOURCES_SOURCE('s1', 'acme/orders-service', 1, 2, 2),
    SOURCES_SOURCE('s2', 'acme/payments-service', 2, 2, 1),
  ],
  version: { id: HEAD_ID, version_label: '2.4.0' },
  entities: [
    { kind: 'class', key: 'Order', source: SOURCES_PROV('s1', 'acme/orders-service', true) },
    { kind: 'class', key: 'OrderLine', source: SOURCES_PROV('s1', 'acme/orders-service', true) },
    { kind: 'class', key: 'Payment', source: SOURCES_PROV('s2', 'acme/payments-service', false) },
    { kind: 'class', key: 'Refund', source: SOURCES_PROV('s2', 'acme/payments-service', false) },
    { kind: 'class', key: 'Problem', source: null },
    { kind: 'path', key: '/orders', source: SOURCES_PROV('s1', 'acme/orders-service', true) },
    { kind: 'path', key: '/orders/{orderId}', source: SOURCES_PROV('s1', 'acme/orders-service', true) },
    { kind: 'path', key: '/payments', source: SOURCES_PROV('s2', 'acme/payments-service', false) },
  ],
  counts: { classes: 5, paths: 3, attributed: 7, unattributed: 1 },
};

describe('the browser fixtures', () => {
  const OUT = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-versions');
  const dump = process.env.VERSIONS_FIXTURE_DUMP === '1';

  /** Write one fixture, or just assert it could be. */
  const write = (name: string, html: string) => {
    expect(html.length).toBeGreaterThan(0);
    if (!dump) return;
    fs.mkdirSync(OUT, { recursive: true });
    fs.writeFileSync(path.join(OUT, `${name}.html`), html);
  };

  it('renders every surface the browser spec mounts (and writes the fixtures on request)', async () => {
    await renderVersions();
    await statusChips();
    await screen.findByTestId('catalog-detail-related-artifacts');
    write('timeline', (document.querySelector('.page') as HTMLElement).outerHTML);

    const menu = await openRowMenu(HEAD_ID);
    write('menu', menu.outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId(`versions-row-menu-content-${HEAD_ID}`)).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId('versions-new-button'));
    write('new', (await screen.findByTestId('new-version-dialog')).outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('new-version-dialog')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId(`versions-quick-publish-${HEAD_ID}`));
    const publish = await screen.findByTestId('publish-version-dialog');
    await within(publish).findByTestId('publish-guide-violations-panel');
    await waitFor(() => expect(within(publish).getByTestId('verification-policy-panel')).toHaveTextContent('Passed'));
    // As a first-time publisher sees it, before any override — the docs site's screenshot
    // (`apiome-docs/screens.json` `publish-dialog`) is captured from this one.
    write('publish-ready', publish.outerHTML);
    fireEvent.click(within(publish).getByTestId('publish-force'));
    await within(publish).findByTestId('publish-force-reason');
    write('publish', publish.outerHTML);
  });

  /**
   * The documentation site's Build pages (`apiome-docs/screens.json`, DOCS-1.5) show every tab
   * and dialog of this screen. The tabs other than the timeline, and the Edit and Sunset dialogs,
   * are written here; no browser spec mounts them.
   */
  it('renders the other tabs and the edit and sunset dialogs for the docs fixtures', async () => {
    // The Repository tab reads the draft's binding and the tenant's repositories: an unbound draft.
    installFetch([
      {
        test: /\/bindings\?version=/,
        reply: () => ({
          success: true,
          version_id: HEAD_ID,
          version_label: '2.4.0',
          published: false,
          bound: false,
          binding: null,
          released: [],
        }),
      },
      { test: /^\/api\/repositories$/, reply: () => ({ success: true, repositories: [] }) },
      // The Sources tab (REPO-5.7): a project merged from two service repositories.
      { test: /\/repository-sources\?version=/, reply: () => ({ success: true, ...SOURCES_REPLY }) },
    ]);
    await renderVersions();

    for (const tab of ['changes', 'repository', 'sources']) {
      fireEvent.click(screen.getByTestId(`versions-tab-${tab}`));
      await waitFor(() =>
        expect(screen.getByTestId(`versions-tab-${tab}`)).toHaveAttribute('aria-selected', 'true'),
      );
      // Let the panel's own load settle before it is written.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      write(`tab-${tab}`, (document.querySelector('.page') as HTMLElement).outerHTML);
    }
    fireEvent.click(screen.getByTestId('versions-tab-timeline'));

    const draftMenu = await openRowMenu(HEAD_ID);
    fireEvent.click(within(draftMenu).getByTestId('versions-row-action-edit'));
    write('edit', (await screen.findByTestId('edit-version-dialog')).outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('edit-version-dialog')).not.toBeInTheDocument());

    const publishedMenu = await openRowMenu(V231_ID);
    fireEvent.click(within(publishedMenu).getByTestId('versions-row-action-scheduleSunset'));
    write('sunset', (await screen.findByTestId('sunset-schedule-dialog')).outerHTML);
  });
});

/* keep `act` referenced for suites that need explicit flushes */
void act;
