/**
 * Export controls × role — X4 (#6225).
 *
 * `docs/export-permission-matrix.json` tables every export action and the controls that offer it;
 * every row is a member action, so apiome-rest lets viewer, editor and owner perform each one
 * (`apiome-rest/tests/test_export_permission_matrix.py`). This suite renders each screen the table
 * names as every role, with the studio released (`NEXT_PUBLIC_APIOME_PREVIEW_FEATURES=export-studio`),
 * and checks each control is offered exactly when the role may perform its action — so no control is
 * offered that the API would refuse, and none is withheld that the API would allow.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let mockRole = 'owner';

jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () =>
    jest.requireActual<typeof import('./helpers/permission-matrix')>('./helpers/permission-matrix').permissionsFor(mockRole),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'u-ada', current_tenant_id: 't-acme', email: 'ada@acme.io' } },
    status: 'authenticated',
    update: jest.fn(),
  }),
  AuthSessionProvider: ({ children }: { children: React.ReactNode }) => children,
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/catalog',
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href }: { children: React.ReactNode; href: string }) => (
    <a href={typeof href === 'string' ? href : '#'}>{children}</a>
  ),
}));

jest.mock('@monaco-editor/react', () => ({ __esModule: true, default: () => null }));

jest.mock('sonner', () => ({
  __esModule: true,
  toast: Object.assign(jest.fn(), { success: jest.fn(), error: jest.fn() }),
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@lib/db/helper-actions', () => ({
  deleteProject: jest.fn(async () => JSON.stringify({ success: true })),
  restoreProject: jest.fn(async () => JSON.stringify({ success: true })),
  permanentDeleteProject: jest.fn(async () => JSON.stringify({ success: true })),
}));

jest.mock('@/app/components/ade/dashboard/catalog/CatalogImportDialog', () => ({
  __esModule: true,
  CatalogImportDialog: () => null,
}));

jest.mock('@/app/components/ade/dashboard/catalog/ConversionPreviewDialog', () => ({
  __esModule: true,
  ConversionPreviewDialog: () => null,
}));

import CatalogClient from '../src/app/ade/dashboard/catalog/CatalogClient';
import { ExportStudio } from '../src/app/components/ade/dashboard/export/ExportStudio';
import { GenerateProgress } from '../src/app/components/ade/dashboard/export/GenerateProgress';
import { MockTestDrivePanel } from '../src/app/components/ade/dashboard/export/MockTestDrivePanel';
import type { UseExportMockTestDriveResult } from '../src/app/components/ade/dashboard/export/useExportMockTestDrive';
import { RecentAsyncJobsPanel } from '../src/app/components/ade/dashboard/asyncJobs/RecentAsyncJobsPanel';
import { __resetExportJobTrackerForTests } from '../src/app/components/ade/dashboard/export/exportJobTracker';
import { __resetVerifyCacheForTests } from '../src/app/components/ade/dashboard/export/exportVerifyCache';
import { EXPORT_DIALOG_PREVIEWS, mockExportDialogFetch } from './helpers/export-dialog-fixture';
import { EXPORT_MATRIX, ROLES, controlsOn, screenMismatches } from './helpers/permission-matrix';

/** Every screen this suite renders; the table may name no other. */
const SCREENS = ['catalog', 'studio-verify', 'studio-review', 'generate-progress', 'mock-test-drive', 'recent-jobs'];

const LIVE = {
  id: '4d1e9a00-0000-4000-8000-000000000001',
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  name: 'Ledger Graph',
  slug: 'ledger-graph',
  description: 'Double-entry ledger schema.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-08-14T16:02:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@acme.io',
  versionsCount: 3,
  qualityScore: 81,
  qualityGrade: 'B',
  sourceFormat: 'graphql',
  protocol: 'graph',
  formatMetadata: { inputKind: 'file', fileName: 'ledger.graphql' },
  conversion: null,
  paradigm: 'graph',
  domain: null,
  tags: [],
};

/** Another member's finished job, as Recent export jobs lists it. */
const OTHER_MEMBERS_JOB = { job_id: 'job-of-grace', state: 'completed', artifact: 'ledger-graph', target: 'openapi' };

/** A JSON response. */
const json = (payload: unknown, ok = true) =>
  Promise.resolve({ ok, status: ok ? 200 : 500, statusText: 'OK', headers: new Headers(), json: () => Promise.resolve(payload) });

/**
 * The BFF behind every screen here: the catalog list, the export registry and previews
 * (`mockExportDialogFetch`), a clean verify of OpenAPI, and a job list holding another member's job.
 */
function installFetch() {
  const exportFetch = mockExportDialogFetch();
  global.fetch = jest.fn((input: unknown, init?: { method?: string; body?: string }) => {
    const url = String(input);
    if (url.startsWith('/api/import/sources')) return json({ success: true, sources: [] });
    if (url.startsWith('/api/catalog')) return json({ success: true, catalog: [LIVE] });
    if (url.startsWith('/api/export/jobs')) return json({ success: true, jobs: [OTHER_MEMBERS_JOB], total: 1, offset: 0 });
    if (url.includes('/api/export/verify') && init?.method === 'POST') {
      return json({
        success: true,
        artifact: 'proj-petstore',
        version: null,
        version_record_id: 'rev-1',
        version_label: '1.2.0',
        fidelity: EXPORT_DIALOG_PREVIEWS.openapi,
        validation: { verdict: 'valid', target: 'openapi', blocks_delivery: false, warns: false, valid: true, findings: [], detail: null, headline: 'Valid', message: 'Re-parsed cleanly.' },
        lint: { applicable: true, pack: 'pack', score: 95, grade: 'A', findings: [] },
        verdict: 'clean',
      });
    }
    return exportFetch(input, init) as ReturnType<typeof json>;
  }) as unknown as typeof fetch;
}

