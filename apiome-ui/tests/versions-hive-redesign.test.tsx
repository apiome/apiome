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
import { VERSION_DIALOG_COPY } from '@/app/components/ade/version-dialogs/versionDialogsModel';
import userEvent from '@testing-library/user-event';
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

const mockGetClasses = jest.fn(async (): Promise<string> => '[]');
const mockGetPropsBatch = jest.fn(async (): Promise<string> => '{}');

jest.mock('@lib/db/helper-actions', () => ({
  deleteVersion: (...args: unknown[]) => mockDeleteVersion(...(args as [])),
  buildOpenApiSpecJsonForVersion: (...args: unknown[]) => mockBuildSpec(...(args as [])),
  getClassesForVersion: (...args: unknown[]) => mockGetClasses(...(args as [])),
  getPropertiesForClass: async () => '[]',
  getPropertiesForClassesBatch: (...args: unknown[]) => mockGetPropsBatch(...(args as [])),
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
/** The Compare dialog's Canvas tab reads both layouts through this (RC6-H3 tests fail it). */
const mockLoadLayout = jest.fn(async (): Promise<unknown> => ({ nodes: [], edges: [] }));
jest.mock('../lib/version-canvas-layout', () => ({
  loadLayoutStateForVersionCompare: (...args: unknown[]) => mockLoadLayout(...(args as [])),
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

// These suites cover the screen as an Owner; what each role is offered is
// tests/permission-matrix-ui.test.tsx (RC6-H5, #6212).
jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () => ({ status: 'ready', can: () => true, isAdmin: true }),
}));

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
// Loading and failure (RC6-H3, #6210)
// ---------------------------------------------------------------------------------------

describe('a pending or failed projects or versions read', () => {
  /**
   * Wrap the suite's fetch so reads matching `pattern` are held (`'hold'`) or fail with a 503
   * (`'fail'`) until the returned `recover()` is called; everything else answers as usual.
   */
  function intercept(pattern: RegExp, mode: 'hold' | 'fail') {
    const answer = global.fetch;
    let failing = true;
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (failing && pattern.test(String(input))) {
        if (mode === 'hold') return new Promise<Response>(() => {});
        return Promise.resolve(jsonResponse({ success: false, error: 'Service unavailable' }, 503));
      }
      return answer(input, init);
    }) as unknown as typeof fetch;
    return { recover: () => { failing = false; } };
  }

  it('keeps the page when every enrichment read fails — no blank, no error (the ledger’s promise)', async () => {
    const answer = global.fetch;
    global.fetch = jest.fn((input: RequestInfo | URL, init?: RequestInit) =>
      /\/version-tags$|\/has-class-schema|\/changelogs$|\/api\/mocks\/usage|\/api\/reviews\/status/.test(String(input))
        ? Promise.resolve(jsonResponse({ success: false, error: 'enrichment down' }, 503))
        : answer(input, init)
    ) as unknown as typeof fetch;
    await renderVersions();
    expect(screen.getByTestId(`versions-cell-${HEAD_ID}`)).toBeInTheDocument();
    expect(screen.queryByText("Couldn't load this project's versions")).toBeNull();
    expect(screen.queryByTestId('versions-projects-error')).toBeNull();
  });

  it('shows a loading state, not "No projects yet", while the projects read is pending', async () => {
    intercept(/^\/api\/projects\?include_catalog=true$/, 'hold');
    render(<Versions />);
    expect(await screen.findByTestId('versions-projects-loading')).toHaveTextContent('Loading projects…');
    expect(screen.queryByTestId('versions-no-projects')).toBeNull();
  });

  it('says a failed projects read failed, and retries it', async () => {
    const read = intercept(/^\/api\/projects\?include_catalog=true$/, 'fail');
    render(<Versions />);
    const error = await screen.findByTestId('versions-projects-error');
    read.recover();
    expect(error).toHaveTextContent("Couldn't load your projects");
    expect(screen.queryByTestId('versions-no-projects')).toBeNull();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('versions-table')).toBeInTheDocument();
  });

  it('holds the table with skeleton rows while the versions read is pending', async () => {
    intercept(/^\/api\/versions\?projectId=/, 'hold');
    render(<Versions />);
    const table = await screen.findByTestId('versions-table');
    expect(await within(table).findByText('Loading versions...')).toBeInTheDocument();
    expect(screen.queryByText('No versions yet')).toBeNull();
  });

  it('says a failed versions read failed, instead of "No versions yet", and retries it', async () => {
    const read = intercept(/^\/api\/versions\?projectId=/, 'fail');
    render(<Versions />);
    expect(await screen.findByText("Couldn't load this project's versions")).toBeInTheDocument();
    expect(screen.queryByText('No versions yet')).toBeNull();
    read.recover();
    fireEvent.click(screen.getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId(`versions-cell-${HEAD_ID}`)).toBeInTheDocument();
  });
});

