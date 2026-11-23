/**
 * The search palette's suggestion SQL (DBP-1.16, #7199).
 *
 * The palette asks on every keystroke, so its statement is built for one thing: a handful of good
 * *name* matches, fast, at any catalog size. It differs from the results page's statement
 * (`./sql.ts`) in three ways:
 *
 * 1. **Names only.** Words match what a thing is called — an organization, API product or project
 *    name or slug, a path, an operation's summary or id, a schema, a property — never descriptions,
 *    notes or changelog entries. Only the kinds in {@link SUGGEST_KINDS} are suggested; the results
 *    page still finds the rest (tags, parameters, bodies, responses, version notes, changes).
 * 2. **Index-driven.** A sub-select starts from the name column, with one `ILIKE` per word on
 *    exactly the expression a GIN trigram index covers (V424; the expressions below must stay
 *    identical to that migration's). The version scope — published, public, the project's latest
 *    unless every version was asked for, plus the query's filters — is checked per candidate row,
 *    not computed for the whole catalog first.
 * 3. **Bounded.** No sub-select can turn into a pass over the catalog, whatever the word. Each
 *    kind is looked up in up to three passes, and each pass has a hard bound:
 *
 *    - *exact* — names that are exactly what was typed: reads at most
 *      {@link SUGGEST_CANDIDATE_CAP} of them;
 *    - *contains* — names containing every word: reads at most {@link SUGGEST_CANDIDATE_CAP}
 *      matches. Complete for a rare word; an arbitrary sample for a common one. Exact and contains
 *      candidates share one sub-select, exact first, which keeps the {@link SUGGEST_MEMBER_CAP}
 *      that are in scope;
 *    - *recent* (operations, schemas, properties) — the same match, inside the
 *      {@link SUGGEST_RECENT_VERSIONS} most recently published versions in scope. This is what
 *      finds a common word: a sample of everything named `…user…` is mostly private or superseded
 *      versions, while the newest public versions are in scope by construction.
 *
 *    Ranking, kind weights and ordering are the results page's.
 *
 * Two consequences a caller should know:
 *
 * - The per-kind counts are floors: a kind that reached its cap is reported as capped and the
 *   palette shows "40+". For a common word the passes can miss in-scope names that the results
 *   page would list.
 * - A trigram needs three characters. Until some word of the query has three, the *exact* and
 *   *contains* passes run only for organizations, API products and projects
 *   ({@link SHORT_QUERY_KINDS}); the other kinds live in tables too large to scan per keystroke
 *   and are then served by the *recent* pass alone.
 *
 * Pure; `lib/db/search.ts` runs it. Unit-tested in `lib/search/__tests__/suggestSql.test.ts`.
 */

import { PORTAL_PRODUCT_ROW_GATES } from '../products/sql';
import type { HitKind } from './kinds';
import type { SearchRequest } from './params';
import {
  HIT_COLUMNS,
  PUBLIC_VERSION_GATES,
  Params,
  applicableKinds,
  escapeLikePattern,
  orderBySql,
  pathFilters,
  rankExpr,
  scopeFilterClauses,
  type ScopeColumns,
  type SqlStatement,
} from './sql';

/** Most rows one kind contributes from its "contains" pass, and from its "recent" pass. */
export const SUGGEST_MEMBER_CAP = 40;

/** Most name matches one sub-select reads before it checks which are in scope. */
export const SUGGEST_CANDIDATE_CAP = 1000;

/** How many of the most recently published in-scope versions the "recent" pass looks inside. */
export const SUGGEST_RECENT_VERSIONS = 25;

/** Most public versions (or, with an owner filter, projects), newest first, the "recent" pass examines. */
export const SUGGEST_RECENT_SCAN_CAP = 500;

/** The kinds the palette suggests: the things a visitor navigates to by name. */
export const SUGGEST_KINDS: readonly HitKind[] = ['organization', 'product', 'project', 'operation', 'schema', 'property'];

/** The kinds whose name passes run while no word of the query has three characters (see the module comment). */
export const SHORT_QUERY_KINDS: readonly HitKind[] = ['organization', 'product', 'project'];

/** Shortest word a trigram index can serve. */
const MIN_TRIGRAM_LENGTH = 3;

