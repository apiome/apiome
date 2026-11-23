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

import { runCatalogSearch, runCatalogSuggest } from '../db/search';
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
    // The rail is the same on page 2, and the per-kind counts still come from page 2's own row.
    expect(page2.facets.orgs).toEqual(ORGS);
    expect(page2.facets.kinds).toEqual([{ value: 'operation', count: 60 }]);
    expect(page2.page).toBe(2);
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