describe('a pending or failed read inside a Versions dialog (RC6-H3, #6210)', () => {
  it('View spec: a code skeleton while the spec builds, then an error with a retry — never a made-up spec', async () => {
    let release: () => void = () => {};
    mockBuildSpec.mockImplementationOnce(
      () => new Promise((_, reject) => { release = () => reject(new Error('Schema store unreachable')); })
    );
    await renderVersions();
    fireEvent.click(within(screen.getByTestId(`versions-cell-${V231_ID}`)).getByRole('button', { name: 'v2.3.1' }));
    const dialog = await screen.findByTestId('spec-viewer-dialog');
    expect(await within(dialog).findByTestId('spec-viewer-loading')).toBeInTheDocument();
    await act(async () => release());
    const error = await within(dialog).findByTestId('spec-viewer-error');
    expect(error).toHaveTextContent("Couldn't build this specification");
    expect(error).toHaveTextContent('Schema store unreachable');
    expect(dialog).not.toHaveTextContent('Error Loading Spec');
    expect(within(dialog).getByTestId('spec-viewer-download')).toBeDisabled();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await within(dialog).findByTestId('mock-monaco')).toBeInTheDocument();
  });

  it('Heatmap: tile skeletons while the classes load, then an error with a retry — not "no classes yet"', async () => {
    let release: () => void = () => {};
    mockGetClasses.mockImplementationOnce(
      () => new Promise((_, reject) => { release = () => reject(new Error('Classes unavailable')); })
    );
    await renderVersions();
    const menu = await openRowMenu(V231_ID);
    fireEvent.click(within(menu).getByTestId('versions-row-action-heatmap'));
    expect(await screen.findByTestId('heatmap-loading')).toBeInTheDocument();
    await act(async () => release());
    const error = await screen.findByTestId('heatmap-error');
    expect(error).toHaveTextContent("Couldn't load this version's classes");
    expect(screen.queryByTestId('heatmap-empty')).toBeNull();
    mockGetClasses.mockResolvedValueOnce(JSON.stringify([{ id: 'c-order', name: 'Order', description: null, updated_at: null }]));
    mockGetPropsBatch.mockResolvedValueOnce(JSON.stringify({}));
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('heatmap-grid')).toBeInTheDocument();
  });

  it('New version: a failed branch read says so, with a retry, and the rest of the dialog still works', async () => {
    installFetch([{ test: /\/version-branches$/, status: 500, reply: () => ({ success: false, error: 'Branch index unavailable' }) }]);
    await renderVersions();
    fireEvent.click(screen.getByTestId('versions-new-button'));
    const dialog = await screen.findByTestId('new-version-dialog');
    const error = await within(dialog).findByTestId('new-version-branches-error');
    expect(error).toHaveTextContent("Couldn't load this project's branches");
    expect(within(dialog).getByTestId('new-version-message')).toBeEnabled();
    const before = calls.filter((call) => call.url.endsWith('/version-branches')).length;
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() =>
      expect(calls.filter((call) => call.url.endsWith('/version-branches')).length).toBeGreaterThan(before)
    );
  });

  it('Compare: a failed spec build is said in the dialog, with a retry — no modal on top of it', async () => {
    mockBuildSpec.mockRejectedValueOnce(new Error('Spec build failed'));
    // The deep link the canvas divergence chip uses (#2723); the row's compare verb is git-like.
    window.history.replaceState(null, '', `/ade/dashboard/versions?compareOpen=1&compareBase=${V231_ID}&compareHead=${HEAD_ID}`);
    await renderVersions();
    const error = await screen.findByTestId('compare-error');
    expect(error).toHaveTextContent("Couldn't load the two specifications");
    expect(mockAlert).not.toHaveBeenCalled();
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    await waitFor(() => expect(screen.queryByTestId('compare-error')).toBeNull());
    expect(await screen.findByRole('tab', { name: /canvas/i })).toBeInTheDocument();
  });

  it('Compare › Canvas: a spinner while the layouts load, then an error with a retry — not a toast', async () => {
    let release: () => void = () => {};
    mockLoadLayout.mockImplementationOnce(
      () => new Promise((_, reject) => { release = () => reject(new Error('Layout store unreachable')); })
    );
    // The deep link the canvas divergence chip uses (#2723); the row's compare verb is git-like.
    window.history.replaceState(null, '', `/ade/dashboard/versions?compareOpen=1&compareBase=${V231_ID}&compareHead=${HEAD_ID}`);
    await renderVersions();
    fireEvent.click(await screen.findByRole('tab', { name: /canvas/i }));
    expect(await screen.findByText(VERSION_DIALOG_COPY.canvasLoading)).toBeInTheDocument();
    await act(async () => release());
    const error = await screen.findByTestId('compare-canvas-error');
    expect(error).toHaveTextContent("Couldn't load the canvas layouts");
    fireEvent.click(within(error).getByRole('button', { name: /try again/i }));
    expect(await screen.findByTestId('canvas-compare')).toBeInTheDocument();
  });
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

  it('leaves the Dependencies tab out while the dependency graph is held back (RC6)', async () => {
    await renderVersions();
    expect(screen.queryByTestId('versions-tab-dependencies')).not.toBeInTheDocument();
  });

  it('opens the project\'s Dependencies tab (CDG-3.4)', async () => {
    process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'dependency-graph';
    try {
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
    } finally {
      delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
    }
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
      'versions-row-action-heatmap',
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

  it('opens the class heatmap from the menu, loading the classes and their properties in one batch (#560)', async () => {
    mockGetClasses.mockResolvedValueOnce(
      JSON.stringify([
        { id: 'c-order', name: 'Order', description: 'An order', updated_at: new Date().toISOString() },
        { id: 'c-item', name: 'Item', description: null, updated_at: '2020-01-01T00:00:00Z' },
      ])
    );
    mockGetPropsBatch.mockResolvedValueOnce(
      JSON.stringify({
        'c-order': [{ id: 'p1', name: 'items', description: 'Lines', data: { type: 'array', items: { $ref: '#/components/schemas/Item' } } }],
      })
    );
    await renderVersions();
    const menu = await openRowMenu(V231_ID);
    fireEvent.click(within(menu).getByTestId('versions-row-action-heatmap'));
    const grid = await screen.findByTestId('heatmap-grid');
    expect(mockGetClasses).toHaveBeenCalledWith(V231_ID);
    expect(mockGetPropsBatch).toHaveBeenCalledWith(['c-order', 'c-item']);
    expect(screen.getByRole('heading', { name: 'Heatmap' })).toBeInTheDocument();
    // Complexity first: Order (1 prop + depth 1 + 1 ref) leads Item (nothing).
    const tiles = within(grid).getAllByRole('listitem');
    expect(tiles.map((t) => t.getAttribute('data-testid'))).toEqual(['heatmap-tile-c-order', 'heatmap-tile-c-item']);
    expect(tiles[0]).toHaveAttribute('data-heat', '4');
    expect(tiles[1]).toHaveAttribute('data-heat', '0');
    // References: Item is the one referenced.
    fireEvent.click(screen.getByTestId('heatmap-metric-references'));
    expect(screen.getByTestId('heatmap-tile-c-item')).toHaveAttribute('data-heat', '4');
    expect(screen.getByTestId('heatmap-tile-c-item')).toHaveTextContent('1 ref');
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
  it('opens Publish from the keyboard and returns focus to the row button on Escape (RC6-H2)', async () => {
    await renderVersions();
    // `userEvent.setup()` swaps in its own clipboard; the suite's `beforeEach` needs the mock back.
    const clipboard = navigator.clipboard;
    const user = userEvent.setup();
    Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
    const trigger = screen.getByTestId(`versions-quick-publish-${HEAD_ID}`);
    trigger.focus();
    await user.keyboard('{Enter}');
    const dialog = await screen.findByTestId('publish-version-dialog');
    await waitFor(() => expect(dialog.contains(document.activeElement)).toBe(true));
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByTestId('publish-version-dialog')).toBeNull());
    await waitFor(() => expect(trigger).toHaveFocus());
  });

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

  it('copies from a version with or without its paths (#771)', async () => {
    // user-event installs its own clipboard; keep the suite's mock for the tests after this one.
    const clipboard = navigator.clipboard;
    const user = userEvent.setup();
    try {
      await renderVersions();
      fireEvent.click(screen.getByTestId('versions-new-button'));
      const dialog = await screen.findByTestId('new-version-dialog');
      // Blank version: nothing to copy, so no choice.
      expect(within(dialog).queryByTestId('new-version-copy-paths')).not.toBeInTheDocument();
      await user.click(within(dialog).getByRole('combobox', { name: 'Copy from version' }));
      await user.click(await screen.findByRole('option', { name: /v2\.3\.1/ }));
      const copyPaths = within(dialog).getByRole('checkbox', { name: 'Copy paths' });
      expect(copyPaths).toBeChecked();
      expect(within(dialog).getByTestId('new-version-copy-note')).toHaveTextContent(
        'Classes, properties and paths will be copied from the selected revision.'
      );
      await user.click(copyPaths);
      expect(copyPaths).not.toBeChecked();
      expect(within(dialog).getByTestId('new-version-copy-note')).toHaveTextContent('Paths will not be copied');
      fireEvent.change(within(dialog).getByTestId('new-version-message'), { target: { value: 'Schemas only' } });
      await waitFor(() => expect(within(dialog).getByTestId('new-version-submit')).toBeEnabled());
      fireEvent.click(within(dialog).getByTestId('new-version-submit'));
      await waitFor(() => {
        const post = calls.find((c) => c.method === 'POST' && c.url === '/api/versions');
        expect(post?.body).toMatchObject({ source_version_id: V231_ID, copyPaths: false });
      });
    } finally {
      Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
    }
  });

  it('sends no copyPaths for a blank version', async () => {
    await renderVersions();
    fireEvent.click(screen.getByTestId('versions-new-button'));
    const dialog = await screen.findByTestId('new-version-dialog');
    fireEvent.change(within(dialog).getByTestId('new-version-message'), { target: { value: 'Blank' } });
    await waitFor(() => expect(within(dialog).getByTestId('new-version-submit')).toBeEnabled());
    fireEvent.click(within(dialog).getByTestId('new-version-submit'));
    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.url === '/api/versions')).toBe(true));
    const post = calls.find((c) => c.method === 'POST' && c.url === '/api/versions');
    expect(post?.body).not.toHaveProperty('copyPaths');
    expect(post?.body).not.toHaveProperty('source_version_id');
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

/** The Sources tab's merge history for the docs fixture (V2-REPO-8.2): a conflict, then a merge. */
const MERGE_HISTORY = [
  {
    id: 'fm-2',
    projectId: 'project-1',
    projectName: 'Payments API',
    status: 'conflicted',
    versionId: null,
    versionLabel: null,
    repositoryFullName: 'acme/payments-service',
    branch: 'main',
    path: 'openapi.yaml',
    sourceCount: 2,
    classesCarried: 0,
    pathsCarried: 0,
    removedCount: 0,
    conflictCount: 1,
    sources: [],
    conflicts: [
      {
        kind: 'class',
        key: 'Order',
        sources: [
          {
            role: 'existing',
            repositoryFullName: 'acme/orders-service',
            branch: 'main',
            path: 'openapi.yaml',
            definition: { type: 'object', required: ['id'], properties: { id: { type: 'string' }, total: { type: 'number' } } },
          },
          {
            role: 'incoming',
            repositoryFullName: 'acme/payments-service',
            branch: 'main',
            path: 'openapi.yaml',
            definition: { type: 'object', required: ['id', 'amount'], properties: { amount: { type: 'number' }, id: { type: 'string' } } },
          },
        ],
      },
    ],
    createdAt: '2026-10-19T14:20:00Z',
  },
  {
    id: 'fm-1',
    projectId: 'project-1',
    projectName: 'Payments API',
    status: 'merged',
    versionId: HEAD_ID,
    versionLabel: '2.4.0',
    repositoryFullName: 'acme/payments-service',
    branch: 'main',
    path: 'openapi.yaml',
    sourceCount: 2,
    classesCarried: 2,
    pathsCarried: 2,
    removedCount: 0,
    conflictCount: 0,
    sources: [],
    conflicts: [],
    createdAt: '2026-10-18T09:00:00Z',
  },
];

/** The PR-back section's listing for the docs fixture (REPO-5.8). */
const PR_BACK_REPOSITORIES = {
  projectId: 'project-1',
  repositories: [
    {
      repositoryId: 'repo-s1',
      repositoryFullName: 'acme/orders-service',
      files: [{ path: 'openapi.yaml', branch: 'main', precedence: 1 }],
      eligible: true,
      baseBranch: 'main',
      reasonCode: null,
      reason: null,
    },
    {
      repositoryId: 'repo-s2',
      repositoryFullName: 'acme/payments-service',
      files: [{ path: 'openapi.yaml', branch: 'main', precedence: 2 }],
      eligible: false,
      baseBranch: null,
      reasonCode: 'pr-back-not-configured',
      reason:
        'acme/payments-service has no PR-back settings, so no project may open pull requests into it. An administrator of the repository can allow projects in its Settings tab.',
    },
  ],
};

/** A PR-back dry run into the orders repository, for the docs fixture (REPO-5.8). */
const PR_BACK_PREVIEW = {
  status: 'preview',
  dryRun: true,
  versionLabel: '2.4.0',
  repositoryFullName: 'acme/orders-service',
  baseBranch: 'main',
  branchName: 'apiome/pr-back-payments-api-main',
  title: 'Apiome: sync Payments API 2.4.0',
  commitMessage: 'Sync Payments API 2.4.0 from Apiome',
  body: '## Payments API 2.4.0 — rendered from Apiome\n\nApiome rendered version **2.4.0** of **Payments API** and wrote 1 of 1 source file(s) back to `acme/orders-service`.\n\n### `openapi.yaml` — modified\n\n2 path(s) and 3 schema(s) rendered from Apiome.\n\n# Change report: Payments API\n\n- Schemas: 1 added, 0 removed, 1 modified\n',
  files: [
    { path: 'openapi.yaml', status: 'modified', paths: 2, schemas: 3, counts: { schemasAdded: 1, schemasModified: 1 }, foreignRefs: [], notes: [] },
  ],
  skipped: [],
  reviewers: [],
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

    // The header's ⋯ menu (HIVE-11.3), which the axe gate holds too (RC6-H2, #6209).
    fireEvent.keyDown(screen.getByTestId('page-header-overflow'), { key: 'Enter' });
    write('header-menu', (await screen.findByTestId('page-header-overflow-menu')).outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('page-header-overflow-menu')).not.toBeInTheDocument());

    fireEvent.click(screen.getByTestId('versions-new-button'));
    const newDialog = await screen.findByTestId('new-version-dialog');
    // Copying from v2.3.1, so the docs screenshot shows the Copy paths choice (#771).
    const clipboard = navigator.clipboard;
    const user = userEvent.setup();
    await user.click(within(newDialog).getByRole('combobox', { name: 'Copy from version' }));
    await user.click(await screen.findByRole('option', { name: /v2\.3\.1/ }));
    Object.defineProperty(navigator, 'clipboard', { value: clipboard, configurable: true });
    await within(newDialog).findByTestId('new-version-copy-paths');
    write('new', newDialog.outerHTML);
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
      // Its PR-back section (REPO-5.8): one repository allows the project, one has no settings.
      { test: /\/pr-back\/repositories$/, reply: () => ({ success: true, ...PR_BACK_REPOSITORIES }) },
      { method: 'POST', test: /\/pr-back$/, reply: () => ({ success: true, ...PR_BACK_PREVIEW }) },
      // Federation (V2-REPO-8.2): the switch is on, and the merge history holds a conflict and a merge.
      { test: /\/repository-federation$/, reply: () => ({ success: true, projectId: 'project-1', enabled: true }) },
      { test: /\/federation-merges$/, reply: () => ({ success: true, merges: MERGE_HISTORY }) },
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
    // Still on Sources: preview a pull request back to the orders repository (REPO-5.8).
    const [prBackRow] = await screen.findAllByTestId('pr-back-repository');
    fireEvent.click(within(prBackRow).getByTestId('pr-back-preview'));
    await within(prBackRow).findByTestId('pr-back-status-preview');
    write('tab-sources-pr-back', (document.querySelector('.page') as HTMLElement).outerHTML);
    // …and the merge history with its conflict opened (V2-REPO-8.2).
    const history = await screen.findByTestId('project-merge-history');
    expect(within(history).getAllByTestId('federation-merge')).toHaveLength(2);
    history.querySelectorAll('details.fed-details').forEach((details) => details.setAttribute('open', ''));
    write('tab-sources-merge-history', (document.querySelector('.page') as HTMLElement).outerHTML);
    fireEvent.click(screen.getByTestId('versions-tab-timeline'));

    const draftMenu = await openRowMenu(HEAD_ID);
    fireEvent.click(within(draftMenu).getByTestId('versions-row-action-edit'));
    write('edit', (await screen.findByTestId('edit-version-dialog')).outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('edit-version-dialog')).not.toBeInTheDocument());

    const publishedMenu = await openRowMenu(V231_ID);
    fireEvent.click(within(publishedMenu).getByTestId('versions-row-action-scheduleSunset'));
    write('sunset', (await screen.findByTestId('sunset-schedule-dialog')).outerHTML);
    fireEvent.keyDown(document.body, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByTestId('sunset-schedule-dialog')).not.toBeInTheDocument());

    // The class heatmap (#560): a small payments schema, coloured by complexity.
    const day = 86_400_000;
    const ago = (n: number) => new Date(Date.now() - n * day).toISOString();
    const ref = (name: string) => ({ $ref: `#/components/schemas/${name}` });
    mockGetClasses.mockResolvedValueOnce(
      JSON.stringify([
        { id: 'h-payment', name: 'Payment', description: 'A charge against a card', updated_at: ago(0) },
        { id: 'h-refund', name: 'Refund', description: 'Money returned', updated_at: ago(4) },
        { id: 'h-customer', name: 'Customer', description: 'Who pays', updated_at: ago(21) },
        { id: 'h-card', name: 'Card', description: null, updated_at: ago(60) },
        { id: 'h-address', name: 'Address', description: null, updated_at: ago(200) },
        { id: 'h-payout', name: 'Payout', description: 'A transfer to the merchant', updated_at: ago(2) },
        { id: 'h-currency', name: 'Currency', description: 'ISO 4217 code', updated_at: ago(400) },
      ])
    );
    mockGetPropsBatch.mockResolvedValueOnce(
      JSON.stringify({
        'h-payment': [
          { id: 'pa1', name: 'id', description: 'Identifier', data: { type: 'string' } },
          { id: 'pa2', name: 'amount', description: 'Minor units', data: { type: 'integer' } },
          { id: 'pa3', name: 'currency', description: null, data: ref('Currency') },
          { id: 'pa4', name: 'customer', description: 'Payer', data: ref('Customer') },
          { id: 'pa5', name: 'card', description: null, data: ref('Card') },
          { id: 'pa6', name: 'metadata', description: null, data: { type: 'object' } },
          { id: 'pa7', name: 'tag', description: null, data: { type: 'string' }, parent_id: 'pa6' },
        ],
        'h-refund': [
          { id: 'rf1', name: 'payment', description: 'Refunded charge', data: ref('Payment') },
          { id: 'rf2', name: 'amount', description: 'Minor units', data: { type: 'integer' } },
          { id: 'rf3', name: 'currency', description: null, data: ref('Currency') },
        ],
        'h-customer': [
          { id: 'cu1', name: 'name', description: 'Full name', data: { type: 'string' } },
          { id: 'cu2', name: 'address', description: 'Billing', data: ref('Address') },
        ],
        'h-card': [
          { id: 'ca1', name: 'last4', description: null, data: { type: 'string' } },
          { id: 'ca2', name: 'billing', description: null, data: ref('Address') },
        ],
        'h-address': [{ id: 'ad1', name: 'line1', description: null, data: { type: 'string' } }],
        'h-payout': [
          { id: 'po1', name: 'amount', description: 'Minor units', data: { type: 'integer' } },
          { id: 'po2', name: 'currency', description: 'Settlement', data: ref('Currency') },
        ],
      })
    );
    const heatmapMenu = await openRowMenu(V231_ID);
    fireEvent.click(within(heatmapMenu).getByTestId('versions-row-action-heatmap'));
    await screen.findByTestId('heatmap-grid');
    write('heatmap', screen.getByTestId('class-heatmap-dialog').outerHTML);
  });
});

/* keep `act` referenced for suites that need explicit flushes */
void act;
