/**
 * The search runner's contract (DBP-1.16, #7199): facets computed once per search, a timeout
 * surfaced as an error instead of "no results", and capped suggestion counts reported as floors.
 */

import { beforeEach, describe, expect, it, vi } from 'vitest';

const { query } = vi.hoisted(() => ({ query: vi.fn() }));

vi.mock('../db/db', () => ({
  default: { query },
  isStatementTimeout: (err: unknown) => (err as { code?: string } | null)?.code === '57014',
}));

import { runAllHitVersions, runCatalogSearch, runCatalogSuggest, runHitVersionsLookup } from '../db/search';
import { DatabaseUnavailableError } from '../db/errors';
import { HIT_VERSIONS_ALL_CAP, HIT_VERSIONS_CAP } from '../search/compare';
import type { CatalogSearchHit } from '../search/hits';
import { SEARCH_KIND_CAP } from '../search/sql';
import { clearBrowseCache } from '../db/ttlCache';
import { SearchTimeoutError } from '../search/errors';
import { resolveSearchRequest } from '../search/params';
import { SUGGEST_MEMBER_CAP } from '../search/suggestSql';

const ORGS = [{ value: 'acme', label: 'Acme', count: 30 }];

/** A result row as the search statement returns it, with or without facets. */
function searchRow(withFacets: boolean) {
  return {
    total: 60,
    total_all_kinds: 60,
    kind_facets: [{ value: 'operation', count: 60 }],
    org_facets: withFacets ? ORGS : [],
    method_facets: [],
    format_facets: [],
    paradigm_facets: [],
    severity_facets: [],
    project_facets: [],
    rows: [{ hit_id: 'op:1' }],
  };
}

/** Whether a recorded statement computes the filter facets. */
function computesFacets(call: unknown[]): boolean {
  return String(call[0]).includes('FROM hits GROUP BY 1, 2');
}

beforeEach(() => {
  clearBrowseCache();
  delete process.env.BROWSE_CACHE_TTL_SECONDS;
  query.mockReset();
  query.mockImplementation(async (text: string) => ({ rows: [searchRow(text.includes('FROM hits GROUP BY 1, 2'))] }));
  vi.spyOn(console, 'error').mockImplementation(() => undefined);
});

