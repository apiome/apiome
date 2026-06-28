/**
 * Unit tests for the MCP catalog grade-led card grid helpers (V2-MCP-24.8 / MCAT-10.8, #3939).
 *
 * Exercises the pure logic the catalog page drives: faceting, composable filtering, the five
 * sort orderings (endpoint + group), the per-host health rollup, the "changed since last view"
 * computation, and the localStorage density / seen-snapshot persistence helpers.
 */

import {
  mcpBrowseEndpointFromPayload,
  type McpBrowseEndpoint,
  type McpBrowseHostGroup,
} from '../src/app/components/ade/dashboard/mcp/mcpBrowseUi';
import {
  MCP_CATALOG_DEFAULT_DENSITY,
  MCP_CATALOG_DEFAULT_SORT,
  MCP_CATALOG_DENSITY_KEY,
  MCP_CATALOG_EMPTY_FILTERS,
  MCP_CATALOG_SEEN_KEY,
  mcpApplyCatalog,
  mcpBuildSeenSnapshot,
  mcpCatalogActiveFilterCount,
  mcpCatalogEndpointMatchesFilters,
  mcpCatalogFacets,
  mcpCatalogFiltersAreEmpty,
  mcpChangedEndpointIds,
  mcpCompareEndpoints,
  mcpEndpointChangedSinceSeen,
  mcpGroupHealthRollup,
  mcpNormalizeDensity,
  mcpNormalizeSortKey,
  mcpReadDensity,
  mcpReadSeenSnapshot,
  mcpSortEndpoints,
  mcpSortGroups,
  mcpWriteDensity,
  mcpWriteSeenSnapshot,
  type McpCatalogFilters,
} from '../src/app/components/ade/dashboard/mcp/mcpCatalogUi';

// --- Fixtures -------------------------------------------------------------------------------

function ep(overrides: Partial<McpBrowseEndpoint> & { id: string }): McpBrowseEndpoint {
  return mcpBrowseEndpointFromPayload({
    name: overrides.id,
    host: 'h',
    transport: 'streamable_http',
    visibility: 'private',
    ...overrides,
  });
}

function group(host: string, endpoints: McpBrowseEndpoint[]): McpBrowseHostGroup {
  return {
    host,
    endpoint_count: endpoints.length,
    capability_count: endpoints.reduce((s, e) => s + e.capability_count, 0),
    endpoints,
  };
}

/** A minimal in-memory Storage for the persistence helpers. */
function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear: () => map.clear(),
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    key: (i: number) => [...map.keys()][i] ?? null,
    removeItem: (k: string) => void map.delete(k),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
  } as Storage;
}

// --- Parsing: auth_scheme -------------------------------------------------------------------

describe('mcpBrowseEndpointFromPayload (auth_scheme)', () => {
  it('parses auth_scheme / auth_type / auth, defaulting to null', () => {
    expect(ep({ id: 'a' }).auth_scheme).toBeNull();
    expect(mcpBrowseEndpointFromPayload({ id: 'a', auth_scheme: 'bearer' }).auth_scheme).toBe('bearer');
    expect(mcpBrowseEndpointFromPayload({ id: 'a', auth_type: 'oauth' }).auth_scheme).toBe('oauth');
    expect(mcpBrowseEndpointFromPayload({ id: 'a', auth: 'header' }).auth_scheme).toBe('header');
  });
});

// --- Sorting --------------------------------------------------------------------------------

describe('mcpNormalizeSortKey', () => {
  it('passes through known keys and defaults unknowns to grade', () => {
    expect(mcpNormalizeSortKey('name')).toBe('name');
    expect(mcpNormalizeSortKey('health')).toBe('health');
    expect(mcpNormalizeSortKey('nope')).toBe(MCP_CATALOG_DEFAULT_SORT);
    expect(mcpNormalizeSortKey(null)).toBe('grade');
  });
});

