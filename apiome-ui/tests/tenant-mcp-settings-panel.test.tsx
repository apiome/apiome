/**
 * Tenant MCP Settings panel — MTG-4.1 (#4780) / MTG-4.2 (#4781).
 */

import React from 'react';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
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
    if (url.includes('/api/tenants/mcp-keys') && method === 'GET' && !url.includes('/capabilities')) {
      return jsonResponse({ success: true, data: { keys: [] } });
    }
    if (url.includes('/capabilities/preview') && method === 'POST') {
      return jsonResponse({ success: true, data: { tools: [] } });
    }
    if (url.includes('/capabilities') && method === 'PUT') {
      return jsonResponse({
        success: true,
        data: { mode: 'inherit', enabled_tools: [] },
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
  it('shows Style Guides admin-only copy when not editable', async () => {
    render(<TenantMcpSettingsPanel editable={false} tenantName="Acme" />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));

    expect(
      await screen.findByText(/Only tenant administrators can change MCP tool policy/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Select Acme as your current tenant/i)).toBeInTheDocument();
    expect(calls).toHaveLength(0);
  });

  it('loads policy and catalog when expanded and editable', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));

    expect(
      await screen.findByText(/tools\/list always returns the full catalog/i),
    ).toBeInTheDocument();
    expect(await screen.findByRole('switch', { name: /Enable health toolset/i })).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /Enable catalog toolset/i })).toBeInTheDocument();

    await waitFor(() => {
      expect(calls.some((c) => c.url.includes('/api/tenants/mcp-policy') && c.method === 'GET')).toBe(
        true,
      );
      expect(calls.some((c) => c.url.includes('/api/api-keys/mcp-tools') && c.method === 'GET')).toBe(
        true,
      );
    });
  });

  it('master toolset switch toggles children and save persists via PUT', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));
    const health = await screen.findByRole('switch', { name: /Enable health toolset/i });
    expect(health).toBeChecked();

    fireEvent.click(health);
    expect(health).not.toBeChecked();

    const save = await screen.findByRole('button', { name: /Save changes/i });
    fireEvent.click(save);

    await waitFor(() => {
      const put = calls.find((c) => c.method === 'PUT' && c.url.includes('/api/tenants/mcp-policy'));
      expect(put).toBeTruthy();
      const tools = (put?.body as { tools: Array<{ tool_id: string; in_ceiling: boolean }> }).tools;
      expect(tools.find((t) => t.tool_id === 'ping')).toMatchObject({
        tool_id: 'ping',
        in_ceiling: false,
      });
      expect(tools.find((t) => t.tool_id === 'spec.list')).toMatchObject({
        tool_id: 'spec.list',
        in_ceiling: true,
      });
    });
  });

  it('shows individual tools in advanced view', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));
    expect(await screen.findByRole('switch', { name: /Enable health toolset/i })).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText(/Advanced: individual tools/i));

    expect(await screen.findByText('ping')).toBeInTheDocument();
    expect(screen.getByText('spec.list')).toBeInTheDocument();
    expect(screen.getByRole('switch', { name: /ping in ceiling/i })).toBeChecked();

    const healthSection = screen.getByRole('region', { name: /health toolset/i });
    expect(within(healthSection).getByText('Health check')).toBeInTheDocument();
  });

  it('shows dirty-state save bar and discards changes', async () => {
    render(<TenantMcpSettingsPanel editable />);

    fireEvent.click(screen.getByRole('button', { name: /MCP Settings/i }));
    const anon = await screen.findByRole('switch', { name: /Allow anonymous MCP calls/i });
    fireEvent.click(anon);

    expect(await screen.findByText(/Unsaved MCP settings changes/i)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /^Discard$/i }));

    await waitFor(() => {
      expect(screen.queryByText(/Unsaved MCP settings changes/i)).not.toBeInTheDocument();
    });
    expect(screen.getByRole('switch', { name: /Allow anonymous MCP calls/i })).toBeChecked();
  });
});
