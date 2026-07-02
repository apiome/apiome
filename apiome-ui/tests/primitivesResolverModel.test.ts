import {
  REGISTRY_BASE_URL,
  collectNamespaces,
  deriveResolutionBase,
  emptyResolveResponse,
  filterResolverRows,
  flattenResolverEdges,
  isCrossScope,
  shortenTarget,
  sourceLabel,
  statusBadgeClass,
  statusLabel,
  summarizeStatuses,
  type ResolvedPrimitiveRefs,
} from '../src/app/ade/dashboard/primitives/primitivesResolverModel';

const PRIMITIVES: ResolvedPrimitiveRefs[] = [
  {
    id: 'p-date',
    name: 'date',
    namespace: 'std/v0/types',
    base_uri: 'https://api.apiome.app/types/std/v0/types/',
    ref_count: 1,
    resolved_count: 1,
    unresolved_count: 0,
    refs: [
      {
        relative_ref: '../primitives/string',
        resolved_target: 'https://api.apiome.app/types/std/v0/primitives/string',
        status: 'resolved',
        target_id: 'p-string',
        target_name: 'string',
      },
    ],
  },
  {
    id: 'p-charge',
    name: 'charge',
    namespace: 'tenant/acme/v1/payments',
    base_uri: 'https://api.apiome.app/types/tenant/acme/v1/payments/',
    ref_count: 2,
    resolved_count: 1,
    unresolved_count: 1,
    refs: [
      {
        relative_ref: '../../../std/v0/types/money',
        resolved_target: 'https://api.apiome.app/types/std/v0/types/money',
        status: 'resolved',
        target_id: 'p-money',
        target_name: 'money',
      },
      {
        relative_ref: './discount',
        resolved_target: 'https://api.apiome.app/types/tenant/acme/v1/payments/discount',
        status: 'unresolved',
        target_id: null,
        target_name: null,
      },
      // Malformed/legacy edge with no relative_ref — must be skipped.
      { relative_ref: null, resolved_target: null, status: 'unresolved' },
    ],
  },
];

describe('primitivesResolverModel', () => {
  it('sourceLabel joins namespace and name, falling back to bare name', () => {
    expect(sourceLabel({ name: 'date', namespace: 'std/v0/types' })).toBe('std/v0/types/date');
    expect(sourceLabel({ name: 'orphan', namespace: null })).toBe('orphan');
    expect(sourceLabel({ name: 'orphan', namespace: '  ' })).toBe('orphan');
  });

  it('shortenTarget strips the registry base, leaving already-relative targets alone', () => {
    expect(shortenTarget(`${REGISTRY_BASE_URL}std/v0/primitives/string`)).toBe(
      'std/v0/primitives/string'
    );
    expect(shortenTarget('std/v0/types/decimal')).toBe('std/v0/types/decimal');
    expect(shortenTarget(null)).toBe('');
  });

  it('deriveResolutionBase reads the registry root from a base URI, else falls back', () => {
    expect(deriveResolutionBase(PRIMITIVES)).toBe(REGISTRY_BASE_URL);
    expect(deriveResolutionBase([])).toBe(REGISTRY_BASE_URL);
    expect(
      deriveResolutionBase([{ ...PRIMITIVES[0], base_uri: null }])
    ).toBe(REGISTRY_BASE_URL);
  });

  it('isCrossScope flags tenant → core (std) edges only', () => {
    expect(isCrossScope('tenant/acme/v1/payments', 'std/v0/types/money')).toBe(true);
    expect(isCrossScope('std/v0/types', 'std/v0/primitives/string')).toBe(false);
    expect(isCrossScope('tenant/acme/v1/payments', 'tenant/acme/v1/payments/discount')).toBe(false);
    expect(isCrossScope(null, 'std/v0/types/money')).toBe(false);
  });

  it('flattenResolverEdges produces one row per valid $ref and skips malformed edges', () => {
    const rows = flattenResolverEdges(PRIMITIVES);
    expect(rows).toHaveLength(3); // 1 (date) + 2 (charge); null-ref edge dropped

    const dateEdge = rows[0];
    expect(dateEdge.key).toBe('p-date:0');
    expect(dateEdge.sourceLabel).toBe('std/v0/types/date');
    expect(dateEdge.resolvedTarget).toBe('std/v0/primitives/string');
    expect(dateEdge.status).toBe('resolved');
    expect(dateEdge.crossScope).toBe(false);

    const crossScopeEdge = rows.find((r) => r.sourceId === 'p-charge' && r.status === 'resolved');
    expect(crossScopeEdge?.resolvedTarget).toBe('std/v0/types/money');
    expect(crossScopeEdge?.crossScope).toBe(true);
    expect(crossScopeEdge?.targetName).toBe('money');
  });

  it('collectNamespaces returns unique sorted namespaces', () => {
    expect(collectNamespaces(PRIMITIVES)).toEqual(['std/v0/types', 'tenant/acme/v1/payments']);
  });

  it('filterResolverRows filters by namespace and status independently', () => {
    const rows = flattenResolverEdges(PRIMITIVES);

    expect(filterResolverRows(rows, { namespace: 'all', status: 'all' })).toHaveLength(3);
    expect(
      filterResolverRows(rows, { namespace: 'std/v0/types', status: 'all' })
    ).toHaveLength(1);
    expect(filterResolverRows(rows, { namespace: 'all', status: 'unresolved' })).toHaveLength(1);
    expect(
      filterResolverRows(rows, { namespace: 'tenant/acme/v1/payments', status: 'resolved' })
    ).toHaveLength(1);
    expect(filterResolverRows(rows, { namespace: 'all', status: 'circular' })).toHaveLength(0);
  });

  it('summarizeStatuses counts by status, including circular (forward-compatible)', () => {
    const rows = flattenResolverEdges(PRIMITIVES);
    expect(summarizeStatuses(rows)).toEqual({ resolved: 2, unresolved: 1, circular: 0 });

    const withCircular = [...rows, { ...rows[0], key: 'x', status: 'circular' as const }];
    expect(summarizeStatuses(withCircular)).toEqual({ resolved: 2, unresolved: 1, circular: 1 });
  });

  it('statusLabel and statusBadgeClass cover every status', () => {
    expect(statusLabel('resolved')).toBe('Resolved');
    expect(statusLabel('unresolved')).toBe('Unresolved');
    expect(statusLabel('circular')).toBe('Circular');

    expect(statusBadgeClass('resolved')).toContain('emerald');
    expect(statusBadgeClass('unresolved')).toContain('amber');
    expect(statusBadgeClass('circular')).toContain('red');
  });

  it('emptyResolveResponse is a zeroed response', () => {
    const empty = emptyResolveResponse();
    expect(empty.primitives).toEqual([]);
    expect(empty.ref_count).toBe(0);
    expect(empty.reresolved_primitive_count).toBe(0);
  });
});