/** `(name || ' ' || slug)` of a project — the expression `idx_projects_name_slug_trgm` indexes. */
export const PROJECT_NAME_EXPR = `(p.name || ' ' || p.slug)`;

/** An operation's summary and id — the expression `idx_path_operation_description_name_trgm` indexes. */
export const OPERATION_NAME_EXPR = `(COALESCE(pod.summary, '') || ' ' || COALESCE(pod.operation_id, ''))`;

/** The scope-filter columns of a version `v` of a project `p` of a tenant `t`. */
const VERSION_ROW_COLUMNS: ScopeColumns = {
  versionPk: 'v.id',
  versionSlug: 'v.version_id',
  publishedAt: 'v.published_at',
  tenantSlug: 't.slug',
  tenantName: 't.name',
  projectSlug: 'p.slug',
  projectName: 'p.name',
  sourceFormat: `LOWER(TRIM(COALESCE(v.source_format, '')))`,
  paradigm: `LOWER(TRIM(COALESCE(v.protocol, '')))`,
};

/** The latest published public version of the project with primary key `projectPkExpr`. */
function latestVersionIdSql(projectPkExpr: string): string {
  return `(SELECT l_v.id
             FROM apiome.versions l_v
            WHERE l_v.project_id = ${projectPkExpr}
              AND l_v.published = true
              AND l_v.visibility = 'public'
              AND l_v.deleted_at IS NULL
            ORDER BY l_v.published_at DESC NULLS LAST, l_v.created_at DESC
            LIMIT 1)`;
}

/**
 * Which sub-select a member is asked for: the name passes (exact and contains, which share one
 * sub-select so their joins are planned once), or the pass over the recent versions in scope.
 */
type Tier = 'name' | 'recent';

interface Build {
  request: SearchRequest;
  params: Params;
  /** The `$n` slot holding {@link SUGGEST_CANDIDATE_CAP}. */
  candidateCap: string;
}

/**
 * The candidate rows of a name sub-select: the exact pass, then the contains pass, each reading at
 * most {@link SUGGEST_CANDIDATE_CAP} rows. Exact rows come first, so the sub-select's own LIMIT
 * keeps them. A row both passes find appears twice; the statement de-duplicates hits at the end.
 *
 * @param build - The statement being built.
 * @param columns - The SELECT list (table-qualified columns the outer query reads).
 * @param from - The FROM clause, with any predicate every row must pass (ending in `WHERE …`).
 * @param exact - The exact-name predicate, or null when the member has no exact pass.
 * @param contains - The contains predicate.
 * @returns A parenthesized row source; the caller gives it the table's alias.
 */
function candidatesSql(build: Build, columns: string, from: string, exact: string | null, contains: string): string {
  const pass = (predicate: string) =>
    `SELECT ${columns}
                  ${from} ${predicate}
                 LIMIT ${build.candidateCap}`;
  if (!exact || needles(build.request).length === 0) return `(${pass(contains)})`;
  return `((${pass(exact)})
                UNION ALL
                (${pass(contains)}))`;
}

/** The words and phrases a name must contain. */
function needles(request: SearchRequest): string[] {
  return [...request.parsed.terms, ...request.parsed.phrases];
}

/**
 * "Every word appears in `expr`, no negated word does" — one `ILIKE` per word, each on the bare
 * expression so a trigram index on it applies. `TRUE` when the query has no words.
 */
function containsSql(expr: string, { request, params }: Build): string {
  const clauses: string[] = [];
  for (const needle of needles(request)) {
    clauses.push(`${expr} ILIKE ${params.add(`%${escapeLikePattern(needle)}%`)} ESCAPE '\\'`);
  }
  for (const needle of request.parsed.negated) {
    clauses.push(`NOT (${expr} ILIKE ${params.add(`%${escapeLikePattern(needle)}%`)} ESCAPE '\\')`);
  }
  return clauses.length > 0 ? clauses.join('\n          AND ') : 'TRUE';
}

/** The whole query text as one literal ILIKE pattern, with an optional prefix / suffix around it. */
function exactSlot({ request, params }: Build, before = '', after = ''): string {
  return params.add(`${before}${escapeLikePattern(needles(request).join(' '))}${after}`);
}

