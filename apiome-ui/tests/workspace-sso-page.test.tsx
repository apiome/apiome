/**
 * Workspace → Single sign-on — the page (EID-1.2, #5012).
 *
 * `/ade/dashboard/sso` against a mocked `fetch` that answers the `/api/workspace-sso` proxy the way
 * apiome-rest does, keeping providers in memory so a flow can be followed end to end.
 *
 * Pinned:
 * - owners and admins only: anyone else is told so, and the provider list is never requested;
 * - the list says where each provider stands — Live only when enabled with a verified domain;
 * - the acceptance path: add a provider, add a domain, see its TXT record, verify, enable;
 * - a DNS lookup that failed reads "Could not check" with what the resolver answered, and the
 *   domain stays "Not verified";
 * - a refusal (`sso-domain-claimed`, `sso-domain-public`) is shown with REST's own message;
 * - Remove says how many members signed in through the provider before anything is removed;
 * - Configure sends only what changed, and never a blank secret;
 * - the page and the drawer's two tabs have no axe violations, and dump the docs fixtures
 *   `sso-providers`, `sso-provider-configure` and `sso-domain-verify`.
 */

import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => ({
    data: { user: { user_id: 'user-1', name: 'Ada', email: 'ada@northwind.io', current_tenant_id: 'tenant-1' } },
  }),
}));

import SsoClient from '../src/app/ade/dashboard/sso/SsoClient';
import type { SsoDomainCheck, WorkspaceSsoDomain, WorkspaceSsoProvider } from '../lib/workspace-sso';
import { liveMarkup, writeA11yFixture } from './helpers/a11y-fixture-dump';

const OKTA_ID = '8dc47ff5-488b-44d0-9d72-ebf5ad0de3b2';
const SAML_ID = '1f0e9c1a-52f4-4c0b-9a55-0d6f1c7e4b10';
const TOKEN = 'q3ZrT8mVx1LkPa7YwN2dHs5BfC0uJeGi';

const domain = (name: string, verified: boolean, token = TOKEN): WorkspaceSsoDomain => ({
  domain: name,
  verified,
  verified_at: verified ? '2026-11-10T09:00:00Z' : null,
  verified_by: verified ? 'user-1' : null,
  verification_token: token,
  record_name: `_apiome-challenge.${name}`,
});

const provider = (overrides: Partial<WorkspaceSsoProvider> = {}): WorkspaceSsoProvider => ({
  id: OKTA_ID,
  slug: 'northwind-okta',
  plugin_provider_id: 'sso-northwind-okta',
  identity_kind: 'sso:northwind-okta',
  protocol: 'oidc',
  display_name: 'Northwind Okta',
  issuer: 'https://northwind.okta.com',
  tenant_id: 'tenant-1',
  tenant_name: 'Northwind',
  oidc_config: { client_id: '0oa9x2apiome' },
  saml_config: null,
  has_client_secret: true,
  has_sp_private_key: false,
  enabled: true,
  routable: true,
  default_role_slug: 'editor',
  member_count: 42,
  domains: [domain('northwind.io', true)],
  ...overrides,
});

const SAML = provider({
  id: SAML_ID,
  slug: 'northwind-entra',
  plugin_provider_id: 'sso-northwind-entra',
  identity_kind: 'sso:northwind-entra',
  protocol: 'saml',
  display_name: 'Northwind Entra ID',
  issuer: 'https://sts.windows.net/2f6c1d7e/',
  oidc_config: null,
  saml_config: { email_source: 'attribute', email_attribute: 'mail' },
  has_client_secret: false,
  enabled: false,
  routable: false,
  default_role_slug: null,
  member_count: 0,
  domains: [domain('northwind.co.uk', false, 'Hc7dWq2nLm0ZpXa9KtRv4sYbUe6JgFi1')],
});

