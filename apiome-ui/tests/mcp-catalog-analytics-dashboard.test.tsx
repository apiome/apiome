/**
 * Render tests for the Catalog analytics dashboard (V2-MCP-32.1 / MCAT-18.1).
 *
 * Covers the acceptance criteria that live in the component (the pure projections are unit-tested in
 * `mcp-catalog-insight-ui.test.ts`): loading / error / empty-catalog states, and that a populated
 * catalog renders every tile — the stat row, the category / transport / grade mixes, the protocol /
 * tool-count / discovery distributions, the change-frequency leaders (linked to the endpoint), and
 * the top-capabilities leaderboard — all from a fixture built through the real parser.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { CatalogAnalyticsDashboard } from '../src/app/components/ui/mcp/CatalogAnalyticsDashboard';
import {
  mcpCatalogInsightFromPayload,
  type McpCatalogInsight,
} from '../src/app/components/ade/dashboard/mcp/mcpCatalogInsightUi';

const POPULATED: McpCatalogInsight = mcpCatalogInsightFromPayload({
  success: true,
  endpoint_count: 12,
  published_count: 7,
  public_count: 5,
  private_count: 7,
  discovered_count: 10,
  scored_count: 9,
  average_score: 78.4,
  type_counts: { tools: 84, resources: 22, resource_templates: 5, prompts: 8, total: 119 },
  grade_distribution: { A: 3, B: 4, C: 1, D: 1 },
  category_distribution: [
    { label: 'search', count: 4 },
    { label: 'Uncategorized', count: 2 },
  ],
  transport_distribution: [{ label: 'streamable_http', count: 8 }],
  protocol_version_distribution: [{ label: '2025-06-18', count: 6 }],
  tool_count_distribution: [
    { label: '0', count: 2 },
    { label: '1–5', count: 4 },
  ],
  discovery_health: [{ label: 'ok', count: 9 }],
  change_leaders: [{ endpoint_id: 'ep-1', name: 'Acme Search', change_count: 23 }],
  top_capabilities: [{ item_type: 'tool', item_name: 'vector_search', endpoint_count: 6 }],
})!;

const EMPTY: McpCatalogInsight = mcpCatalogInsightFromPayload({
  success: true,
  endpoint_count: 0,
  published_count: 0,
  public_count: 0,
  private_count: 0,
  discovered_count: 0,
  scored_count: 0,
  average_score: null,
  type_counts: { tools: 0, resources: 0, resource_templates: 0, prompts: 0, total: 0 },
  grade_distribution: {},
})!;

describe('CatalogAnalyticsDashboard', () => {
  it('shows the loading state while first loading', () => {
    render(<CatalogAnalyticsDashboard data={null} loading error={null} />);
    expect(screen.getByText(/loading catalog analytics/i)).toBeInTheDocument();
  });

  it('shows the error state with the message', () => {
    render(<CatalogAnalyticsDashboard data={null} loading={false} error="boom" />);
    expect(screen.getByText(/catalog analytics unavailable/i)).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('shows the empty-catalog first-run state', () => {
    render(<CatalogAnalyticsDashboard data={EMPTY} loading={false} error={null} />);
    expect(screen.getByText(/no servers in the catalog yet/i)).toBeInTheDocument();
  });

  it('renders the headline stat row from real aggregates', () => {
    render(<CatalogAnalyticsDashboard data={POPULATED} loading={false} error={null} />);
    expect(screen.getByText('Endpoints')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    // average score, rendered to one decimal.
    expect(screen.getByText('78.4')).toBeInTheDocument();
  });

  it('renders the composition tiles', () => {
    render(<CatalogAnalyticsDashboard data={POPULATED} loading={false} error={null} />);
    expect(screen.getByText('Category mix')).toBeInTheDocument();
    expect(screen.getByText('Transport mix')).toBeInTheDocument();
    expect(screen.getByText('Grade distribution')).toBeInTheDocument();
    expect(screen.getByText('Protocol version adoption')).toBeInTheDocument();
    expect(screen.getByText('Tool-count distribution')).toBeInTheDocument();
    expect(screen.getByText('Discovery health')).toBeInTheDocument();
  });

  it('links each change-frequency leader to its endpoint detail', () => {
    render(<CatalogAnalyticsDashboard data={POPULATED} loading={false} error={null} />);
    const link = screen.getByRole('link', { name: 'Acme Search' });
    expect(link).toHaveAttribute('href', '/ade/dashboard/mcp/ep-1');
    expect(screen.getByText(/23 changes/)).toBeInTheDocument();
  });

  it('renders the top-capabilities leaderboard', () => {
    render(<CatalogAnalyticsDashboard data={POPULATED} loading={false} error={null} />);
    expect(screen.getByText('Top capabilities')).toBeInTheDocument();
    expect(screen.getByText('vector_search')).toBeInTheDocument();
    expect(screen.getByText(/6 endpoints/)).toBeInTheDocument();
  });

  it('renders nothing when data is null and not loading (no error)', () => {
    const { container } = render(
      <CatalogAnalyticsDashboard data={null} loading={false} error={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