/** "`expr` is exactly what was typed" (case-insensitive). */
function exactSql(expr: string, build: Build): string {
  return `${expr} ILIKE ${exactSlot(build)} ESCAPE '\\'`;
}

/** The joins from a version primary key to its project and tenant. */
function versionJoinsSql(versionPkExpr: string): string {
  return `JOIN apiome.versions v ON v.id = ${versionPkExpr}
        JOIN apiome.projects p ON p.id = v.project_id
        JOIN apiome.tenants t ON t.id = p.tenant_id`;
}

/** The scope a version row must be in: public, latest (unless every version was asked for), filters. */
function versionScopeSql({ request, params }: Build): string {
  const clauses = [PUBLIC_VERSION_GATES];
  if (!request.allVersions) clauses.push(`v.id = ${latestVersionIdSql('v.project_id')}`);
  clauses.push(...scopeFilterClauses(request, params, VERSION_ROW_COLUMNS));
  return clauses.join('\n          AND ');
}

/** The identity columns every version-attached hit carries. */
const VERSION_HIT_IDENTITY = `t.slug AS tenant_slug, t.name AS tenant_name,
               p.slug AS project_slug, p.name AS project_name, v.version_id AS version_slug,
               v.published_at`;

/** The format / paradigm columns every version-attached hit carries. */
const VERSION_HIT_FORMAT = `NULLIF(${VERSION_ROW_COLUMNS.sourceFormat}, '') AS source_format,
               NULLIF(${VERSION_ROW_COLUMNS.paradigm}, '') AS paradigm`;

/** "This tenant publishes something in scope" — the gate for organization and product hits. */
function tenantInScopeSql(build: Build, versionFiltersApply: boolean): string {
  const { request, params } = build;
  const clauses = [
    'p.tenant_id = t.id',
    'p.deleted_at IS NULL',
    'v.published = true',
    `v.visibility = 'public'`,
    'v.deleted_at IS NULL',
  ];
  if (versionFiltersApply) {
    // Without a version filter "has a public version" and "has a latest public version" are the
    // same thing, so the latest-version probe is only paid for when a filter needs it.
    const filters = scopeFilterClauses({ ...request, orgs: [] }, params, VERSION_ROW_COLUMNS);
    if (filters.length > 0 && !request.allVersions) clauses.push(`v.id = ${latestVersionIdSql('v.project_id')}`);
    clauses.push(...filters);
  }
  return `EXISTS (SELECT 1
                    FROM apiome.projects p
                    JOIN apiome.versions v ON v.project_id = p.id
                   WHERE ${clauses.join('\n                     AND ')})`;
}

/** The `org:` filter on a tenant `t`, or null when the request has none. */
function orgFilterSql({ request, params }: Build): string | null {
  if (request.orgs.length === 0) return null;
  const slot = params.add(request.orgs);
  return `(t.slug = ANY(${slot}::text[]) OR LOWER(t.name) = ANY(${slot}::text[]))`;
}

/** One sub-select: its SQL without the LIMIT, per pass. `null` means the member has no such pass. */
type Member = (build: Build, tier: Tier) => string | null;

const ORG_NAME_EXPR = `(t.name || ' ' || t.slug)`;
const PRODUCT_NAME_EXPR = `(ap.name || ' ' || ap.slug)`;

const organizationMember: Member = (build, tier) => {
  if (tier !== 'name') return null; // Few rows: the contains pass ranks every match it keeps.
  const org = orgFilterSql(build);
  return `SELECT 'org:' || t.id::text AS hit_id, 'organization' AS hit_type,
               t.slug AS tenant_slug, t.name AS tenant_name,
               NULL::text AS project_slug, NULL::text AS project_name, NULL::text AS version_slug,
               NULL::timestamptz AS published_at,
               t.name AS title,
               LEFT(COALESCE(NULLIF(TRIM(t.description), ''), 'Organization'), 400) AS snippet,
               '/' || t.slug AS subtitle,
               NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
               NULL::text AS source_format, NULL::text AS paradigm,
               ${rankExpr('organization', ['t.name', 't.slug'], build.request, build.params)} AS rank,
               t.name AS name_key, NULL::text AS severity
          FROM apiome.tenants t
         WHERE t.deleted_at IS NULL
           AND ${containsSql(ORG_NAME_EXPR, build)}${org ? `\n           AND ${org}` : ''}
           AND ${tenantInScopeSql(build, true)}`;
};

