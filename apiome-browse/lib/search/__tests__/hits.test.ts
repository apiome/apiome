import { describe, expect, it } from 'vitest';
import { operationAnchorId, schemaAnchorId, versionHref } from '../anchors';
import { excerptAround, highlightSegments } from '../highlight';
import { groupHitsByKind, hitCrumbs, hitHref, type CatalogSearchHit } from '../hits';
import { resolveHitKind, resolveScope, scopeOfKind } from '../kinds';

function hit(partial: Partial<CatalogSearchHit>): CatalogSearchHit {
  return {
    hit_id: 'x',
    hit_type: 'operation',
    tenant_slug: 'acme',
    tenant_name: 'Acme',
    project_slug: 'payments',
    project_name: 'Payments',
    version_slug: '2.1.0',
    published_at: null,
    title: 't',
    snippet: '',
    subtitle: null,
    method: null,
    path: null,
    anchor_key: null,
    source_format: null,
    paradigm: null,
    rank: 0,
    name_key: 't',
    ...partial,
  };
}

describe('anchors', () => {
  it('match the version page element ids', () => {
    expect(operationAnchorId('GET', '/pets/{petId}')).toBe('op-get-pets-petid');
    expect(schemaAnchorId('Pet Store')).toBe('schema-Pet-Store');
    expect(schemaAnchorId('---')).toBe('schema-unnamed');
    expect(versionHref('a b', 'p', '1.0', 'op-x')).toBe('/tenant/a%20b/p/1.0#op-x');
  });
});

describe('hitHref / hitCrumbs', () => {
  it('links each kind to the right page and anchor', () => {
    expect(hitHref(hit({ hit_type: 'organization', project_slug: null, version_slug: null }))).toBe('/tenant/acme');
    expect(hitHref(hit({ hit_type: 'project' }))).toBe('/tenant/acme/payments');
    expect(hitHref(hit({ hit_type: 'operation', method: 'POST', path: '/orders' }))).toBe(
      '/tenant/acme/payments/2.1.0#op-post-orders'
    );
    expect(hitHref(hit({ hit_type: 'schema', anchor_key: 'Order' }))).toBe('/tenant/acme/payments/2.1.0#schema-Order');
    expect(hitHref(hit({ hit_type: 'property', anchor_key: 'Order' }))).toBe('/tenant/acme/payments/2.1.0#schema-Order');
    expect(hitHref(hit({ hit_type: 'response' }))).toBe('/tenant/acme/payments/2.1.0');
  });

  it('builds crumbs down to the version except for projects', () => {
    expect(hitCrumbs(hit({ hit_type: 'operation' })).map((c) => c.label)).toEqual(['Acme', 'Payments', 'v2.1.0']);
    expect(hitCrumbs(hit({ hit_type: 'project' })).map((c) => c.label)).toEqual(['Acme', 'Payments']);
    expect(hitCrumbs(hit({ hit_type: 'organization', project_slug: null })).map((c) => c.label)).toEqual(['Acme']);
  });

  it('groups a page by kind in first-seen order', () => {
    const rows = [hit({ hit_type: 'schema' }), hit({ hit_type: 'operation' }), hit({ hit_type: 'schema' })];
    expect(groupHitsByKind(rows).map((g) => [g.kind, g.rows.length])).toEqual([
      ['schema', 2],
      ['operation', 1],
    ]);
  });
});

describe('kinds', () => {
  it('resolves aliases and scopes', () => {
    expect(resolveHitKind('endpoint')).toBe('operation');
    expect(resolveHitKind('Request Body')).toBe('request_body');
    expect(resolveHitKind('model')).toBe('schema');
    expect(resolveHitKind('nope')).toBeNull();
    expect(resolveScope('MCP')).toBe('mcp');
    expect(resolveScope('x')).toBe('all');
    expect(scopeOfKind('property')).toBe('schemas');
    expect(scopeOfKind('tag')).toBe('catalog');
  });
});

describe('highlight', () => {
  it('marks every needle case-insensitively, longest first, without overlap', () => {
    const segments = highlightSegments('Pet store pets', ['pet', 'pet store']);
    expect(segments).toEqual([
      { text: 'Pet store', hit: true },
      { text: ' ', hit: false },
      { text: 'pet', hit: true },
      { text: 's', hit: false },
    ]);
    expect(segments.map((s) => s.text).join('')).toBe('Pet store pets');
  });

  it('returns the text untouched without needles', () => {
    expect(highlightSegments('abc', [])).toEqual([{ text: 'abc', hit: false }]);
    expect(highlightSegments('', ['a'])).toEqual([]);
  });

  it('excerpts around the first needle', () => {
    const long = `${'a'.repeat(300)} needle ${'b'.repeat(300)}`;
    const excerpt = excerptAround(long, ['needle'], 20);
    expect(excerpt.startsWith('…')).toBe(true);
    expect(excerpt.endsWith('…')).toBe(true);
    expect(excerpt).toContain('needle');
    expect(excerpt.length).toBeLessThan(60);
    expect(excerptAround('short', ['x'])).toBe('short');
  });
});
