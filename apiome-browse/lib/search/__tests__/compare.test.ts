import { describe, expect, it } from 'vitest';
import {
  buildHitVersionsSql,
  compareHref,
  compareLabel,
  hitAnchor,
  isCompareEligible,
  orderForCompare,
  toggleCompare,
  versionMenuEntries,
  type HitVersion,
  HIT_VERSIONS_ALL_CAP,
  HIT_VERSIONS_CAP,
  moreVersionsCount,
} from '../compare';
import type { CatalogSearchHit } from '../hits';

function hit(partial: Partial<CatalogSearchHit>): CatalogSearchHit {
  return {
    hit_id: 'op:1',
    hit_type: 'operation',
    tenant_slug: 'acme',
    tenant_name: 'Acme',
    project_slug: 'orders',
    project_name: 'Orders',
    version_slug: '1.0.0',
    published_at: '2026-01-01T00:00:00Z',
    title: 'Create order',
    snippet: '',
    subtitle: null,
    method: 'POST',
    path: '/orders',
    anchor_key: null,
    source_format: null,
    paradigm: null,
    rank: 0,
    name_key: '/orders',
    severity: null,
    ...partial,
  };
}

const v1 = hit({ hit_id: 'op:1', version_slug: '1.0.0', published_at: '2026-01-01T00:00:00Z' });
const v2 = hit({ hit_id: 'op:2', version_slug: '2.0.0', published_at: '2026-06-01T00:00:00Z' });

describe('isCompareEligible', () => {
  it('accepts version, operation and schema hits with a project and version', () => {
    expect(isCompareEligible(hit({ hit_type: 'operation' }))).toBe(true);
    expect(isCompareEligible(hit({ hit_type: 'schema', anchor_key: 'Order' }))).toBe(true);
    expect(isCompareEligible(hit({ hit_type: 'version' }))).toBe(true);
  });

  it('refuses other kinds and hits without a version', () => {
    expect(isCompareEligible(hit({ hit_type: 'project' }))).toBe(false);
    expect(isCompareEligible(hit({ hit_type: 'property' }))).toBe(false);
    expect(isCompareEligible(hit({ hit_type: 'change' }))).toBe(false);
    expect(isCompareEligible(hit({ version_slug: null }))).toBe(false);
    expect(isCompareEligible(hit({ project_slug: null }))).toBe(false);
  });
});

describe('toggleCompare', () => {
  it('adds and removes hits', () => {
    const one = toggleCompare([], v1);
    expect(one).toEqual({ selection: [v1], error: null });
    const two = toggleCompare(one.selection, v2);
    expect(two.selection).toEqual([v1, v2]);
    expect(toggleCompare(two.selection, v1)).toEqual({ selection: [v2], error: null });
  });

  it('refuses a hit of a different project with a message', () => {
    const other = hit({ hit_id: 'op:9', project_slug: 'billing', project_name: 'Billing', version_slug: '3.0.0' });
    const result = toggleCompare([v1], other);
    expect(result.selection).toEqual([v1]);
    expect(result.error).toMatch(/one project/);
    expect(result.error).toMatch(/Orders/);
  });

  it('treats the same project slug under another organization as a different project', () => {
    const result = toggleCompare([v1], hit({ hit_id: 'op:8', tenant_slug: 'globex', version_slug: '2.0.0' }));
    expect(result.selection).toEqual([v1]);
    expect(result.error).not.toBeNull();
  });

  it('refuses a third hit', () => {
    const third = hit({ hit_id: 'op:3', version_slug: '3.0.0' });
    const result = toggleCompare([v1, v2], third);
    expect(result.selection).toEqual([v1, v2]);
    expect(result.error).toMatch(/two hits/);
  });

  it('refuses a second hit from the same version', () => {
    const sameVersion = hit({ hit_id: 'schema:1', hit_type: 'schema', anchor_key: 'Order', version_slug: '1.0.0' });
    const result = toggleCompare([v1], sameVersion);
    expect(result.selection).toEqual([v1]);
    expect(result.error).toMatch(/v1\.0\.0/);
  });

  it('refuses an ineligible hit', () => {
    const result = toggleCompare([], hit({ hit_type: 'project' }));
    expect(result.selection).toEqual([]);
    expect(result.error).toMatch(/version, operation and schema/);
  });

  it('never mutates the input selection', () => {
    const selection = [v1];
    toggleCompare(selection, v2);
    expect(selection).toEqual([v1]);
  });
});

describe('compareHref / compareLabel', () => {
  it('links the older version as v1 whatever the tick order', () => {
    expect(compareHref([v2, v1])).toBe('/tenant/acme/orders/compare?v1=1.0.0&v2=2.0.0');
    expect(compareHref([v1, v2])).toBe('/tenant/acme/orders/compare?v1=1.0.0&v2=2.0.0');
    expect(compareLabel([v2, v1])).toBe('Compare v1.0.0 → v2.0.0');
  });

  it('mixes kinds of one project (an operation and a version hit)', () => {
    const versionHit = hit({ hit_id: 'version:2', hit_type: 'version', method: null, path: null, version_slug: '2.0.0', published_at: '2026-06-01T00:00:00Z' });
    expect(compareHref([v1, versionHit])).toBe('/tenant/acme/orders/compare?v1=1.0.0&v2=2.0.0');
  });

  it('keeps tick order when a date is missing', () => {
    const a = hit({ hit_id: 'a', version_slug: '2.0.0', published_at: null });
    expect(orderForCompare([a, v1])).toEqual([a, v1]);
  });

  it('encodes slugs', () => {
    const a = hit({ hit_id: 'a', tenant_slug: 'a b', version_slug: '1.0 beta' });
    const b = hit({ hit_id: 'b', tenant_slug: 'a b', version_slug: '2.0', published_at: '2027-01-01T00:00:00Z' });
    expect(compareHref([a, b])).toBe('/tenant/a%20b/orders/compare?v1=1.0+beta&v2=2.0');
  });

  it('is null until the selection is complete and valid', () => {
    expect(compareHref([])).toBeNull();
    expect(compareHref([v1])).toBeNull();
    expect(compareHref([v1, hit({ hit_id: 'x', version_slug: '1.0.0' })])).toBeNull();
    expect(compareHref([v1, hit({ hit_id: 'x', project_slug: 'billing', version_slug: '2.0.0' })])).toBeNull();
    expect(compareLabel([v1])).toBeNull();
  });
});