const productMember: Member = (build, tier) => {
  if (tier !== 'name') return null;
  const org = orgFilterSql(build);
  return `SELECT 'product:' || ap.id::text AS hit_id, 'product' AS hit_type,
               t.slug AS tenant_slug, t.name AS tenant_name,
               NULL::text AS project_slug, NULL::text AS project_name, NULL::text AS version_slug,
               ap.updated_at AS published_at,
               ap.name AS title,
               LEFT(COALESCE(NULLIF(TRIM(ap.summary), ''), 'API product of ' || t.name), 400) AS snippet,
               t.name || ' · API product' AS subtitle,
               NULL::text AS method, NULL::text AS path, ap.slug AS anchor_key,
               NULL::text AS source_format, NULL::text AS paradigm,
               ${rankExpr('product', ['ap.name', 'ap.slug'], build.request, build.params)} AS rank,
               ap.name AS name_key, NULL::text AS severity
          FROM apiome.api_products ap
          JOIN apiome.tenants t ON t.id = ap.tenant_id
         WHERE ${PORTAL_PRODUCT_ROW_GATES}
           AND t.deleted_at IS NULL
           AND ${containsSql(PRODUCT_NAME_EXPR, build)}${org ? `\n           AND ${org}` : ''}
           AND ${tenantInScopeSql(build, false)}`;
};

const projectMember: Member = (build, tier) => {
  if (tier === 'recent') return null;
  const { request, params } = build;
  // Exact: the slug is the text after the last space of the indexed expression; the name is the
  // text before it, which the index narrows by prefix and the name comparison then confirms.
  const exact = `(${PROJECT_NAME_EXPR} ILIKE ${exactSlot(build, '% ')} ESCAPE '\\'
                    OR (${PROJECT_NAME_EXPR} ILIKE ${exactSlot(build, '', ' %')} ESCAPE '\\' AND ${exactSql('p.name', build)}))`;
  const filters = scopeFilterClauses(request, params, VERSION_ROW_COLUMNS);
  return `SELECT 'project:' || p.id::text AS hit_id, 'project' AS hit_type,
               ${VERSION_HIT_IDENTITY},
               p.name AS title,
               LEFT(COALESCE(NULLIF(TRIM(p.description), ''), 'Project in ' || t.name), 400) AS snippet,
               t.name AS subtitle,
               NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
               ${VERSION_HIT_FORMAT},
               ${rankExpr('project', ['p.name', 'p.slug'], request, params)} AS rank,
               p.name AS name_key, NULL::text AS severity
          FROM ${candidatesSql(
            build,
            'p.id, p.tenant_id, p.name, p.slug, p.description',
            'FROM apiome.projects p WHERE p.deleted_at IS NULL AND',
            exact,
            containsSql(PROJECT_NAME_EXPR, build)
          )} p
          JOIN apiome.tenants t ON t.id = p.tenant_id
          JOIN apiome.versions v ON v.id = ${latestVersionIdSql('p.id')}
         WHERE t.deleted_at IS NULL${filters.map((f) => `\n           AND ${f}`).join('')}`;
};

/** The SELECT list of an operation hit; `vp`, `po`, `pod`, `v`, `p`, `t` must be in scope. */
function operationSelectSql({ request, params }: Build): string {
  return `SELECT 'op:' || po.id::text AS hit_id, 'operation' AS hit_type,
               ${VERSION_HIT_IDENTITY},
               COALESCE(NULLIF(TRIM(pod.summary), ''), UPPER(po.operation) || ' ' || vp.pathname) AS title,
               LEFT(COALESCE(NULLIF(TRIM(pod.description), ''), NULLIF(TRIM(pod.operation_id), ''), ''), 400) AS snippet,
               UPPER(po.operation) || ' ' || vp.pathname AS subtitle,
               UPPER(po.operation) AS method, vp.pathname AS path, NULL::text AS anchor_key,
               ${VERSION_HIT_FORMAT},
               ${rankExpr('operation', ['vp.pathname', 'pod.summary', 'pod.operation_id', "UPPER(po.operation) || ' ' || vp.pathname"], request, params)} AS rank,
               vp.pathname AS name_key, NULL::text AS severity`;
}

