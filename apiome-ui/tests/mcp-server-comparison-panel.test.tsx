/**
 * Render tests for the side-by-side server comparison panel (V2-MCP-32.2 / MCAT-18.2).
 *
 * Covers the acceptance criteria that live in the component (the pure projections are unit-tested in
 * `mcp-server-compare-ui.test.ts`): the loading / error / too-few-selected states; that a populated
 * comparison renders each column header, every metric section, the capability-overlap presence matrix
 * and unique-tool lists; and that differing protocol versions surface a banner.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom';

import { ServerComparisonPanel } from '../src/app/components/ui/mcp/ServerComparisonPanel';
import type { McpCapabilityItem } from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import { mcpTrustProfileFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpTrustUi';
import { mcpToolReliabilityFromPayload } from '../src/app/components/ade/dashboard/mcp/mcpReliabilityUi';
import type { McpCompareServer } from '../src/app/components/ade/dashboard/mcp/mcpServerCompareUi';

function item(item_type: string, name: string, extra: Partial<McpCapabilityItem> = {}): McpCapabilityItem {
  return {
    item_type,
    name,
    title: null,
    description: null,
    uri: null,
    uri_template: null,
    input_schema: null,
    output_schema: null,
    annotations: null,
    ordinal: 0,
    ...extra,
  };
}

const TRUST = mcpTrustProfileFromPayload({
  version_id: 'v1',
  auth_type: 'bearer',
  profile: {
    axes: [
      { key: 'quality', label: 'Quality', value: 88, available: true, detail: '', methodology: '' },
      { key: 'safety', label: 'Safety', value: 72, available: true, detail: '', methodology: '' },
      { key: 'documentation', label: 'Docs', value: 64, available: true, detail: '', methodology: '' },
    ],
  },
});

const RELIABILITY = mcpToolReliabilityFromPayload({
  tools: {
    tools: [
      { tool_name: 'search', call_count: 100, error_count: 3, success_count: 97, latency: { count: 100, p50_ms: 200, p95_ms: 500, p99_ms: 800 } },
    ],
    window_days: 7,
  },
});

const ALPHA: McpCompareServer = {
  endpointId: 'A',
  endpointName: 'alpha-endpoint',
  displayName: 'Alpha Search',
  transport: 'streamable_http',
  category: 'retrieval',
  protocolVersion: '2025-06-18',
  grade: 'A',
  score: 92,
  authType: 'bearer',
  items: [item('tool', 'search'), item('tool', 'index')],
  trust: TRUST,
  reliability: RELIABILITY,
};

const BRAVO: McpCompareServer = {
  ...ALPHA,
  endpointId: 'B',
  endpointName: 'bravo-endpoint',
  displayName: 'Bravo Crawl',
  grade: 'C',
  score: 61,
  protocolVersion: '2025-03-26',
  items: [item('tool', 'search'), item('tool', 'crawl')],
  trust: null,
  reliability: null,
};

describe('ServerComparisonPanel', () => {
  it('shows the loading state while first comparing', () => {
    render(<ServerComparisonPanel servers={null} loading error={null} />);
    expect(screen.getByText(/comparing servers/i)).toBeInTheDocument();
  });

  it('shows the error state with the message', () => {
    render(<ServerComparisonPanel servers={null} loading={false} error="boom" />);
    expect(screen.getByText(/comparison unavailable/i)).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('prompts to pick more servers when fewer than two are selected', () => {
    render(<ServerComparisonPanel servers={[ALPHA]} loading={false} error={null} />);
    expect(screen.getByText(/select two or three servers/i)).toBeInTheDocument();
  });

  it('renders nothing when servers is null and not loading (no error)', () => {
    const { container } = render(<ServerComparisonPanel servers={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders both column headers and every metric section', () => {
    render(<ServerComparisonPanel servers={[ALPHA, BRAVO]} loading={false} error={null} />);
    // The display name heads the metric table and the overlap matrix, so it appears more than once.
    expect(screen.getAllByText('Alpha Search').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Bravo Crawl').length).toBeGreaterThan(0);
    for (const title of [
      'Surface',
      'Quality',
      'Safety posture',
      'Documentation coverage',
      'Tool latency & reliability',
      'Composite trust',
    ]) {
      // Some titles (e.g. "Quality") also occur as a trust-axis label, so assert at least one.
      expect(screen.getAllByText(title).length).toBeGreaterThan(0);
    }
  });

  it('flags differing protocol versions with a banner', () => {
    render(<ServerComparisonPanel servers={[ALPHA, BRAVO]} loading={false} error={null} />);
    expect(screen.getByText(/protocol versions differ/i)).toBeInTheDocument();
  });

  it('renders the capability-overlap presence matrix and unique tools', () => {
    render(<ServerComparisonPanel servers={[ALPHA, BRAVO]} loading={false} error={null} />);
    expect(screen.getByText('Capability overlap')).toBeInTheDocument();
    // `search` is shared → it appears in the presence matrix.
    expect(screen.getByText('search')).toBeInTheDocument();
    // Each server's unique tool is listed under its own heading.
    expect(screen.getByText(/unique to alpha search/i)).toBeInTheDocument();
    expect(screen.getByText('index')).toBeInTheDocument();
    expect(screen.getByText(/unique to bravo crawl/i)).toBeInTheDocument();
    expect(screen.getByText('crawl')).toBeInTheDocument();
  });

  it('renders a trust radar for a server with a profile and a fallback otherwise', () => {
    render(<ServerComparisonPanel servers={[ALPHA, BRAVO]} loading={false} error={null} />);
    // Alpha has a trust profile → an accessible radar figure names it.
    expect(screen.getByRole('img', { name: /trust radar — alpha search/i })).toBeInTheDocument();
    // Bravo has none → the explicit "Not measured" fallback.
    expect(screen.getByText(/not measured/i)).toBeInTheDocument();
  });

  it('shows a compatible-protocol note when versions match but one is unknown', () => {
    const unknownProtocol: McpCompareServer = { ...BRAVO, protocolVersion: null, grade: 'A', score: 92 };
    render(<ServerComparisonPanel servers={[ALPHA, unknownProtocol]} loading={false} error={null} />);
    expect(screen.queryByText(/protocol versions differ/i)).not.toBeInTheDocument();
    expect(screen.getByText(/protocol version is unknown/i)).toBeInTheDocument();
  });

  it('scopes the shared-tool checkmarks to the servers that expose the tool', () => {
    render(<ServerComparisonPanel servers={[ALPHA, BRAVO]} loading={false} error={null} />);
    const sharedRow = screen.getByText('search').closest('tr')!;
    // Both servers expose `search`, so both cells are marked present.
    expect(within(sharedRow).getAllByLabelText('present')).toHaveLength(2);
  });
});
