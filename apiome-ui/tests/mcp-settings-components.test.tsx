/**
 * Render/interaction tests for the MCP endpoint-detail "Settings" tab (V2-MCP-24.9 / MCAT-10.9).
 *
 * Covers form seeding, the dirty-gated Save (PATCH) call, inline validation, the enable/disable
 * lifecycle toggle, and the typed-confirm delete (DELETE) that surfaces the teardown summary.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import McpEndpointSettings from '../src/app/ade/dashboard/mcp/[endpointId]/McpEndpointSettings';
import {
  mcpEndpointDetailFromPayload,
  type McpEndpointDetail,
} from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

// sonner's toast is a side-effect only; stub it so tests don't need a Toaster mounted.
jest.mock('sonner', () => ({
  toast: { success: jest.fn(), error: jest.fn(), info: jest.fn() },
}));

const ENDPOINT_ID = '11111111-1111-1111-8111-111111111111';

function endpoint(overrides: Record<string, unknown> = {}): McpEndpointDetail {
  const parsed = mcpEndpointDetailFromPayload({
    endpoint: {
      id: ENDPOINT_ID,
      name: 'Acme Weather',
      slug: 'acme-weather',
      endpoint_url: 'https://mcp.acme.example/sse',
      transport: 'streamable_http',
      visibility: 'private',
      published: false,
      enabled: true,
      discovery_cadence_seconds: 86400,
      ...overrides,
    },
  });
  if (!parsed) throw new Error('fixture failed to parse');
  return parsed;
}

/** A mock `fetch` that returns `body` (JSON) with the given status. */
function mockFetchOnce(body: unknown, ok = true, status = 200) {
  (global.fetch as jest.Mock).mockResolvedValueOnce({
    ok,
    status,
    statusText: ok ? 'OK' : 'Bad Request',
    json: async () => body,
  });
}

beforeEach(() => {
  global.fetch = jest.fn();
});

afterEach(() => {
  jest.clearAllMocks();
});

describe('McpEndpointSettings — identity form', () => {
  it('seeds the inputs from the endpoint', () => {
    render(
      <McpEndpointSettings endpoint={endpoint()} onSaved={jest.fn()} onDeleted={jest.fn()} />,
    );
    expect((screen.getByLabelText(/^Name/) as HTMLInputElement).value).toBe('Acme Weather');
    expect((screen.getByLabelText(/Endpoint URL/) as HTMLInputElement).value).toBe(
      'https://mcp.acme.example/sse',
    );
  });

  it('disables Save until a field changes, then PATCHes only the change', async () => {
    const onSaved = jest.fn();
    render(<McpEndpointSettings endpoint={endpoint()} onSaved={onSaved} onDeleted={jest.fn()} />);

    const save = screen.getByRole('button', { name: /Save changes/i });
    expect(save).toBeDisabled();

    fireEvent.change(screen.getByLabelText(/^Name/), { target: { value: 'Acme Weather 2' } });
    expect(save).toBeEnabled();

    mockFetchOnce({ endpoint: { ...endpoint(), name: 'Acme Weather 2' } });
    fireEvent.click(save);

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe(`/api/mcp/endpoints/${ENDPOINT_ID}`);
    expect(init.method).toBe('PATCH');
    expect(JSON.parse(init.body)).toEqual({ name: 'Acme Weather 2' });
    expect(onSaved.mock.calls[0][0].name).toBe('Acme Weather 2');
  });

  it('shows an inline validation error and does not call the API for a bad URL', () => {
    render(<McpEndpointSettings endpoint={endpoint()} onSaved={jest.fn()} onDeleted={jest.fn()} />);
    fireEvent.change(screen.getByLabelText(/Endpoint URL/), { target: { value: 'not-a-url' } });
    fireEvent.click(screen.getByRole('button', { name: /Save changes/i }));
    expect(screen.getByRole('alert')).toHaveTextContent(/valid URL/i);
    expect(global.fetch).not.toHaveBeenCalled();
  });
});

describe('McpEndpointSettings — lifecycle', () => {
  it('toggles enabled via PATCH', async () => {
    const onSaved = jest.fn();
    render(<McpEndpointSettings endpoint={endpoint()} onSaved={onSaved} onDeleted={jest.fn()} />);

    mockFetchOnce({ endpoint: { ...endpoint(), enabled: false } });
    fireEvent.click(screen.getByRole('button', { name: /^Disable/i }));

    await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1));
    const [, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(JSON.parse(init.body)).toEqual({ enabled: false });
  });
});

describe('McpEndpointSettings — delete', () => {
  it('requires the typed confirm word before deleting and surfaces the teardown summary', async () => {
    const onDeleted = jest.fn();
    render(<McpEndpointSettings endpoint={endpoint()} onSaved={jest.fn()} onDeleted={onDeleted} />);

    fireEvent.click(screen.getByRole('button', { name: /Delete endpoint/i }));

    // The dialog's action button is gated until "DELETE" is typed (scoped to the dialog so it is
    // not confused with the danger-zone trigger button of the same name).
    const dialog = screen.getByRole('alertdialog');
    const confirmInput = within(dialog).getByLabelText(/to\s+confirm/i);
    const actionButton = within(dialog).getByRole('button', { name: /^Delete endpoint$/i });
    expect(actionButton).toBeDisabled();

    fireEvent.change(confirmInput, { target: { value: 'DELETE' } });
    expect(actionButton).toBeEnabled();

    mockFetchOnce({
      success: true,
      credentials_purged: true,
      versions_deleted: 3,
      jobs_deleted: 2,
    });
    fireEvent.click(actionButton);

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe(`/api/mcp/endpoints/${ENDPOINT_ID}`);
    expect(init.method).toBe('DELETE');
    expect(onDeleted.mock.calls[0][0]).toEqual({
      credentials_purged: true,
      versions_deleted: 3,
      jobs_deleted: 2,
    });
  });
});
