/**
 * System Configuration screen — sign-in provider cards (OLO-8.7, #4973).
 *
 * Integration tests (RTL) for `AuthProviderSettingsClient` against a mocked
 * `/api/admin/auth-providers` proxy, covering the issue's acceptance criteria:
 * one card per registry provider (coming-soon as disabled placeholders), write-only
 * secret handling ("set / not set", never a value), per-field ".env fallback"
 * indicators, dirty-only partial saves, blocked-enable 422 guidance, the Validate
 * affordance, and the enablement override semantics (true / false / null).
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import AuthProviderSettingsClient from '../src/app/admin/dashboard/settings/AuthProviderSettingsClient';
import type { AdminProviderConfigView } from '../lib/auth/admin-provider-config';

/** Build a full masked view with sensible env-fallback defaults. */
function makeView(overrides: Partial<AdminProviderConfigView>): AdminProviderConfigView {
  return {
    provider_id: 'github',
    label: 'GitHub',
    status: 'available',
    enabled: null,
    enabled_source: 'env-fallback',
    client_id: null,
    client_id_source: 'env-fallback',
    secret_set: false,
    secret_source: 'env-fallback',
    config: {},
    required_fields: ['client_id', 'client_secret'],
    missing_for_enable: ['client_id', 'client_secret'],
    can_enable: false,
    updated_at: null,
    updated_by: null,
    ...overrides,
  };
}

const GITHUB = makeView({});
const GITLAB = makeView({
  provider_id: 'gitlab',
  label: 'GitLab',
  enabled: true,
  enabled_source: 'db',
  client_id: 'gitlab-client-id',
  client_id_source: 'db',
  secret_set: true,
  secret_source: 'db',
  config: { GITLAB_BASE_URL: 'https://git.example.com' },
  missing_for_enable: [],
  can_enable: true,
  updated_at: '2026-07-20T10:00:00Z',
  updated_by: 'admin',
});
const AZURE = makeView({
  provider_id: 'azure',
  label: 'Microsoft',
});
const GOOGLE = makeView({
  provider_id: 'google',
  label: 'Google / GCP',
  status: 'coming-soon',
  required_fields: [],
  missing_for_enable: [],
});
const AWS = makeView({
  provider_id: 'aws',
  label: 'AWS',
  status: 'coming-soon',
  required_fields: [],
  missing_for_enable: [],
});

const DEFAULT_LIST = { providers: [GITHUB, GITLAB, AZURE, GOOGLE, AWS] };

/** Install a fetch mock; `putHandler` decides PUT responses, `listBodies` queues GET bodies. */
function mockFetch(
  putHandler?: (url: string, body: Record<string, unknown>) => { status: number; body: unknown },
  listBodies: unknown[] = [DEFAULT_LIST]
) {
  let listCall = 0;
  const impl = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (method === 'GET') {
      const body = listBodies[Math.min(listCall, listBodies.length - 1)];
      listCall += 1;
      return { ok: true, status: 200, json: async () => body } as unknown as Response;
    }
    if (method === 'PUT' && putHandler) {
      const parsed = JSON.parse(String(init?.body ?? '{}'));
      const result = putHandler(url, parsed);
      return {
        ok: result.status >= 200 && result.status < 300,
        status: result.status,
        json: async () => result.body,
      } as unknown as Response;
    }
    throw new Error(`Unexpected fetch: ${method} ${url}`);
  });
  global.fetch = impl as unknown as typeof fetch;
  return impl;
}

