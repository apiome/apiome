/**
 * The versions table at 300 revisions — RC6-H6 (#6213).
 *
 * A long-lived project has hundreds of revisions. The table draws one page of them
 * (`VERSIONS_PAGE_SIZE`, the page in the URL with the filters), so the first row, a filter and a
 * re-sort cost the same at 300 as at 50. Budgets: `tests/helpers/list-budgets.ts`.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let mockRole = 'owner';

jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () => jest.requireActual<typeof import('./helpers/permission-matrix')>('./helpers/permission-matrix').permissionsFor(mockRole),
}));

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
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
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
import { VERSIONS_PAGE_SIZE } from '../src/app/components/ade/versions/versionsModel';
import { LIST_BUDGET_MS, timed, writeAtSizeFixture } from './helpers/list-budgets';

const PROJECT_ID = '8f2a1c00-0000-4000-8000-000000000001';

/** 300 revisions, `1.0.0` … `1.29.9`, every third one published. */
const VERSIONS = Array.from({ length: 300 }, (_, index) => ({
  project_id: PROJECT_ID,
  creator_id: 'u-ada',
  shortMessage: `Revision ${index}`,
  changelog: null,
  enabled: true,
  deleted_at: null,
  updated_at: '2026-01-01T00:00:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
  id: `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`,
  version_id: `1.${Math.floor(index / 10)}.${index % 10}`,
  published: index % 3 === 0,
  published_at: index % 3 === 0 ? '2026-08-03T10:00:00.000Z' : null,
  created_at: new Date(Date.UTC(2026, 0, 1) + index * 3_600_000).toISOString(),
}));

const rows = () => document.querySelectorAll('[data-testid="versions-table"] tr[data-row-id]').length;
const foot = () => screen.getByTestId('versions-table-foot').textContent ?? '';

beforeAll(() => {
  (global as unknown as { ResizeObserver: unknown }).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  mockRole = 'owner';
  mockSearch = new URLSearchParams();
  window.sessionStorage.clear();
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.startsWith('/api/projects?include_catalog=true')
      ? { success: true, projects: [{ id: PROJECT_ID, name: 'Payments API', slug: 'payments-api', publishable: true }] }
      : url.startsWith('/api/versions?projectId=')
        ? { success: true, versions: VERSIONS }
        : { success: true };
    return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body) } as unknown as Response;
  }) as unknown as typeof fetch;
});

/** Render the page and wait for the first row. */
async function renderVersions() {
  render(<Versions />);
  await screen.findByTestId('versions-table');
  await waitFor(() => expect(rows()).toBeGreaterThan(0));
}

describe('the versions table at 300 revisions', () => {
  it('draws its first row within budget, and one page rather than every revision', async () => {
    const ms = await timed(renderVersions);
    expect(ms).toBeLessThan(LIST_BUDGET_MS.firstRow);
    expect(rows()).toBe(VERSIONS_PAGE_SIZE);
    expect(foot()).toMatch(/^Showing 1–50 of 300 revisions/);
  });

  it('filters within budget, back on page 1', async () => {
    await renderVersions();
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(foot()).toMatch(/^Showing 51–100 of 300/));
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(foot()).toMatch(/^Showing 101–150 of 300/));
    const ms = await timed(async () => {
      fireEvent.click(screen.getByTestId('versions-facet-published'));
      await waitFor(() => expect(foot()).toMatch(/^Showing 1–50 of 100 revisions/));
    });
    expect(ms).toBeLessThan(LIST_BUDGET_MS.filter);
    expect(rows()).toBe(VERSIONS_PAGE_SIZE);
  });

  it('re-sorts within budget', async () => {
    await renderVersions();
    const before = foot();
    const ms = await timed(async () => {
      fireEvent.click(screen.getByRole('button', { name: /^Version/ }));
      await waitFor(() => expect(foot()).not.toBe(before));
    });
    expect(ms).toBeLessThan(LIST_BUDGET_MS.sort);
    expect(rows()).toBe(VERSIONS_PAGE_SIZE);
  });
});

describe('the at-size fixture', () => {
  it('renders the fixture the browser spec measures', async () => {
    await renderVersions();
    writeAtSizeFixture('versions-300');
  });
});
