import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { McpCatalogCard } from '../src/app/components/ade/dashboard/mcp/McpCatalogCard';
import { mcpBrowseEndpointFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

const HREF = '/ade/dashboard/mcp/ep-1';

function endpoint(overrides: Record<string, unknown> = {}) {
  return mcpBrowseEndpointFromPayload({
    id: 'ep-1',
    name: 'Acme Search',
    host: 'mcp.acme.dev',
    endpoint_url: 'https://mcp.acme.dev/search',
    transport: 'streamable_http',
    visibility: 'private',
    grade: 'A',
    score: 92,
    ...overrides,
  });
}

describe('McpCatalogCard freshness badge', () => {
  it('shows no freshness badge for healthy endpoints', () => {
    render(<McpCatalogCard href={HREF} endpoint={endpoint({ freshness: 'fresh' })} />);
    expect(screen.queryByText('Stale')).not.toBeInTheDocument();
    expect(screen.queryByText('Failing')).not.toBeInTheDocument();
  });

  it('shows a stale badge when the endpoint is past cadence', () => {
    render(
      <McpCatalogCard
        href={HREF}
        endpoint={endpoint({
          freshness: 'stale',
          last_known_good_at: '2026-07-06T10:00:00Z',
        })}
      />,
    );
    expect(screen.getByText('Stale')).toBeInTheDocument();
  });

  it('shows a failing badge when discovery is failing', () => {
    render(<McpCatalogCard href={HREF} endpoint={endpoint({ freshness: 'failing' })} />);
    expect(screen.getByText('Failing')).toBeInTheDocument();
  });
});