const ROLES = [
  { id: 'r-owner', slug: 'owner', name: 'Owner', is_builtin: true },
  { id: 'r-admin', slug: 'admin', name: 'Admin', is_builtin: true },
  { id: 'r-editor', slug: 'editor', name: 'Editor', is_builtin: true },
  { id: 'r-viewer', slug: 'viewer', name: 'Viewer', is_builtin: true },
];

/** What the fake REST surface holds, and what it was asked. */
let state: {
  providers: WorkspaceSsoProvider[];
  isAdmin: boolean;
  /** domain -> the check the next verify answers with. */
  dns: Record<string, SsoDomainCheck['status']>;
  /** `METHOD path` -> a refusal to answer with instead. */
  refuse: Record<string, { status: number; error: string; code?: string }>;
  calls: Array<{ method: string; path: string; body: unknown }>;
};

const json = (status: number, body: unknown) => ({ status, ok: status >= 200 && status < 300, json: async () => body });

const checkFor = (entry: WorkspaceSsoDomain, status: SsoDomainCheck['status']): SsoDomainCheck => ({
  status,
  verified: status === 'verified',
  record_name: entry.record_name,
  expected: entry.verification_token,
  observed:
    status === 'could-not-check'
      ? ['SERVFAIL: no nameserver answered for this name.']
      : status === 'mismatch'
        ? ['an-older-token']
        : status === 'not-found'
          ? ['NXDOMAIN: the name does not exist.']
          : [entry.verification_token],
  message:
    status === 'verified'
      ? `${entry.domain} is verified.`
      : status === 'could-not-check'
        ? `Could not check ${entry.record_name}. Nothing was changed; try again in a few minutes.`
        : status === 'mismatch'
          ? `${entry.record_name} has a TXT record, but not the expected value.`
          : `No TXT record was found at ${entry.record_name}. DNS changes can take a while to appear.`,
});

beforeEach(() => {
  state = { providers: [provider(), SAML], isAdmin: true, dns: {}, refuse: {}, calls: [] };
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';
    if (url === '/api/access/permissions/me') {
      return json(200, { success: true, data: { is_admin: state.isAdmin, permissions: [] } });
    }
    if (url === '/api/access/roles') return json(200, { success: true, data: ROLES });

    const path = url.replace('/api/workspace-sso', '');
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    state.calls.push({ method, path, body });
    const refusal = state.refuse[`${method} ${path}`];
    if (refusal) return json(refusal.status, { success: false, error: refusal.error, code: refusal.code });

    const [, id, , name, action] = path.split('/');
    const index = state.providers.findIndex((entry) => entry.id === id);
    const update = (next: WorkspaceSsoProvider) => {
      const routable = next.enabled && next.domains.some((entry) => entry.verified);
      state.providers[index] = { ...next, routable };
      return state.providers[index];
    };

    if (path === '' && method === 'GET') return json(200, { providers: state.providers });
    if (path === '' && method === 'POST') {
      const created = provider({
        id: '5b2d3c4e-6f70-4a81-9b92-c3d4e5f60718',
        slug: body.slug,
        plugin_provider_id: `sso-${body.slug}`,
        identity_kind: `sso:${body.slug}`,
        display_name: body.display_name,
        issuer: body.issuer,
        oidc_config: { client_id: body.client_id },
        default_role_slug: body.default_role_slug ?? null,
        enabled: false,
        routable: false,
        member_count: 0,
        domains: [],
      });
      state.providers.unshift(created);
      return json(201, created);
    }
    const current = state.providers[index];
    if (!current) return json(404, { success: false, error: 'No such SSO provider.', code: 'sso-provider-not-found' });
    if (action === 'verify') {
      const entry = current.domains.find((candidate) => candidate.domain === name)!;
      const status = state.dns[name] ?? 'not-found';
      const next =
        status === 'verified'
          ? update({ ...current, domains: current.domains.map((d) => (d.domain === name ? domain(name, true, d.verification_token) : d)) })
          : current;
      return json(200, { provider: next, check: checkFor(entry, status) });
    }
    if (name && method === 'DELETE') {
      return json(200, update({ ...current, domains: current.domains.filter((d) => d.domain !== name) }));
    }
    if (path.endsWith('/domains') && method === 'POST') {
      return json(201, update({ ...current, domains: [...current.domains, domain(body.domain, false, 'new-token-0001')] }));
    }
    if (method === 'PATCH') {
      return json(200, update({ ...current, ...(body.enabled === undefined ? {} : { enabled: body.enabled }), display_name: body.display_name ?? current.display_name }));
    }
    if (method === 'DELETE') {
      state.providers.splice(index, 1);
      return json(200, current);
    }
    return json(200, current);
  }) as unknown as typeof fetch;
});

