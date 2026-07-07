/**
 * Render/interaction tests for the Capability presence-matrix panel (V2-MCP-30.2 / MCAT-16.2).
 *
 * Covers the acceptance criteria that live in the component (the pure projection is unit-tested in
 * `mcp-presence-matrix-ui.test.ts`): loading / error / empty states; the headline metrics; a row per
 * distinct capability with its lifespan badge; a clickable version-column header that deep-links to
 * that snapshot's diff via `onSelectVersion`; and the four-state legend.
 */
import React from 'react';
import { render, screen, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { CapabilityPresenceMatrixPanel } from '../src/app/components/ui/mcp/CapabilityPresenceMatrixPanel';
import type { McpCapabilityItem, McpVersionDetail } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';

function item(overrides: Partial<McpCapabilityItem> = {}): McpCapabilityItem {
  return {
    item_type: overrides.item_type ?? 'tool',
    name: overrides.name ?? 'search',
    title: overrides.title ?? null,
    description: overrides.description ?? null,
    uri: overrides.uri ?? null,
    uri_template: overrides.uri_template ?? null,
    input_schema: overrides.input_schema ?? null,
    output_schema: overrides.output_schema ?? null,
    annotations: overrides.annotations ?? null,
    ordinal: overrides.ordinal ?? 0,
  };
}

function version(overrides: Partial<McpVersionDetail> = {}): McpVersionDetail {
  return {
    id: overrides.id ?? 'ver-1',
    version_seq: overrides.version_seq ?? 1,
    version_tag: overrides.version_tag ?? null,
    server_name: null,
    server_version: null,
    server_title: null,
    protocol_version: null,
    instructions: null,
    score: null,
    grade: null,
    is_current: overrides.is_current ?? false,
    discovered_at: overrides.discovered_at ?? null,
    items: overrides.items ?? [],
  };
}

const VERSIONS: McpVersionDetail[] = [
  version({ id: 'v1', version_seq: 1, items: [item({ name: 'alpha' }), item({ name: 'beta' })] }),
  version({ id: 'v2', version_seq: 2, items: [item({ name: 'alpha' })] }),
  version({
    id: 'v3',
    version_seq: 3,
    is_current: true,
    items: [item({ name: 'alpha' }), item({ name: 'gamma' })],
  }),
];

/** The clickable header button for a version column, matched by its deep-link call to action. */
function columnHeader(seq: string) {
  return screen.getByRole('button', { name: new RegExp(`${seq}.*open this snapshot's diff`) });
}

describe('CapabilityPresenceMatrixPanel', () => {
  it('shows a loading state before the snapshots arrive', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={null} loading error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText(/Loading presence matrix/i)).toBeInTheDocument();
  });

  it('shows an error state (not a crash) on failure', () => {
    render(
      <CapabilityPresenceMatrixPanel
        versions={null}
        loading={false}
        error="snapshots unreachable"
        onSelectVersion={jest.fn()}
      />,
    );
    expect(screen.getByText('Presence matrix unavailable')).toBeInTheDocument();
    expect(screen.getByText('snapshots unreachable')).toBeInTheDocument();
  });

  it('shows an empty state when there are no capabilities to chart', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={[]} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText('No capabilities to chart')).toBeInTheDocument();
  });

  it('renders the headline metrics, a column per snapshot, and a row per capability', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={VERSIONS} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    // Column headers (one per snapshot), the current one flagged.
    expect(columnHeader('v1')).toBeInTheDocument();
    expect(columnHeader('v2')).toBeInTheDocument();
    expect(columnHeader('v3')).toBeInTheDocument();
    expect(within(columnHeader('v3')).getByText(/current/i)).toBeInTheDocument();
    // Rows for each capability (row-header cells).
    expect(screen.getByRole('rowheader', { name: /alpha/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /beta/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /gamma/ })).toBeInTheDocument();
  });

  it('badges each capability with its lifespan', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={VERSIONS} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    // alpha present throughout → Stable; beta gone by current → Removed; gamma first seen at current → New.
    expect(within(screen.getByRole('rowheader', { name: /alpha/ })).getByText('Stable')).toBeInTheDocument();
    expect(within(screen.getByRole('rowheader', { name: /beta/ })).getByText('Removed')).toBeInTheDocument();
    expect(within(screen.getByRole('rowheader', { name: /gamma/ })).getByText('New')).toBeInTheDocument();
  });

  it('deep-links a clicked column header to that snapshot’s version id', () => {
    const onSelect = jest.fn();
    render(
      <CapabilityPresenceMatrixPanel versions={VERSIONS} loading={false} error={null} onSelectVersion={onSelect} />,
    );
    fireEvent.click(columnHeader('v2'));
    expect(onSelect).toHaveBeenCalledWith('v2');
  });

  it('exposes each cell’s state to assistive tech (added / present / absent)', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={VERSIONS} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    // alpha: added in v1, present in v2/v3.
    expect(screen.getByRole('img', { name: 'alpha in v1: added' })).toBeInTheDocument();
    expect(screen.getByRole('img', { name: 'alpha in v2: present' })).toBeInTheDocument();
    // beta: added in v1, absent afterwards.
    expect(screen.getByRole('img', { name: 'beta in v2: absent' })).toBeInTheDocument();
    // gamma: absent until it appears at v3.
    expect(screen.getByRole('img', { name: 'gamma in v3: added' })).toBeInTheDocument();
  });

  it('renders the four-state legend', () => {
    render(
      <CapabilityPresenceMatrixPanel versions={VERSIONS} loading={false} error={null} onSelectVersion={jest.fn()} />,
    );
    expect(screen.getByText('Added')).toBeInTheDocument();
    expect(screen.getByText('Present')).toBeInTheDocument();
    expect(screen.getByText('Modified')).toBeInTheDocument();
    expect(screen.getByText('Absent')).toBeInTheDocument();
  });
});
