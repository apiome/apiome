/**
 * Catalog list × role — RC6-H5 (#6212).
 *
 * Renders the Catalog as Viewer, Editor and Owner and checks every control
 * `docs/catalog-projects-permission-matrix.json` puts on it: offered exactly when the role may
 * perform the action, as apiome-rest decides it (`apiome-rest/tests/test_permission_matrix.py`).
 */

import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

let mockRole = 'owner';

jest.mock('../src/app/components/ade/access/useMyPermissions', () => ({
  ...jest.requireActual('../src/app/components/ade/access/useMyPermissions'),
  useMyPermissions: () => jest.requireActual<typeof import('./helpers/permission-matrix')>('./helpers/permission-matrix').permissionsFor(mockRole),
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
import { ROLES, screenMismatches } from './helpers/permission-matrix';

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

const DELETED = {
  ...LIVE,
  id: 'deadbe00-0000-4000-8000-000000000004',
  name: 'Legacy Graph',
  slug: 'legacy-graph',
  deleted_at: '2026-08-10T09:00:00.000Z',
};

/** Serve `/api/catalog` (honouring `include_deleted`) and the import-source registry. */
function mockCatalog() {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.startsWith('/api/import/sources')) {
      return { ok: true, statusText: 'OK', json: async () => ({ success: true, sources: [] }) } as Response;
    }
    const catalog = url.includes('include_deleted=true') ? [LIVE, DELETED] : [LIVE];
    return { ok: true, statusText: 'OK', json: async () => ({ success: true, catalog }) } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  window.localStorage.clear();
  mockCatalog();
});

describe.each(ROLES)('the Catalog as %s', (role) => {
  it('offers each control exactly when the role may use it', async () => {
    mockRole = role;
    render(<CatalogClient />);
    await screen.findByText(LIVE.name);

    // The table, with deleted items shown, draws every control the table lists.
    fireEvent.click(screen.getByTestId('catalog-view-table'));
    await screen.findByTestId('catalog-table');
    fireEvent.click(document.getElementById('catalog-show-deleted') as HTMLElement);
    await screen.findByText(DELETED.name);

    const problems = await screenMismatches('catalog', role, {
      ids: { live: LIVE.id, deleted: DELETED.id },
      selectAll: async () => {
        fireEvent.click(screen.getByRole('checkbox', { name: 'Select all rows' }));
        await screen.findByRole('checkbox', { name: 'Clear selection' });
      },
      clearSelection: () => {
        fireEvent.click(screen.getByRole('checkbox', { name: 'Clear selection' }));
      },
    });
    expect(problems).toEqual([]);
  });
});
