/**
 * The Single sign-on card on System settings — EID-1.1 (#5011).
 *
 * Pinned: providers load through the admin proxy and show their status (Live only when enabled with
 * a verified domain), the values the IdP needs, and their domains; adding an OIDC provider posts the
 * form; Mark verified, Enable and a two-step Remove call the right proxy routes; REST's stable
 * message reaches the admin; a secret typed into the form is never rendered back; and the card is
 * axe-clean.
 */
import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';
import { axe } from 'jest-axe';
import 'jest-axe/extend-expect';

import SsoProvidersCard from '../src/app/admin/dashboard/settings/SsoProvidersCard';
import type { AdminSsoProviderView } from '../lib/auth/admin-sso';

const ID = '3f2b8c1e-0d4a-4b7e-9c11-2a6f5e8d9b01';

function provider(overrides: Partial<AdminSsoProviderView> = {}): AdminSsoProviderView {
  return {
    id: ID,
    slug: 'acme-okta',
    plugin_provider_id: 'sso-acme-okta',
    identity_kind: 'sso:acme-okta',
    protocol: 'oidc',
    display_name: 'Acme Okta',
    issuer: 'https://acme.okta.test',
    tenant_id: null,
    tenant_name: 'Acme Corp',
    oidc_config: { client_id: 'apiome' },
    saml_config: null,
    has_client_secret: true,
    has_sp_private_key: false,
    enabled: false,
    routable: false,
    domains: [{ domain: 'acme.com', verified: false, verified_at: null, verified_by: null, verification_token: 'tok' }],
    ...overrides,
  };
}

type Handler = (method: string, url: string, body: unknown) => { status: number; body: unknown };

function mockFetch(handler: Handler) {
  const calls: { method: string; url: string; body: unknown }[] = [];
  global.fetch = jest.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? 'GET';
    const url = String(input);
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    calls.push({ method, url, body });
    const result = handler(method, url, body);
    return { ok: result.status < 300, status: result.status, json: async () => result.body } as unknown as Response;
  }) as unknown as typeof fetch;
  return calls;
}

async function renderCard() {
  await act(async () => {
    render(<SsoProvidersCard />);
  });
}