describe('mcpSortEndpoints', () => {
  const a = ep({ id: 'a', name: 'Zeta', grade: 'A', score: 95, capability_count: 1 });
  const b = ep({ id: 'b', name: 'Alpha', grade: 'C', score: 60, capability_count: 9 });
  const c = ep({ id: 'c', name: 'Mid', grade: null, score: null, capability_count: 4 });

  it('grade: best grade first, unscored last; does not mutate input', () => {
    const input = [b, c, a];
    const sorted = mcpSortEndpoints(input, 'grade');
    expect(sorted.map((e) => e.id)).toEqual(['a', 'b', 'c']);
    expect(input.map((e) => e.id)).toEqual(['b', 'c', 'a']); // original untouched
  });

  it('grade: same letter falls back to higher numeric score then name', () => {
    const hi = ep({ id: 'hi', name: 'B-hi', grade: 'B', score: 88 });
    const lo = ep({ id: 'lo', name: 'A-lo', grade: 'B', score: 72 });
    expect(mcpSortEndpoints([lo, hi], 'grade').map((e) => e.id)).toEqual(['hi', 'lo']);
  });

  it('name: alphabetical', () => {
    expect(mcpSortEndpoints([a, b, c], 'name').map((e) => e.name)).toEqual(['Alpha', 'Mid', 'Zeta']);
  });

  it('capabilities: most capabilities first', () => {
    expect(mcpSortEndpoints([a, b, c], 'capabilities').map((e) => e.id)).toEqual(['b', 'c', 'a']);
  });

  it('recency: most recently discovered first, missing timestamps last', () => {
    const older = ep({ id: 'o', name: 'older', last_discovered_at: '2026-01-01T00:00:00Z' });
    const newer = ep({ id: 'n', name: 'newer', last_discovered_at: '2026-06-01T00:00:00Z' });
    const never = ep({ id: 'x', name: 'never', last_discovered_at: null });
    expect(mcpSortEndpoints([older, never, newer], 'recency').map((e) => e.id)).toEqual([
      'n',
      'o',
      'x',
    ]);
  });

  it('health: healthy before degraded before failing before unknown', () => {
    const ok = ep({ id: 'ok', name: 'ok', last_discovery_status: 'ok' });
    const warn = ep({ id: 'warn', name: 'warn', last_discovery_status: 'degraded' });
    const fail = ep({ id: 'fail', name: 'fail', last_discovery_status: 'failed' });
    const unk = ep({ id: 'unk', name: 'unk', last_discovery_status: null });
    expect(mcpSortEndpoints([fail, unk, ok, warn], 'health').map((e) => e.id)).toEqual([
      'ok',
      'warn',
      'fail',
      'unk',
    ]);
  });
});

describe('mcpCompareEndpoints', () => {
  it('is a total, name-tiebroken comparator', () => {
    const x = ep({ id: 'x', name: 'Same', grade: 'B', score: 80 });
    const y = ep({ id: 'y', name: 'Same', grade: 'B', score: 80 });
    expect(mcpCompareEndpoints(x, y, 'grade')).toBe(0);
  });
});

describe('mcpSortGroups', () => {
  const g1 = group('beta.example', [ep({ id: 'b1', grade: 'C', capability_count: 2 })]);
  const g2 = group('acme.example', [
    ep({ id: 'a1', grade: 'A', capability_count: 1 }),
    ep({ id: 'a2', grade: 'F', capability_count: 8 }),
  ]);

  it('grade: orders groups by their best endpoint grade and sorts within', () => {
    const sorted = mcpSortGroups([g1, g2], 'grade');
    expect(sorted.map((g) => g.host)).toEqual(['acme.example', 'beta.example']);
    expect(sorted[0].endpoints.map((e) => e.id)).toEqual(['a1', 'a2']); // A before F
  });

  it('name: orders groups by host alphabetically', () => {
    expect(mcpSortGroups([g1, g2], 'name').map((g) => g.host)).toEqual([
      'acme.example',
      'beta.example',
    ]);
  });

  it('capabilities: orders groups by total capability count desc', () => {
    expect(mcpSortGroups([g1, g2], 'capabilities').map((g) => g.host)).toEqual([
      'acme.example',
      'beta.example',
    ]);
  });

  it('does not mutate the input groups', () => {
    const original = [g1, g2];
    mcpSortGroups(original, 'grade');
    expect(original[0].host).toBe('beta.example');
  });
});

// --- Filtering & facets ---------------------------------------------------------------------

describe('mcpCatalogFacets', () => {
  const groups = [
    group('acme.example', [
      ep({ id: 'a', host: 'acme.example', grade: 'A', transport: 'streamable_http', visibility: 'private', category: 'weather', auth_scheme: 'bearer' }),
      ep({ id: 'b', host: 'acme.example', grade: 'C', transport: 'http+sse', visibility: 'public', category: 'weather' }),
    ]),
    group('beta.example', [ep({ id: 'c', host: 'beta.example', grade: 'A', transport: 'streamable_http', visibility: 'private' })]),
  ];

  it('computes facets with counts, sorted by count desc then value', () => {
    const facets = mcpCatalogFacets(groups);
    const byKey = Object.fromEntries(facets.map((f) => [f.key, f]));
    expect(byKey.hosts.values.map((v) => v.value)).toEqual(['acme.example', 'beta.example']);
    expect(byKey.grades.values).toEqual([
      { value: 'A', count: 2 },
      { value: 'C', count: 1 },
    ]);
    expect(byKey.categories.values).toEqual([{ value: 'weather', count: 2 }]);
  });

  it('drops facets with no present values (e.g. auth when only one endpoint has it)', () => {
    const facets = mcpCatalogFacets(groups);
    const auth = facets.find((f) => f.key === 'auths');
    expect(auth?.values).toEqual([{ value: 'bearer', count: 1 }]);
    // A catalog with no auth at all omits the facet entirely.
    const noAuth = mcpCatalogFacets([group('h', [ep({ id: 'x' })])]);
    expect(noAuth.find((f) => f.key === 'auths')).toBeUndefined();
  });
});

