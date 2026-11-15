import {
  mcpApplySavedSearch,
  mcpPinnedSavedSearches,
  mcpSavedSearchCreateBody,
  mcpSavedSearchFiltersFromPayload,
  mcpSavedSearchFromPayload,
  mcpSavedSearchesFromPayload,
  mcpSavedSearchIsCurrent,
  type McpSavedSearch,
} from '../src/app/components/ade/dashboard/mcp/mcpSavedSearchUi';
import { MCP_CATALOG_EMPTY_FILTERS } from '../src/app/components/ade/dashboard/mcp/mcpCatalogUi';

describe('mcpSavedSearchFromPayload', () => {
  it('parses a saved search row', () => {
    const search = mcpSavedSearchFromPayload({
      id: 'ss-1',
      name: 'Weekly',
      filters: { grades: ['A'], safeties: ['has_destructive'] },
      query: 'weather',
      sort: 'recency',
      isPinned: true,
      createdAt: '2026-07-01T00:00:00Z',
      updatedAt: '2026-07-02T00:00:00Z',
    });
    expect(search?.name).toBe('Weekly');
    expect(search?.filters.grades).toEqual(['A']);
    expect(search?.isPinned).toBe(true);
    expect(search?.sort).toBe('recency');
  });

  it('returns null for malformed rows', () => {
    expect(mcpSavedSearchFromPayload(null)).toBeNull();
    expect(mcpSavedSearchFromPayload({ id: 'x' })).toBeNull();
  });
});

describe('mcpSavedSearchFiltersFromPayload', () => {
  it('defaults to empty filters', () => {
    expect(mcpSavedSearchFiltersFromPayload(undefined)).toEqual(MCP_CATALOG_EMPTY_FILTERS);
  });

  it('drops blank strings', () => {
    expect(
      mcpSavedSearchFiltersFromPayload({ hosts: ['api.example.com', '  ', 1] }),
    ).toEqual({ ...MCP_CATALOG_EMPTY_FILTERS, hosts: ['api.example.com'] });
  });
});

describe('mcpSavedSearchesFromPayload', () => {
  it('parses list envelopes', () => {
    const list = mcpSavedSearchesFromPayload({
      searches: [{ id: 'a', name: 'One', filters: {} }],
    });
    expect(list).toHaveLength(1);
    expect(list[0]?.name).toBe('One');
  });
});

describe('mcpSavedSearchCreateBody / mcpApplySavedSearch', () => {
  it('builds create payloads and applies saved state', () => {
    const body = mcpSavedSearchCreateBody(
      'Pinned view',
      { ...MCP_CATALOG_EMPTY_FILTERS, grades: ['F'] },
      'alpha',
      'name',
      true,
    );
    expect(body.name).toBe('Pinned view');
    expect(body.isPinned).toBe(true);

    const applied = mcpApplySavedSearch({
      id: 'x',
      name: 'Pinned view',
      filters: { ...MCP_CATALOG_EMPTY_FILTERS, grades: ['F'] },
      query: 'alpha',
      sort: 'name',
      isPinned: true,
      createdAt: '',
      updatedAt: '',
    });
    expect(applied.filters.grades).toEqual(['F']);
    expect(applied.query).toBe('alpha');
    expect(applied.sort).toBe('name');
  });
});

describe('mcpPinnedSavedSearches', () => {
  it('returns only pinned searches', () => {
    const pinned = mcpPinnedSavedSearches([
      {
        id: '1',
        name: 'A',
        filters: MCP_CATALOG_EMPTY_FILTERS,
        query: '',
        sort: 'grade',
        isPinned: true,
        createdAt: '',
        updatedAt: '',
      },
      {
        id: '2',
        name: 'B',
        filters: MCP_CATALOG_EMPTY_FILTERS,
        query: '',
        sort: 'grade',
        isPinned: false,
        createdAt: '',
        updatedAt: '',
      },
    ]);
    expect(pinned).toHaveLength(1);
    expect(pinned[0]?.name).toBe('A');
  });
});

describe('mcpSavedSearchIsCurrent', () => {
  const search: McpSavedSearch = {
    id: '1',
    name: 'Public A/B',
    filters: { ...MCP_CATALOG_EMPTY_FILTERS, visibilities: ['public'], grades: ['A', 'B'] },
    query: 'acme',
    sort: 'grade',
    isPinned: true,
    createdAt: '',
    updatedAt: '',
  };
  const filters = { ...MCP_CATALOG_EMPTY_FILTERS, visibilities: ['public'], grades: ['A', 'B'] };

  it('is true when query, facets and sort all match', () => {
    expect(mcpSavedSearchIsCurrent(search, filters, 'acme', 'grade')).toBe(true);
  });

  it('ignores facet order and surrounding query whitespace', () => {
    expect(mcpSavedSearchIsCurrent(search, { ...filters, grades: ['B', 'A'] }, '  acme ', 'grade')).toBe(true);
  });

  it('is false once any facet, the query or the sort differs', () => {
    expect(mcpSavedSearchIsCurrent(search, { ...filters, grades: ['A'] }, 'acme', 'grade')).toBe(false);
    expect(mcpSavedSearchIsCurrent(search, { ...filters, hosts: ['h1'] }, 'acme', 'grade')).toBe(false);
    expect(mcpSavedSearchIsCurrent(search, filters, 'acme2', 'grade')).toBe(false);
    expect(mcpSavedSearchIsCurrent(search, filters, 'acme', 'recency')).toBe(false);
  });

  it('does not treat a duplicated value as a different selection of the same size', () => {
    expect(mcpSavedSearchIsCurrent(search, { ...filters, grades: ['A', 'A'] }, 'acme', 'grade')).toBe(false);
  });
});