/** Radix tabs change on mouse down, not click. */
const selectTab = (drawer: HTMLElement, name: string | RegExp) =>
  fireEvent.mouseDown(within(drawer).getByRole('tab', { name }), { button: 0 });

async function openProvider(name: string) {
  fireEvent.click(await screen.findByRole('button', { name }));
  return screen.findByTestId('sso-provider-drawer');
}

/**
 * The page and its open drawer, for a docs fixture. jsdom's origin is `http://localhost`; the docs
 * show the URLs a real installation would give its IdP.
 */
const bodyMarkup = () =>
  liveMarkup(document.body)
    .replace(/^<body[^>]*>|<\/body>$/g, '')
    .replaceAll('http://localhost/', 'https://apiome.northwind.io/');
const writes = () => state.calls.filter((call) => call.method !== 'GET');

describe('who may see it', () => {
  it('tells a member who is not an admin, and never asks for the providers', async () => {
    state.isAdmin = false;
    render(<SsoClient />);
    expect(await screen.findByText('Owners and admins only')).toBeInTheDocument();
    expect(screen.queryByTestId('sso-add')).not.toBeInTheDocument();
    expect(state.calls).toEqual([]);
  });

  it('offers a retry when the providers cannot be read', async () => {
    state.refuse['GET '] = { status: 503, error: 'Single sign-on settings are unavailable.' };
    render(<SsoClient />);
    expect(await screen.findByText('Single sign-on could not be read')).toBeInTheDocument();
    delete state.refuse['GET '];
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('sso-table')).toBeInTheDocument();
  });
});

describe('the provider list', () => {
  it('says where each provider stands', async () => {
    render(<SsoClient />);
    const okta = await screen.findByTestId('sso-row-northwind-okta');
    expect(within(okta).getByText('Live')).toBeInTheDocument();
    expect(within(okta).getByText('OIDC')).toBeInTheDocument();
    expect(within(okta).getByText('1 of 1 verified')).toBeInTheDocument();
    expect(within(okta).getByText('42')).toBeInTheDocument();

    const entra = screen.getByTestId('sso-row-northwind-entra');
    expect(within(entra).getByText('Disabled')).toBeInTheDocument();
    expect(within(entra).getByText('SAML 2.0')).toBeInTheDocument();
    expect(within(entra).getByText('0 of 1 verified')).toBeInTheDocument();
  });

  it('shows an enabled provider without a verified domain as waiting, not live', async () => {
    state.providers = [provider({ routable: false, domains: [domain('northwind.io', false)] })];
    render(<SsoClient />);
    const row = await screen.findByTestId('sso-row-northwind-okta');
    expect(within(row).getByText('Needs a verified domain')).toBeInTheDocument();
    expect(within(row).queryByText('Live')).not.toBeInTheDocument();
  });

  it('invites the first provider when there are none', async () => {
    state.providers = [];
    render(<SsoClient />);
    expect(await screen.findByText('No identity providers yet')).toBeInTheDocument();
  });

  it('has no axe violations, and dumps the docs fixture `sso-providers`', async () => {
    const { container } = render(<SsoClient />);
    await screen.findByTestId('sso-table');
    expect(await axe(container)).toHaveNoViolations();
    writeA11yFixture('sso-providers', liveMarkup(document.querySelector('.page') as HTMLElement));
  });
});