/** Operations whose *path* matches. */
const operationByPathMember: Member = (build, tier) =>
  tier === 'recent'
    ? null
    : `${operationSelectSql(build)}
          FROM ${candidatesSql(
            build,
            'vp.id, vp.version_id, vp.pathname',
            'FROM apiome.version_path vp WHERE',
            exactSql('vp.pathname', build),
            containsSql('vp.pathname', build)
          )} vp
          JOIN apiome.path_operation po ON po.version_path_id = vp.id
          LEFT JOIN apiome.path_operation_description pod ON pod.path_operation_id = po.id
        ${versionJoinsSql('vp.version_id')}
         WHERE ${pathFilters(build.request, build.params, true)}
           AND ${versionScopeSql(build)}`;

/**
 * Operations whose *summary or operation id* matches. Exact means the operation id, which is the
 * text after the last space of the indexed expression.
 */
const operationByNameMember: Member = (build, tier) =>
  tier === 'recent'
    ? null
    : `${operationSelectSql(build)}
          FROM ${candidatesSql(
            build,
            'pod.path_operation_id, pod.summary, pod.description, pod.operation_id',
            'FROM apiome.path_operation_description pod WHERE',
            `${OPERATION_NAME_EXPR} ILIKE ${exactSlot(build, '% ')} ESCAPE '\\'`,
            containsSql(OPERATION_NAME_EXPR, build)
          )} pod
          JOIN apiome.path_operation po ON po.id = pod.path_operation_id
          JOIN apiome.version_path vp ON vp.id = po.version_path_id
        ${versionJoinsSql('vp.version_id')}
         WHERE ${pathFilters(build.request, build.params, true)}
           AND ${versionScopeSql(build)}`;

/** Operations of the recent versions whose path, or whose summary / id, contains every word. */
const operationRecentMember: Member = (build, tier) =>
  tier !== 'recent'
    ? null
    : `${operationSelectSql(build)}
          FROM recent_scope rs
          JOIN apiome.version_path vp ON vp.version_id = rs.version_pk
          JOIN apiome.path_operation po ON po.version_path_id = vp.id
          LEFT JOIN apiome.path_operation_description pod ON pod.path_operation_id = po.id
        ${versionJoinsSql('rs.version_pk')}
         WHERE ${pathFilters(build.request, build.params, true)}
           AND ((${containsSql('vp.pathname', build)})
             OR (${containsSql(OPERATION_NAME_EXPR, build)}))`;

/** The SELECT list of a schema hit; `c`, `v`, `p`, `t` must be in scope. */
function schemaSelectSql({ request, params }: Build): string {
  return `SELECT 'schema:' || c.id::text AS hit_id, 'schema' AS hit_type,
               ${VERSION_HIT_IDENTITY},
               c.name AS title,
               LEFT(COALESCE(NULLIF(TRIM(c.description), ''), c.schema::text, ''), 400) AS snippet,
               'Schema · v' || v.version_id AS subtitle,
               NULL::text AS method, NULL::text AS path, c.name AS anchor_key,
               ${VERSION_HIT_FORMAT},
               ${rankExpr('schema', ['c.name'], request, params)} AS rank,
               c.name AS name_key, NULL::text AS severity`;
}

const schemaMember: Member = (build, tier) =>
  tier === 'recent'
    ? `${schemaSelectSql(build)}
          FROM recent_scope rs
          JOIN apiome.classes c ON c.version_id = rs.version_pk AND c.deleted_at IS NULL
        ${versionJoinsSql('rs.version_pk')}
         WHERE ${containsSql('c.name', build)}`
    : `${schemaSelectSql(build)}
          FROM ${candidatesSql(
            build,
            'c.id, c.version_id, c.name, c.description, c.schema',
            'FROM apiome.classes c WHERE c.deleted_at IS NULL AND',
            exactSql('c.name', build),
            containsSql('c.name', build)
          )} c
        ${versionJoinsSql('c.version_id')}
         WHERE ${versionScopeSql(build)}`;