describe('mcpCatalogEndpointMatchesFilters / mcpApplyCatalog', () => {
  const groups = [
    group('acme.example', [
      ep({ id: 'a', name: 'Weather', grade: 'A', transport: 'streamable_http', visibility: 'private', category: 'weather', auth_scheme: 'bearer', capability_count: 4 }),
      ep({ id: 'b', name: 'Calendar', grade: 'C', transport: 'http+sse', visibility: 'public', category: 'time', capability_count: 3 }),
    ]),
    group('beta.example', [
      ep({ id: 'c', name: 'Beta', grade: 'A', transport: 'streamable_http', visibility: 'private', capability_count: 1 }),
    ]),
  ];

  it('matches an empty filter set', () => {
    expect(mcpCatalogEndpointMatchesFilters(groups[0].endpoints[0], MCP_CATALOG_EMPTY_FILTERS)).toBe(true);
  });

  it('filters compose (grade AND visibility AND host)', () => {
    const filters: McpCatalogFilters = {
      ...MCP_CATALOG_EMPTY_FILTERS,
      grades: ['A'],
      visibilities: ['private'],
    };
    const result = mcpApplyCatalog(groups, filters, '');
    expect(result.flatMap((g) => g.endpoints.map((e) => e.id))).toEqual(['a', 'c']);
  });

  it('grade filter excludes unscored endpoints', () => {
    const withUnscored = [group('h', [ep({ id: 'u', grade: null })])];
    const filters: McpCatalogFilters = { ...MCP_CATALOG_EMPTY_FILTERS, grades: ['A'] };
    expect(mcpApplyCatalog(withUnscored, filters, '')).toHaveLength(0);
  });

  it('auth filter excludes endpoints without an auth scheme', () => {
    const filters: McpCatalogFilters = { ...MCP_CATALOG_EMPTY_FILTERS, auths: ['bearer'] };
    const result = mcpApplyCatalog(groups, filters, '');
    expect(result.flatMap((g) => g.endpoints.map((e) => e.id))).toEqual(['a']);
  });

  it('combines filters with the free-text search and recomputes group counts', () => {
    const filters: McpCatalogFilters = { ...MCP_CATALOG_EMPTY_FILTERS, grades: ['A'] };
    const result = mcpApplyCatalog(groups, filters, 'weather');
    expect(result).toHaveLength(1);
    expect(result[0].host).toBe('acme.example');
    expect(result[0].endpoint_count).toBe(1);
    expect(result[0].capability_count).toBe(4);
  });

  it('returns groups unchanged when there is nothing to apply', () => {
    expect(mcpApplyCatalog(groups, MCP_CATALOG_EMPTY_FILTERS, '   ')).toBe(groups);
  });
});

describe('mcpCatalogFiltersAreEmpty / mcpCatalogActiveFilterCount', () => {
  it('reports emptiness and the active constraint count', () => {
    expect(mcpCatalogFiltersAreEmpty(MCP_CATALOG_EMPTY_FILTERS)).toBe(true);
    expect(mcpCatalogActiveFilterCount(MCP_CATALOG_EMPTY_FILTERS)).toBe(0);
    const filters: McpCatalogFilters = {
      ...MCP_CATALOG_EMPTY_FILTERS,
      grades: ['A', 'B'],
      hosts: ['h'],
    };
    expect(mcpCatalogFiltersAreEmpty(filters)).toBe(false);
    expect(mcpCatalogActiveFilterCount(filters)).toBe(3);
  });
});

// --- Health rollup --------------------------------------------------------------------------

describe('mcpGroupHealthRollup', () => {
  it('tallies statuses and formats a summary omitting empty buckets', () => {
    const endpoints = [
      ...Array.from({ length: 11 }, (_, i) => ep({ id: `ok${i}`, last_discovery_status: 'ok' })),
      ep({ id: 'fail', last_discovery_status: 'failed' }),
    ];
    const rollup = mcpGroupHealthRollup(endpoints);
    expect(rollup).toMatchObject({ healthy: 11, failing: 1, degraded: 0, unknown: 0, total: 12 });
    expect(rollup.summary).toBe('11 healthy · 1 failing');
  });

  it('reads all unknown for never-discovered endpoints', () => {
    const rollup = mcpGroupHealthRollup([ep({ id: 'x', last_discovery_status: null })]);
    expect(rollup.unknown).toBe(1);
    expect(rollup.summary).toBe('1 unknown');
  });
});