describe('version menu', () => {
  const versions: HitVersion[] = [
    { version_slug: '3.0.0', published_at: '2026-09-01T00:00:00Z', has_anchor: false },
    { version_slug: '2.0.0', published_at: '2026-06-01T00:00:00Z', has_anchor: true },
    { version_slug: '1.0.0', published_at: '2026-01-01T00:00:00Z', has_anchor: true },
  ];

  it('computes the anchor of operation and schema hits only', () => {
    expect(hitAnchor(v1)).toBe('op-post-orders');
    expect(hitAnchor(hit({ hit_type: 'schema', anchor_key: 'Order' }))).toBe('schema-Order');
    expect(hitAnchor(hit({ hit_type: 'version' }))).toBeNull();
  });

  it('lists the other versions, landing on the anchor where the operation exists', () => {
    expect(versionMenuEntries(v1, versions)).toEqual([
      { versionSlug: '3.0.0', href: '/tenant/acme/orders/3.0.0', atAnchor: false, missing: true },
      { versionSlug: '2.0.0', href: '/tenant/acme/orders/2.0.0#op-post-orders', atAnchor: true, missing: false },
    ]);
  });

  it('links version hits to the version pages', () => {
    const versionHit = hit({ hit_type: 'version', method: null, path: null, version_slug: '2.0.0' });
    const entries = versionMenuEntries(versionHit, versions.map((v) => ({ ...v, has_anchor: null })));
    expect(entries.map((e) => e.href)).toEqual(['/tenant/acme/orders/3.0.0', '/tenant/acme/orders/1.0.0']);
    expect(entries.every((e) => !e.missing && !e.atAnchor)).toBe(true);
  });

  it('is empty without a lookup or for ineligible hits', () => {
    expect(versionMenuEntries(v1, undefined)).toEqual([]);
    expect(versionMenuEntries(hit({ hit_type: 'project' }), versions)).toEqual([]);
    expect(versionMenuEntries(v1, [versions[2]])).toEqual([]);
  });
});

describe('buildHitVersionsSql', () => {
  it('is null when no row is eligible', () => {
    expect(buildHitVersionsSql([])).toBeNull();
    expect(buildHitVersionsSql([hit({ hit_type: 'project' })])).toBeNull();
  });

  it('binds eligible rows as six parallel arrays and a per-hit limit, behind the public gates', () => {
    const schema = hit({ hit_id: 'schema:5', hit_type: 'schema', method: null, path: null, anchor_key: 'Order' });
    const versionHit = hit({ hit_id: 'version:7', hit_type: 'version', method: null, path: null });
    const statement = buildHitVersionsSql([v1, hit({ hit_id: 'p', hit_type: 'project' }), schema, versionHit]);
    expect(statement).not.toBeNull();
    expect(statement!.values).toEqual([
      ['op:1', 'schema:5', 'version:7'],
      ['acme', 'acme', 'acme'],
      ['orders', 'orders', 'orders'],
      ['operation', 'schema', 'version'],
      ['POST', null, null],
      ['/orders', 'Order', null],
      HIT_VERSIONS_CAP,
    ]);
    expect(statement!.text).toContain("v.visibility = 'public'");
    expect(statement!.text).toContain('v.published = true');
    expect(statement!.text).toContain('v.deleted_at IS NULL');
    expect(statement!.text).toMatch(/ORDER BY pv\.published_at DESC NULLS LAST/);
    // Only $1..$7 are bound, whatever the page size.
    expect(statement!.text.match(/\$\d+/g)?.every((p) => Number(p.slice(1)) <= 7)).toBe(true);
    expect(statement!.text).toContain('t.deleted_at IS NULL');
    expect(statement!.text).toContain('p.deleted_at IS NULL');
  });

  it('reads a bounded number of versions per hit, and the project total from the summary (DBP-1.27)', () => {
    const statement = buildHitVersionsSql([v1])!;
    expect(statement.text).toContain('JOIN apiome.browse_public_projects b ON b.project_id = p.id');
    expect(statement.text).toContain('SELECT w.hit_id, w.version_count,');
    expect(statement.text).toMatch(/ORDER BY v\.published_at DESC NULLS LAST, v\.created_at DESC\s+LIMIT \$7/);
    // The "show all" request asks for the long list of one hit.
    expect(buildHitVersionsSql([v1], HIT_VERSIONS_ALL_CAP)!.values[6]).toBe(HIT_VERSIONS_ALL_CAP);
    expect(HIT_VERSIONS_CAP).toBeLessThan(HIT_VERSIONS_ALL_CAP);
  });

  it('counts the versions a menu does not list', () => {
    const listed = [{ version_slug: '2.0.0', published_at: null, has_anchor: null }];
    expect(moreVersionsCount(listed, 1)).toBe(0);
    expect(moreVersionsCount(listed, 45)).toBe(44);
    expect(moreVersionsCount(undefined, undefined)).toBe(0);
    expect(moreVersionsCount(listed, 0)).toBe(0);
  });
});
