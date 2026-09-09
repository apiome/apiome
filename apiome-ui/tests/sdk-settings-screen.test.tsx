/**
 * Ship → SDK settings, rendered (SDK-3.4, #4494).
 *
 * The screen's behaviour against a mocked `fetch`: which scope it reads, what the Inherit
 * checkbox does to the body it sends, that every problem a `422` lists reaches the user, and that
 * a member without `projects:edit` gets a disabled form with the reason on it rather than a
 * missing one.
 */

import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

import SdkSettingsClient from '@/app/ade/dashboard/sdk-settings/SdkSettingsClient';
import {
  SDK_FIELD_KEYS,
  type SdkSettingsResponse,
} from '@/app/ade/dashboard/sdk-settings/sdkSettingsModel';

const PROJECT_ID = 'p-1';

/** A settings response with the fields a test cares about. */
function settings(partial: Partial<SdkSettingsResponse> = {}): SdkSettingsResponse {
  return {
    schemaVersion: 'sdk.generation-settings.v1',
    source: 'default',
    contentFingerprint: `sha256:${'a'.repeat(64)}`,
    settings: {
      packageNamePatterns: {},
      licenseHeader: null,
      userAgent: null,
      publicSdkEnabled: false,
    },
    resolved: { packageNames: {}, licenseHeader: null, userAgent: null },
    scope: 'tenant',
    scopeBody: null,
    tenantSettingsId: null,
    projectSettingsId: null,
    updatedAt: null,
    updatedBy: null,
    degraded: false,
    ...partial,
  };
}

/** Every request the screen makes, in order, so a test can assert what was sent. */
let calls: { url: string; init?: RequestInit }[] = [];

/**
 * Install a `fetch` double.
 *
 * @param options.settings The settings response the proxy answers with.
 * @param options.canEdit Whether the session holds `projects:edit`.
 * @param options.saveError A refusal to answer a PUT/DELETE with.
 */
function mockFetch(options: {
  settings?: SdkSettingsResponse;
  canEdit?: boolean;
  saveError?: { error: string; errors?: string[]; status?: number };
} = {}) {
  const answer = options.settings ?? settings();
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url: String(url), init });
    const json = (body: unknown, status = 200) =>
      ({ ok: status < 400, status, json: async () => body }) as unknown as Response;

    if (String(url).startsWith('/api/projects')) {
      return json({ success: true, projects: [{ id: PROJECT_ID, name: 'Petstore' }] });
    }
    if (String(url).startsWith('/api/access/permissions/me')) {
      return json({
        success: true,
        data: {
          is_admin: false,
          permissions: options.canEdit === false ? ['projects:view'] : ['projects:edit'],
        },
      });
    }
    if (init && init.method && options.saveError) {
      return json({ success: false, ...options.saveError }, options.saveError.status ?? 422);
    }
    if (init?.method === 'DELETE') {
      return json({ success: true, data: settings() });
    }
    if (init?.method === 'PUT') {
      return json({ success: true, data: answer });
    }
    return json({ success: true, data: answer });
  }) as unknown as typeof fetch;
}

/** The most recent request made with a body. */
function lastBody(): Record<string, unknown> {
  const call = [...calls].reverse().find((entry) => entry.init?.body);
  return JSON.parse(String(call?.init?.body ?? '{}'));
}

beforeEach(() => {
  calls = [];
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('loading', () => {
  it('reads the workspace defaults first', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    expect(calls.some((call) => call.url === '/api/sdk-settings')).toBe(true);
  });

  it('announces the wait to a screen reader rather than showing a bare spinner', () => {
    mockFetch();
    render(<SdkSettingsClient />);
    expect(screen.getByTestId('sdk-settings-loading')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Loading SDK settings');
  });

  it('says plainly when nothing is configured', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    expect(await screen.findByText(/no branding/i)).toBeInTheDocument();
  });

  it('shows a load failure instead of an empty form', async () => {
    global.fetch = jest.fn(async (url: string) => {
      if (String(url).startsWith('/api/sdk-settings')) {
        return { ok: false, status: 500, json: async () => ({ success: false, error: 'boom' }) } as unknown as Response;
      }
      return { ok: true, status: 200, json: async () => ({ success: true, projects: [], data: {} }) } as unknown as Response;
    }) as unknown as typeof fetch;
    render(<SdkSettingsClient />);
    expect(await screen.findByText('boom')).toBeInTheDocument();
  });
});

describe('the scope picker', () => {
  it('re-reads against the chosen project', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: PROJECT_ID } });
    await waitFor(() =>
      expect(calls.some((call) => call.url === `/api/sdk-settings/${PROJECT_ID}`)).toBe(true),
    );
  });

  it('offers no Inherit checkbox at workspace scope, because there is nothing above it', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    expect(screen.queryByLabelText('Inherit from workspace')).not.toBeInTheDocument();
  });

  it('offers one per field at project scope', async () => {
    mockFetch({ settings: settings({ scope: 'project' }) });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: PROJECT_ID } });
    // The four text fields plus the SDK-3.3 public-access switch, which is tri-state in exactly
    // the same way.
    await waitFor(() =>
      expect(screen.getAllByLabelText('Inherit from workspace')).toHaveLength(
        SDK_FIELD_KEYS.length + 1,
      ),
    );
  });
});

