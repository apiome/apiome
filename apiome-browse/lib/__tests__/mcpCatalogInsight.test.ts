/**
 * Unit tests for the public catalog-analytics presentation helpers (V2-MCP-32.1 / MCAT-18.1).
 *
 * These cover the shaping the public dashboard depends on without a database: empty detection,
 * whole-number percentages against an explicit or implicit total (never dividing by zero), and the
 * grade → display-tone classification.
 */

import { describe, expect, it } from 'vitest';

import {
  mcpCatalogBucketTotal,
  mcpCatalogBucketViews,
  mcpCatalogPercent,
  mcpPublicCatalogIsEmpty,
  mcpPublicGradeTone,
} from '../mcpCatalogInsight';
import type { McpPublicCatalogInsight } from '../types';

function insight(overrides: Partial<McpPublicCatalogInsight> = {}): McpPublicCatalogInsight {
  return {
    endpoint_count: 0,
    average_score: null,
    category_distribution: [],
    transport_distribution: [],
    grade_distribution: [],
    ...overrides,
  };
}

describe('mcpPublicCatalogIsEmpty', () => {
  it('is true for a catalog with no endpoints', () => {
    expect(mcpPublicCatalogIsEmpty(insight({ endpoint_count: 0 }))).toBe(true);
  });

  it('is false once the catalog has endpoints', () => {
    expect(mcpPublicCatalogIsEmpty(insight({ endpoint_count: 3 }))).toBe(false);
  });
});

describe('mcpCatalogPercent', () => {
  it('computes whole-number percentages', () => {
    expect(mcpCatalogPercent(3, 12)).toBe(25);
    expect(mcpCatalogPercent(1, 3)).toBe(33);
  });

  it('returns 0 rather than NaN when the total is zero or negative', () => {
    expect(mcpCatalogPercent(5, 0)).toBe(0);
    expect(mcpCatalogPercent(5, -2)).toBe(0);
  });
});

describe('mcpCatalogBucketViews', () => {
  it('shares each bucket against an explicit total', () => {
    const rows = mcpCatalogBucketViews(
      [
        { label: 'search', count: 4 },
        { label: 'data', count: 2 },
      ],
      8,
    );
    expect(rows).toEqual([
      { label: 'search', count: 4, percent: 50 },
      { label: 'data', count: 2, percent: 25 },
    ]);
  });

  it('falls back to the sum of the buckets when no total is given', () => {
    const rows = mcpCatalogBucketViews([
      { label: 'A', count: 3 },
      { label: 'B', count: 1 },
    ]);
    expect(rows.map((r) => r.percent)).toEqual([75, 25]);
  });

  it('preserves order and handles an empty breakdown', () => {
    expect(mcpCatalogBucketViews([])).toEqual([]);
  });
});

describe('mcpCatalogBucketTotal', () => {
  it('sums the bucket counts', () => {
    expect(
      mcpCatalogBucketTotal([
        { label: 'A', count: 3 },
        { label: 'B', count: 4 },
      ]),
    ).toBe(7);
    expect(mcpCatalogBucketTotal([])).toBe(0);
  });
});

describe('mcpPublicGradeTone', () => {
  it('classifies A/B as good, C as ok, and D-and-below as poor', () => {
    expect(mcpPublicGradeTone('A')).toBe('good');
    expect(mcpPublicGradeTone('b')).toBe('good');
    expect(mcpPublicGradeTone('C')).toBe('ok');
    expect(mcpPublicGradeTone('D')).toBe('poor');
    expect(mcpPublicGradeTone('F')).toBe('poor');
  });
});
