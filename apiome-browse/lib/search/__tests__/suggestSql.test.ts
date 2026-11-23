/**
 * The search palette's suggestion statement (DBP-1.16, #7199): names only, index-shaped
 * predicates, every pass bounded. The statement's speed was measured on the scale database; these
 * tests keep its shape — and the expressions the trigram indexes of V424 depend on — from drifting.
 */

import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';
import { resolveSearchRequest } from '../params';
import {
  OPERATION_NAME_EXPR,
  PROJECT_NAME_EXPR,
  SHORT_QUERY_KINDS,
  SUGGEST_CANDIDATE_CAP,
  SUGGEST_KINDS,
  SUGGEST_MEMBER_CAP,
  SUGGEST_RECENT_SCAN_CAP,
  SUGGEST_RECENT_VERSIONS,
  buildSuggestSql,
  suggestKinds,
} from '../suggestSql';

type UrlState = Parameters<typeof resolveSearchRequest>[0];

function request(state: UrlState) {
  return { ...resolveSearchRequest(state), perPage: 8, page: 1 };
}

function build(state: UrlState) {
  const statement = buildSuggestSql(request(state));
  if (!statement) throw new Error('expected a statement');
  return statement;
}

/** The `$n` placeholder a value is bound to. */
function slot(values: unknown[], value: unknown): string {
  const index = values.findIndex((v) => JSON.stringify(v) === JSON.stringify(value));
  if (index < 0) throw new Error(`value not bound: ${JSON.stringify(value)}`);
  return `$${index + 1}`;
}

describe('suggestKinds', () => {
  it('suggests the kinds a visitor navigates to by name', () => {
    expect(suggestKinds(request({ q: 'order' }))).toEqual([...SUGGEST_KINDS]);
    expect(SUGGEST_KINDS).toEqual(['organization', 'product', 'project', 'operation', 'schema', 'property']);
  });

  it('honours the scope tab and a type: filter', () => {
    expect(suggestKinds(request({ q: 'order', scope: 'schemas' }))).toEqual(['schema', 'property']);
    expect(suggestKinds(request({ q: 'order type:operation' }))).toEqual(['operation']);
  });

  it('drops kinds that cannot honour a filter', () => {
    expect(suggestKinds(request({ q: 'order method:POST' }))).toEqual(['operation']);
    // A version filter rules out API products, which are not versions of a project.
    expect(suggestKinds(request({ q: 'order format:openapi' }))).not.toContain('product');
  });

  it('suggests nothing for a filter only changelog entries can honour', () => {
    expect(suggestKinds(request({ q: 'order severity:breaking' }))).toEqual([]);
    expect(buildSuggestSql(request({ q: 'order severity:breaking' }))).toBeNull();
  });
});

