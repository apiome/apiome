/**
 * System settings — the Sign-up card (SGN-1.4, #5653).
 *
 * Integration tests (RTL) for `SignupPolicyCard` against a mocked `/api/admin/signup-policy`
 * proxy: the env-derived and stored states, choosing a mode, the allowed-domain list (validated,
 * normalized, sent only for Open), saving, reverting to .env, and the failure paths.
 *
 * The docs fixture at the end is what `apiome-docs/screens.json` captures as
 * `admin-signup-policy`.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import SignupPolicyCard from '../src/app/admin/dashboard/settings/SignupPolicyCard';
import type { AdminSignupPolicyView } from '../lib/auth/admin-signup-policy';

jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), refresh: jest.fn() }),
  usePathname: () => '/admin/dashboard/settings',
}));

/** Build a policy view; the default is "nothing stored, env gives Open". */
function makeView(overrides: Partial<AdminSignupPolicyView> = {}): AdminSignupPolicyView {
  return {
    mode: 'open',
    allowed_email_domains: [],
    source: 'env',
    env_mode: 'open',
    updated_at: null,
    updated_by: null,
    ...overrides,
  };
}

const STORED = makeView({
  mode: 'open',
  allowed_email_domains: ['northwind.io'],
  source: 'db',
  updated_at: '2026-10-09T15:30:00Z',
  updated_by: 'admin',
});

/**
 * Install a fetch mock for the proxy: GET answers `initial`; PUT answers what `put` returns
 * (default: the payload echoed back as a stored policy).
 */
function mockFetch(
  initial: AdminSignupPolicyView,
  put?: (body: { mode: string | null; allowed_email_domains: string[] }) => {
    status: number;
    body: unknown;
  }
) {
  const impl = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    expect(String(input)).toBe('/api/admin/signup-policy');
    if ((init?.method ?? 'GET') === 'GET') {
      return { ok: true, status: 200, json: async () => initial } as unknown as Response;
    }
    const payload = JSON.parse(String(init?.body));
    const result = put
      ? put(payload)
      : {
          status: 200,
          body:
            payload.mode === null
              ? makeView({ mode: initial.env_mode, env_mode: initial.env_mode })
              : makeView({ ...payload, source: 'db', updated_at: '2026-10-11T08:00:00Z', updated_by: 'admin' }),
        };
    return {
      ok: result.status >= 200 && result.status < 300,
      status: result.status,
      json: async () => result.body,
    } as unknown as Response;
  });
  global.fetch = impl as unknown as typeof fetch;
  return impl;
}

/** The PUT bodies sent so far. */
const putBodies = (impl: jest.Mock) =>
  impl.mock.calls
    .filter(([, init]) => (init as RequestInit | undefined)?.method === 'PUT')
    .map(([, init]) => JSON.parse(String((init as RequestInit).body)));

/** The card, once its policy has loaded. */
async function loadedCard() {
  const region = await screen.findByRole('region', { name: 'Sign-up policy' });
  await within(region).findByRole('radio', { name: /^Open/ });
  return within(region);
}

