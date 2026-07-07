/**
 * Render tests for the MCP <McpCatalogCard> server logo (V2-MCP-34.2, #4656).
 *
 * The catalog card shows the server's advertised logo beside its name when the current snapshot
 * carries a usable icon, and falls back to the text-only card (no image) when none is advertised.
 * The logo is a *referenced* https URL rendered with `referrerPolicy="no-referrer"`.
 */
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

describe('McpCatalogCard branding logo', () => {
  it.each(['grid', 'list'] as const)('renders the advertised logo in the %s density', (density) => {
    const { container } = render(
      <McpCatalogCard
        density={density}
        href={HREF}
        endpoint={endpoint({
          server_branding: { icon_url: 'https://cdn.acme.dev/logo.png' },
        })}
      />,
    );
    // Decorative (alt=""), so it is queried structurally rather than by role.
    const logo = container.querySelector('img');
    expect(logo).not.toBeNull();
    expect(logo).toHaveAttribute('src', 'https://cdn.acme.dev/logo.png');
    expect(logo).toHaveAttribute('referrerpolicy', 'no-referrer');
    // The card is still a single link to the detail — the logo is decorative, not a nested anchor.
    expect(screen.getByRole('link', { name: /Open Acme Search/ })).toHaveAttribute('href', HREF);
  });

  it('renders no image when no branding is advertised (text-only fallback)', () => {
    const { container } = render(<McpCatalogCard href={HREF} endpoint={endpoint()} />);
    expect(container.querySelector('img')).toBeNull();
    expect(screen.getByText('Acme Search')).toBeInTheDocument();
  });
});