describe('saving', () => {
  it('sends only the fields the form speaks for', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.change(screen.getByLabelText('User agent'), {
      target: { value: 'acme-sdk/{version}' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(lastBody()).toEqual({ settings: { userAgent: 'acme-sdk/{version}' } }));
  });

  it('is disabled until something changes', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();

    fireEvent.change(screen.getByLabelText('npm package name'), {
      target: { value: '@acme/{project}' },
    });
    expect(screen.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('lists every problem a refusal reported, not just the first', async () => {
    mockFetch({
      saveError: {
        error: 'Invalid settings',
        errors: ['userAgent: too long', 'packageNamePatterns.npm: not a legal npm package name'],
      },
    });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.change(screen.getByLabelText('User agent'), { target: { value: 'x' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByText('userAgent: too long')).toBeInTheDocument();
    expect(
      screen.getByText('packageNamePatterns.npm: not a legal npm package name'),
    ).toBeInTheDocument();
  });
});

describe('clearing', () => {
  it('is offered only when the scope saved something of its own', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    expect(screen.queryByRole('button', { name: /Clear/ })).not.toBeInTheDocument();
  });

  it("drops the scope's row when it has one", async () => {
    mockFetch({
      settings: settings({ source: 'tenant', tenantSettingsId: 't-1', scopeBody: { userAgent: 'acme/1.0' } }),
    });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.click(screen.getByRole('button', { name: 'Clear defaults' }));
    await waitFor(() =>
      expect(
        calls.some((call) => call.url === '/api/sdk-settings' && call.init?.method === 'DELETE'),
      ).toBe(true),
    );
  });
});

describe('the in-force panel', () => {
  it('shows what the merged settings resolve to', async () => {
    mockFetch({
      settings: settings({
        source: 'merged',
        resolved: {
          packageNames: { npm: '@acme/petstore-sdk' },
          licenseHeader: 'Copyright (c) 2026 Acme',
          userAgent: 'acme-sdk/1.0.0',
        },
      }),
    });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-preview');
    expect(screen.getByText(/npm: @acme\/petstore-sdk/)).toBeInTheDocument();
    expect(screen.getByText('acme-sdk/1.0.0')).toBeInTheDocument();
    expect(screen.getByText('Copyright (c) 2026 Acme')).toBeInTheDocument();
  });

  it('surfaces a settings row that could not be read', async () => {
    mockFetch({ settings: settings({ degraded: true }) });
    render(<SdkSettingsClient />);
    expect(await screen.findByText(/could not be read/i)).toBeInTheDocument();
  });
});

describe('a member without projects:edit', () => {
  it('sees the settings, disabled, with the reason', async () => {
    mockFetch({ canEdit: false });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    expect(await screen.findByText(/Read-only for members/)).toBeInTheDocument();
    expect(screen.getByLabelText('User agent')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled();
  });
});

describe('the public SDK switch (SDK-3.3)', () => {
  it('starts off, so a project is never published to the world by inaction', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    const toggle = screen.getByLabelText('Allow anonymous visitors to download this SDK');
    expect(toggle).not.toBeChecked();
    expect(screen.getByText('No public SDK')).toBeInTheDocument();
  });

  it('sends the boolean when it is turned on', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.click(screen.getByLabelText('Allow anonymous visitors to download this SDK'));
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(lastBody()).toEqual({ settings: { publicSdkEnabled: true } }));
  });

  it('explains what turning it on actually exposes', async () => {
    mockFetch();
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');

    fireEvent.click(screen.getByLabelText('Allow anonymous visitors to download this SDK'));
    expect(screen.getByText(/Anonymous visitors to the published version/)).toBeInTheDocument();
  });

  it('sends an explicit false at project scope, to close a workspace that opened it', async () => {
    mockFetch({ settings: settings({ scope: 'project' }) });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-form');
    fireEvent.change(screen.getByLabelText('Scope'), { target: { value: PROJECT_ID } });

    await screen.findByLabelText('Allow anonymous visitors to download this SDK');
    // Stop inheriting, leaving the switch off: that is a project saying "not here", which only an
    // explicit false can express.
    const inherits = screen.getAllByLabelText('Inherit from workspace');
    fireEvent.click(inherits[inherits.length - 1]);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(lastBody()).toEqual({ settings: { publicSdkEnabled: false } }));
  });

  it('reports the answer in force in the preview panel', async () => {
    mockFetch({
      settings: settings({
        settings: {
          packageNamePatterns: {},
          licenseHeader: null,
          userAgent: null,
          publicSdkEnabled: true,
        },
      }),
    });
    render(<SdkSettingsClient />);
    await screen.findByTestId('sdk-settings-preview');

    expect(screen.getByText('Enabled')).toBeInTheDocument();
  });
});