describe('SsoProvidersCard', () => {
  it('lists a provider with its status, the values for the IdP and its domains', async () => {
    mockFetch(() => ({ status: 200, body: { providers: [provider()] } }));
    await renderCard();

    const row = await screen.findByTestId('sso-provider-acme-okta');
    expect(within(row).getByText('Acme Okta')).toBeInTheDocument();
    expect(within(row).getByText('OIDC')).toBeInTheDocument();
    expect(within(row).getByText('Disabled')).toBeInTheDocument();
    expect(within(row).getByText('sso:acme-okta')).toBeInTheDocument();
    expect(within(row).getByText(/\/api\/auth\/sso\/callback\/sso-acme-okta$/)).toBeInTheDocument();
    expect(within(row).getByText('acme.com')).toBeInTheDocument();
    expect(within(row).getByRole('button', { name: 'Mark verified' })).toBeInTheDocument();
  });

  it('says what an enabled provider still needs, and shows a live one as Live', async () => {
    mockFetch(() => ({
      status: 200,
      body: {
        providers: [
          provider({ enabled: true }),
          provider({
            id: '11111111-1111-4111-8111-111111111111',
            slug: 'live',
            display_name: 'Live IdP',
            enabled: true,
            routable: true,
            domains: [{ domain: 'live.com', verified: true, verified_at: 'now', verified_by: 'admin', verification_token: 't' }],
          }),
        ],
      },
    }));
    await renderCard();
    expect(within(await screen.findByTestId('sso-provider-acme-okta')).getByText('Needs a verified domain')).toBeInTheDocument();
    const live = screen.getByTestId('sso-provider-live');
    expect(within(live).getByText('Live')).toBeInTheDocument();
    expect(within(live).getByText('Verified')).toBeInTheDocument();
  });

  it('adds an OIDC provider, and never renders the secret back', async () => {
    let listed: AdminSsoProviderView[] = [];
    const calls = mockFetch((method) => {
      if (method === 'POST') {
        listed = [provider()];
        return { status: 201, body: provider() };
      }
      return { status: 200, body: { providers: listed } };
    });
    await renderCard();
    fireEvent.click(await screen.findByRole('button', { name: /Add identity provider/ }));

    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme Okta' } });
    expect(screen.getByLabelText('ID')).toHaveValue('acme-okta');
    fireEvent.change(screen.getByLabelText('Issuer URL'), { target: { value: 'https://acme.okta.test' } });
    fireEvent.change(screen.getByLabelText('Client ID'), { target: { value: 'apiome' } });
    fireEvent.change(screen.getByLabelText('Client secret'), { target: { value: 'top-secret-value' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('sso-add-submit'));
    });

    const post = calls.find((c) => c.method === 'POST');
    expect(post?.url).toBe('/api/admin/sso/providers');
    expect(post?.body).toEqual({
      protocol: 'oidc',
      slug: 'acme-okta',
      display_name: 'Acme Okta',
      issuer: 'https://acme.okta.test',
      client_id: 'apiome',
      client_secret: 'top-secret-value',
    });
    expect(await screen.findByTestId('sso-provider-acme-okta')).toBeInTheDocument();
    expect(screen.queryByTestId('sso-add-form')).not.toBeInTheDocument();
    expect(document.body.textContent).not.toContain('top-secret-value');
  });

  it('shows REST’s stable message when adding fails', async () => {
    mockFetch((method) =>
      method === 'POST'
        ? { status: 422, body: { detail: { error: 'sso-binding-unsupported', message: 'The IdP offers single sign-on only over HTTP-Artifact.' } } }
        : { status: 200, body: { providers: [] } }
    );
    await renderCard();
    fireEvent.click(await screen.findByRole('button', { name: /Add identity provider/ }));
    fireEvent.click(screen.getByLabelText('SAML 2.0'));
    fireEvent.change(screen.getByLabelText('Name'), { target: { value: 'Acme' } });
    fireEvent.change(screen.getByLabelText('IdP metadata URL'), { target: { value: 'https://idp.test/md' } });
    await act(async () => {
      fireEvent.click(screen.getByTestId('sso-add-submit'));
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('only over HTTP-Artifact');
  });

  it('marks a domain verified, enables, and removes in two steps', async () => {
    let current = provider();
    const calls = mockFetch((method, url) => {
      if (method === 'POST' && url.endsWith('/domains/acme.com/verify')) {
        current = { ...current, domains: [{ ...current.domains[0], verified: true }] };
        return { status: 200, body: current };
      }
      if (method === 'PATCH') {
        current = { ...current, enabled: true, routable: true };
        return { status: 200, body: current };
      }
      if (method === 'DELETE') return { status: 200, body: current };
      return { status: 200, body: { providers: [current] } };
    });
    await renderCard();
    const row = await screen.findByTestId('sso-provider-acme-okta');

    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Mark verified' }));
    });
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Enable' }));
    });
    expect(within(row).getByText('Live')).toBeInTheDocument();

    fireEvent.click(within(row).getByRole('button', { name: 'Remove…' }));
    expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: 'Remove Acme Okta' }));
    });
    await waitFor(() => expect(screen.queryByTestId('sso-provider-acme-okta')).not.toBeInTheDocument());

    expect(calls.map((c) => `${c.method} ${c.url}`)).toEqual([
      'GET /api/admin/sso/providers',
      `POST /api/admin/sso/providers/${ID}/domains/acme.com/verify`,
      `PATCH /api/admin/sso/providers/${ID}`,
      `DELETE /api/admin/sso/providers/${ID}`,
    ]);
    expect(calls[2].body).toEqual({ enabled: true });
  });

  it('adds a domain', async () => {
    const calls = mockFetch((method) =>
      method === 'POST' ? { status: 201, body: provider() } : { status: 200, body: { providers: [provider({ domains: [] })] } }
    );
    await renderCard();
    const row = await screen.findByTestId('sso-provider-acme-okta');
    fireEvent.change(within(row).getByLabelText('Add a domain to Acme Okta'), { target: { value: 'acme.com' } });
    await act(async () => {
      fireEvent.click(within(row).getByRole('button', { name: /Add domain/ }));
    });
    expect(calls[1]).toEqual({ method: 'POST', url: `/api/admin/sso/providers/${ID}/domains`, body: { domain: 'acme.com' } });
  });

  it('offers a retry when the list cannot load', async () => {
    mockFetch(() => ({ status: 502, body: { error: 'rest_unreachable', message: 'Could not reach the configuration service.' } }));
    await renderCard();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the configuration service.');
    expect(screen.getByRole('button', { name: /Retry/ })).toBeInTheDocument();
  });

  it('has no axe violations', async () => {
    mockFetch(() => ({ status: 200, body: { providers: [provider({ protocol: 'saml', oidc_config: null, saml_config: {} })] } }));
    let container!: HTMLElement;
    await act(async () => {
      container = render(<SsoProvidersCard />).container;
    });
    await screen.findByTestId('sso-provider-acme-okta');
    expect(await axe(container)).toHaveNoViolations();
  });
});