describe('runCatalogSearch facets', () => {
  it('computes the facets on the first page', async () => {
    const response = await runCatalogSearch(resolveSearchRequest({ q: 'order' }));
    expect(query).toHaveBeenCalledTimes(1);
    expect(computesFacets(query.mock.calls[0])).toBe(true);
    expect(response.facets.orgs).toEqual(ORGS);
  });

  it('reuses them on the following pages, whose statement skips the facet aggregates', async () => {
    await runCatalogSearch(resolveSearchRequest({ q: 'order' }));
    const page2 = await runCatalogSearch(resolveSearchRequest({ q: 'order', page: '2' }));
    expect(query).toHaveBeenCalledTimes(2);
    expect(computesFacets(query.mock.calls[1])).toBe(false);
    // The rail and the per-kind counts are the same on page 2.
    expect(page2.facets.orgs).toEqual(ORGS);
    expect(page2.facets.kinds).toEqual([{ value: 'operation', count: 60 }]);
    expect(page2.page).toBe(2);
  });

  it('reuses the per-kind counts too, so a later page runs only the kinds it lists (DBP-1.27)', async () => {
    // Page 1 of the Schemas tab counts the other kinds for the tabs…
    query.mockImplementationOnce(async () => ({
      rows: [
        {
          ...searchRow(true),
          total: 40,
          total_all_kinds: 100,
          kind_facets: [
            { value: 'operation', count: 60 },
            { value: 'schema', count: 40 },
          ],
        },
      ],
    }));
    await runCatalogSearch(resolveSearchRequest({ q: 'order', scope: 'schemas' }));
    expect(String(query.mock.calls[0][0])).toContain("SELECT 'operation'::text AS hit_type, COUNT(*)::int AS c FROM (");

    // …and page 2 runs the schema kinds only, answering with page 1's counts.
    query.mockImplementationOnce(async () => ({
      rows: [{ ...searchRow(false), total: 40, total_all_kinds: 40, kind_facets: [{ value: 'schema', count: 40 }] }],
    }));
    const page2 = await runCatalogSearch(resolveSearchRequest({ q: 'order', scope: 'schemas', page: '2' }));
    const text = String(query.mock.calls[1][0]);
    expect(text).not.toContain("'operation'::text AS hit_type");
    expect(text).not.toContain('FROM apiome.path_operation');
    expect(page2.totalAllKinds).toBe(100);
    expect(page2.facets.kinds).toEqual([
      { value: 'operation', count: 60 },
      { value: 'schema', count: 40 },
    ]);
  });

  it('says "more than" when a kind reached its own cap, and only then', async () => {
    const capped = { ...searchRow(true), kind_facets: [{ value: 'property', count: SEARCH_KIND_CAP }, { value: 'operation', count: 12 }] };
    query.mockImplementationOnce(async () => ({ rows: [capped] }));
    expect((await runCatalogSearch(resolveSearchRequest({ q: 'id' }))).truncated).toBe(true);
    expect((await runCatalogSearch(resolveSearchRequest({ q: 'order' }))).truncated).toBe(false);
  });

  it('computes them on a later page when nothing is cached (a shared deep link)', async () => {
    const page3 = await runCatalogSearch(resolveSearchRequest({ q: 'order', page: '3' }));
    expect(computesFacets(query.mock.calls[0])).toBe(true);
    expect(page3.facets.orgs).toEqual(ORGS);
    // …and the next page of that search reuses them.
    await runCatalogSearch(resolveSearchRequest({ q: 'order', page: '4' }));
    expect(computesFacets(query.mock.calls[1])).toBe(false);
  });

  it('does not reuse the facets of a different search', async () => {
    await runCatalogSearch(resolveSearchRequest({ q: 'order' }));
    await runCatalogSearch(resolveSearchRequest({ q: 'order', page: '2', org: 'acme' }));
    await runCatalogSearch(resolveSearchRequest({ q: 'invoice', page: '2' }));
    expect(computesFacets(query.mock.calls[1])).toBe(true);
    expect(computesFacets(query.mock.calls[2])).toBe(true);
  });

  it('computes them on every page when the cache is off', async () => {
    process.env.BROWSE_CACHE_TTL_SECONDS = '0';
    await runCatalogSearch(resolveSearchRequest({ q: 'order' }));
    await runCatalogSearch(resolveSearchRequest({ q: 'order', page: '2' }));
    expect(computesFacets(query.mock.calls[1])).toBe(true);
  });
});

describe('runCatalogSearch failures', () => {
  it('throws SearchTimeoutError when the statement was cancelled by statement_timeout', async () => {
    query.mockRejectedValueOnce({ code: '57014', message: 'canceling statement due to statement timeout' });
    await expect(runCatalogSearch(resolveSearchRequest({ q: 'order' }))).rejects.toBeInstanceOf(SearchTimeoutError);
  });

  it('still renders any other failure as an empty result', async () => {
    query.mockRejectedValueOnce({ code: '42P01', message: 'relation does not exist' });
    const response = await runCatalogSearch(resolveSearchRequest({ q: 'order' }));
    expect(response.total).toBe(0);
    expect(response.rows).toEqual([]);
  });

  it('runs nothing for an empty request', async () => {
    expect((await runCatalogSearch(resolveSearchRequest({}))).rows).toEqual([]);
    expect(query).not.toHaveBeenCalled();
  });
});

