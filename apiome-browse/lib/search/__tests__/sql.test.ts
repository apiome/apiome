import { describe, expect, it } from 'vitest';
import { resolveSearchRequest } from '../params';
import { SEARCH_HIT_CAP, applicableKinds, buildCatalogSearchSql, escapeLikePattern, orderBySql } from '../sql';
import { HIT_KINDS } from '../kinds';

function build(state: Parameters<typeof resolveSearchRequest>[0]) {
  const statement = buildCatalogSearchSql(resolveSearchRequest(state));
  if (!statement) throw new Error('expected a statement');
  return statement;
}

describe('escapeLikePattern', () => {
  it('escapes LIKE metacharacters', () => {
    expect(escapeLikePattern('a%b_c\\d')).toBe('a\\%b\\_c\\\\d');
  });
});

describe('applicableKinds', () => {
  it('runs every member by default', () => {
    expect(applicableKinds(resolveSearchRequest({ q: 'x' }))).toEqual([...HIT_KINDS]);
  });

  it('narrows to operations for a method filter and to path kinds for a path filter', () => {
    expect(applicableKinds(resolveSearchRequest({ q: 'x method:GET' }))).toEqual(['operation']);
    expect(applicableKinds(resolveSearchRequest({ q: 'x path:/pets' }))).toEqual([
      'operation',
      'parameter',
      'request_body',
      'response',
    ]);
  });
});

describe('buildCatalogSearchSql', () => {
  it('returns null when the scope and the filters leave nothing to run', () => {
    expect(buildCatalogSearchSql(resolveSearchRequest({ q: 'x method:GET', scope: 'schemas' }))).toBeNull();
  });

  it('binds every word as its own ILIKE pattern and negations as NOT', () => {
    const { text, values } = build({ q: 'create order -draft' });
    expect(values).toContain('%create%');
    expect(values).toContain('%order%');
    expect(values).toContain('%draft%');
    const draftSlot = `$${values.indexOf('%draft%') + 1}`;
    expect(text).toContain(`NOT (concat_ws(' ', COALESCE(sv.project_name::text, '')`);
    expect(text).toContain(`ILIKE ${draftSlot} ESCAPE '\\')`);
  });

  it('restricts to each project\'s latest version unless all versions are asked for', () => {
    expect(build({ q: 'x' }).text).toContain('sc.version_rank = 1');
    expect(build({ q: 'x', all: '1' }).text).not.toContain('sc.version_rank = 1');
  });

  it('applies the scope filters with array parameters', () => {
    const { text, values } = build({
      q: 'x org:acme project:payments version:2. format:openapi paradigm:rest tag:stable after:2026-01 before:2026-07',
    });
    expect(values).toContainEqual(['acme']);
    expect(values).toContainEqual(['payments']);
    expect(values).toContainEqual(['openapi']);
    expect(values).toContainEqual(['openapi-%']);
    expect(values).toContainEqual(['rest']);
    expect(values).toContainEqual(['stable']);
    expect(values).toContain('2026-01-01');
    expect(values).toContain('2026-07-01');
    expect(text).toContain('sc.tenant_slug = ANY(');
    expect(text).toContain('sc.source_format LIKE ANY(');
    expect(text).toContain('FROM apiome.version_tags vt');
    expect(text).toContain('sc.published_at >= ');
    expect(text).toContain('sc.published_at < ');
    expect(text).toContain("sc.version_slug ILIKE");
  });

  it('applies method and path filters inside the operation member', () => {
    const { text, values } = build({ q: 'x method:GET path:/pets' });
    expect(values).toContainEqual(['GET']);
    expect(values).toContain('%/pets%');
    expect(text).toContain('UPPER(po.operation) = ANY(');
    expect(text).toContain('vp.pathname ILIKE');
    // Only the operation member runs, so no schema member is in the union.
    expect(text).not.toContain("'schema' AS hit_type");
  });

  it('filters the page by the requested kinds while counting every kind', () => {
    const { text, values } = build({ q: 'x', scope: 'schemas' });
    expect(values).toContainEqual(['schema', 'property']);
    expect(text).toContain('hit_type = ANY(');
    expect(text).toContain('FROM hits_all GROUP BY 1) x), \'[]\'::json) AS kind_facets');
    expect(text).toContain('(SELECT COUNT(*)::int FROM hits_all) AS total_all_kinds');
  });

  it('pages with the request\'s page size and offset, and caps the corpus', () => {
    const { values } = build({ q: 'x', page: '3' });
    expect(values).toContain(25);
    expect(values).toContain(50);
    expect(values).toContain(SEARCH_HIT_CAP);
  });

  it('ranks with exact / prefix / contains tiers plus the kind weight', () => {
    const { text, values } = build({ q: 'Pet Store' });
    expect(values).toContain('pet store');
    expect(values).toContain('pet store%');
    expect(values).toContain('%pet store%');
    expect(text).toMatch(/THEN 100\s+WHEN LOWER\(sv\.project_name\) LIKE/);
    expect(text).toContain('GREATEST(10,');
  });

  it('uses the kind weight alone when there is nothing to rank by', () => {
    const { text } = build({ method: 'DELETE' });
    expect(text).toContain('8 AS rank');
    expect(text).not.toContain('GREATEST(10,');
  });

  it('orders per sort mode', () => {
    expect(orderBySql('relevance')).toBe('rank DESC, published_at DESC NULLS LAST, title ASC');
    expect(orderBySql('newest')).toBe('published_at DESC NULLS LAST, rank DESC, title ASC');
    expect(orderBySql('oldest')).toBe('published_at ASC NULLS LAST, rank DESC, title ASC');
    expect(orderBySql('name')).toBe('LOWER(name_key) ASC, rank DESC, published_at DESC NULLS LAST');
    expect(build({ q: 'x', sort: 'name' }).text).toContain('ORDER BY LOWER(name_key) ASC');
  });

  it('reuses a parameter slot for a repeated value', () => {
    const { values } = build({ q: 'pet' });
    expect(values.filter((v) => v === '%pet%')).toHaveLength(1);
  });

  it('never interpolates user text into the statement', () => {
    const { text } = build({ q: `pet'); DROP TABLE apiome.versions; --` });
    expect(text).not.toContain('DROP TABLE');
  });
});

