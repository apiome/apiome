import { describe, expect, it } from 'vitest';
import {
  hasSearchableContent,
  parseQuery,
  resolveFilterKey,
  stringifyQuery,
  textNeedles,
  withFilter,
} from '../query';

describe('parseQuery', () => {
  it('returns the empty parse for blank input', () => {
    expect(parseQuery('')).toEqual({ terms: [], phrases: [], negated: [], filters: {} });
    expect(parseQuery('   ')).toEqual({ terms: [], phrases: [], negated: [], filters: {} });
    expect(parseQuery(undefined)).toEqual({ terms: [], phrases: [], negated: [], filters: {} });
  });

  it('splits words and keeps their order', () => {
    expect(parseQuery('create  order').terms).toEqual(['create', 'order']);
  });

  it('reads quoted phrases, including unterminated ones', () => {
    expect(parseQuery('"payment intent" refund')).toEqual({
      terms: ['refund'],
      phrases: ['payment intent'],
      negated: [],
      filters: {},
    });
    expect(parseQuery('"open ended').phrases).toEqual(['open ended']);
  });

  it('negates with a leading dash but not an inner one', () => {
    const parsed = parseQuery('orders -deprecated read-only -"beta channel"');
    expect(parsed.terms).toEqual(['orders', 'read-only']);
    expect(parsed.negated).toEqual(['deprecated', 'beta channel']);
  });

  it('parses known filters and upper-cases methods', () => {
    const parsed = parseQuery('method:post Path:/orders org:Acme type:Operation');
    expect(parsed.filters).toEqual({
      method: ['POST'],
      path: ['/orders'],
      org: ['acme'],
      type: ['operation'],
    });
    expect(parsed.terms).toEqual([]);
  });

  it('ORs repeated filter values and de-duplicates them', () => {
    expect(parseQuery('method:GET method:post method:get').filters.method).toEqual(['GET', 'POST']);
  });

  it('accepts aliases for filter keys', () => {
    expect(resolveFilterKey('verb')).toBe('method');
    expect(resolveFilterKey('tenant')).toBe('org');
    expect(resolveFilterKey('since')).toBe('after');
    expect(resolveFilterKey('nope')).toBeNull();
    expect(parseQuery('verb:DELETE tenant:acme').filters).toEqual({ method: ['DELETE'], org: ['acme'] });
  });

  it('keeps unknown key:value tokens as words', () => {
    const parsed = parseQuery('foo:bar a:b');
    expect(parsed.terms).toEqual(['foo:bar', 'a:b']);
    expect(parsed.filters).toEqual({});
  });

  it('keeps a bare colon-terminated key as a word', () => {
    expect(parseQuery('method:').terms).toEqual(['method:']);
    expect(parseQuery('method: get').terms).toEqual(['method:', 'get']);
  });

  it('reads a quoted filter value', () => {
    expect(parseQuery('project:"Payments API"').filters.project).toEqual(['payments api']);
  });

  it('treats a negated filter as a negated word', () => {
    const parsed = parseQuery('-method:GET');
    expect(parsed.filters).toEqual({});
    expect(parsed.negated).toEqual(['GET']);
  });
});

describe('hasSearchableContent / textNeedles', () => {
  it('counts words, phrases and filters but not bare negations', () => {
    expect(hasSearchableContent(parseQuery('orders'))).toBe(true);
    expect(hasSearchableContent(parseQuery('method:GET'))).toBe(true);
    expect(hasSearchableContent(parseQuery('-draft'))).toBe(false);
    expect(hasSearchableContent(parseQuery(''))).toBe(false);
  });

  it('orders needles longest first and de-duplicates', () => {
    expect(textNeedles(parseQuery('pet "pet store" pet'))).toEqual(['pet store', 'pet']);
  });
});

describe('stringifyQuery / withFilter', () => {
  it('round-trips a query up to normalization', () => {
    const text = 'create order "payment intent" -deprecated method:POST org:acme';
    const parsed = parseQuery(text);
    expect(stringifyQuery(parsed)).toBe('create order "payment intent" -deprecated method:POST org:acme');
    expect(parseQuery(stringifyQuery(parsed))).toEqual(parsed);
  });

  it('quotes values that need it', () => {
    expect(stringifyQuery(parseQuery('project:"Payments API"'))).toBe('project:"payments api"');
  });

  it('toggles a filter value', () => {
    const base = parseQuery('orders');
    const added = withFilter(base, 'method', 'get');
    expect(added.filters.method).toEqual(['GET']);
    const removed = withFilter(added, 'method', 'GET');
    expect(removed.filters.method).toBeUndefined();
    expect(withFilter(added, 'method', 'GET', 'add').filters.method).toEqual(['GET']);
  });
});
