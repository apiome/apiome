/**
 * Render tests for the DocCoveragePanel (V2-MCP-29.5 / MCAT-15.5).
 *
 * Covers the loading / error / no-capability states, the four coverage gauges with their
 * percentages and counts, the drill-down of under-documented items (and the params tally), the
 * "all documented" state at 100%, and the not-applicable (N/A) meters for a tool-less server.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { DocCoveragePanel } from '../src/app/components/ui/mcp/DocCoveragePanel';
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

function item(overrides: Partial<McpCapabilityItem>): McpCapabilityItem {
  return {
    item_type: 'tool',
    name: 'thing',
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    ...overrides,
  };
}

/** A tool with two params, one documented, so the params meter sits at a partial percentage. */
function partlyDocumentedTool(name: string, extra: Partial<McpCapabilityItem> = {}): McpCapabilityItem {
  return item({
    item_type: 'tool',
    name,
    input_schema: {
      type: 'object',
      properties: { q: { type: 'string', description: 'query' }, limit: { type: 'number' } },
    },
    ...extra,
  });
}

describe('DocCoveragePanel', () => {
  it('shows a loading state while items have not arrived', () => {
    render(<DocCoveragePanel items={null} loading error={null} />);
    expect(screen.getByText('Loading documentation coverage…')).toBeInTheDocument();
  });

  it('shows an error state without blanking', () => {
    render(<DocCoveragePanel items={null} loading={false} error="metrics down" />);
    expect(screen.getByText('Coverage unavailable')).toBeInTheDocument();
    expect(screen.getByText('metrics down')).toBeInTheDocument();
  });

  it('renders nothing before a surface is selected (items null, not loading, no error)', () => {
    const { container } = render(<DocCoveragePanel items={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a no-capability empty state for an empty surface', () => {
    render(<DocCoveragePanel items={[]} loading={false} error={null} />);
    expect(screen.getByText('No capabilities')).toBeInTheDocument();
  });

  it('renders all four gauges with their labels', () => {
    render(<DocCoveragePanel items={[partlyDocumentedTool('search')]} loading={false} error={null} />);
    expect(screen.getByText('Items described')).toBeInTheDocument();
    expect(screen.getByText('Items titled')).toBeInTheDocument();
    expect(screen.getByText('Tool params documented')).toBeInTheDocument();
    expect(screen.getByText('Tools with output schema')).toBeInTheDocument();
  });

  it('drills a meter down to the specific under-documented items', () => {
    const items = [
      item({ item_type: 'tool', name: 'search', description: 'finds things' }),
      item({ item_type: 'resource', name: 'undocumented_file', description: null }),
    ];
    render(<DocCoveragePanel items={items} loading={false} error={null} />);

    // Scope to the described meter's card (other meters can share the same count).
    const describedCard = screen.getByText('Items described').parentElement as HTMLElement;
    // The described meter is 1 / 2 → one under-documented item behind the summary.
    const summary = within(describedCard).getByText('1 under-documented →');
    const details = summary.closest('details') as HTMLElement;
    expect(within(details).getByText('undocumented_file')).toBeInTheDocument();
    // The documented item is not listed as an offender.
    expect(within(details).queryByText('search')).not.toBeInTheDocument();
  });

  it('shows the undocumented-parameter tally in the params drill-down', () => {
    render(<DocCoveragePanel items={[partlyDocumentedTool('search')]} loading={false} error={null} />);
    // One of two params documented → "1 of 2 undocumented" on the tool's drill-down row.
    expect(screen.getByText('1 of 2 undocumented')).toBeInTheDocument();
  });

  it('shows an "all documented" state for a fully documented meter', () => {
    const items = [
      item({
        item_type: 'tool',
        name: 'search',
        description: 'd',
        title: 't',
        output_schema: { type: 'object' },
        input_schema: { properties: { q: { type: 'string', description: 'query' } } },
      }),
    ];
    render(<DocCoveragePanel items={items} loading={false} error={null} />);
    // Every meter is at 100%, so each renders the "All documented" affordance.
    expect(screen.getAllByText('All documented')).toHaveLength(4);
    expect(screen.queryByText(/under-documented/)).not.toBeInTheDocument();
  });

  it('renders N/A for tool-level meters when the server has no tools', () => {
    const items = [item({ item_type: 'resource', name: 'file', description: 'd', title: 't' })];
    render(<DocCoveragePanel items={items} loading={false} error={null} />);
    // Params and output-schema have no denominator → an explicit N/A, not a red 0%.
    expect(
      screen.getByLabelText('Tool params documented: not applicable — no parameters'),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText('Tools with output schema: not applicable — no tools'),
    ).toBeInTheDocument();
  });

  it('renders 0% coverage as a measured gauge (not N/A) with every item drilled down', () => {
    const items = [
      item({ item_type: 'tool', name: 'a', description: null }),
      item({ item_type: 'tool', name: 'b', description: null }),
    ];
    render(<DocCoveragePanel items={items} loading={false} error={null} />);
    // The described gauge reads 0% and lists both items — distinct from the N/A state.
    const describedCard = screen.getByText('Items described').parentElement as HTMLElement;
    expect(within(describedCard).getByText('2 under-documented →')).toBeInTheDocument();
    expect(within(describedCard).getByText('0%')).toBeInTheDocument();
  });
});
