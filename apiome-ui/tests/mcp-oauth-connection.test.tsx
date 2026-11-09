/**
 * Component tests for the MCP OAuth connection section and callback page
 * (V2-MCP-20.4 / MCAT-6.4, #3680): the section appears only for an OAuth-protected server, starts
 * the authorization and sends the browser to the authorization URL; the callback page posts the
 * redirect parameters and returns to the endpoint's Credentials tab, or shows why it failed.
 */

import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, jest } from '@jest/globals';

const mockReplace = jest.fn();
jest.mock('next/navigation', () => ({
  useRouter: () => ({ push: jest.fn(), replace: mockReplace }),
  useSearchParams: () => new URLSearchParams(),
  usePathname: () => '/ade/dashboard/mcp/oauth/callback',
}));

import McpOAuthConnection from '../src/app/ade/dashboard/mcp/[endpointId]/McpOAuthConnection';
import McpOAuthCallbackClient from '../src/app/ade/dashboard/mcp/oauth/callback/McpOAuthCallbackClient';

const ENDPOINT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';

const DISCOVERED = {
  issuer: 'https://auth.example.com',
  authorization_endpoint: 'https://auth.example.com/authorize',
  token_endpoint: 'https://auth.example.com/token',
  registration_endpoint: 'https://auth.example.com/register',
  pkce_s256_supported: true,
};

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: ok ? 'OK' : 'Error', json: async () => body } as Response;
}

let posts: Array<{ url: string; body: Record<string, unknown> }> = [];

function routeFetch(credential: Record<string, unknown>, post = () => jsonResponse({})) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith('/credentials')) return jsonResponse({ success: true, credential });
    if (init?.method === 'POST') {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return post();
    }
    throw new Error(`unexpected fetch: ${url}`);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  posts = [];
  mockReplace.mockReset();
});

describe('McpOAuthConnection', () => {
  it('renders nothing for a server without OAuth metadata', async () => {
    routeFetch({ auth_type: 'bearer', configured: true, oauth_metadata: {} });
    const { container } = render(<McpOAuthConnection endpointId={ENDPOINT_ID} />);
    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('starts the authorization and sends the browser to the authorization URL', async () => {
    routeFetch({ auth_type: 'none', configured: false, oauth_metadata: DISCOVERED }, () =>
      jsonResponse({ success: true, authorization_url: 'https://auth.example.com/authorize?x=1' }),
    );
    const navigate = jest.fn();
    render(<McpOAuthConnection endpointId={ENDPOINT_ID} navigate={navigate} />);

    expect(await screen.findByText('Not connected')).toBeInTheDocument();
    expect(screen.queryByLabelText('Client ID')).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Connect with OAuth/ }));

    await waitFor(() => expect(navigate).toHaveBeenCalledWith('https://auth.example.com/authorize?x=1'));
    expect(posts[0].url).toBe(`/api/mcp/endpoints/${ENDPOINT_ID}/oauth/authorize`);
    expect(posts[0].body).toEqual({ redirect_uri: `${window.location.origin}/ade/dashboard/mcp/oauth/callback` });
  });

  it('asks for a client id when the server cannot register clients', async () => {
    routeFetch({ auth_type: 'none', configured: false, oauth_metadata: { ...DISCOVERED, registration_endpoint: null } }, () =>
      jsonResponse({ success: true, authorization_url: 'https://auth.example.com/a' }),
    );
    const navigate = jest.fn();
    render(<McpOAuthConnection endpointId={ENDPOINT_ID} navigate={navigate} />);

    await userEvent.click(await screen.findByRole('button', { name: /Connect with OAuth/ }));
    expect(screen.getByTestId('mcp-oauth-error')).toHaveTextContent('Enter the client ID');
    expect(posts).toHaveLength(0);

    await userEvent.type(screen.getByLabelText('Client ID'), 'pre-1');
    await userEvent.click(screen.getByRole('button', { name: /Connect with OAuth/ }));
    await waitFor(() => expect(navigate).toHaveBeenCalled());
    expect(posts[0].body.client_id).toBe('pre-1');
  });

  it('shows a connected token, its renewal and a failed refresh', async () => {
    routeFetch({
      auth_type: 'oauth2',
      configured: true,
      oauth_metadata: {
        ...DISCOVERED,
        token: {
          expires_at: '2026-11-08T13:00:00+00:00',
          refreshable: true,
          scope: 'mcp:read',
          last_refresh_error: { code: 'token_error', message: 'token refresh returned HTTP 400 (invalid_grant)' },
        },
      },
    });
    render(<McpOAuthConnection endpointId={ENDPOINT_ID} />);
    expect(await screen.findByText('Connected')).toBeInTheDocument();
    expect(screen.getByTestId('mcp-oauth-detail')).toHaveTextContent('renews automatically');
    expect(screen.getByText('Scope: mcp:read')).toBeInTheDocument();
    expect(screen.getByTestId('mcp-oauth-refresh-error')).toHaveTextContent('invalid_grant');
    expect(screen.getByRole('button', { name: /Reconnect/ })).toBeEnabled();
  });

  it('refuses to connect without PKCE', async () => {
    routeFetch({ auth_type: 'none', configured: false, oauth_metadata: { ...DISCOVERED, pkce_s256_supported: false } });
    render(<McpOAuthConnection endpointId={ENDPOINT_ID} />);
    expect(await screen.findByTestId('mcp-oauth-no-pkce')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Connect with OAuth/ })).toBeDisabled();
  });

  it('shows the server error when the authorization cannot start', async () => {
    routeFetch({ auth_type: 'none', configured: false, oauth_metadata: DISCOVERED }, () =>
      jsonResponse({ success: false, error: 'client registration returned HTTP 400 (registration_failed)' }, false, 502),
    );
    render(<McpOAuthConnection endpointId={ENDPOINT_ID} navigate={jest.fn()} />);
    await userEvent.click(await screen.findByRole('button', { name: /Connect with OAuth/ }));
    expect(await screen.findByTestId('mcp-oauth-error')).toHaveTextContent('registration_failed');
  });
});

describe('McpOAuthCallbackClient', () => {
  function at(search: string) {
    window.history.replaceState({}, '', `/ade/dashboard/mcp/oauth/callback${search}`);
  }

  it('posts the redirect parameters and returns to Credentials', async () => {
    at('?code=c1&state=s1&iss=https%3A%2F%2Fauth.example.com');
    routeFetch({}, () => jsonResponse({ success: true, endpoint_id: ENDPOINT_ID }));
    render(<McpOAuthCallbackClient />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledWith(`/ade/dashboard/mcp/${ENDPOINT_ID}?tab=credentials`));
    expect(posts).toHaveLength(1);
    expect(posts[0].url).toBe('/api/mcp/oauth/callback');
    expect(posts[0].body).toEqual({
      state: 's1',
      code: 'c1',
      error: null,
      error_description: null,
      iss: 'https://auth.example.com',
    });
  });

  it('shows why the connection failed', async () => {
    at('?error=access_denied&state=s1');
    routeFetch({}, () => jsonResponse({ success: false, error: 'the authorization server returned access_denied' }, false, 400));
    render(<McpOAuthCallbackClient />);
    expect(await screen.findByTestId('mcp-oauth-callback-error')).toHaveTextContent('access_denied');
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it('explains a visit without a state', async () => {
    at('');
    routeFetch({});
    render(<McpOAuthCallbackClient />);
    expect(await screen.findByTestId('mcp-oauth-callback-error')).toHaveTextContent('opened by the authorization server');
    expect(posts).toHaveLength(0);
  });
});
