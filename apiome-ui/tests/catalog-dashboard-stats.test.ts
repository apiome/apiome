/**
 * Unit tests for the Catalog stats-row metrics (MFI-24.1, #4081).
 *
 * Asserts each of the four metrics — cataloged items (active/disabled), average quality
 * (letter + score), formats represented (distinct count + sample), and converted-to-OpenAPI — from
 * a fixture list, including the soft-deleted-exclusion, empty-list and format-normalisation edges.
 */

import {
  computeCatalogStats,
  type CatalogStatsItem,
} from '@/app/utils/catalog-dashboard-stats';

function item(partial: Partial<CatalogStatsItem> = {}): CatalogStatsItem {
  return {
    enabled: true,
    deleted_at: null,
    qualityScore: null,
    sourceFormat: null,
    conversion: null,
    ...partial,
  };
}

describe('computeCatalogStats', () => {
  it('returns an empty-catalog baseline with no scored average', () => {
    const stats = computeCatalogStats([]);
    expect(stats.total).toBe(0);
    expect(stats.active).toBe(0);
    expect(stats.disabled).toBe(0);
    expect(stats.avgScore).toBeNull();
    expect(stats.avgGrade).toBeNull();
    expect(stats.avgTier).toBeNull();
    expect(stats.formatCount).toBe(0);
    expect(stats.sampleFormats).toEqual([]);
    expect(stats.converted).toBe(0);
  });

  it('counts cataloged items and splits active vs disabled (non-deleted only)', () => {
    const stats = computeCatalogStats([
      item({ enabled: true }),
      item({ enabled: true }),
      item({ enabled: false }),
      // Soft-deleted items are excluded from every headline metric.
      item({ enabled: true, deleted_at: '2026-06-01T00:00:00Z' }),
    ]);
    expect(stats.total).toBe(3);
    expect(stats.active).toBe(2);
    expect(stats.disabled).toBe(1);
  });

  it('averages quality across scored items and derives the letter grade', () => {
    const stats = computeCatalogStats([
      item({ qualityScore: 92 }),
      item({ qualityScore: 88 }),
      item({ qualityScore: null }), // unscored — ignored by the average
    ]);
    expect(stats.avgScore).toBe(90); // round((92 + 88) / 2)
    expect(stats.avgGrade).toBe('A'); // 90 -> A
    expect(stats.avgTier?.band).toBe('excellent');
  });

  it('rounds the average and grades a mid-band score', () => {
    const stats = computeCatalogStats([
      item({ qualityScore: 61 }),
      item({ qualityScore: 62 }),
      item({ qualityScore: 60 }),
    ]);
    expect(stats.avgScore).toBe(61);
    expect(stats.avgGrade).toBe('C'); // 50–69 band -> C
    expect(stats.avgTier?.band).toBe('fair');
  });

  it('excludes soft-deleted items from the quality average', () => {
    const stats = computeCatalogStats([
      item({ qualityScore: 80 }),
      item({ qualityScore: 10, deleted_at: '2026-06-01T00:00:00Z' }),
    ]);
    expect(stats.avgScore).toBe(80);
  });

  it('counts distinct formats and normalises version variants to one', () => {
    const stats = computeCatalogStats([
      item({ sourceFormat: 'graphql' }),
      item({ sourceFormat: 'grpc' }),
      item({ sourceFormat: 'asyncapi' }),
      // openapi30 / openapi31 collapse to a single "openapi" format.
      item({ sourceFormat: 'openapi30' }),
      item({ sourceFormat: 'openapi31' }),
      item({ sourceFormat: null }), // no format — not counted
    ]);
    expect(stats.formatCount).toBe(4);
    expect(stats.sampleFormats).toContain('GraphQL');
    expect(stats.sampleFormats).toContain('OpenAPI');
  });

  it('keeps an unrecognised-but-present format under its raw label', () => {
    const stats = computeCatalogStats([item({ sourceFormat: 'madeupfmt' })]);
    expect(stats.formatCount).toBe(1);
    expect(stats.sampleFormats).toEqual(['madeupfmt']);
  });

  it('caps the sample formats but keeps the full distinct count', () => {
    const stats = computeCatalogStats([
      item({ sourceFormat: 'graphql' }),
      item({ sourceFormat: 'grpc' }),
      item({ sourceFormat: 'asyncapi' }),
      item({ sourceFormat: 'odata' }),
      item({ sourceFormat: 'thrift' }),
      item({ sourceFormat: 'avro' }),
    ]);
    expect(stats.formatCount).toBe(6);
    expect(stats.sampleFormats).toHaveLength(4);
  });

  it('counts converted items (conversion present) among live items only', () => {
    const stats = computeCatalogStats([
      item({ conversion: { kind: 'grpc', project: 'Payments API' } }),
      item({ conversion: { kind: 'graphql', project: 'Catalog API' } }),
      item({ conversion: null }),
      // A deleted converted item does not count toward the live promotion-path metric.
      item({ conversion: { kind: 'asyncapi', project: 'Events' }, deleted_at: '2026-06-01T00:00:00Z' }),
    ]);
    expect(stats.converted).toBe(2);
  });
});
