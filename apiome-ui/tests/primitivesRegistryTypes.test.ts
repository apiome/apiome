import {
  countUnresolvedByNamespace,
  formatRelativeTime,
  sourceKindLabel,
} from '../src/app/ade/dashboard/primitives/primitivesRegistryTypes';

describe('primitivesRegistryTypes helpers', () => {
  it('countUnresolvedByNamespace aggregates by namespace path', () => {
    const counts = countUnresolvedByNamespace([
      { namespace: 'tenant/acme/v1/payments', unresolved_count: 2 },
      { namespace: 'tenant/acme/v1/payments', unresolved_count: 1 },
      { namespace: null, unresolved_count: 1 },
    ]);
    expect(counts['tenant/acme/v1/payments']).toBe(3);
    expect(counts['']).toBe(1);
  });

  it('formatRelativeTime returns human-readable deltas', () => {
    const fiveMinutesAgo = new Date(Date.now() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveMinutesAgo)).toBe('5 min ago');
    expect(formatRelativeTime(null)).toBe('');
  });

  it('sourceKindLabel maps known import kinds', () => {
    expect(sourceKindLabel('json-schema')).toBe('JSON Schema');
    expect(sourceKindLabel('type-def-bundle')).toBe('Type definitions');
    expect(sourceKindLabel('custom')).toBe('custom');
  });
});
