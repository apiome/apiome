/**
 * Render tests for the SafetyPosturePanel (V2-MCP-29.4 / MCAT-15.4).
 *
 * Covers the loading / error / no-tools states, the posture headline + auth badge, the per-tool
 * hint matrix and its tri-state cells, the destructive+no-auth alert, and the fully-unannotated
 * caution state.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { SafetyPosturePanel } from '../src/app/components/ui/mcp/SafetyPosturePanel';
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

/** Build a `tool` capability item with the given name and raw annotations object. */
function tool(name: string, annotations: Record<string, unknown> | null): McpCapabilityItem {
  return {
    item_type: 'tool',
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations,
    ordinal: 0,
  };
}

const MIXED: McpCapabilityItem[] = [
  tool('search', { readOnlyHint: true, destructiveHint: false }),
  tool('delete_record', { destructiveHint: true, openWorldHint: true }),
];

describe('SafetyPosturePanel', () => {
  it('shows a loading state while items have not arrived', () => {
    render(<SafetyPosturePanel items={null} authType={null} loading error={null} />);
    expect(screen.getByText('Loading safety posture…')).toBeInTheDocument();
  });

  it('shows an error state without blanking', () => {
    render(
      <SafetyPosturePanel items={null} authType={null} loading={false} error="metrics down" />,
    );
    expect(screen.getByText('Safety posture unavailable')).toBeInTheDocument();
    expect(screen.getByText('metrics down')).toBeInTheDocument();
  });

  it('renders nothing before a surface is selected (items null, not loading, no error)', () => {
    const { container } = render(
      <SafetyPosturePanel items={null} authType={null} loading={false} error={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows a no-tools empty state for a surface with no tools', () => {
    render(<SafetyPosturePanel items={[]} authType="bearer" loading={false} error={null} />);
    expect(screen.getByText('No tools')).toBeInTheDocument();
  });

  it('renders the posture headline, auth badge, and a matrix row per tool', () => {
    render(<SafetyPosturePanel items={MIXED} authType="bearer" loading={false} error={null} />);

    // Headline: annotated tally + per-hint chips + auth badge.
    expect(screen.getByText('2 of 2 tools annotated')).toBeInTheDocument();
    expect(screen.getByText('1 destructive')).toBeInTheDocument();
    expect(screen.getByText('1 open-world')).toBeInTheDocument();
    expect(screen.getByText('1 read-only')).toBeInTheDocument();
    expect(screen.getByText('bearer')).toBeInTheDocument();

    // One matrix row header (scope="row") per tool.
    expect(screen.getByRole('rowheader', { name: /search/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /delete_record/ })).toBeInTheDocument();
  });

  it('paints each cell as asserted / declared false / not declared via aria-labels', () => {
    render(<SafetyPosturePanel items={MIXED} authType="bearer" loading={false} error={null} />);

    const searchRow = screen.getByRole('rowheader', { name: /search/ }).closest('tr') as HTMLElement;
    const scoped = within(searchRow);
    // search: readOnly asserted, destructive explicitly false, idempotent/openWorld not declared.
    expect(scoped.getByLabelText('Read-only: asserted')).toBeInTheDocument();
    expect(scoped.getByLabelText('Destructive: declared false')).toBeInTheDocument();
    expect(scoped.getByLabelText('Idempotent: not declared')).toBeInTheDocument();
    expect(scoped.getByLabelText('Open-world: not declared')).toBeInTheDocument();
  });

  it('flags destructive tools reachable with no auth on an anonymous endpoint', () => {
    render(<SafetyPosturePanel items={MIXED} authType="none" loading={false} error={null} />);
    const alert = screen.getByRole('alert');
    expect(alert).toHaveTextContent('1 destructive tool reachable with no auth');
    expect(alert).toHaveTextContent('delete_record');
    // The read-only tool is not named in the alert.
    expect(within(alert).queryByText('search')).not.toBeInTheDocument();
  });

  it('does not flag destructive tools when the endpoint is authenticated', () => {
    render(<SafetyPosturePanel items={MIXED} authType="bearer" loading={false} error={null} />);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('shows an explicit unannotated caution when no tool declares a hint', () => {
    const bare: McpCapabilityItem[] = [tool('a', null), tool('b', {})];
    render(<SafetyPosturePanel items={bare} authType="bearer" loading={false} error={null} />);
    expect(screen.getByText('Unannotated — treat with caution')).toBeInTheDocument();
    // Every tool row is marked unannotated.
    expect(screen.getAllByText('unannotated')).toHaveLength(2);
  });
});