/** A test-drive hook result: the server can mock OpenAPI, nothing is running yet. */
function testDrive(): UseExportMockTestDriveResult {
  return {
    capability: {
      available: true,
      reason: null,
      supportedTargets: ['openapi'],
      defaultTtlMinutes: 30,
      maxTtlMinutes: 120,
      maxPerTenant: 3,
      rateLimitPerMinute: 60,
    },
    capabilityLoading: false,
    instance: null,
    reattached: false,
    busy: false,
    error: null,
    log: null,
    lastResult: null,
    sending: false,
    start: jest.fn(async () => undefined),
    stop: jest.fn(async () => undefined),
    restart: jest.fn(async () => undefined),
    send: jest.fn(async () => undefined),
  } as unknown as UseExportMockTestDriveResult;
}

/** Render the studio on OpenAPI at Verify, waiting for its registry and fidelity preview. */
async function renderStudioAtVerify() {
  render(<ExportStudio artifact="proj-petstore" artifactLabel="Pet Store API" version="rev-1" initialTarget="openapi" initialStep="verify" />);
  await screen.findByTestId('verify-run');
}

/** How each screen is drawn and its controls reached. */
const SCREEN_SETUP: Record<string, () => Promise<Parameters<typeof screenMismatches>[2]>> = {
  catalog: async () => {
    render(<CatalogClient />);
    await screen.findByText(LIVE.name);
    fireEvent.click(screen.getByTestId('catalog-view-table'));
    await screen.findByTestId('catalog-table');
    return {
      ids: { live: LIVE.id },
      selectAll: async () => {
        fireEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }));
        await screen.findByRole('checkbox', { name: 'Clear selection' });
      },
      clearSelection: () => {
        fireEvent.click(screen.getByRole('checkbox', { name: 'Clear selection' }));
      },
    };
  },
  'studio-verify': async () => {
    await renderStudioAtVerify();
    return { ids: {} };
  },
  'studio-review': async () => {
    await renderStudioAtVerify();
    fireEvent.click(screen.getByTestId('verify-run'));
    const toReview = screen.getByRole('button', { name: /continue to review/i });
    await waitFor(() => expect(toReview).toBeEnabled());
    fireEvent.click(toReview);
    await screen.findByTestId('export-studio-generate');
    return { ids: {} };
  },
  'generate-progress': async () => {
    render(
      <GenerateProgress
        status={{ job_id: 'job-1', state: 'running', percent: 40, events: [], progress: { phase: 'emitting', total: 5, completed: 2 } } as never}
        targetLabel="OpenAPI 3.1"
        submitting={false}
        onRetry={jest.fn()}
        onCancel={jest.fn()}
      />,
    );
    return { ids: {} };
  },
  'mock-test-drive': async () => {
    render(<MockTestDrivePanel testDrive={testDrive()} targetKey="openapi" targetLabel="OpenAPI 3.1" />);
    return { ids: {} };
  },
  'recent-jobs': async () => {
    render(<RecentAsyncJobsPanel kind="export" />);
    await screen.findByText(OTHER_MEMBERS_JOB.job_id);
    return { ids: {} };
  },
};

const PREVIEW = process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;

beforeAll(() => {
  Element.prototype.scrollIntoView = jest.fn();
  Element.prototype.hasPointerCapture = jest.fn(() => false);
});

beforeEach(() => {
  process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = 'export-studio';
  __resetVerifyCacheForTests();
  __resetExportJobTrackerForTests();
  window.sessionStorage.clear();
  window.localStorage.clear();
  installFetch();
});

afterEach(() => {
  if (PREVIEW === undefined) delete process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES;
  else process.env.NEXT_PUBLIC_APIOME_PREVIEW_FEATURES = PREVIEW;
});

describe('the export table', () => {
  it('makes every export action a member action', () => {
    for (const action of EXPORT_MATRIX.actions) expect([action.id, action.permission]).toEqual([action.id, null]);
  });

  it('puts every control on a screen this suite renders', () => {
    const named = new Set(EXPORT_MATRIX.actions.flatMap((action) => action.ui.map((control) => control.screen)));
    expect([...named].filter((name) => !SCREENS.includes(name))).toEqual([]);
    for (const name of SCREENS) expect(controlsOn(name, EXPORT_MATRIX).length).toBeGreaterThan(0);
  });

  it('says why an action has no control', () => {
    for (const action of EXPORT_MATRIX.actions) {
      if (action.ui.length === 0) expect(action.ui_note).toBeTruthy();
    }
  });
});

describe.each(ROLES)('export controls as %s', (role) => {
  it.each(SCREENS)('the %s screen offers each control exactly when the role may use it', async (name) => {
    mockRole = role;
    const driver = await SCREEN_SETUP[name]();
    expect(await screenMismatches(name, role, driver, EXPORT_MATRIX)).toEqual([]);
  });

  it('lists another member’s job in Recent export jobs', async () => {
    mockRole = role;
    render(<RecentAsyncJobsPanel kind="export" />);
    expect(await screen.findByText(OTHER_MEMBERS_JOB.job_id)).toBeInTheDocument();
  });
});