/** The SELECT list of a property hit; `cp`, `c`, `v`, `p`, `t` must be in scope. */
function propertySelectSql({ request, params }: Build): string {
  return `SELECT 'prop:' || cp.id::text AS hit_id, 'property' AS hit_type,
               ${VERSION_HIT_IDENTITY},
               c.name || '.' || cp.name AS title,
               LEFT(COALESCE(NULLIF(TRIM(cp.description), ''), cp.data::text, ''), 400) AS snippet,
               'Property of ' || c.name AS subtitle,
               NULL::text AS method, NULL::text AS path, c.name AS anchor_key,
               ${VERSION_HIT_FORMAT},
               ${rankExpr('property', ['cp.name', "c.name || '.' || cp.name"], request, params)} AS rank,
               c.name || '.' || cp.name AS name_key, NULL::text AS severity`;
}

const propertyMember: Member = (build, tier) =>
  tier === 'recent'
    ? `${propertySelectSql(build)}
          FROM recent_scope rs
          JOIN apiome.classes c ON c.version_id = rs.version_pk AND c.deleted_at IS NULL
          JOIN apiome.class_properties cp ON cp.class_id = c.id
        ${versionJoinsSql('rs.version_pk')}
         WHERE ${containsSql('cp.name', build)}`
    : `${propertySelectSql(build)}
          FROM ${candidatesSql(
            build,
            'cp.id, cp.class_id, cp.name, cp.description, cp.data',
            'FROM apiome.class_properties cp WHERE',
            exactSql('cp.name', build),
            containsSql('cp.name', build)
          )} cp
          JOIN apiome.classes c ON c.id = cp.class_id AND c.deleted_at IS NULL
        ${versionJoinsSql('c.version_id')}
         WHERE ${versionScopeSql(build)}`;

/**
 * The sub-selects of each suggested kind. A member answers the passes it has and returns `null` for
 * the others (an operation is found by its path and by its name, and has one "recent" member).
 */
const MEMBERS: Readonly<Partial<Record<HitKind, readonly Member[]>>> = {
  organization: [organizationMember],
  product: [productMember],
  project: [projectMember],
  operation: [operationByPathMember, operationByNameMember, operationRecentMember],
  schema: [schemaMember],
  property: [propertyMember],
};

/**
 * The kinds a suggestion request will actually run: suggestable, selected by the request's scope or
 * `type:` filter, and able to honour its other filters (see `applicableKinds`).
 *
 * @param request - The resolved request.
 * @returns The kinds, in {@link SUGGEST_KINDS} order; empty when nothing can be suggested.
 */
export function suggestKinds(request: SearchRequest): HitKind[] {
  const applicable = applicableKinds(request);
  return SUGGEST_KINDS.filter((kind) => applicable.includes(kind) && request.kinds.includes(kind));
}

/**
 * The `recent_scope` CTE: the primary keys of the {@link SUGGEST_RECENT_VERSIONS} most recently
 * published versions in scope. It has two shapes:
 *
 * - **The query names an organization or a project** (`org:`, `project:`): start from that owner's
 *   projects — its {@link SUGGEST_RECENT_SCAN_CAP} most recently created ones — and take each
 *   one's latest public version, one index probe per project. The filter is then searched in
 *   *that* owner's versions rather than lost among everyone else's. (With "every version" asked
 *   for, the sample is still each project's latest version.)
 * - **Otherwise**: walk `idx_versions_public_published_recent` (V412) newest first, examine at
 *   most {@link SUGGEST_RECENT_SCAN_CAP} public versions, and keep the ones that are their
 *   project's latest and pass the filters.
 */
