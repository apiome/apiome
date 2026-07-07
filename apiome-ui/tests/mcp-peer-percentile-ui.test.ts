/**
 * Unit tests for the peer percentile & category ranking pure helpers (V2-MCP-32.3 / MCAT-18.3).
 *
 * Exercises `mcpPeerPercentileUi` in isolation (no React): the defensive parser (re-derived
 * availability, gaps never rendered as ranks, `rankedCount` re-derived from the axes), the standing
 * bands, and the badge / category label projections the panel renders.
 */

import {
  mcpPeerPercentileFromPayload,
  mcpPeerBand,
  mcpPeerBadgeLabel,
  mcpPeerCategoryLabel,
  MCP_PEER_BAND_TONE,
  type McpPeerAxis,
} from '../src/app/components/ade/dashboard/mcp/mcpPeerPercentileUi';

function axisPayload(extra: Record<string, unknown> = {}) {
  return {
    key: 'documentation',
    label: 'Documentation',
    value: 70,
    percentile: 92,
    rank: 1,
    top_percent: 10,
    cohort_size: 8,
    available: true,
    detail: 'Rank 1 of 8 · top 10%',
    ...extra,
  };
}

function payload(extra: Record<string, unknown> = {}) {
  return {
    success: true,
    endpoint_id: 'ep-1',
    profile: {
      category: 'finance',
      cohort_size: 8,
      axes: [axisPayload()],
      ...extra,
    },
  };
}

describe('mcpPeerPercentileFromPayload', () => {
  it('parses a populated profile and re-derives rankedCount', () => {
    const profile = mcpPeerPercentileFromPayload(payload())!;
    expect(profile.category).toBe('finance');
    expect(profile.cohortSize).toBe(8);
    expect(profile.rankedCount).toBe(1);
    const axis = profile.axes[0];
    expect(axis.key).toBe('documentation');
    expect(axis.value).toBe(70);
    expect(axis.percentile).toBe(92);
    expect(axis.rank).toBe(1);
    expect(axis.topPercent).toBe(10);
    expect(axis.available).toBe(true);
  });

  it('treats an axis with available:false as a gap and nulls its ranked fields', () => {
    const profile = mcpPeerPercentileFromPayload(
      payload({
        axes: [
          axisPayload({ key: 'latency', label: 'Latency', available: false, value: null, percentile: null, cohort_size: 3 }),
        ],
      }),
    )!;
    const axis = profile.axes[0];
    expect(axis.available).toBe(false);
    expect(axis.value).toBeNull();
    expect(axis.percentile).toBeNull();
    expect(axis.rank).toBeNull();
    expect(axis.topPercent).toBeNull();
    // the cohort_size (peers that DO have the axis) is still preserved.
    expect(axis.cohortSize).toBe(3);
    expect(profile.rankedCount).toBe(0);
  });

  it('re-derives a gap when the wire says available but the value is missing', () => {
    const profile = mcpPeerPercentileFromPayload(
      payload({ axes: [axisPayload({ available: true, value: null })] }),
    )!;
    expect(profile.axes[0].available).toBe(false);
    expect(profile.axes[0].percentile).toBeNull();
  });

  it('drops malformed axes without a key', () => {
    const profile = mcpPeerPercentileFromPayload(
      payload({ axes: [axisPayload(), { label: 'no key' }] }),
    )!;
    expect(profile.axes).toHaveLength(1);
  });

  it('returns null when the payload has no profile', () => {
    expect(mcpPeerPercentileFromPayload({ success: true })).toBeNull();
    expect(mcpPeerPercentileFromPayload(null)).toBeNull();
    expect(mcpPeerPercentileFromPayload({ profile: 'nope' })).toBeNull();
  });

  it('preserves a null (uncategorized) category', () => {
    const profile = mcpPeerPercentileFromPayload(payload({ category: null }))!;
    expect(profile.category).toBeNull();
  });
});

function axis(extra: Partial<McpPeerAxis> = {}): McpPeerAxis {
  return {
    key: 'documentation',
    label: 'Documentation',
    value: 70,
    percentile: 92,
    rank: 1,
    topPercent: 10,
    cohortSize: 8,
    available: true,
    detail: '',
    ...extra,
  };
}

describe('mcpPeerBand', () => {
  it('bands by the "top N%" standing', () => {
    expect(mcpPeerBand(axis({ topPercent: 10 }))).toBe('leading');
    expect(mcpPeerBand(axis({ topPercent: 25 }))).toBe('strong');
    expect(mcpPeerBand(axis({ topPercent: 50 }))).toBe('middle');
    expect(mcpPeerBand(axis({ topPercent: 80 }))).toBe('trailing');
  });

  it('is a gap for an unavailable axis', () => {
    expect(mcpPeerBand(axis({ available: false, topPercent: null }))).toBe('gap');
  });

  it('maps every band to a badge tone', () => {
    for (const band of ['leading', 'strong', 'middle', 'trailing', 'gap'] as const) {
      expect(MCP_PEER_BAND_TONE[band]).toBeTruthy();
    }
  });
});

describe('mcpPeerBadgeLabel', () => {
  it('renders "Top N%" for a ranked axis', () => {
    expect(mcpPeerBadgeLabel(axis({ topPercent: 10 }))).toBe('Top 10%');
  });

  it('calls out a single-member category explicitly', () => {
    expect(mcpPeerBadgeLabel(axis({ cohortSize: 1, topPercent: 100 }))).toBe('Only in category');
  });

  it('is null for a gap (the panel renders "Not ranked")', () => {
    expect(mcpPeerBadgeLabel(axis({ available: false, topPercent: null }))).toBeNull();
  });
});

describe('mcpPeerCategoryLabel', () => {
  it('passes a real category through', () => {
    expect(mcpPeerCategoryLabel('finance')).toBe('finance');
  });

  it('names the uncategorized cohort', () => {
    expect(mcpPeerCategoryLabel(null)).toBe('uncategorized servers');
    expect(mcpPeerCategoryLabel('   ')).toBe('uncategorized servers');
  });
});