describe('register, verify, enable', () => {
  it('walks the whole path', async () => {
    state.providers = [];
    render(<SsoClient />);
    fireEvent.click(await screen.findByTestId('sso-add'));
    const dialog = await screen.findByTestId('sso-add-dialog');

    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: 'Acme Okta' } });
    // The ID follows the name until it is edited.
    expect(within(dialog).getByLabelText(/^ID/)).toHaveValue('acme-okta');
    fireEvent.change(within(dialog).getByLabelText(/^Issuer URL/), { target: { value: 'https://acme.okta.com' } });
    fireEvent.change(within(dialog).getByLabelText(/^Client ID/), { target: { value: 'apiome' } });
    fireEvent.change(within(dialog).getByLabelText(/^Client secret/), { target: { value: 's3cret-value' } });
    // Owner is not offered as a default role.
    const role = within(dialog).getByLabelText(/^Default role/);
    expect(within(role).queryByRole('option', { name: 'Owner' })).not.toBeInTheDocument();
    fireEvent.change(role, { target: { value: 'viewer' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('sso-add-submit'));
    });

    expect(writes()[0]).toEqual({
      method: 'POST',
      path: '',
      body: {
        protocol: 'oidc',
        slug: 'acme-okta',
        display_name: 'Acme Okta',
        issuer: 'https://acme.okta.com',
        client_id: 'apiome',
        client_secret: 's3cret-value',
        default_role_slug: 'viewer',
      },
    });

    // The new provider opens straight away, disabled, with nothing routing.
    const drawer = await screen.findByTestId('sso-provider-drawer');
    expect(within(drawer).getByTestId('sso-drawer-status')).toHaveTextContent('Disabled');

    selectTab(drawer, /Domains/);
    fireEvent.change(await within(drawer).findByLabelText('Add a domain'), { target: { value: 'acme.com' } });
    await act(async () => {
      fireEvent.click(within(drawer).getByRole('button', { name: 'Add domain' }));
    });
    const row = await within(drawer).findByTestId('sso-domain-acme.com');
    expect(within(row).getByText('Not verified')).toBeInTheDocument();
    expect(within(row).getByText('_apiome-challenge.acme.com')).toBeInTheDocument();
    expect(within(row).getByText('new-token-0001')).toBeInTheDocument();

    // Not published yet.
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    expect(await within(row).findByText('Record not found')).toBeInTheDocument();
    expect(within(row).getByText('Not verified')).toBeInTheDocument();

    // Published.
    state.dns['acme.com'] = 'verified';
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    await waitFor(() => expect(within(row).getByText('acme.com is verified.')).toBeInTheDocument());
    expect(within(row).queryByText('Not verified')).not.toBeInTheDocument();
    expect(within(row).queryByRole('button', { name: 'Verify' })).not.toBeInTheDocument();

    await act(async () => {
      fireEvent.click(within(drawer).getByTestId('sso-toggle'));
    });
    await waitFor(() => expect(within(drawer).getByTestId('sso-drawer-status')).toHaveTextContent('Live'));
    expect(writes().at(-1)).toMatchObject({ method: 'PATCH', body: { enabled: true } });
  });

  it('shows a refusal with REST’s own words and keeps the dialog open', async () => {
    state.refuse['POST '] = {
      status: 422,
      error: 'An SSO provider called “acme-okta” already exists.',
      code: 'sso-slug-taken',
    };
    render(<SsoClient />);
    fireEvent.click(await screen.findByTestId('sso-add'));
    const dialog = await screen.findByTestId('sso-add-dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Name/), { target: { value: 'Acme Okta' } });
    fireEvent.change(within(dialog).getByLabelText(/^Issuer URL/), { target: { value: 'https://acme.okta.com' } });
    fireEvent.change(within(dialog).getByLabelText(/^Client ID/), { target: { value: 'apiome' } });
    fireEvent.change(within(dialog).getByLabelText(/^Client secret/), { target: { value: 'x' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('sso-add-submit'));
    });
    expect(await within(dialog).findByText(/already exists/)).toBeInTheDocument();
  });

  it('asks SAML for metadata, where the email comes from, and no client secret', async () => {
    render(<SsoClient />);
    fireEvent.click(await screen.findByTestId('sso-add'));
    const dialog = await screen.findByTestId('sso-add-dialog');
    fireEvent.click(within(dialog).getByLabelText('SAML 2.0'));
    expect(within(dialog).getByLabelText(/^IdP metadata URL/)).toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/^Client secret/)).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText(/^Email attribute name/)).not.toBeInTheDocument();
    fireEvent.click(within(dialog).getByLabelText('An attribute'));
    expect(within(dialog).getByLabelText(/^Email attribute name/)).toBeInTheDocument();
  });
});

