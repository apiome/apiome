/**
 * Component tests for the MCP endpoint Credentials tab (V2-MCP-24.6 / MCAT-10.6, #3702).
 *
 * The acceptance criteria, as the screen shows them: a stored credential is shown **masked** with
 * its scheme and never its value; a bearer token or a custom header can be set (`PUT`) and the
 * typed secret leaves the page with the request; a credential can be cleared (`DELETE`) behind a
 * confirm; the encryption-at-rest note is present; and the OAuth connection section appears for
 * an OAuth-protected server.
 */

import React from 'react';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import '@testing-library/jest-dom';
import { beforeEach, describe, expect, it, jest } from '@jest/globals';

const mockConfirm = jest.fn<() => Promise<boolean>>(async () => true);
jest.mock('@/app/components/providers/DialogProvider', () => ({
  useDialog: () => ({ confirm: mockConfirm, alert: jest.fn(), prompt: jest.fn() }),
}));

const mockToast = { success: jest.fn(), error: jest.fn(), info: jest.fn() };
jest.mock('@/app/components/ui/toast', () => ({ toast: mockToast }));

import McpEndpointCredentials from '../src/app/ade/dashboard/mcp/[endpointId]/McpEndpointCredentials';
import {
  MCP_CREDENTIAL_ENCRYPTION_NOTE,
  MCP_CREDENTIAL_MASK,
} from '../src/app/components/ade/dashboard/mcp/mcpCredentialsForm';

const ENDPOINT_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CREDENTIALS_URL = `/api/mcp/endpoints/${ENDPOINT_ID}/credentials`;

const STORED_BEARER = {
  endpoint_id: ENDPOINT_ID,
  auth_type: 'bearer',
  configured: true,
  masked_secret: '********',
  key_version: 2,
  oauth_metadata: {},
  updated_at: '2026-11-08T12:00:00Z',
};

const NONE = { endpoint_id: ENDPOINT_ID, auth_type: 'none', configured: false, oauth_metadata: {} };

const OAUTH_DISCOVERED = {
  issuer: 'https://auth.example.com',
  authorization_endpoint: 'https://auth.example.com/authorize',
  token_endpoint: 'https://auth.example.com/token',
  registration_endpoint: 'https://auth.example.com/register',
  pkce_s256_supported: true,
};

function jsonResponse(body: unknown, ok = true, status = 200) {
  return { ok, status, statusText: ok ? 'OK' : 'Error', json: async () => body } as Response;
}

/** Every write the panel makes, so a test can assert what it sent. */
let writes: Array<{ url: string; method: string; body: unknown }> = [];

/**
 * Route the panel's reads and writes.
 *
 * @param credential What `GET …/credentials` answers.
 * @param put What `PUT …/credentials` answers (default: the stored-bearer status).
 * @param del What `DELETE …/credentials` answers.
 */
function routeFetch(
  credential: Record<string, unknown>,
  put: () => Response = () => jsonResponse({ success: true, credential: STORED_BEARER }),
  del: () => Response = () => jsonResponse({ success: true, endpoint_id: ENDPOINT_ID, removed: true }),
) {
  global.fetch = jest.fn(async (url: string, init?: RequestInit) => {
    const method = (init?.method ?? 'GET').toUpperCase();
    if (url !== CREDENTIALS_URL) throw new Error(`unexpected fetch: ${url}`);
    if (method === 'GET') return jsonResponse({ success: true, credential });
    writes.push({ url, method, body: init?.body ? JSON.parse(String(init.body)) : null });
    if (method === 'PUT') return put();
    if (method === 'DELETE') return del();
    throw new Error(`unexpected method: ${method}`);
  }) as unknown as typeof fetch;
}

beforeEach(() => {
  writes = [];
  mockConfirm.mockReset();
  mockConfirm.mockResolvedValue(true);
  mockToast.success.mockReset();
  mockToast.error.mockReset();
});