/** The card `section` for a provider label, as a `within` scope. */
async function card(label: string) {
  const region = await screen.findByRole('region', {
    name: `${label} provider configuration`,
  });
  return within(region);
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe('AuthProviderSettingsClient — rendering', () => {
  it('renders one card per registry provider, coming-soon ones as disabled placeholders', async () => {
    mockFetch();
    render(<AuthProviderSettingsClient />);

    for (const label of ['GitHub', 'GitLab', 'Microsoft', 'Google / GCP', 'AWS']) {
      expect(
        await screen.findByRole('region', { name: `${label} provider configuration` })
      ).toBeInTheDocument();
    }

    const google = await card('Google / GCP');
    expect(google.getByText('Coming soon')).toBeInTheDocument();
    expect(google.queryByRole('textbox')).not.toBeInTheDocument();
    expect(google.queryByRole('button', { name: 'Save' })).not.toBeInTheDocument();
  });

  it('shows per-field "using .env fallback" indicators exactly where no DB value is set', async () => {
    mockFetch();
    render(<AuthProviderSettingsClient />);

    // GitHub stores nothing: enablement, client id, secret, and both extras fall back.
    const github = await card('GitHub');
    expect(github.getAllByText('using .env fallback').length).toBe(5);

    // GitLab stores everything it renders: no fallback badges at all.
    const gitlab = await card('GitLab');
    expect(gitlab.queryByText('using .env fallback')).not.toBeInTheDocument();
  });

  it('never renders a secret: only set/not-set state, an empty write-only input', async () => {
    mockFetch();
    render(<AuthProviderSettingsClient />);

    const gitlab = await card('GitLab');
    expect(gitlab.getByText('Secret: set')).toBeInTheDocument();
    const secretInput = gitlab.getByLabelText('Client secret') as HTMLInputElement;
    expect(secretInput.type).toBe('password');
    expect(secretInput.value).toBe('');
    expect(secretInput.placeholder).toMatch(/Secret is set/);

    const github = await card('GitHub');
    expect(github.getByText('Secret: not set')).toBeInTheDocument();
  });

  it('reflects stored state: enablement chip, client id value, extras from config JSONB', async () => {
    mockFetch();
    render(<AuthProviderSettingsClient />);

    const gitlab = await card('GitLab');
    expect(gitlab.getByText('Enabled (database)')).toBeInTheDocument();
    expect((gitlab.getByLabelText('Client ID') as HTMLInputElement).value).toBe(
      'gitlab-client-id'
    );
    expect((gitlab.getByLabelText('Base URL') as HTMLInputElement).value).toBe(
      'https://git.example.com'
    );
    expect(gitlab.getByText(/Last changed/)).toBeInTheDocument();

    const github = await card('GitHub');
    expect(github.getByText('Env-derived')).toBeInTheDocument();
  });

  it('surfaces a load failure with a retry affordance', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('down')) as unknown as typeof fetch;
    render(<AuthProviderSettingsClient />);

    expect(await screen.findByRole('alert')).toHaveTextContent(/could not be reached/);
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });
});

