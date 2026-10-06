/**
 * Render tests for MCP section tabs — the catalog's views (Analytics, Capabilities, Compare) are
 * hidden until at least one server is in the catalog; Servers and Agent access (AGX-3.4, #4540)
 * are always offered.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';

const mockUsePathname = jest.fn<string, []>();
const mockUseSession = jest.fn<{ data: unknown }, []>();

jest.mock('next/navigation', () => ({
  usePathname: () => mockUsePathname(),
}));

jest.mock('@lib/auth/session-client', () => ({
  useAuthSession: () => mockUseSession(),
}));

jest.mock('next/link', () => ({
  __esModule: true,
  default: ({ href, children, ...rest }: { href: string; children: React.ReactNode }) => (
    <a href={href} {...rest}>
      {children}
    </a>
  ),
}));

import { McpSectionTabs } from '../src/app/components/ade/dashboard/mcp/McpSectionTabs';

describe('McpSectionTabs', () => {
  beforeEach(() => {
    mockUsePathname.mockReturnValue('/ade/dashboard/mcp');
    mockUseSession.mockReturnValue({
      data: { user: { current_tenant_id: 'tenant-1' } },
    });
    global.fetch = jest.fn();
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('offers only Servers and Agent access when hasServers is false', () => {
    render(<McpSectionTabs hasServers={false} />);
    expect(screen.getByRole('link', { name: 'Servers' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Agent access' })).toHaveAttribute(
      'href',
      '/ade/dashboard/mcp/agents',
    );
    expect(screen.queryByRole('link', { name: /Analytics/ })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Capabilities' })).toBeNull();
    expect(screen.queryByRole('link', { name: 'Compare' })).toBeNull();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('renders nothing without a workspace', () => {
    mockUseSession.mockReturnValue({ data: { user: {} } });
    const { container } = render(<McpSectionTabs />);
    expect(container).toBeEmptyDOMElement();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('marks Agent access, not Servers, as current on the agents route', () => {
    mockUsePathname.mockReturnValue('/ade/dashboard/mcp/agents');
    render(<McpSectionTabs hasServers />);
    expect(screen.getByRole('link', { name: 'Agent access' })).toHaveAttribute(
      'aria-current',
      'page',
    );
    expect(screen.getByRole('link', { name: 'Servers' })).not.toHaveAttribute('aria-current');
  });

  it('renders the section tabs when hasServers is true', () => {
    render(<McpSectionTabs hasServers />);
    const nav = screen.getByRole('navigation', { name: 'MCP Servers sections' });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Servers' })).toHaveAttribute(
      'href',
      '/ade/dashboard/mcp',
    );
    expect(screen.getByRole('link', { name: 'Capabilities' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Analytics/ })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Compare' })).toBeInTheDocument();
    expect(global.fetch).not.toHaveBeenCalled();
  });

  it('prints only the counts the caller knows, and marks Analytics as preview', () => {
    render(<McpSectionTabs hasServers counts={{ servers: 6, capabilities: 65 }} />);
    expect(screen.getByRole('link', { name: 'Servers 6' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Capabilities 65' })).toBeInTheDocument();
    // Compare has no figure this screen can know, so it draws no chip rather than a zero.
    expect(screen.getByRole('link', { name: 'Compare' })).toBeInTheDocument();
    // The maturity marker resolves through the shared vocabulary rather than a local palette.
    expect(screen.getByText('Preview')).toHaveAttribute('data-status', 'preview');
  });

  it('probes the browse catalog and hides the catalog views when empty', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({ groups: [] }),
    });

    render(<McpSectionTabs />);
    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledWith('/api/mcp/browse', { credentials: 'include' });
    });
    expect(screen.getByRole('link', { name: 'Agent access' })).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Compare' })).toBeNull();
  });

  it('probes the browse catalog and shows tabs when a server exists', async () => {
    (global.fetch as jest.Mock).mockResolvedValue({
      ok: true,
      json: async () => ({
        groups: [
          {
            host: 'mcp.example.com',
            endpoints: [{ id: 'ep-1', name: 'demo', slug: 'demo', host: 'mcp.example.com' }],
          },
        ],
      }),
    });

    render(<McpSectionTabs />);
    await waitFor(() => {
      expect(
        screen.getByRole('navigation', { name: 'MCP Servers sections' }),
      ).toBeInTheDocument();
    });
  });
});