describe('the Domains tab', () => {
  it('reads a failed lookup as “Could not check”, with the answer, and leaves the domain unverified', async () => {
    state.dns['northwind.co.uk'] = 'could-not-check';
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    selectTab(drawer, /Domains/);
    const row = await within(drawer).findByTestId('sso-domain-northwind.co.uk');
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    const result = await within(row).findByTestId('sso-domain-check-northwind.co.uk');
    expect(result).toHaveAttribute('data-check-status', 'could-not-check');
    expect(within(result).getByText('Could not check')).toBeInTheDocument();
    expect(within(result).getByText('SERVFAIL: no nameserver answered for this name.')).toBeInTheDocument();
    expect(within(result).queryByText('Verified')).not.toBeInTheDocument();
    expect(within(row).getByText('Not verified')).toBeInTheDocument();
    expect(within(drawer).getByTestId('sso-drawer-status')).toHaveTextContent('Disabled');
  });

  it('shows what DNS holds when the record has another value', async () => {
    state.dns['northwind.co.uk'] = 'mismatch';
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    selectTab(drawer, /Domains/);
    const row = await within(drawer).findByTestId('sso-domain-northwind.co.uk');
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    expect(await within(row).findByText('Record has another value')).toBeInTheDocument();
    expect(within(row).getByText('an-older-token')).toBeInTheDocument();
  });

  it.each([
    ['sso-domain-claimed', 409, 'acme.com is already verified for another SSO provider.'],
    ['sso-domain-public', 422, 'gmail.com is a public email provider. Add a domain your organization owns.'],
  ])('shows %s as REST worded it', async (code, status, message) => {
    state.refuse[`POST /${SAML_ID}/domains`] = { status, error: message, code };
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    selectTab(drawer, /Domains/);
    fireEvent.change(await within(drawer).findByLabelText('Add a domain'), { target: { value: 'acme.com' } });
    await act(async () => {
      fireEvent.click(within(drawer).getByRole('button', { name: 'Add domain' }));
    });
    expect(await within(drawer).findByTestId('sso-domain-error')).toHaveTextContent(message);
    // What was typed is still there to correct.
    expect(within(drawer).getByLabelText('Add a domain')).toHaveValue('acme.com');
  });

  it('says a checked-too-often domain must wait', async () => {
    state.refuse[`POST /${SAML_ID}/domains/northwind.co.uk/verify`] = {
      status: 429,
      error: 'This domain was checked 3 times in the last hour. Try again in about 41 minutes.',
      code: 'sso-verify-rate-limited',
    };
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    selectTab(drawer, /Domains/);
    const row = await within(drawer).findByTestId('sso-domain-northwind.co.uk');
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    expect(await within(drawer).findByTestId('sso-domain-error')).toHaveTextContent(/about 41 minutes/);
  });

  it('removes a domain', async () => {
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Okta');
    selectTab(drawer, /Domains/);
    await act(async () => {
      fireEvent.click(await within(drawer).findByRole('button', { name: 'Remove northwind.io' }));
    });
    expect(await within(drawer).findByTestId('sso-domains-empty')).toBeInTheDocument();
    // Enabled with no verified domain left: no longer live.
    expect(within(drawer).getByTestId('sso-drawer-status')).toHaveTextContent('Needs a verified domain');
  });

  it('has no axe violations, and dumps the docs fixture `sso-domain-verify`', async () => {
    state.dns['northwind.co.uk'] = 'could-not-check';
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    selectTab(drawer, /Domains/);
    const row = await within(drawer).findByTestId('sso-domain-northwind.co.uk');
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Verify' }));
    });
    await within(row).findByText('Could not check');
    expect(await axe(drawer)).toHaveNoViolations();
    writeA11yFixture('sso-domain-verify', bodyMarkup());
  });
});

