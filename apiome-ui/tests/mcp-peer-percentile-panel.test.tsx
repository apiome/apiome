/**
 * Render tests for the peer percentile & category ranking panel (V2-MCP-32.3 / MCAT-18.3).
 *
 * Covers the acceptance criteria that live in the component (the pure projections are unit-tested in
 * `mcp-peer-percentile-ui.test.ts`): loading / error / nothing-ranked states, that a populated profile
 * renders each axis's "top N%" badge and cohort context, that a single-member category is called out
 * explicitly, and that an unmeasured axis renders as a labelled gap rather than a rank.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom';

import { PeerPercentilePanel } from '../src/app/components/ui/mcp/PeerPercentilePanel';
import {
  mcpPeerPercentileFromPayload,
  type McpPeerPercentileProfile,
} from '../src/app/components/ade/dashboard/mcp/mcpPeerPercentileUi';

function axis(key: string, label: string, extra: Record<string, unknown> = {}) {
  return {
    key,
    label,
    value: 70,
    percentile: 92,
    rank: 1,
    top_percent: 10,
    cohort_size: 8,
    available: true,
    detail: `${label}: rank 1 of 8 · top 10%`,
    ...extra,
  };
}

const POPULATED: McpPeerPercentileProfile = mcpPeerPercentileFromPayload({
  profile: {
    category: 'finance',
    cohort_size: 8,
    axes: [
      axis('grade', 'Grade', { value: 88, top_percent: 25, detail: 'Rank 2 of 8 · top 25%' }),
      axis('safety', 'Safety', { value: 90, top_percent: 10 }),
      axis('documentation', 'Documentation', { value: 70, top_percent: 10 }),
      axis('latency', 'Latency', { available: false, value: null, percentile: null, rank: null, top_percent: null, cohort_size: 4, detail: 'Not measured' }),
    ],
  },
})!;

const SINGLE_MEMBER: McpPeerPercentileProfile = mcpPeerPercentileFromPayload({
  profile: {
    category: 'niche',
    cohort_size: 1,
    axes: [axis('grade', 'Grade', { top_percent: 100, cohort_size: 1, detail: 'Only server with a grade score in this category' })],
  },
})!;

const NOTHING_RANKED: McpPeerPercentileProfile = mcpPeerPercentileFromPayload({
  profile: {
    category: 'weather',
    cohort_size: 3,
    axes: [axis('grade', 'Grade', { available: false, value: null, percentile: null, top_percent: null })],
  },
})!;

describe('PeerPercentilePanel', () => {
  it('shows the loading state while first loading', () => {
    render(<PeerPercentilePanel profile={null} loading error={null} />);
    expect(screen.getByText(/loading peer ranking/i)).toBeInTheDocument();
  });

  it('shows the error state with the message', () => {
    render(<PeerPercentilePanel profile={null} loading={false} error="boom" />);
    expect(screen.getByText(/peer ranking unavailable/i)).toBeInTheDocument();
    expect(screen.getByText('boom')).toBeInTheDocument();
  });

  it('renders nothing when profile is null and not loading (no error)', () => {
    const { container } = render(<PeerPercentilePanel profile={null} loading={false} error={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the nothing-ranked empty state', () => {
    render(<PeerPercentilePanel profile={NOTHING_RANKED} loading={false} error={null} />);
    expect(screen.getByText(/not enough peers to rank yet/i)).toBeInTheDocument();
  });

  it('renders each axis with its "top N%" badge and cohort context', () => {
    render(<PeerPercentilePanel profile={POPULATED} loading={false} error={null} />);
    // Cohort context names the category and the peer count.
    expect(screen.getByText(/ranked against/i)).toBeInTheDocument();
    expect(screen.getByText('finance')).toBeInTheDocument();
    // Ranked axes render their standing badge.
    expect(screen.getByText('Grade')).toBeInTheDocument();
    expect(screen.getByText('Top 25%')).toBeInTheDocument();
    expect(screen.getAllByText('Top 10%').length).toBeGreaterThanOrEqual(2);
  });

  it('renders an unmeasured axis as a labelled gap, not a rank', () => {
    render(<PeerPercentilePanel profile={POPULATED} loading={false} error={null} />);
    expect(screen.getByText('Latency')).toBeInTheDocument();
    expect(screen.getByText('Not ranked')).toBeInTheDocument();
    // and the footnote explaining gaps appears.
    expect(screen.getByText(/unranked axes have no measurement/i)).toBeInTheDocument();
  });

  it('calls out a single-member category explicitly', () => {
    render(<PeerPercentilePanel profile={SINGLE_MEMBER} loading={false} error={null} />);
    expect(screen.getByText(/only server in the/i)).toBeInTheDocument();
    expect(screen.getByText('Only in category')).toBeInTheDocument();
  });
});