// --- Changed since last view ----------------------------------------------------------------

describe('mcpEndpointChangedSinceSeen / mcpChangedEndpointIds', () => {
  it('marks an endpoint whose current version id changed', () => {
    const before = ep({ id: 'a', current_version_id: 'v1' });
    const after = ep({ id: 'a', current_version_id: 'v2' });
    const snapshot = mcpBuildSeenSnapshot([group('h', [before])]);
    expect(mcpEndpointChangedSinceSeen(after, snapshot)).toBe(true);
    expect(mcpEndpointChangedSinceSeen(before, snapshot)).toBe(false);
  });

  it('marks an endpoint rediscovered later even when the version id is stable', () => {
    const before = ep({ id: 'a', current_version_id: 'v1', last_discovered_at: '2026-01-01T00:00:00Z' });
    const after = ep({ id: 'a', current_version_id: 'v1', last_discovered_at: '2026-02-01T00:00:00Z' });
    const snapshot = mcpBuildSeenSnapshot([group('h', [before])]);
    expect(mcpEndpointChangedSinceSeen(after, snapshot)).toBe(true);
  });

  it('does NOT mark brand-new endpoints absent from the snapshot', () => {
    const snapshot = mcpBuildSeenSnapshot([group('h', [ep({ id: 'old', current_version_id: 'v1' })])]);
    const fresh = ep({ id: 'new', current_version_id: 'v9' });
    expect(mcpEndpointChangedSinceSeen(fresh, snapshot)).toBe(false);
  });

  it('returns an empty set when there is no prior snapshot', () => {
    const groups = [group('h', [ep({ id: 'a', current_version_id: 'v2' })])];
    expect(mcpChangedEndpointIds(groups, null).size).toBe(0);
  });

  it('collects the ids that changed across all groups', () => {
    const prior = mcpBuildSeenSnapshot([
      group('h', [
        ep({ id: 'a', current_version_id: 'v1' }),
        ep({ id: 'b', current_version_id: 'v1' }),
      ]),
    ]);
    const now = [
      group('h', [
        ep({ id: 'a', current_version_id: 'v2' }), // changed
        ep({ id: 'b', current_version_id: 'v1' }), // unchanged
        ep({ id: 'c', current_version_id: 'v1' }), // new (not changed)
      ]),
    ];
    const changed = mcpChangedEndpointIds(now, prior);
    expect([...changed]).toEqual(['a']);
  });
});

// --- Persistence ----------------------------------------------------------------------------

describe('density persistence', () => {
  it('normalizes density values', () => {
    expect(mcpNormalizeDensity('list')).toBe('list');
    expect(mcpNormalizeDensity('grid')).toBe('grid');
    expect(mcpNormalizeDensity('nope')).toBe(MCP_CATALOG_DEFAULT_DENSITY);
    expect(mcpNormalizeDensity(null)).toBe('grid');
  });

  it('round-trips through storage and defaults when unset', () => {
    const storage = memoryStorage();
    expect(mcpReadDensity(storage)).toBe('grid');
    mcpWriteDensity('list', storage);
    expect(storage.getItem(MCP_CATALOG_DENSITY_KEY)).toBe('list');
    expect(mcpReadDensity(storage)).toBe('list');
  });

  it('degrades to the default when storage is unavailable', () => {
    expect(mcpReadDensity(undefined)).toBe('grid');
    expect(() => mcpWriteDensity('list', undefined)).not.toThrow();
  });
});

describe('seen-snapshot persistence', () => {
  it('round-trips a snapshot and reads null when absent or malformed', () => {
    const storage = memoryStorage();
    expect(mcpReadSeenSnapshot(storage)).toBeNull();
    const snapshot = mcpBuildSeenSnapshot([
      group('h', [ep({ id: 'a', current_version_id: 'v1', last_discovered_at: '2026-01-01T00:00:00Z' })]),
    ]);
    mcpWriteSeenSnapshot(snapshot, storage);
    expect(mcpReadSeenSnapshot(storage)).toEqual(snapshot);

    storage.setItem(MCP_CATALOG_SEEN_KEY, 'not json');
    expect(mcpReadSeenSnapshot(storage)).toBeNull();
    storage.setItem(MCP_CATALOG_SEEN_KEY, '["array"]');
    expect(mcpReadSeenSnapshot(storage)).toBeNull();
  });

  it('degrades safely when storage is unavailable', () => {
    expect(mcpReadSeenSnapshot(undefined)).toBeNull();
    expect(() => mcpWriteSeenSnapshot({}, undefined)).not.toThrow();
  });
});