describe('runCatalogSuggest', () => {
  const request = { ...resolveSearchRequest({ q: 'order' }), perPage: 8, page: 1 };

  it('reports a kind that filled its cap as a floor', async () => {
    query.mockResolvedValueOnce({
      rows: [
        {
          total: SUGGEST_MEMBER_CAP + 60 + 3,
          kind_facets: [
            { value: 'operation', count: SUGGEST_MEMBER_CAP + 60 },
            { value: 'schema', count: 3 },
          ],
          rows: [{ hit_id: 'op:1' }],
        },
      ],
    });
    const response = await runCatalogSuggest(request);
    expect(response.kinds).toEqual([
      { value: 'operation', count: SUGGEST_MEMBER_CAP, capped: true },
      { value: 'schema', count: 3 },
    ]);
    expect(response.total).toBe(SUGGEST_MEMBER_CAP + 3);
    expect(response.truncated).toBe(true);
    expect(response.rows).toEqual([{ hit_id: 'op:1' }]);
  });

  it('reports exact counts when no kind was capped', async () => {
    query.mockResolvedValueOnce({ rows: [{ total: 2, kind_facets: [{ value: 'schema', count: 2 }], rows: [] }] });
    const response = await runCatalogSuggest(request);
    expect(response.truncated).toBe(false);
    expect(response.total).toBe(2);
  });

  it('runs the suggestion statement, not the full search', async () => {
    query.mockResolvedValueOnce({ rows: [{ total: 0, kind_facets: [], rows: [] }] });
    await runCatalogSuggest(request);
    const text = String(query.mock.calls[0][0]);
    expect(text).toContain('recent_scope');
    expect(text).not.toContain('hits_all');
  });

  it('throws SearchTimeoutError on a statement timeout and is empty on any other failure', async () => {
    query.mockRejectedValueOnce({ code: '57014' });
    await expect(runCatalogSuggest(request)).rejects.toBeInstanceOf(SearchTimeoutError);
    query.mockRejectedValueOnce(new Error('connection refused'));
    expect(await runCatalogSuggest(request)).toMatchObject({ rows: [], total: 0, truncated: false });
  });

  it('runs nothing when no suggestable kind can honour the request', async () => {
    const severity = { ...resolveSearchRequest({ q: 'order severity:breaking' }), perPage: 8, page: 1 };
    expect((await runCatalogSuggest(severity)).rows).toEqual([]);
    expect(query).not.toHaveBeenCalled();
  });
});

/** A search hit for the version-menu lookups. */
function versionHit(overrides: Partial<CatalogSearchHit> = {}): CatalogSearchHit {
  return {
    hit_id: 'op:1',
    hit_type: 'operation',
    tenant_slug: 'acme',
    project_slug: 'orders',
    version_slug: '2.0.0',
    method: 'post',
    path: '/orders',
    ...overrides,
  } as CatalogSearchHit;
}

describe('hit version menus (DBP-1.27)', () => {
  const versions = [{ version_slug: '2.0.0', published_at: null, has_anchor: true }];

  it('looks up a capped list per hit, with the project total', async () => {
    query.mockResolvedValue({ rows: [{ hit_id: 'op:1', version_count: 45, versions }] });
    const lookup = await runHitVersionsLookup([versionHit()]);
    expect(lookup).toEqual({ versions: { 'op:1': versions }, counts: { 'op:1': 45 } });
    expect((query.mock.calls[0][1] as unknown[])[6]).toBe(HIT_VERSIONS_CAP);
  });

  it('renders no menus, not an error, when the lookup fails or nothing is eligible', async () => {
    query.mockRejectedValue(new Error('connection refused'));
    expect(await runHitVersionsLookup([versionHit()])).toEqual({ versions: {}, counts: {} });
    query.mockClear();
    expect(await runHitVersionsLookup([versionHit({ hit_type: 'project' })])).toEqual({ versions: {}, counts: {} });
    expect(query).not.toHaveBeenCalled();
  });

  it('loads the long list of one hit on request', async () => {
    query.mockResolvedValue({ rows: [{ hit_id: 'op:1', version_count: 45, versions }] });
    expect(await runAllHitVersions(versionHit())).toEqual(versions);
    expect((query.mock.calls[0][1] as unknown[])[6]).toBe(HIT_VERSIONS_ALL_CAP);
  });

  it('answers an empty list for a hit that is not eligible or whose project is not public', async () => {
    expect(await runAllHitVersions(versionHit({ hit_type: 'project' }))).toEqual([]);
    expect(query).not.toHaveBeenCalled();
    query.mockResolvedValue({ rows: [] });
    expect(await runAllHitVersions(versionHit())).toEqual([]);
  });

  it('raises a database failure of the on-request load, so its route answers 503', async () => {
    query.mockRejectedValue(new Error('timeout exceeded when trying to connect'));
    await expect(runAllHitVersions(versionHit())).rejects.toBeInstanceOf(DatabaseUnavailableError);
  });
});
