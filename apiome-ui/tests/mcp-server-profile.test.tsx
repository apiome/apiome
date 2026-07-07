/**
 * Render tests for the MCP <ServerProfileCard> identity header (V2-MCP-29.1 / MCAT-15.1, #4631).
 *
 * Covers the acceptance criteria: a fully-populated card for a discovered endpoint, graceful
 * degradation for an older (2025-03-26) server missing title/protocol, an unscored/never-discovered
 * endpoint, the instructions block only when present, and the trust snapshot's link to 17.4.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ServerProfileCard } from '../src/app/components/ui/mcp/ServerProfileCard';
import type { McpServerProfile } from '../src/app/components/ade/dashboard/mcp/mcpInsightUi';

const NOW = Date.parse('2026-07-06T12:00:00Z');

const FULL: McpServerProfile = {
  displayName: 'Acme Search',
  endpointName: 'acme-search-prod',
  endpointUrl: 'https://mcp.acme.dev/search',
  serverVersion: '1.4.0',
  protocolVersion: '2025-06-18',
  transport: 'streamable_http',
  versionSeq: 7,
  versionTag: '2026-07-06',
  isCurrent: true,
  score: 92,
  grade: 'A',
  capabilityCounts: { tools: 8, resources: 3, resource_templates: 1, prompts: 2, total: 14 },
  discoveryStatus: 'changed',
  lastChangedAt: '2026-07-06T10:00:00Z',
  instructions: 'Use search for queries.',
};

describe('ServerProfileCard', () => {
  it('renders a fully-populated card for a discovered endpoint', () => {
    render(<ServerProfileCard profile={FULL} trustHref="#insight-reliability" nowMs={NOW} />);

    // Identity: server title as the headline, catalog name subtitle, url, and self-reported version.
    expect(screen.getByRole('heading', { name: /Acme Search/ })).toBeInTheDocument();
    expect(screen.getByText('acme-search-prod')).toBeInTheDocument();
    expect(screen.getByText('https://mcp.acme.dev/search')).toBeInTheDocument();
    expect(screen.getByText('1.4.0')).toBeInTheDocument();

    // Protocol + transport chips and the current-snapshot chip.
    expect(screen.getByText('MCP 2025-06-18')).toBeInTheDocument();
    expect(screen.getByText('streamable_http')).toBeInTheDocument();
    expect(screen.getByText('v7 · current')).toBeInTheDocument();

    // Grade glyph exposes the grade + score to assistive tech.
    expect(screen.getByRole('img', { name: /Grade A, score 92 of 100/ })).toBeInTheDocument();

    // Health pill (from status 'changed' → Healthy) and the surface-changed recency.
    expect(screen.getByText('Healthy')).toBeInTheDocument();
    expect(screen.getByText(/Surface changed/)).toBeInTheDocument();

    // Capability counts.
    expect(screen.getByText('14')).toBeInTheDocument();
    expect(screen.getByText('tools')).toBeInTheDocument();

    // Instructions rendered prominently.
    const instructions = screen.getByRole('heading', { name: 'Instructions' });
    expect(instructions).toBeInTheDocument();
    expect(screen.getByText('Use search for queries.')).toBeInTheDocument();

    // Trust snapshot links to the composite trust radar (17.4).
    const trustLink = screen.getByRole('link', { name: /Composite trust radar/ });
    expect(trustLink).toHaveAttribute('href', '#insight-reliability');
  });

  it('degrades gracefully for an older server missing title/protocol', () => {
    const legacy: McpServerProfile = {
      ...FULL,
      displayName: 'legacy-notes',
      endpointName: 'legacy-notes',
      serverVersion: null,
      protocolVersion: null,
      transport: 'http+sse',
      isCurrent: false,
      instructions: null,
    };
    render(<ServerProfileCard profile={legacy} nowMs={NOW} />);

    expect(screen.getByRole('heading', { name: /legacy-notes/ })).toBeInTheDocument();
    // Missing protocol reads as an explicit note, not a broken chip.
    expect(screen.getByText('protocol unknown')).toBeInTheDocument();
    expect(screen.getByText('http+sse (legacy)')).toBeInTheDocument();
    // Historical snapshot chip (no "current").
    expect(screen.getByText('v7')).toBeInTheDocument();
    // No instructions block.
    expect(screen.queryByRole('heading', { name: 'Instructions' })).not.toBeInTheDocument();
    // Without a trustHref the snapshot is static text, not a link.
    expect(screen.queryByRole('link', { name: /Composite trust radar/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Composite trust radar coming soon/)).toBeInTheDocument();
  });

  it('handles an unscored, never-discovered endpoint', () => {
    const unscored: McpServerProfile = {
      displayName: 'staging-gateway',
      endpointName: 'staging-gateway',
      endpointUrl: 'https://staging.example.com/mcp',
      serverVersion: null,
      protocolVersion: null,
      transport: 'streamable_http',
      versionSeq: null,
      versionTag: null,
      isCurrent: false,
      score: null,
      grade: null,
      capabilityCounts: null,
      discoveryStatus: null,
      lastChangedAt: null,
      instructions: null,
    };
    render(<ServerProfileCard profile={unscored} nowMs={NOW} />);

    // Unscored → neutral grade glyph.
    expect(screen.getByRole('img', { name: 'Unscored' })).toBeInTheDocument();
    // Unknown health before the first discovery.
    expect(screen.getByText('Unknown')).toBeInTheDocument();
    // Never changed.
    expect(screen.getByText(/Surface changed never/)).toBeInTheDocument();
    // The trust snapshot shows an em-dash grade rather than crashing.
    const trust = screen.getByText('Trust').closest('div') as HTMLElement;
    expect(within(trust).getByText('—')).toBeInTheDocument();
  });
});
