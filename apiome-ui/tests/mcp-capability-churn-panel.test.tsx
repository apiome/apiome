/**
 * Render/interaction tests for the Capability churn timeline panel (V2-MCP-30.1 / MCAT-16.1).
 *
 * Covers the acceptance criteria that live in the component (the pure projection is unit-tested in
 * `mcp-evolution-ui.test.ts`): loading / error / no-history states; the legend + total-churn headline;
 * a clickable column per snapshot (including a zero-churn one) that deep-links to that version's diff
 * via `onSelectVersion`; keyboard activation of a column; and the busiest-release callout.
 */
import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom';

import { CapabilityChurnPanel } from '../src/app/components/ui/mcp/CapabilityChurnPanel';
import type { McpEvolutionPoint } from '../src/app/components/ade/dashboard/mcp/mcpEvolutionUi';

function point(overrides: Partial<McpEvolutionPoint> = {}): McpEvolutionPoint {
  return {
    version_id: overrides.version_id ?? 'v-1',
    version_seq: overrides.version_seq ?? 1,
    version_tag: overrides.version_tag ?? null,
    discovered_at: overrides.discovered_at ?? '2026-07-01T10:00:00Z',
    is_current: overrides.is_current ?? false,
    type_counts: overrides.type_counts ?? {
      tools: 2,
      resources: 1,
      resource_templates: 0,
      prompts: 0,
      total: 3,
    },
    score: overrides.score ?? 90,
    grade: overrides.grade ?? 'A',
    change_counts: overrides.change_counts ?? { added: 0, removed: 0, modified: 0, total: 0 },
  };
}

/**
 * The clickable column for a version, matched by its tag plus the column-only call to action — the
 * busiest-release callout shares the tag/date text, so this disambiguates the column from the callout.
 */
function columnButton(tag: string) {
  return screen.getByRole('button', { name: new RegExp(`${tag}.*Click to view the diff`) });
}

const SERIES: McpEvolutionPoint[] = [
  point({ version_id: 'a', version_seq: 1, version_tag: 'v1-tag', change_counts: { added: 4, removed: 0, modified: 0, total: 4 } }),
  // A quiet release — no churn, but still a column.
  point({ version_id: 'b', version_seq: 2, version_tag: 'v2-tag', change_counts: { added: 0, removed: 0, modified: 0, total: 0 } }),
  point({
    version_id: 'c',
    version_seq: 3,
    version_tag: 'v3-tag',
    is_current: true,
    change_counts: { added: 2, removed: 3, modified: 4, total: 9 },
  }),
];

describe('CapabilityChurnPanel', () => {
  it('shows a loading state before the series arrives', () => {
    render(
      <CapabilityChurnPanel series={null} loading error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText(/Loading churn timeline/i)).toBeInTheDocument();
  });

  it('shows an error state (not a crash) on failure', () => {
    render(
      <CapabilityChurnPanel
        series={null}
        loading={false}
        error="evolution engine down"
        onSelectVersion={jest.fn()}
      />,
    );
    expect(screen.getByText('Churn timeline unavailable')).toBeInTheDocument();
    expect(screen.getByText('evolution engine down')).toBeInTheDocument();
  });

  it('shows a no-history empty state for an endpoint with no snapshots', () => {
    render(
      <CapabilityChurnPanel series={[]} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText('No history yet')).toBeInTheDocument();
  });

  it('renders the legend, total-churn headline, and one interactive column per snapshot', () => {
    render(
      <CapabilityChurnPanel series={SERIES} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    // Legend bands (also appear as the chart's sr-only table headers, so allow multiple).
    expect(screen.getAllByText('Added').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Removed').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Modified').length).toBeGreaterThan(0);
    // Total churn = 4 + 0 + 9 = 13, across 3 snapshots.
    expect(screen.getByText('13')).toBeInTheDocument();
    // Three clickable columns — the zero-churn v2 included (role=button hit targets).
    expect(columnButton('v1-tag')).toBeInTheDocument();
    expect(columnButton('v2-tag')).toBeInTheDocument();
    expect(columnButton('v3-tag')).toBeInTheDocument();
  });

  it('keeps a zero-churn version clickable and deep-links it', () => {
    const onSelect = jest.fn();
    render(
      <CapabilityChurnPanel series={SERIES} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    fireEvent.click(columnButton('v2-tag'));
    expect(onSelect).toHaveBeenCalledWith('b');
  });

  it('deep-links the clicked column to its version id', () => {
    const onSelect = jest.fn();
    render(
      <CapabilityChurnPanel series={SERIES} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    fireEvent.click(columnButton('v3-tag'));
    expect(onSelect).toHaveBeenCalledWith('c');
  });

  it('activates a column from the keyboard (Enter)', () => {
    const onSelect = jest.fn();
    render(
      <CapabilityChurnPanel series={SERIES} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    fireEvent.keyDown(columnButton('v1-tag'), { key: 'Enter' });
    expect(onSelect).toHaveBeenCalledWith('a');
  });

  it('calls out the busiest release and deep-links it', () => {
    const onSelect = jest.fn();
    render(
      <CapabilityChurnPanel series={SERIES} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    // v3 is the busiest (9 changes).
    const callout = screen.getByRole('button', { name: /Busiest release/ });
    expect(callout).toHaveTextContent('v3');
    expect(callout).toHaveTextContent('9');
    fireEvent.click(callout);
    expect(onSelect).toHaveBeenCalledWith('c');
  });

  it('omits the busiest-release callout when every snapshot is churn-free', () => {
    const flat = [
      point({ version_id: 'a', version_seq: 1, version_tag: 'v1-tag' }),
      point({ version_id: 'b', version_seq: 2, version_tag: 'v2-tag' }),
    ];
    render(
      <CapabilityChurnPanel series={flat} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.queryByRole('button', { name: /Busiest release/ })).not.toBeInTheDocument();
  });
});