describe('the stored credential', () => {
  it('shows the scheme and a mask, and never the secret', async () => {
    routeFetch(STORED_BEARER);
    const { container } = render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);

    expect(await screen.findByTestId('mcp-credentials-title')).toHaveTextContent('Bearer token stored');
    expect(screen.getByTestId('mcp-credentials-badge')).toHaveTextContent('bearer');
    expect(screen.getByTestId('mcp-credentials-mask')).toHaveTextContent(MCP_CREDENTIAL_MASK);
    expect(screen.getByTestId('mcp-credentials-meta')).toHaveTextContent(/Encrypted with key v2/);
    expect(screen.getByRole('button', { name: /Clear credential/ })).toBeEnabled();
    // apiome-rest's own placeholder is not echoed either: the page draws its mask, not the API's.
    expect(container.textContent).not.toContain('********');
    // The form offers to replace, not to set.
    expect(screen.getByRole('heading', { name: 'Replace credential' })).toBeInTheDocument();
  });

  it('explains the anonymous state and offers nothing to clear', async () => {
    routeFetch(NONE);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);

    expect(await screen.findByTestId('mcp-credentials-title')).toHaveTextContent('No credential stored');
    expect(screen.getByTestId('mcp-credentials-badge')).toHaveTextContent('No auth');
    expect(screen.queryByTestId('mcp-credentials-mask')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Clear credential/ })).not.toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Set credential' })).toBeInTheDocument();
  });

  it('states the encryption-at-rest note', async () => {
    routeFetch(NONE);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    expect(await screen.findByTestId('mcp-credentials-encryption-note')).toHaveTextContent(MCP_CREDENTIAL_ENCRYPTION_NOTE);
  });

  it('says why the status could not be read', async () => {
    global.fetch = jest.fn(async () => jsonResponse({ success: false, error: 'Endpoint not found' }, false, 404)) as unknown as typeof fetch;
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    expect(await screen.findByTestId('mcp-credentials-load-error')).toHaveTextContent('Endpoint not found');
  });
});

describe('setting a credential', () => {
  it('sends a bearer token, empties the field and shows the new status masked', async () => {
    routeFetch(NONE);
    const onChanged = jest.fn();
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} onChanged={onChanged} />);
    await screen.findByTestId('mcp-credentials-title');

    const save = screen.getByTestId('mcp-credentials-save');
    expect(save).toBeDisabled();

    const secret = screen.getByLabelText(/Access token/);
    expect(secret).toHaveAttribute('type', 'password');
    await userEvent.type(secret, 'sk-live-123');
    expect(save).toBeEnabled();
    await userEvent.click(save);

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({
      url: CREDENTIALS_URL,
      method: 'PUT',
      body: { auth_type: 'bearer', payload: { token: 'sk-live-123' } },
    });
    await waitFor(() => expect(screen.getByTestId('mcp-credentials-mask')).toBeInTheDocument());
    expect(screen.getByTestId('mcp-credentials-title')).toHaveTextContent('Bearer token stored');
    expect(secret).toHaveValue('');
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ authType: 'bearer', configured: true }));
    expect(mockToast.success).toHaveBeenCalled();
    // The typed secret is nowhere on the page once stored.
    expect(document.body.textContent).not.toContain('sk-live-123');
  });

  it('sends a custom header with its name', async () => {
    routeFetch(NONE, () =>
      jsonResponse({ success: true, credential: { ...STORED_BEARER, auth_type: 'header' } }),
    );
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-title');

    await userEvent.click(screen.getByTestId('mcp-credentials-auth-type'));
    await userEvent.click(await screen.findByRole('option', { name: 'Custom header' }));

    await userEvent.type(screen.getByLabelText(/Header name/), 'X-Api-Key');
    await userEvent.type(screen.getByLabelText(/Header value/), 'k-42');
    await userEvent.click(screen.getByTestId('mcp-credentials-save'));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0].body).toEqual({ auth_type: 'header', payload: { name: 'X-Api-Key', value: 'k-42' } });
    expect(await screen.findByTestId('mcp-credentials-title')).toHaveTextContent('Custom header stored');
  });

  it('states a validation failure in words and sends nothing', async () => {
    routeFetch(NONE);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-title');

    await userEvent.click(screen.getByTestId('mcp-credentials-auth-type'));
    await userEvent.click(await screen.findByRole('option', { name: 'Custom header' }));
    await userEvent.type(screen.getByLabelText(/Header value/), 'v');
    await userEvent.click(screen.getByTestId('mcp-credentials-save'));

    const error = await screen.findByTestId('mcp-credentials-error');
    expect(error).toHaveAttribute('role', 'alert');
    expect(error).toHaveTextContent('Enter the header name.');
    expect(writes).toHaveLength(0);
  });

  it('shows the server’s refusal — such as encryption not being configured — beside the form', async () => {
    routeFetch(NONE, () =>
      jsonResponse({ success: false, error: 'MCP credential encryption is not configured' }, false, 503),
    );
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-title');

    await userEvent.type(screen.getByLabelText(/Access token/), 'tok');
    await userEvent.click(screen.getByTestId('mcp-credentials-save'));

    expect(await screen.findByTestId('mcp-credentials-error')).toHaveTextContent('encryption is not configured');
    // Nothing was stored, so nothing is masked and the field keeps what was typed for a retry.
    expect(screen.queryByTestId('mcp-credentials-mask')).not.toBeInTheDocument();
    expect(screen.getByLabelText(/Access token/)).toHaveValue('tok');
  });

  it('reveals and hides what is typed on request', async () => {
    routeFetch(NONE);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-title');

    const secret = screen.getByLabelText(/Access token/);
    const reveal = screen.getByTestId('mcp-credentials-reveal');
    expect(reveal).toHaveAttribute('aria-pressed', 'false');
    await userEvent.click(reveal);
    expect(secret).toHaveAttribute('type', 'text');
    expect(reveal).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(reveal);
    expect(secret).toHaveAttribute('type', 'password');
  });
});