describe('SignupPolicyCard — states', () => {
  it('shows the env-derived mode until a policy is stored', async () => {
    mockFetch(makeView({ mode: 'closed', env_mode: 'closed' }));
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    expect(card.getByText('Env-derived')).toBeInTheDocument();
    expect(card.getByRole('radio', { name: /^Closed/ })).toBeChecked();
    expect(card.getByText('Not stored — .env gives Closed')).toBeInTheDocument();
    // Nothing is stored, so there is nothing to revert.
    expect(card.queryByRole('button', { name: 'Use .env' })).not.toBeInTheDocument();
    // Saving pins the shown mode in the database, so it is offered straight away.
    expect(card.getByRole('button', { name: 'Save' })).toBeEnabled();
  });

  it('shows a stored policy with its domains and who changed it', async () => {
    mockFetch(STORED);
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    expect(card.queryByText('Env-derived')).not.toBeInTheDocument();
    expect(card.getByRole('radio', { name: /^Open/ })).toBeChecked();
    expect(card.getByLabelText('Allowed email domains')).toHaveValue('northwind.io');
    expect(card.getByText(/Last changed .* by admin/)).toBeInTheDocument();
    expect(card.getByRole('button', { name: 'Use .env' })).toBeInTheDocument();
    // Unchanged, so there is nothing to save.
    expect(card.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('lists the three modes in one radio group', async () => {
    mockFetch(makeView());
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    const group = card.getByRole('group', { name: 'Who can create an account' });
    expect(within(group).getAllByRole('radio').map((radio) => (radio as HTMLInputElement).value)).toEqual([
      'open',
      'invite_only',
      'closed',
    ]);
  });
});

describe('SignupPolicyCard — saving', () => {
  it('saves a chosen mode and reports it', async () => {
    const fetchImpl = mockFetch(makeView());
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.click(card.getByRole('radio', { name: /^Invite only/ }));
    fireEvent.click(card.getByRole('button', { name: 'Save' }));

    expect(await card.findByRole('status')).toHaveTextContent('Saved');
    expect(putBodies(fetchImpl)).toEqual([{ mode: 'invite_only', allowed_email_domains: [] }]);
    expect(card.queryByText('Env-derived')).not.toBeInTheDocument();
    expect(card.getByRole('button', { name: 'Save' })).toBeDisabled();
  });

  it('sends normalized, de-duplicated domains for Open', async () => {
    const fetchImpl = mockFetch(makeView());
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.change(card.getByLabelText('Allowed email domains'), {
      target: { value: 'Northwind.io\n@contoso.example, northwind.io' },
    });
    fireEvent.click(card.getByRole('button', { name: 'Save' }));

    await card.findByRole('status');
    expect(putBodies(fetchImpl)).toEqual([
      { mode: 'open', allowed_email_domains: ['northwind.io', 'contoso.example'] },
    ]);
  });

  it('blocks saving an invalid domain and says which entry', async () => {
    const fetchImpl = mockFetch(makeView());
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.change(card.getByLabelText('Allowed email domains'), {
      target: { value: 'northwind.io\nada@northwind.io' },
    });

    expect(card.getByRole('alert')).toHaveTextContent('Not a valid email domain: ada@northwind.io.');
    expect(card.getByLabelText('Allowed email domains')).toHaveAttribute('aria-invalid', 'true');
    expect(card.getByRole('button', { name: 'Save' })).toBeDisabled();
    expect(putBodies(fetchImpl)).toEqual([]);
  });

  it('disables the domain list outside Open and sends none', async () => {
    const fetchImpl = mockFetch(STORED);
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.click(card.getByRole('radio', { name: /^Closed/ }));
    expect(card.getByLabelText('Allowed email domains')).toBeDisabled();
    expect(card.getByText('Applies only while sign-up is Open.')).toBeInTheDocument();

    fireEvent.click(card.getByRole('button', { name: 'Save' }));
    await card.findByRole('status');
    expect(putBodies(fetchImpl)).toEqual([{ mode: 'closed', allowed_email_domains: [] }]);
  });

  it('Use .env clears the stored policy', async () => {
    const fetchImpl = mockFetch({ ...STORED, env_mode: 'closed' });
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.click(card.getByRole('button', { name: 'Use .env' }));

    expect(await card.findByText('Env-derived')).toBeInTheDocument();
    expect(putBodies(fetchImpl)).toEqual([{ mode: null, allowed_email_domains: [] }]);
    expect(card.getByRole('radio', { name: /^Closed/ })).toBeChecked();
    expect(card.queryByRole('button', { name: 'Use .env' })).not.toBeInTheDocument();
  });
});

describe('SignupPolicyCard — failures', () => {
  it('surfaces the REST validation message and keeps the draft', async () => {
    mockFetch(makeView(), () => ({
      status: 422,
      body: { detail: { error: 'invalid_email_domain', message: "'x' is not a valid email domain" } },
    }));
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.click(card.getByRole('radio', { name: /^Closed/ }));
    fireEvent.click(card.getByRole('button', { name: 'Save' }));

    expect(await card.findByRole('alert')).toHaveTextContent("'x' is not a valid email domain");
    expect(card.getByRole('radio', { name: /^Closed/ })).toBeChecked();
    expect(card.queryByRole('status')).not.toBeInTheDocument();
  });

  it('tells an expired session to sign in again', async () => {
    mockFetch(makeView(), () => ({ status: 403, body: { detail: 'Invalid or expired super-admin session.' } }));
    render(<SignupPolicyCard />);
    const card = await loadedCard();

    fireEvent.click(card.getByRole('button', { name: 'Save' }));
    expect(await card.findByRole('alert')).toHaveTextContent(
      'Your admin session has expired. Sign out and back in.'
    );
  });

  it('offers Retry when the policy cannot be loaded', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('down')) as unknown as typeof fetch;
    render(<SignupPolicyCard />);

    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Could not load the sign-up policy: the server could not be reached.');

    mockFetch(makeView());
    fireEvent.click(within(alert).getByRole('button', { name: /Retry/ }));
    await loadedCard();
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
  });
});

// ---------------------------------------------------------------------------------------
// The docs fixture
// ---------------------------------------------------------------------------------------

/**
 * The documentation site's sign-up policy screenshot (`admin-signup-policy` in
 * `apiome-docs/screens.json`) is captured from this dump:
 * `A11Y_FIXTURE_DUMP=1 npx jest tests/signup-policy-card.test.tsx -t "docs fixtures"`.
 *
 * The card is drawn where it lives — at the top of System settings, inside the admin console's
 * frame, above the sign-in providers.
 */
describe('the docs fixtures', () => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const { liveMarkup, writeA11yFixture } = require('./helpers/a11y-fixture-dump') as typeof import('./helpers/a11y-fixture-dump');
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const AdminSidebar = require('../src/app/admin/dashboard/AdminSidebar').default as React.ComponentType;
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const AuthProviderSettingsClient = require('../src/app/admin/dashboard/settings/AuthProviderSettingsClient')
    .default as React.ComponentType;

  /** One configured provider, so the capture shows the card beside the sign-in providers. */
  const DOCS_PROVIDERS = {
    providers: [
      {
        provider_id: 'github',
        label: 'GitHub',
        status: 'available',
        enabled: true,
        enabled_source: 'db',
        client_id: 'Iv1.example0docs0id',
        client_id_source: 'db',
        secret_set: true,
        secret_source: 'db',
        config: {},
        required_fields: ['client_id', 'client_secret'],
        missing_for_enable: [],
        can_enable: true,
        updated_at: '2026-09-28T14:05:00Z',
        updated_by: 'operator@northwind.io',
      },
    ],
  };

  it('renders the Sign-up card above the sign-in providers', async () => {
    global.fetch = jest.fn(async (input: RequestInfo | URL) => ({
      ok: true,
      status: 200,
      json: async () =>
        String(input) === '/api/admin/signup-policy'
          ? { ...STORED, allowed_email_domains: ['northwind.io', 'contoso.example'] }
          : DOCS_PROVIDERS,
    })) as unknown as typeof fetch;

    render(
      <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">
        <AdminSidebar />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <AuthProviderSettingsClient />
        </div>
      </div>
    );

    const card = await loadedCard();
    expect(card.getByLabelText('Allowed email domains')).toHaveValue('northwind.io\ncontoso.example');
    await screen.findByRole('region', { name: 'GitHub provider configuration' });

    writeA11yFixture(
      'admin-signup-policy',
      liveMarkup(document.body).replace(/^<body[^>]*>|<\/body>$/g, '')
    );
  });
});