describe('the Configure tab and the footer', () => {
  it('gives the IdP its values and sends only what changed', async () => {
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Okta');
    expect(
      within(drawer).getByText('http://localhost/api/auth/sso/callback/sso-northwind-okta')
    ).toBeInTheDocument();
    const save = within(drawer).getByTestId('sso-configure-save');
    expect(save).toBeDisabled();
    expect(save).toHaveAttribute('title', 'Nothing has changed');
    // The stored secret is never read back: the field starts blank and says one is stored.
    expect(within(drawer).getByLabelText(/^Client secret/)).toHaveValue('');
    expect(within(drawer).getByText('A client secret is stored. Leave blank to keep it.')).toBeInTheDocument();

    fireEvent.change(within(drawer).getByLabelText(/^Name/), { target: { value: 'Northwind SSO' } });
    await act(async () => {
      fireEvent.click(save);
    });
    expect(writes()).toEqual([{ method: 'PATCH', path: `/${OKTA_ID}`, body: { display_name: 'Northwind SSO' } }]);
    expect(await within(drawer).findByText('Saved.')).toBeInTheDocument();
  });

  it('disables a live provider in one request', async () => {
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Okta');
    await act(async () => {
      fireEvent.click(within(drawer).getByRole('button', { name: 'Disable' }));
    });
    expect(writes()).toEqual([{ method: 'PATCH', path: `/${OKTA_ID}`, body: { enabled: false } }]);
    await waitFor(() => expect(within(drawer).getByTestId('sso-drawer-status')).toHaveTextContent('Disabled'));
    expect(within(screen.getByTestId('sso-row-northwind-okta')).getByText('Disabled')).toBeInTheDocument();
  });

  it('says how many members used a provider before removing it', async () => {
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Okta');
    fireEvent.click(within(drawer).getByTestId('sso-remove'));
    expect(within(drawer).getByTestId('sso-remove-impact')).toHaveTextContent(
      '42 members have signed in through this provider.'
    );
    expect(writes()).toEqual([]);

    fireEvent.click(within(drawer).getByRole('button', { name: 'Keep it' }));
    expect(within(drawer).queryByTestId('sso-remove-impact')).not.toBeInTheDocument();

    fireEvent.click(within(drawer).getByTestId('sso-remove'));
    await act(async () => {
      fireEvent.click(within(drawer).getByTestId('sso-remove-confirm'));
    });
    expect(writes()).toEqual([{ method: 'DELETE', path: `/${OKTA_ID}`, body: undefined }]);
    await waitFor(() => expect(screen.queryByTestId('sso-row-northwind-okta')).not.toBeInTheDocument());
  });

  it('has no axe violations, and dumps the docs fixture `sso-provider-configure`', async () => {
    render(<SsoClient />);
    const drawer = await openProvider('Northwind Entra ID');
    await within(drawer).findByTestId('sso-configure-form');
    expect(await axe(drawer)).toHaveNoViolations();
    writeA11yFixture('sso-provider-configure', bodyMarkup());
  });
});