describe('clearing a credential', () => {
  it('asks first, then deletes and returns to the anonymous state', async () => {
    routeFetch(STORED_BEARER);
    const onChanged = jest.fn();
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} onChanged={onChanged} />);
    await screen.findByTestId('mcp-credentials-mask');

    await userEvent.click(screen.getByRole('button', { name: /Clear credential/ }));
    expect(mockConfirm).toHaveBeenCalledWith(expect.objectContaining({ title: 'Clear this credential?', variant: 'danger' }));

    await waitFor(() => expect(writes).toHaveLength(1));
    expect(writes[0]).toEqual({ url: CREDENTIALS_URL, method: 'DELETE', body: null });
    await waitFor(() => expect(screen.getByTestId('mcp-credentials-title')).toHaveTextContent('No credential stored'));
    expect(screen.queryByTestId('mcp-credentials-mask')).not.toBeInTheDocument();
    expect(onChanged).toHaveBeenCalledWith(expect.objectContaining({ authType: 'none', configured: false }));
  });

  it('does nothing when the confirm is declined', async () => {
    routeFetch(STORED_BEARER);
    mockConfirm.mockResolvedValue(false);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-mask');

    await userEvent.click(screen.getByRole('button', { name: /Clear credential/ }));
    expect(mockConfirm).toHaveBeenCalled();
    expect(writes).toHaveLength(0);
    expect(screen.getByTestId('mcp-credentials-mask')).toBeInTheDocument();
  });

  it('reports a failed clear and keeps the credential shown', async () => {
    routeFetch(STORED_BEARER, undefined, () => jsonResponse({ success: false, error: 'Endpoint not found' }, false, 404));
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-mask');

    await userEvent.click(screen.getByRole('button', { name: /Clear credential/ }));
    await waitFor(() => expect(mockToast.error).toHaveBeenCalledWith('Endpoint not found'));
    expect(screen.getByTestId('mcp-credentials-mask')).toBeInTheDocument();
  });
});

describe('the OAuth connection', () => {
  it('is absent for a server without discovered OAuth metadata', async () => {
    routeFetch(STORED_BEARER);
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);
    await screen.findByTestId('mcp-credentials-mask');
    await waitFor(() => expect((global.fetch as jest.Mock).mock.calls.length).toBeGreaterThanOrEqual(2));
    expect(screen.queryByTestId('mcp-oauth-connection')).not.toBeInTheDocument();
  });

  it('is offered for an OAuth-protected server, inside the tab', async () => {
    routeFetch({ ...NONE, oauth_metadata: OAUTH_DISCOVERED });
    render(<McpEndpointCredentials endpointId={ENDPOINT_ID} />);

    const section = await screen.findByTestId('mcp-oauth-connection');
    expect(within(section).getByRole('button', { name: /Connect with OAuth/ })).toBeEnabled();
    expect(within(screen.getByTestId('mcp-credentials')).getByTestId('mcp-oauth-connection')).toBe(section);
  });
});