describe('change member (BDX-1.4)', () => {
  it('joins the classified changelog through the scope and unnests its entries', () => {
    const { text } = build({ q: 'status' });
    expect(text).toContain("'change' AS hit_type");
    expect(text).toContain('JOIN apiome.version_changelogs vc ON vc.published_revision_id = sv.version_pk');
    expect(text).toContain('jsonb_array_elements(');
    expect(text).toContain('WITH ORDINALITY AS e(entry, ord)');
  });

  it('contributes nothing (and does not fail) for a payload without an entries array', () => {
    const { text } = build({ q: 'status' });
    // The inner join drops versions with no row; the typeof guard turns a missing or non-array
    // `entries` (initial publication, failed run) into an empty set instead of an error.
    expect(text).toContain("CASE WHEN jsonb_typeof(vc.changelog_json -> 'entries') = 'array'");
    expect(text).toContain("ELSE '[]'::jsonb END");
  });

  it('folds unknown severities into docs-only and projects a severity column on every member', () => {
    const { text } = build({ q: 'x' });
    expect(text).toContain("IN ('breaking', 'non-breaking')");
    expect(text).toContain("ELSE 'docs-only' END AS severity");
    expect(text.match(/NULL::text AS severity/g)?.length).toBe(HIT_KINDS.length - 1);
    expect(text).toContain('AS severity_facets');
  });

  it('matches the summary, pointer (escaped and not), path group, rule and change kind', () => {
    const { text } = build({ q: 'status' });
    expect(text).toContain(
      "concat_ws(' ', COALESCE(ch.summary::text, ''), COALESCE(ch.pointer::text, ''), COALESCE(ch.pointer_text::text, ''), COALESCE(ch.path_group_text::text, ''), COALESCE(ch.rule_id::text, ''), COALESCE(ch.change_kind::text, ''))"
    );
    expect(text).toContain("replace(replace(COALESCE(e.entry ->> 'pointer', ''), '~1', '/'), '~0', '~') AS pointer_text");
    // The hit shows the stored pointer, the same string the Changes tab prints.
    expect(text).toContain("NULLIF(ch.pointer, '') AS subtitle");
  });

  it('ranks severity first and text second', () => {
    const { text } = build({ q: 'status' });
    expect(text).toContain("CASE ch.severity WHEN 'breaking' THEN 60");
    expect(text).toContain("WHEN 'non-breaking' THEN 30");
    expect(text).toMatch(/\+ \(GREATEST\(10, [\s\S]*?\)\) \/ 4\) AS rank/);
    // Without words, the severity bonus plus the kind weight alone orders.
    expect(build({ q: 'type:change' }).text).toMatch(/ELSE 0 END \+ 1\) AS rank/);
  });

  it('applies a severity filter and narrows the run to change hits', () => {
    const query = 'severity:breaking status after:2026';
    expect(applicableKinds(resolveSearchRequest({ q: query }))).toEqual(['change']);
    const { text, values } = build({ q: query });
    expect(values).toContainEqual(['breaking']);
    expect(values).toContain('2026-01-01');
    expect(values).toContain('%status%');
    const slot = `$${values.findIndex((v) => JSON.stringify(v) === '["breaking"]') + 1}`;
    expect(text).toContain(`ch.severity = ANY(${slot}::text[])`);
    expect(text).toContain('sc.published_at >= ');
    expect(text).not.toContain("'operation' AS hit_type");
  });

  it('does not run when a severity filter meets a kind that carries none', () => {
    expect(buildCatalogSearchSql(resolveSearchRequest({ q: 'severity:breaking method:GET' }))).toBeNull();
    expect(buildCatalogSearchSql(resolveSearchRequest({ q: 'severity:breaking', scope: 'schemas' }))).toBeNull();
  });

  it('selects the kind with type:change and its aliases', () => {
    expect(resolveSearchRequest({ q: 'type:change' }).kinds).toEqual(['change']);
    expect(resolveSearchRequest({ q: 'type:changelog' }).kinds).toEqual(['change']);
  });
});

describe('project hit facts (BDX-2.2)', () => {
  it('joins the card facts to the page rows only, keyed to the project hit\'s version', () => {
    const { text } = build({ q: 'payments' });
    const pageFacts = text.slice(text.indexOf('page_facts AS ('));
    expect(pageFacts).toContain('FROM page pg');
    expect(pageFacts).toContain("pg.hit_type = 'project'");
    expect(pageFacts).toContain("pg.hit_id = 'project:' || sv.project_id::text");
    expect(pageFacts).toContain('WHERE f_v.id = fv.version_pk');
    expect(pageFacts).toContain('to_jsonb(cf) AS facts');
    expect(text).toContain("json_agg(to_jsonb(pf) - 'ord' ORDER BY pf.ord) FROM page_facts pf");
  });
});