describe('AuthProviderSettingsClient — saving', () => {
  it('saves only the fields the admin changed (partial update), then shows Saved', async () => {
    const puts: Array<{ url: string; body: Record<string, unknown> }> = [];
    mockFetch((url, body) => {
      puts.push({ url, body });
      return {
        status: 200,
        body: makeView({ client_id: 'new-github-id', client_id_source: 'db' }),
      };
    });
    render(<AuthProviderSettingsClient />);

    const github = await card('GitHub');
    expect(github.getByRole('button', { name: 'Save' })).toBeDisabled();

    fireEvent.change(github.getByLabelText('Client ID'), {
      target: { value: 'new-github-id' },
    });
    expect(github.getByRole('button', { name: 'Save' })).toBeEnabled();
    fireEvent.click(github.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(github.getByText('Saved')).toBeInTheDocument());
    expect(puts).toEqual([
      {
        url: '/api/admin/auth-providers/github',
        body: { client_id: 'new-github-id' },
      },
    ]);
  });

  it('sends a typed secret write-only and resets the input after saving', async () => {
    const puts: Array<Record<string, unknown>> = [];
    mockFetch((_url, body) => {
      puts.push(body);
      return { status: 200, body: makeView({ secret_set: true, secret_source: 'db' }) };
    });
    render(<AuthProviderSettingsClient />);

    const github = await card('GitHub');
    fireEvent.change(github.getByLabelText('Client secret'), {
      target: { value: 'super-secret-value' },
    });
    fireEvent.click(github.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(github.getByText('Saved')).toBeInTheDocument());
    expect(puts).toEqual([{ client_secret: 'super-secret-value' }]);
    expect((github.getByLabelText('Client secret') as HTMLInputElement).value).toBe('');
    expect(github.getByText('Secret: set')).toBeInTheDocument();
  });

  it('clears a stored secret via the clear affordance (client_secret: null)', async () => {
    const puts: Array<Record<string, unknown>> = [];
    mockFetch((_url, body) => {
      puts.push(body);
      return {
        status: 200,
        body: { ...GITLAB, secret_set: false, secret_source: 'env-fallback' },
      };
    });
    render(<AuthProviderSettingsClient />);

    const gitlab = await card('GitLab');
    fireEvent.click(gitlab.getByRole('button', { name: 'Clear stored secret' }));
    expect(gitlab.getByText(/will be cleared on save/)).toBeInTheDocument();
    fireEvent.click(gitlab.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(gitlab.getByText('Saved')).toBeInTheDocument());
    expect(puts).toEqual([{ client_secret: null }]);
    expect(gitlab.getByText('Secret: not set')).toBeInTheDocument();
  });

  it('clears the enable override back to env-derived (enabled: null)', async () => {
    const puts: Array<Record<string, unknown>> = [];
    mockFetch((_url, body) => {
      puts.push(body);
      return {
        status: 200,
        body: { ...GITLAB, enabled: null, enabled_source: 'env-fallback' },
      };
    });
    render(<AuthProviderSettingsClient />);

    const gitlab = await card('GitLab');
    fireEvent.click(gitlab.getByRole('radio', { name: 'Use .env' }));
    fireEvent.click(gitlab.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(gitlab.getByText('Saved')).toBeInTheDocument());
    expect(puts).toEqual([{ enabled: null }]);
    expect(gitlab.getByText('Env-derived')).toBeInTheDocument();
  });

  it('shows the structured 422 guidance when enabling an incomplete provider', async () => {
    mockFetch(() => ({
      status: 422,
      body: {
        detail: {
          error: 'provider_incomplete',
          provider_id: 'github',
          missing_fields: ['client_id', 'client_secret'],
          message:
            "Cannot enable 'github': missing required fields client_id, client_secret. " +
            'Set them (or the corresponding env vars) before enabling.',
        },
      },
    }));
    render(<AuthProviderSettingsClient />);

    const github = await card('GitHub');
    fireEvent.click(github.getByRole('radio', { name: 'Enabled' }));
    fireEvent.click(github.getByRole('button', { name: 'Save' }));

    const alert = await waitFor(() => github.getByRole('alert'));
    expect(alert).toHaveTextContent(/Cannot enable 'github'/);
    expect(alert).toHaveTextContent(/Missing: client_id, client_secret/);
    // The card still shows the stored (env-derived) state — nothing was written.
    expect(github.getByText('Env-derived')).toBeInTheDocument();
  });

  it('explains an expired session instead of a generic failure', async () => {
    mockFetch(() => ({ status: 401, body: { error: 'unauthorized' } }));
    render(<AuthProviderSettingsClient />);

    const github = await card('GitHub');
    fireEvent.change(github.getByLabelText('Client ID'), { target: { value: 'x' } });
    fireEvent.click(github.getByRole('button', { name: 'Save' }));

    const alert = await waitFor(() => github.getByRole('alert'));
    expect(alert).toHaveTextContent(/session has expired/);
  });
});

describe('AuthProviderSettingsClient — validate affordance', () => {
  it('surfaces the server-computed completeness check (missing fields)', async () => {
    mockFetch(undefined, [DEFAULT_LIST, DEFAULT_LIST]);
    render(<AuthProviderSettingsClient />);

    const github = await card('GitHub');
    fireEvent.click(github.getByRole('button', { name: /Validate/ }));

    await waitFor(() =>
      expect(github.getByText(/Not ready to enable/)).toBeInTheDocument()
    );
    expect(github.getByText(/missing: client_id, client_secret/)).toBeInTheDocument();
  });

  it('reports a complete configuration as enable-ready', async () => {
    mockFetch(undefined, [DEFAULT_LIST, DEFAULT_LIST]);
    render(<AuthProviderSettingsClient />);

    const gitlab = await card('GitLab');
    fireEvent.click(gitlab.getByRole('button', { name: /Validate/ }));

    await waitFor(() =>
      expect(
        gitlab.getByText(/configuration is complete — this provider can be enabled/)
      ).toBeInTheDocument()
    );
  });
});