describe('buildSuggestSql', () => {
  it('matches names only: no description, note or stored JSON is searched', () => {
    const { text } = build({ q: 'order' });
    const predicates = text.match(/[^\n]* ILIKE \$\d+ ESCAPE[^\n]*/g) ?? [];
    expect(predicates.length).toBeGreaterThan(0);
    for (const predicate of predicates) {
      // (`path_operation_description` is a table name; the column `description` is never matched.)
      expect(predicate).not.toMatch(/\.description|change_log|commit_message|\.schema|\.data|metadata|concat_ws/);
    }
  });

  it('puts one ILIKE per word on the bare indexed expression', () => {
    const { text, values } = build({ q: 'create order' });
    const create = slot(values, '%create%');
    const order = slot(values, '%order%');
    for (const expr of ['c.name', 'cp.name', 'vp.pathname', PROJECT_NAME_EXPR, OPERATION_NAME_EXPR]) {
      expect(text).toContain(`${expr} ILIKE ${create} ESCAPE '\\'`);
      expect(text).toContain(`${expr} ILIKE ${order} ESCAPE '\\'`);
    }
  });

  it('uses exactly the expressions the V424 trigram indexes are built on', () => {
    const migration = fs
      .readFileSync(
        path.resolve(__dirname, '../../../../apiome-db/scripts/V424__public_browse_counts_and_name_search_7199.sql'),
        'utf8'
      )
      .replace(/\s+/g, ' ');
    // The builder writes the same expressions with a table alias in front of each column.
    const unaliased = (expr: string) => expr.replace(/\b(p|pod)\./g, '');
    expect(migration).toContain(`ON apiome.projects USING gin (${unaliased(PROJECT_NAME_EXPR)} gin_trgm_ops)`);
    expect(migration).toContain(`USING gin (${unaliased(OPERATION_NAME_EXPR)} gin_trgm_ops)`);
    expect(migration).toContain('ON apiome.classes USING gin (name gin_trgm_ops)');
    expect(migration).toContain('ON apiome.class_properties USING gin (name gin_trgm_ops)');
    expect(migration).toContain('ON apiome.version_path USING gin (pathname gin_trgm_ops)');
  });

  it('adds an exact-name pass ahead of the contains pass', () => {
    const { text, values } = build({ q: 'Pet Store' });
    const exact = slot(values, 'Pet Store');
    expect(text).toContain(`c.name ILIKE ${exact} ESCAPE '\\'`);
    expect(text).toContain(`vp.pathname ILIKE ${exact} ESCAPE '\\'`);
    // An operation id ends the indexed expression; a project slug ends its expression too.
    expect(text).toContain(`${OPERATION_NAME_EXPR} ILIKE ${slot(values, '% Pet Store')} ESCAPE '\\'`);
    expect(text).toContain(`${PROJECT_NAME_EXPR} ILIKE ${slot(values, '% Pet Store')} ESCAPE '\\'`);
    expect(text).toContain(`${PROJECT_NAME_EXPR} ILIKE ${slot(values, 'Pet Store %')} ESCAPE '\\' AND p.name ILIKE ${exact}`);
    // Exact candidates are read first, so the sub-select's LIMIT keeps them.
    const schema = text.slice(text.indexOf("'schema' AS hit_type"));
    expect(schema.indexOf(`c.name ILIKE ${exact}`)).toBeLessThan(schema.indexOf(`c.name ILIKE ${slot(values, '%Pet%')}`));
  });

  it('escapes LIKE metacharacters in every pattern', () => {
    const { values } = build({ q: '50%_off' });
    expect(values).toContain('%50\\%\\_off%');
    expect(values).toContain('50\\%\\_off');
  });

  it('negates with NOT on the same expression', () => {
    const { text, values } = build({ q: 'order -draft' });
    expect(text).toContain(`NOT (c.name ILIKE ${slot(values, '%draft%')} ESCAPE '\\')`);
  });

  it('bounds every pass: candidates read, rows kept, recent versions examined', () => {
    const { text, values } = build({ q: 'order' });
    const candidates = slot(values, SUGGEST_CANDIDATE_CAP);
    const kept = slot(values, SUGGEST_MEMBER_CAP);
    // Every sub-select that reads a name column stops at the candidate cap…
    const nameScans = text.match(/FROM apiome\.(projects p|classes c|class_properties cp|version_path vp|path_operation_description pod) WHERE[\s\S]*?LIMIT (\$\d+)/g) ?? [];
    expect(nameScans.length).toBe(10); // five tables, exact + contains
    for (const scan of nameScans) expect(scan.endsWith(`LIMIT ${candidates}`)).toBe(true);
    // …and every member of the union stops at the member cap.
    const members = text.slice(text.indexOf('WITH'), text.indexOf('hits AS')).split('UNION ALL\n        (');
    expect(members.length).toBe(10); // org, product, project, 3 × operation, 2 × schema, 2 × property
    for (const member of members) expect(member).toMatch(new RegExp(`LIMIT \\${kept}\\)\\s*(\\) m\\s*\\),\\s*)?$`));
    expect(text).toContain(`LIMIT ${slot(values, SUGGEST_RECENT_SCAN_CAP)}) r`);
    expect(text).toContain(`LIMIT ${slot(values, SUGGEST_RECENT_VERSIONS)}`);
  });

  it('checks the scope per candidate: public, and the latest version of its project', () => {
    const { text } = build({ q: 'order' });
    expect(text).not.toContain('ROW_NUMBER() OVER (PARTITION BY');
    expect(text).toContain("v.visibility = 'public'");
    expect(text).toContain('AND v.id = (SELECT l_v.id');
    expect(text).toContain('ORDER BY l_v.published_at DESC NULLS LAST, l_v.created_at DESC');
  });

  it('searches every published version when asked', () => {
    const statement = buildSuggestSql({ ...request({ q: 'order', all: '1' }) });
    // A project hit always describes the project's latest version; the candidates are no longer limited to it.
    expect(statement?.text).not.toContain('AND v.id = (SELECT l_v.id');
    expect(statement?.text).toContain('ON v.id = (SELECT l_v.id');
  });

  it('applies the query\'s filters to the version of each candidate', () => {
    const { text, values } = build({ q: 'order org:acme format:openapi after:2026-01' });
    const org = slot(values, ['acme']);
    expect(text).toContain(`(t.slug = ANY(${org}::text[]) OR LOWER(t.name) = ANY(${org}::text[]))`);
    expect(text).toContain(`LOWER(TRIM(COALESCE(v.source_format, ''))) = ANY(${slot(values, ['openapi'])}::text[])`);
    expect(text).toContain(`v.published_at >= ${slot(values, '2026-01-01')}::date`);
  });

  it('looks inside the most recently published versions in scope, so a common word still finds something', () => {
    const { text } = build({ q: 'order' });
    expect(text).toContain('recent_scope AS MATERIALIZED');
    expect(text).toContain('ORDER BY r_v.published_at DESC NULLS LAST, r_v.created_at DESC');
    expect(text).toContain('JOIN apiome.classes c ON c.version_id = rs.version_pk AND c.deleted_at IS NULL');
    expect(text).toContain('JOIN apiome.version_path vp ON vp.version_id = rs.version_pk');
  });

  it('starts the recent scope from the named owner\'s projects when the query has an org: or project: filter', () => {
    const { text, values } = build({ q: 'order org:acme format:openapi' });
    const scope = text.slice(text.indexOf('recent_scope AS MATERIALIZED'), text.indexOf('members AS'));
    const org = slot(values, ['acme']);
    // One latest-version probe per project of that organization — no walk of everyone's versions —
    // over a bounded number of its newest projects.
    expect(scope).toContain('FROM apiome.projects p');
    expect(scope).toContain(`(t.slug = ANY(${org}::text[]) OR LOWER(t.name) = ANY(${org}::text[]))`);
    expect(scope).toContain(`ORDER BY p.created_at DESC, p.id DESC\n               LIMIT ${slot(values, SUGGEST_RECENT_SCAN_CAP)}) rp`);
    expect(scope).toContain('JOIN apiome.versions v ON v.id = (SELECT l_v.id');
    expect(scope).toContain('WHERE l_v.project_id = rp.id');
    // A filter on the version itself applies to those latest versions.
    expect(scope).toContain(`WHERE (LOWER(TRIM(COALESCE(v.source_format, ''))) = ANY(${slot(values, ['openapi'])}::text[])`);
    expect(scope).not.toContain('r_v');
    expect(scope).toContain(`LIMIT ${slot(values, SUGGEST_RECENT_VERSIONS)}`);
    const byProject = build({ q: 'order project:payments' }).text;
    expect(byProject).toContain('p.slug = ANY(');
    expect(byProject).toContain(') rp\n        JOIN apiome.versions v');
  });

  it('runs only the recent pass for large-table kinds until a word has three characters', () => {
    const { text } = build({ q: 'id' });
    expect(SHORT_QUERY_KINDS).toEqual(['organization', 'product', 'project']);
    // No name scan of the large tables…
    expect(text).not.toMatch(/FROM apiome\.(classes c|class_properties cp|version_path vp|path_operation_description pod) WHERE/);
    // …but projects are still matched by name, and the recent versions are still searched.
    expect(text).toContain('FROM apiome.projects p WHERE p.deleted_at IS NULL AND');
    expect(text).toContain('FROM recent_scope rs');
    // One long word is enough for the index to narrow the scan.
    expect(build({ q: 'id order' }).text).toContain('FROM apiome.classes c WHERE');
  });

  it('skips the exact pass when the query has no words', () => {
    const { text } = build({ q: 'org:acme' });
    expect(text).toContain('FROM apiome.projects p WHERE p.deleted_at IS NULL AND TRUE');
    expect(text).not.toContain('UNION ALL\n                (SELECT p.id');
  });

  it('leaves the recent scope out when no kind uses it', () => {
    expect(build({ q: 'acme', scope: 'catalog' }).text).not.toContain('recent_scope');
  });

  it('de-duplicates a row two passes found and returns one page, ranked like the results page', () => {
    const { text, values } = build({ q: 'order' });
    expect(text).toContain('SELECT DISTINCT ON (hit_id) * FROM members ORDER BY hit_id, rank DESC');
    expect(text).toContain('ORDER BY rank DESC, published_at DESC NULLS LAST, title ASC');
    expect(text).toContain(`LIMIT ${slot(values, 8)}`);
    expect(text).toContain('AS kind_facets');
  });
});
