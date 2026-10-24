/**
 * Projects list × role — RC6-H5 (#6212).
 *
 * Renders Projects as Viewer, Editor and Owner and checks every control
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

jest.mock('@lib/db/project-pins', () => ({
  listPinnedProjectIdsForSession: jest.fn(async () => []),
  pinProjectForSession: jest.fn(async () => 'pinned'),
  unpinProjectForSession: jest.fn(async () => true),
}));

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/projects',
}));

jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: jest.fn(async () => true), alert: jest.fn(async () => undefined) }),
}));

jest.mock('@lib/db/helper-actions', () => ({
  createProject: jest.fn(async () => JSON.stringify({ success: true })),
  updateProject: jest.fn(async () => JSON.stringify({ success: true })),
  deleteProject: jest.fn(async () => JSON.stringify({ success: true })),
  restoreProject: jest.fn(async () => JSON.stringify({ success: true })),
  permanentDeleteProject: jest.fn(async () => JSON.stringify({ success: true })),
}));

jest.mock('@/app/components/ade/dashboard/ImportDialog', () => ({ __esModule: true, default: () => null }));
jest.mock('@/app/components/ade/dashboard/LLMImportDialog', () => ({ __esModule: true, LLMChatPanel: () => null }));

import ProjectsClient from '../src/app/ade/dashboard/projects/ProjectsClient';
import { roleMay, ROLES, screenMismatches } from './helpers/permission-matrix';

const LIVE = {
  id: '8f2a1c00-0000-4000-8000-000000000001',
  tenant_id: 't-acme',
  creator_id: 'u-ada',
  name: 'Payments API',
  slug: 'payments-api',
  description: 'Card, refund and payout endpoints.',
  enabled: true,
  deleted_at: null,
  created_at: '2026-06-01T10:00:00.000Z',
  updated_at: '2026-08-15T09:12:00.000Z',
  creator_name: 'Ada Lovelace',
  creator_email: 'ada@example.com',
  versionsCount: 6,
  qualityScore: 88,
  qualityGrade: 'B',
};

const DELETED = {
  ...LIVE,
  id: '11aa0900-0000-4000-8000-000000000003',
  name: 'Legacy Gateway',
  slug: 'legacy-gateway',
  deleted_at: '2026-08-09T14:15:00.000Z',
};

/** Serve `/api/projects`, honouring `include_deleted`. */
function mockProjects() {
  global.fetch = jest.fn(async (input: RequestInfo | URL) => {
    const projects = String(input).includes('include_deleted=true') ? [LIVE, DELETED] : [LIVE];
    return { ok: true, statusText: 'OK', json: async () => ({ success: true, projects }) } as Response;
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  window.localStorage.clear();
  mockProjects();
});

describe.each(ROLES)('Projects as %s', (role) => {
  it('offers each control exactly when the role may use it', async () => {
    mockRole = role;
    render(<ProjectsClient />);
    await screen.findByText(LIVE.name);

    fireEvent.click(screen.getByTestId('projects-view-table'));
    await screen.findByTestId('projects-table-foot');
    fireEvent.click(document.getElementById('projects-show-deleted') as HTMLElement);
    await screen.findByText(DELETED.name);

    const problems = await screenMismatches('projects', role, {
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

  it('offers the New project tile on the cards only to a role that may create', async () => {
    mockRole = role;
    render(<ProjectsClient />);
    await screen.findByText(LIVE.name);
    const may = roleMay(role, 'projects:create');
    expect(Boolean(screen.queryByTestId('projects-create-tile'))).toBe(may);
  });
});
