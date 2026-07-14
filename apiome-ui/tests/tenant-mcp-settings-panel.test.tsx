/**
 * Tenant MCP Settings panel — MTG-4.1 (#4780).
 */

import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import { jest } from '@jest/globals';

jest.mock('sonner', () => ({
  toast: {
    success: jest.fn(),
    error: jest.fn(),
  },
}));

import TenantMcpSettingsPanel from '../src/app/ade/dashboard/tenants/TenantMcpSettingsPanel';

const POLICY = {
  default_mode: 'all',
  allow_anonymous_mcp: true,
  tools: [
    {
      tool_id: 'ping',
      in_ceiling: true,
      default_enabled: true,
      anonymous_enabled: true,
    },
  ],
  updated_at: null,
  updated_by: null,
};

const CATALOG = {
  tools: [
    { id: 'ping', description: 'Health check', toolset: 'health' },
    { id: 'spec.list', description: 'List specs', toolset: 'catalog' },
  ],
};

let calls: { url: string; method: string; body: unknown }[] = [];

function jsonResponse(payload: unknown) {
  return Promise.resolve({
    status: 200,
    ok: true,
    json: () => Promise.resolve(payload),
  } as Response);
}

function mockFetch() {
  const fn = jest.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input.toString();
    const method = init?.method || 'GET';
    calls.push({
      url,
      method,
      body: init?.body ? JSON.parse(init.body as string) : null,
    });

    if (url.includes('/api/tenants/mcp-policy') && method === 'GET') {
      return jsonResponse({ success: true, data: POLICY });
    }
    if (url.includes('/api/api-keys/mcp-tools') && method === 'GET') {
      return jsonResponse({ success: true, data: CATALOG });
    }
    if (url.includes('/api/tenants/mcp-policy') && method === 'PUT') {
      return jsonResponse({
        success: true,
        data: { ...POLICY, ...(init?.body ? JSON.parse(init.body as string) : {}) },
      });
    }
    return jsonResponse({ success: false, error: `Unhandled ${method} ${url}` });
  });
  // @ts-expect-error test double
  global.fetch = fn;
  return fn;
}

beforeEach(() => {
  calls = [];
  mockFetch();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe('TenantMcpSettingsPanel', () => {
  it('shows a disabled note when not editable', async () => {
    render(<TenantMcpSettingsPanel editable={false} tenantName="Acme" />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));

    expect(
      await screen.findByText(/Select Acme to edit MCP settings/i),
    ).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it('loads policy and catalog when expanded and editable', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));

    expect(
      await screen.findByText(/tools\/list always returns the full catalog/i),
    ).toBeInTheDocument();
    expect(await screen.findByText('ping')).toBeInTheDocument();
    expect(screen.getByText('spec.list')).toBeInTheDocument();

    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/api/tenants/mcp-policy') && c.method === 'GET')).toBe(
        true,
      );
      expect(calls.some((c) => c.url.includes('/api/api-keys/mcp-tools') && c.method === 'GET')).toBe(
        true,
      );
    });
  });

  it('saves dirty changes via PUT', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));
    expect(await screen.findByText('ping')).toBeInTheDocument();

    const anon = screen.getByLabelText(/Allow anonymous MCP calls/i);
    fireEvent.click(anon);

    const save = await screen.findByRole('button', { name: /^Save$/i });
    fireEvent.click(save);

    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/api/tenants/mcp-policy'));
      expect(put).toBeTruthy();
      expect(put?.body).toMatchObject({
        default_mode: 'all',
        allow_anonymous_mcp: false,
      });
      expect(Array.isArray((put?.body as { tools: unknown[] }).tools)).toBe(true);
    });
  });
});