function recentScopeSql(build: Build): string {
  const { request, params } = build;
  const order = 'ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC';
  if (request.orgs.length > 0 || request.projects.length > 0) {
    // The owner filters pick the projects (before the cap); the rest filter their latest versions.
    const owner = { ...request, versions: [], formats: [], paradigms: [], tags: [], after: null, before: null };
    const ownerFilters = scopeFilterClauses(owner, params, VERSION_ROW_COLUMNS);
    const versionFilters = scopeFilterClauses({ ...request, orgs: [], projects: [] }, params, VERSION_ROW_COLUMNS);
    return `recent_scope AS MATERIALIZED (
      SELECT v.id AS version_pk
        FROM (SELECT p.id
                FROM apiome.projects p
                JOIN apiome.tenants t ON t.id = p.tenant_id
               WHERE p.deleted_at IS NULL
                 AND t.deleted_at IS NULL${ownerFilters.map((f) => `\n                 AND ${f}`).join('')}
               ORDER BY p.created_at DESC, p.id DESC
               LIMIT ${params.add(SUGGEST_RECENT_SCAN_CAP)}) rp
        JOIN apiome.versions v ON v.id = ${latestVersionIdSql('rp.id')}${
          versionFilters.length > 0 ? `\n       WHERE ${versionFilters.join('\n         AND ')}` : ''
        }
       ${order}
       LIMIT ${params.add(SUGGEST_RECENT_VERSIONS)}
    ),
    `;
  }
  return `recent_scope AS MATERIALIZED (
      SELECT v.id AS version_pk
        FROM (SELECT r_v.id
                FROM apiome.versions r_v
               WHERE r_v.published = true
                 AND r_v.visibility = 'public'
                 AND r_v.deleted_at IS NULL
               ORDER BY r_v.published_at DESC NULLS LAST, r_v.created_at DESC
               LIMIT ${params.add(SUGGEST_RECENT_SCAN_CAP)}) r
        ${versionJoinsSql('r.id')}
       WHERE ${versionScopeSql(build)}
       ${order}
       LIMIT ${params.add(SUGGEST_RECENT_VERSIONS)}
    ),
    `;
}

/**
 * Build the suggestion statement.
 *
 * It returns one row: `total` (hits found, a floor when a kind was capped), `kind_facets`
 * (`[{value, count}]`, most hits first) and `rows` (the best `request.perPage` hits, in the shape of
 * `CatalogSearchHit` without `facts`).
 *
 * @param request - The resolved request; `perPage` is how many suggestions to return. `page` is
 *   ignored: suggestions have one page.
 * @returns The statement, or `null` when no kind can be suggested for this request (for example a
 *   `severity:` filter, which only changelog entries can honour).
 */
export function buildSuggestSql(request: SearchRequest): SqlStatement | null {
  const kinds = suggestKinds(request);
  if (kinds.length === 0) return null;

  const params = new Params();
  const build: Build = { request, params, candidateCap: '' };
  build.candidateCap = params.add(SUGGEST_CANDIDATE_CAP);
  const words = needles(request);
  const indexable = words.some((needle) => needle.length >= MIN_TRIGRAM_LENGTH);
  const memberCap = params.add(SUGGEST_MEMBER_CAP);

  const selects: string[] = [];
  let usesRecentScope = false;
  for (const kind of kinds) {
    const namePasses = indexable || SHORT_QUERY_KINDS.includes(kind);
    for (const member of MEMBERS[kind] ?? []) {
      const named = namePasses ? member(build, 'name') : null;
      if (named) selects.push(`(${named}\n         LIMIT ${memberCap})`);
      const recent = member(build, 'recent');
      if (recent) {
        usesRecentScope = true;
        selects.push(`(${recent}\n         LIMIT ${memberCap})`);
      }
    }
  }
  const scopeCte = usesRecentScope ? recentScopeSql(build) : '';
  const perSlot = params.add(request.perPage);
  const order = orderBySql(request.sort);

  const text = `
    WITH ${scopeCte}members AS (
      SELECT ${HIT_COLUMNS.join(', ')} FROM (
        ${selects.join('\n        UNION ALL\n        ')}
      ) m
    ),
    hits AS (
      -- A row found by more than one pass (or by an operation's path and its name) is one hit.
      SELECT DISTINCT ON (hit_id) * FROM members ORDER BY hit_id, rank DESC
    ),
    page AS (
      SELECT h.*, ROW_NUMBER() OVER (ORDER BY ${order}) AS ord
      FROM hits h
      ORDER BY ${order}
      LIMIT ${perSlot}
    )
    SELECT
      (SELECT COUNT(*)::int FROM hits) AS total,
      COALESCE((SELECT json_agg(json_build_object('value', x.hit_type, 'count', x.c) ORDER BY x.c DESC, x.hit_type)
                FROM (SELECT hit_type, COUNT(*)::int AS c FROM hits GROUP BY 1) x), '[]'::json) AS kind_facets,
      COALESCE((SELECT json_agg(to_jsonb(pg) - 'ord' ORDER BY pg.ord) FROM page pg), '[]'::json) AS rows
  `;
  return { text, values: params.values };
}
