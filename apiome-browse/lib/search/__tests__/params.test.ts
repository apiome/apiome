import { describe, expect, it } from 'vitest';
import {
  SEARCH_MAX_PAGE,
  SEARCH_PAGE_SIZE,
  isEmptyRequest,
  normalizeDate,
  patchSearchRequest,
  resolveSearchRequest,
  searchHref,
  splitParam,
  toSearchParams,
  toUrlState,
  toggleUrlValue,
} from '../params';
import { HIT_KINDS, SCOPE_KINDS } from '../kinds';

describe('splitParam / normalizeDate', () => {
  it('splits repeated and comma-separated values', () => {
    expect(splitParam(['a,b', ' c '])).toEqual(['a', 'b', 'c']);
    expect(splitParam('a,,a')).toEqual(['a']);
    expect(splitParam(undefined)).toEqual([]);
  });

  it('accepts full, month and year dates and rejects garbage', () => {
    expect(normalizeDate('2026-03-05')).toBe('2026-03-05');
    expect(normalizeDate('2026-03')).toBe('2026-03-01');
    expect(normalizeDate('2026')).toBe('2026-01-01');
    expect(normalizeDate('2026-02-30')).toBeNull();
    expect(normalizeDate('yesterday')).toBeNull();
    expect(normalizeDate('')).toBeNull();
  });
});

describe('resolveSearchRequest', () => {
  it('defaults to every kind, relevance with words, newest without', () => {
    const withWords = resolveSearchRequest({ q: 'orders' });
    expect(withWords.scope).toBe('all');
    expect(withWords.kinds).toEqual([...HIT_KINDS]);
    expect(withWords.sort).toBe('relevance');
    expect(withWords.page).toBe(1);
    expect(withWords.perPage).toBe(SEARCH_PAGE_SIZE);
    expect(withWords.allVersions).toBe(false);

    const filterOnly = resolveSearchRequest({ q: 'method:GET' });
    expect(filterOnly.sort).toBe('newest');
  });

  it('merges inline and URL filters', () => {
    const request = resolveSearchRequest({
      q: 'orders method:POST org:acme',
      method: 'get,post',
      org: ['Globex'],
      format: 'OpenAPI',
      paradigm: 'rest',
    });
    expect(request.methods).toEqual(['GET', 'POST']);
    expect(request.orgs).toEqual(['globex', 'acme']);
    expect(request.formats).toEqual(['openapi']);
    expect(request.paradigms).toEqual(['rest']);
  });

  it('intersects scope and explicit types', () => {
    const schemas = resolveSearchRequest({ q: 'pet', scope: 'schemas' });
    expect(schemas.kinds).toEqual([...SCOPE_KINDS.schemas]);

    const narrowed = resolveSearchRequest({ q: 'pet', scope: 'schemas', type: 'property' });
    expect(narrowed.kinds).toEqual(['property']);
    expect(narrowed.types).toEqual(['property']);

    const contradictory = resolveSearchRequest({ q: 'pet type:operation', scope: 'schemas' });
    expect(contradictory.kinds).toEqual([]);
  });

  it('resolves type aliases', () => {
    expect(resolveSearchRequest({ q: 'x', type: 'endpoint,model' }).types).toEqual(['operation', 'schema']);
  });

  it('clamps the page and reads dates from either source', () => {
    expect(resolveSearchRequest({ q: 'x', page: '0' }).page).toBe(1);
    expect(resolveSearchRequest({ q: 'x', page: '999' }).page).toBe(SEARCH_MAX_PAGE);
    expect(resolveSearchRequest({ q: 'x after:2026-01' }).after).toBe('2026-01-01');
    expect(resolveSearchRequest({ q: 'x', before: '2026-06-15' }).before).toBe('2026-06-15');
  });

  it('knows when nothing was asked', () => {
    expect(isEmptyRequest(resolveSearchRequest({}))).toBe(true);
    expect(isEmptyRequest(resolveSearchRequest({ q: '-draft' }))).toBe(true);
    expect(isEmptyRequest(resolveSearchRequest({ method: 'GET' }))).toBe(false);
    expect(isEmptyRequest(resolveSearchRequest({ q: 'orders' }))).toBe(false);
  });
});

describe('URL round-trip', () => {
  it('writes only non-default dimensions and keeps inline filters inside q', () => {
    const request = resolveSearchRequest({
      q: 'orders method:POST',
      scope: 'operations',
      method: 'GET',
      org: 'acme',
      sort: 'newest',
      page: '3',
      all: '1',
    });
    expect(toUrlState(request)).toEqual({
      q: 'orders method:POST',
      scope: 'operations',
      org: 'acme',
      method: 'GET',
      sort: 'newest',
      page: '3',
      all: '1',
    });
    expect(toSearchParams(toUrlState(request))).toBe(
      'q=orders+method%3APOST&scope=operations&org=acme&method=GET&sort=newest&all=1&page=3'
    );
    expect(searchHref(resolveSearchRequest({}))).toBe('/search');
  });

  it('omits the default sort for the query shape', () => {
    expect(toUrlState(resolveSearchRequest({ q: 'orders', sort: 'relevance' })).sort).toBeUndefined();
    expect(toUrlState(resolveSearchRequest({ method: 'GET', sort: 'newest' })).sort).toBeUndefined();
    expect(toUrlState(resolveSearchRequest({ method: 'GET', sort: 'relevance' })).sort).toBe('relevance');
  });

  it('patching resets the page unless only the page changed', () => {
    const request = resolveSearchRequest({ q: 'orders', page: '4', org: 'acme' });
    expect(patchSearchRequest(request, { page: '5' })).toEqual({ q: 'orders', org: 'acme', page: '5' });
    expect(patchSearchRequest(request, { sort: 'name' })).toEqual({ q: 'orders', org: 'acme', sort: 'name' });
    expect(patchSearchRequest(request, { org: null })).toEqual({ q: 'orders' });
  });

  it('toggles multi-valued URL dimensions', () => {
    const request = resolveSearchRequest({ q: 'orders', method: 'GET' });
    expect(toggleUrlValue(request, 'method', 'post')).toEqual({ q: 'orders', method: 'GET,POST' });
    expect(toggleUrlValue(request, 'method', 'GET')).toEqual({ q: 'orders' });
    expect(toggleUrlValue(request, 'org', 'Acme')).toEqual({ q: 'orders', method: 'GET', org: 'acme' });
  });
});
