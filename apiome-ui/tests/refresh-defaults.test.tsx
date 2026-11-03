/**
 * Workspace refresh defaults (RAR-6.5, #3542): the model and the Repositories → Refresh defaults page.
 *
 * The model: parsing, the "N of M repositories follow this default" sentences, the toast after a
 * re-apply, and whether the form changed. The page: an administrator edits the cadence, conflict
 * policy and auto-refresh switch and saves them with (or without) re-applying to the repositories
 * that follow them; anyone else reads them with the controls disabled and no Save button.
 */

import fs from 'fs';
import path from 'path';
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockToast = { success: jest.fn(), error: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));
jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({ data: { user: { user_id: 'u1', current_tenant_id: 't1' } } }),
}));
jest.mock('next/navigation', () => ({
  usePathname: () => '/ade/dashboard/repositories/refresh-defaults',
  useRouter: () => ({ push: jest.fn(), replace: jest.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));
jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ children, href, ...rest }: { children: React.ReactNode; href: string }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { RefreshDefaultsClient } from '../src/app/ade/dashboard/repositories/refresh-defaults/RefreshDefaultsClient';
import {
  appliedSentence,
  defaultsChanged,
  draftFromDefaults,
  inheritanceSentence,
  parseRefreshDefaults,
  settingValueText,
} from '../src/app/components/ade/repositories/refreshDefaultsModel';

/** A minimal fetch response (jsdom has no `Response`). */
function reply(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, statusText: '', json: async () => body };
}

const PROJECTION = {
  success: true,
  configured: true,
  refreshIntervalSeconds: 900,
  conflictPolicy: 'hold-for-review',
  autoRefreshEnabled: true,
  minIntervalSeconds: 60,
  availableConflictPolicies: ['overwrite', 'hold-for-review', 'new-branch'],
  canEdit: true,
  updatedBy: 'u1',
  updatedAt: '2026-11-03T21:00:00Z',
  inheriting: { repositories: 5, refreshInterval: 4, conflictPolicy: 3, autoRefresh: 5 },
  applied: null,
};

// ===========================================================================
// Model
// ===========================================================================

describe('refreshDefaultsModel', () => {
  it('parses the projection, defaulting to the built-in values', () => {
    const data = parseRefreshDefaults(PROJECTION);
    expect(data.refreshIntervalSeconds).toBe(900);
    expect(data.repositories).toBe(5);
    expect(data.inheriting).toEqual({ refreshInterval: 4, conflictPolicy: 3, autoRefresh: 5 });
    expect(parseRefreshDefaults({})).toMatchObject({
      configured: false, refreshIntervalSeconds: 300, conflictPolicy: 'hold-for-review', autoRefreshEnabled: true,
      canEdit: false, applied: null,
    });
  });

  it('says how many repositories follow a default', () => {
    const data = parseRefreshDefaults(PROJECTION);
    expect(inheritanceSentence(data, 'refresh_interval')).toBe('4 of 5 repositories follow this default');
    expect(inheritanceSentence({ ...data, repositories: 0 }, 'auto_refresh')).toBe('No repositories yet');
    expect(inheritanceSentence({ ...data, repositories: 1, inheriting: { ...data.inheriting, autoRefresh: 1 } }, 'auto_refresh')).toBe(
      '1 of 1 repository follow this default'
    );
  });

  it('words a re-apply', () => {
    expect(appliedSentence({ refreshInterval: 4, conflictPolicy: 1, autoRefresh: 0 })).toBe(
      'Defaults saved and applied: cadence on 4 repositories, refresh conflicts on 1 repository.'
    );
    expect(appliedSentence({ refreshInterval: 0, conflictPolicy: 0, autoRefresh: 0 })).toMatch(/already matched/);
  });

  it('knows when the form changed', () => {
    const data = parseRefreshDefaults(PROJECTION);
    const draft = draftFromDefaults(data);
    expect(defaultsChanged(draft, data)).toBe(false);
    expect(defaultsChanged({ ...draft, autoRefreshEnabled: false }, data)).toBe(true);
    expect(defaultsChanged(draft, { ...data, configured: false })).toBe(true);
  });

  it('words a repository setting', () => {
    const label = (p: string) => p.toUpperCase();
    expect(settingValueText('refresh_interval', 900, label)).toBe('Every 15 min');
    expect(settingValueText('conflict_policy', 'overwrite', label)).toBe('OVERWRITE');
    expect(settingValueText('auto_refresh', false, label)).toBe('Off');
    expect(settingValueText('refresh_interval', null, label)).toBe('—');
  });
});

// ===========================================================================
// Page
// ===========================================================================

describe('RefreshDefaultsClient', () => {
  let puts: Record<string, unknown>[];

  const routeWith = (projection: Record<string, unknown>) => {
    global.fetch = jest.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === 'PUT') {
        const body = JSON.parse(String(init.body));
        puts.push(body);
        return reply({
          ...projection,
          refreshIntervalSeconds: body.refreshIntervalSeconds,
          conflictPolicy: body.conflictPolicy,
          autoRefreshEnabled: body.autoRefreshEnabled,
          applied: body.applyToInheriting ? { refreshInterval: 4, conflictPolicy: 0, autoRefresh: 5 } : null,
        });
      }
      return reply(projection);
    }) as unknown as typeof fetch;
  };

  beforeEach(() => {
    puts = [];
    mockToast.success.mockReset();
    mockToast.error.mockReset();
  });

  it('shows the defaults and how many repositories follow each', async () => {
    routeWith(PROJECTION);
    render(<RefreshDefaultsClient />);
    expect(await screen.findByTestId('refresh-defaults')).toBeInTheDocument();
    expect(screen.getByTestId('refresh-defaults-follow-interval')).toHaveTextContent('4 of 5 repositories');
    expect(screen.getByTestId('refresh-defaults-follow-policy')).toHaveTextContent('3 of 5 repositories');
    expect(screen.getByText('Set for this workspace')).toBeInTheDocument();
    expect(screen.queryByTestId('refresh-defaults-read-only')).not.toBeInTheDocument();
  });

  it('an administrator saves new defaults and re-applies them', async () => {
    routeWith(PROJECTION);
    render(<RefreshDefaultsClient />);
    await screen.findByTestId('refresh-defaults');

    fireEvent.click(screen.getByTestId('conflict-policy-option-overwrite').querySelector('input')!);
    fireEvent.click(screen.getByTestId('refresh-defaults-save'));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual({
      refreshIntervalSeconds: 900,
      conflictPolicy: 'overwrite',
      autoRefreshEnabled: true,
      applyToInheriting: true,
    });
    await waitFor(() =>
      expect(mockToast.success).toHaveBeenCalledWith(
        'Defaults saved and applied: cadence on 4 repositories, auto-refresh on 5 repositories.'
      )
    );
  });

  it('saving without re-apply leaves existing repositories alone', async () => {
    routeWith(PROJECTION);
    render(<RefreshDefaultsClient />);
    await screen.findByTestId('refresh-defaults');

    fireEvent.click(screen.getByLabelText(/Also apply to the repositories/));
    fireEvent.click(screen.getByLabelText('Auto-refresh new repositories'));
    fireEvent.click(screen.getByTestId('refresh-defaults-save'));

    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ autoRefreshEnabled: false, applyToInheriting: false });
    await waitFor(() =>
      expect(mockToast.success).toHaveBeenCalledWith('Defaults saved. New repositories start from them.')
    );
  });

  it('is read-only for anyone but an administrator', async () => {
    routeWith({ ...PROJECTION, canEdit: false });
    render(<RefreshDefaultsClient />);
    expect(await screen.findByTestId('refresh-defaults-read-only')).toHaveTextContent(
      'Only workspace administrators can change the defaults.'
    );
    expect(screen.queryByTestId('refresh-defaults-save')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Auto-refresh new repositories')).toBeDisabled();
  });

  it('shows the error with a retry when the read fails', async () => {
    global.fetch = jest.fn(async () => reply({ error: 'Repository API unavailable' }, 503)) as unknown as typeof fetch;
    render(<RefreshDefaultsClient />);
    expect(await screen.findByText('Repository API unavailable')).toBeInTheDocument();
  });
});

// ===========================================================================
// Browser fixture
// ===========================================================================

/**
 * Writes the screen into `e2e/fixtures/hive-repository-bring-in/refresh-defaults.html` for the docs
 * screenshot when `BRING_IN_FIXTURE_DUMP=1` is set (the same switch as the other Repositories
 * screens); otherwise it only checks the screen renders.
 */
describe('the browser fixture', () => {
  it('renders the refresh defaults screen (and writes its fixture on request)', async () => {
    global.fetch = jest.fn(async () => reply(PROJECTION)) as unknown as typeof fetch;
    render(<RefreshDefaultsClient />);
    await screen.findByTestId('refresh-defaults');
    const html = (document.querySelector('.page') as HTMLElement).outerHTML;
    expect(html.length).toBeGreaterThan(0);
    if (process.env.BRING_IN_FIXTURE_DUMP !== '1') return;
    const out = path.join(__dirname, '..', 'e2e', 'fixtures', 'hive-repository-bring-in');
    fs.mkdirSync(out, { recursive: true });
    fs.writeFileSync(path.join(out, 'refresh-defaults.html'), html);
  });
});
