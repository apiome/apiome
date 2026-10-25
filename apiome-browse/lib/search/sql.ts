/**
 * The catalog search SQL, built from a {@link SearchRequest}.
 *
 * One statement, one round trip. A `scope` CTE picks the published public versions in play (each
 * project's latest unless the visitor asked for every version, then narrowed by the organization,
 * project, format, paradigm, tag and date filters). One union member per *kind* joins that scope to
 * the normalized model — operations, schemas, properties, parameters, bodies, responses, version
 * notes, tags, projects, organizations — and projects it onto one common row shape with a text
 * match predicate and a relevance rank. The tail of the statement counts, facets and pages those
 * rows in SQL, and returns everything as one row of JSON columns.
 *
 * Why not Postgres full-text search: the tsvector/GIN index over the normalized model is the REST
 * side's MFI-6.2 (#3754), which has not landed. Until it does this is substring matching (`ILIKE`)
 * on a bounded public corpus, the same contract the previous search had — but ranked, filtered,
 * faceted and paged. The builder is pure so the shape of the statement is unit-tested without a
 * database; `lib/db/search.ts` runs it.
 */

import { HIT_KIND_WEIGHT, type HitKind } from './kinds';
import type { SearchRequest } from './params';

/** A parameterized statement for `pg`. */
export interface SqlStatement {
  text: string;
  values: unknown[];
}

/** Rows past this many are not counted or paged; the UI says "more than N" and asks for a narrower query. */
export const SEARCH_HIT_CAP = 5000;

const PUBLIC_VERSION_GATES = `v.published = true
      AND v.visibility = 'public'
      AND t.deleted_at IS NULL
      AND p.deleted_at IS NULL
      AND v.deleted_at IS NULL`;

/** Escape `%`, `_` and `\` so a value is matched literally inside an ILIKE pattern. */
export function escapeLikePattern(raw: string): string {
  return raw.replace(/\\/g, '\\\\').replace(/%/g, '\\%').replace(/_/g, '\\_');
}

/** Kinds whose rows hang off a path, and so can honour a `path:` filter. */
const PATH_KINDS: readonly HitKind[] = ['operation', 'parameter', 'request_body', 'response'];

/** Kinds that carry an HTTP method, and so can honour a `method:` filter. */
const METHOD_KINDS: readonly HitKind[] = ['operation'];

/**
 * A small parameter registry: every value becomes `$n`, and repeated values reuse their slot so
 * the ten union members do not bind the same pattern ten times.
 */
class Params {
  readonly values: unknown[] = [];
  private readonly index = new Map<string, string>();

  add(value: unknown): string {
    const key = typeof value === 'string' ? `s:${value}` : `j:${JSON.stringify(value)}`;
    const hit = this.index.get(key);
    if (hit) return hit;
    this.values.push(value);
    const slot = `$${this.values.length}`;
    this.index.set(key, slot);
    return slot;
  }
}

/**
 * The text-match predicate for one haystack expression: every term and phrase must appear, no
 * negated token may. Returns `TRUE` when the query has no text.
 */
function textPredicate(haystack: string, request: SearchRequest, params: Params): string {
  const clauses: string[] = [];
  for (const needle of [...request.parsed.terms, ...request.parsed.phrases]) {
    clauses.push(`${haystack} ILIKE ${params.add(`%${escapeLikePattern(needle)}%`)} ESCAPE '\\'`);
  }
  for (const needle of request.parsed.negated) {
    clauses.push(`NOT (${haystack} ILIKE ${params.add(`%${escapeLikePattern(needle)}%`)} ESCAPE '\\')`);
  }
  return clauses.length > 0 ? `(${clauses.join('\n          AND ')})` : 'TRUE';
}

/**
 * The relevance rank for a member: the best of an exact / prefix / contains match on each of the
 * given expressions, plus the kind's weight. With no text to rank by, the weight alone orders.
 */
function rankExpr(kind: HitKind, exprs: string[], request: SearchRequest, params: Params): string {
  const weight = HIT_KIND_WEIGHT[kind];
  const needles = [...request.parsed.phrases, ...request.parsed.terms];
  if (needles.length === 0) return `${weight}`;
  const full = needles.join(' ').toLowerCase();
  const exact = params.add(full);
  const prefix = params.add(`${escapeLikePattern(full)}%`);
  const contains = params.add(`%${escapeLikePattern(full)}%`);
  const cases = exprs.map(
    (e) =>
      `CASE WHEN LOWER(${e}) = ${exact} THEN 100
            WHEN LOWER(${e}) LIKE ${prefix} ESCAPE '\\' THEN 70
            WHEN ${e} ILIKE ${contains} ESCAPE '\\' THEN 45
            ELSE 0 END`
  );
  // Several words that each appear but never as one string still matched every word (the text
  // predicate guarantees that), so the floor is 10, not 0.
  return `(GREATEST(10, ${cases.join(', ')}) + ${weight})`;
}

/** `concat_ws(' ', a, b, c)` with NULL-safe pieces. */
function haystack(...columns: string[]): string {
  return `concat_ws(' ', ${columns.map((c) => `COALESCE(${c}::text, '')`).join(', ')})`;
}

/** The common SELECT list every member must produce, in this order. */
const HIT_COLUMNS = [
  'hit_id',
  'hit_type',
  'tenant_slug',
  'tenant_name',
  'project_slug',
  'project_name',
  'version_slug',
  'published_at',
  'title',
  'snippet',
  'subtitle',
  'method',
  'path',
  'anchor_key',
  'source_format',
  'paradigm',
  'rank',
  'name_key',
] as const;

interface MemberArgs {
  request: SearchRequest;
  params: Params;
}

type MemberBuilder = (args: MemberArgs) => string;

const organizationMember: MemberBuilder = ({ request, params }) => `
      SELECT 'org:' || sv.tenant_pk::text AS hit_id,
             'organization' AS hit_type,
             sv.tenant_slug, sv.tenant_name,
             NULL::text AS project_slug, NULL::text AS project_name, NULL::text AS version_slug,
             MAX(sv.published_at) AS published_at,
             sv.tenant_name AS title,
             LEFT(COALESCE(NULLIF(TRIM(sv.tenant_description), ''),
                  'Publishes ' || COUNT(DISTINCT sv.project_id) || ' public project' ||
                  CASE WHEN COUNT(DISTINCT sv.project_id) = 1 THEN '' ELSE 's' END), 400) AS snippet,
             '/' || sv.tenant_slug AS subtitle,
             NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
             NULL::text AS source_format, NULL::text AS paradigm,
             ${rankExpr('organization', ['sv.tenant_name', 'sv.tenant_slug'], request, params)} AS rank,
             sv.tenant_name AS name_key
      FROM sv
      WHERE ${textPredicate(haystack('sv.tenant_name', 'sv.tenant_slug', 'sv.tenant_description'), request, params)}
      GROUP BY sv.tenant_pk, sv.tenant_slug, sv.tenant_name, sv.tenant_description`;

const projectMember: MemberBuilder = ({ request, params }) => `
      SELECT 'project:' || sv.project_id::text AS hit_id,
             'project' AS hit_type,
             sv.tenant_slug, sv.tenant_name,
             sv.project_slug, sv.project_name,
             (array_agg(sv.version_slug ORDER BY sv.published_at DESC NULLS LAST))[1] AS version_slug,
             MAX(sv.published_at) AS published_at,
             sv.project_name AS title,
             LEFT(COALESCE(NULLIF(TRIM(sv.project_description), ''), 'Project in ' || sv.tenant_name), 400) AS snippet,
             sv.tenant_name || ' · ' || COUNT(*) || CASE WHEN COUNT(*) = 1 THEN ' version' ELSE ' versions' END AS subtitle,
             NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
             MAX(NULLIF(sv.source_format, '')) AS source_format,
             MAX(NULLIF(sv.paradigm, '')) AS paradigm,
             ${rankExpr('project', ['sv.project_name', 'sv.project_slug'], request, params)} AS rank,
             sv.project_name AS name_key
      FROM sv
      WHERE ${textPredicate(haystack('sv.project_name', 'sv.project_slug', 'sv.project_description', 'sv.tenant_name'), request, params)}
      GROUP BY sv.project_id, sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.project_description`;

const versionMember: MemberBuilder = ({ request, params }) => `
      SELECT 'version:' || sv.version_pk::text AS hit_id,
             'version' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             sv.project_name || ' v' || sv.version_slug AS title,
             LEFT(COALESCE(NULLIF(TRIM(v.description), ''), NULLIF(TRIM(v.change_log), ''),
                  NULLIF(TRIM(v.commit_message), ''), 'Published version'), 400) AS snippet,
             'Version notes' AS subtitle,
             NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('version', ['sv.version_slug', 'sv.project_name'], request, params)} AS rank,
             sv.project_name || ' ' || sv.version_slug AS name_key
      FROM sv
      JOIN apiome.versions v ON v.id = sv.version_pk
      WHERE ${textPredicate(haystack('sv.version_slug', 'v.description', 'v.change_log', 'v.commit_message'), request, params)}`;

const tagMember: MemberBuilder = ({ request, params }) => `
      SELECT 'tag:' || vt.id::text AS hit_id,
             'tag' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             vt.name AS title,
             LEFT(COALESCE(NULLIF(TRIM(vt.message), ''), 'Tag on ' || sv.project_name || ' v' || sv.version_slug), 400) AS snippet,
             'Tag · v' || sv.version_slug AS subtitle,
             NULL::text AS method, NULL::text AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('tag', ['vt.name'], request, params)} AS rank,
             vt.name AS name_key
      FROM sv
      JOIN apiome.version_tags vt ON vt.version_id = sv.version_pk
      WHERE ${textPredicate(haystack('vt.name', 'vt.message'), request, params)}`;

/** The method / path filters an operation-ish member applies, or `TRUE`. */
function pathFilters(request: SearchRequest, params: Params, withMethod: boolean): string {
  const clauses: string[] = [];
  if (withMethod && request.methods.length > 0) {
    clauses.push(`UPPER(po.operation) = ANY(${params.add(request.methods)}::text[])`);
  }
  for (const fragment of request.paths) {
    clauses.push(`vp.pathname ILIKE ${params.add(`%${escapeLikePattern(fragment)}%`)} ESCAPE '\\'`);
  }
  return clauses.length > 0 ? clauses.join('\n        AND ') : 'TRUE';
}

const operationMember: MemberBuilder = ({ request, params }) => `
      SELECT 'op:' || po.id::text AS hit_id,
             'operation' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             COALESCE(NULLIF(TRIM(pod.summary), ''), UPPER(po.operation) || ' ' || vp.pathname) AS title,
             LEFT(COALESCE(NULLIF(TRIM(pod.description), ''), NULLIF(TRIM(pod.operation_id), ''), ''), 400) AS snippet,
             UPPER(po.operation) || ' ' || vp.pathname AS subtitle,
             UPPER(po.operation) AS method, vp.pathname AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('operation', ['vp.pathname', 'pod.summary', 'pod.operation_id', "UPPER(po.operation) || ' ' || vp.pathname"], request, params)} AS rank,
             vp.pathname AS name_key
      FROM sv
      JOIN apiome.version_path vp ON vp.version_id = sv.version_pk
      JOIN apiome.path_operation po ON po.version_path_id = vp.id
      LEFT JOIN apiome.path_operation_description pod ON pod.path_operation_id = po.id
      WHERE ${pathFilters(request, params, true)}
        AND ${textPredicate(haystack('vp.pathname', 'po.operation', 'pod.summary', 'pod.description', 'pod.operation_id', 'pod.metadata', 'po.metadata'), request, params)}`;

const parameterMember: MemberBuilder = ({ request, params }) => `
      SELECT 'param:' || spp.id::text AS hit_id,
             'parameter' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             spp.name AS title,
             LEFT(COALESCE(NULLIF(TRIM(spp.summary), ''), NULLIF(TRIM(spp.description), ''), spp.data::text, ''), 400) AS snippet,
             spp.in_location || ' parameter · ' || vp.pathname AS subtitle,
             NULL::text AS method, vp.pathname AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('parameter', ['spp.name'], request, params)} AS rank,
             spp.name AS name_key
      FROM sv
      JOIN apiome.version_path vp ON vp.version_id = sv.version_pk
      JOIN apiome.shared_path_parameter spp ON spp.version_path_id = vp.id
      WHERE ${pathFilters(request, params, false)}
        AND ${textPredicate(haystack('spp.name', 'spp.summary', 'spp.description', 'spp.data'), request, params)}`;

const requestBodyMember: MemberBuilder = ({ request, params }) => `
      SELECT 'body:' || sprb.id::text AS hit_id,
             'request_body' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             sprb.name AS title,
             LEFT(COALESCE(NULLIF(TRIM(sprb.description), ''), string_agg(DISTINCT sprbc.media_type, ', '), ''), 400) AS snippet,
             'Request body · ' || vp.pathname AS subtitle,
             NULL::text AS method, vp.pathname AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('request_body', ['sprb.name'], request, params)} AS rank,
             sprb.name AS name_key
      FROM sv
      JOIN apiome.version_path vp ON vp.version_id = sv.version_pk
      JOIN apiome.shared_path_request_body sprb ON sprb.version_path_id = vp.id
      LEFT JOIN apiome.shared_path_request_body_content sprbc ON sprbc.shared_path_request_body_id = sprb.id
      WHERE ${pathFilters(request, params, false)}
        AND ${textPredicate(haystack('sprb.name', 'sprb.description', 'sprbc.media_type', 'sprbc.inline_schema', 'sprbc.examples'), request, params)}
      GROUP BY sprb.id, sprb.name, sprb.description, vp.pathname,
               sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
               sv.published_at, sv.source_format, sv.paradigm`;

const responseMember: MemberBuilder = ({ request, params }) => `
      SELECT 'resp:' || spr.id::text AS hit_id,
             'response' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             'HTTP ' || spr.status_code AS title,
             LEFT(COALESCE(NULLIF(TRIM(spr.description), ''), string_agg(DISTINCT sprc.media_type, ', '), ''), 400) AS snippet,
             'Response · ' || vp.pathname AS subtitle,
             NULL::text AS method, vp.pathname AS path, NULL::text AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('response', ['spr.status_code::text', 'spr.description'], request, params)} AS rank,
             vp.pathname || ' ' || spr.status_code AS name_key
      FROM sv
      JOIN apiome.version_path vp ON vp.version_id = sv.version_pk
      JOIN apiome.shared_path_response spr ON spr.version_path_id = vp.id
      LEFT JOIN apiome.shared_path_response_content sprc ON sprc.shared_path_response_id = spr.id
      WHERE ${pathFilters(request, params, false)}
        AND ${textPredicate(haystack('spr.status_code', 'spr.description', 'spr.inline_schema', 'spr.data', 'sprc.media_type', 'sprc.inline_schema', 'sprc.examples'), request, params)}
      GROUP BY spr.id, spr.status_code, spr.description, vp.pathname,
               sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
               sv.published_at, sv.source_format, sv.paradigm`;

const schemaMember: MemberBuilder = ({ request, params }) => `
      SELECT 'schema:' || c.id::text AS hit_id,
             'schema' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             c.name AS title,
             LEFT(COALESCE(NULLIF(TRIM(c.description), ''), c.schema::text, ''), 400) AS snippet,
             'Schema · v' || sv.version_slug AS subtitle,
             NULL::text AS method, NULL::text AS path, c.name AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('schema', ['c.name'], request, params)} AS rank,
             c.name AS name_key
      FROM sv
      JOIN apiome.classes c ON c.version_id = sv.version_pk AND c.deleted_at IS NULL
      WHERE ${textPredicate(haystack('c.name', 'c.description', 'c.schema'), request, params)}`;

const propertyMember: MemberBuilder = ({ request, params }) => `
      SELECT 'prop:' || cp.id::text AS hit_id,
             'property' AS hit_type,
             sv.tenant_slug, sv.tenant_name, sv.project_slug, sv.project_name, sv.version_slug,
             sv.published_at,
             c.name || '.' || cp.name AS title,
             LEFT(COALESCE(NULLIF(TRIM(cp.description), ''), cp.data::text, ''), 400) AS snippet,
             'Property of ' || c.name AS subtitle,
             NULL::text AS method, NULL::text AS path, c.name AS anchor_key,
             NULLIF(sv.source_format, '') AS source_format, NULLIF(sv.paradigm, '') AS paradigm,
             ${rankExpr('property', ['cp.name', "c.name || '.' || cp.name"], request, params)} AS rank,
             c.name || '.' || cp.name AS name_key
      FROM sv
      JOIN apiome.classes c ON c.version_id = sv.version_pk AND c.deleted_at IS NULL
      JOIN apiome.class_properties cp ON cp.class_id = c.id
      WHERE ${textPredicate(haystack('cp.name', 'cp.description', 'cp.data'), request, params)}`;

const MEMBERS: Readonly<Record<HitKind, MemberBuilder>> = {
  organization: organizationMember,
  project: projectMember,
  version: versionMember,
  tag: tagMember,
  operation: operationMember,
  parameter: parameterMember,
  request_body: requestBodyMember,
  response: responseMember,
  schema: schemaMember,
  property: propertyMember,
};

/**
 * The kinds a request can produce at all, regardless of the tab: a `method:` filter only means
 * something for operations, a `path:` filter only for path-attached rows. Members outside this
 * set are not even run, so their facet counts are an honest zero.
 */
export function applicableKinds(request: SearchRequest): HitKind[] {
  let kinds: readonly HitKind[] = Object.keys(MEMBERS) as HitKind[];
  if (request.methods.length > 0) kinds = kinds.filter((k) => METHOD_KINDS.includes(k));
  if (request.paths.length > 0) kinds = kinds.filter((k) => PATH_KINDS.includes(k));
  return [...kinds];
}

/** The version-scope filters (everything that narrows which versions are searched). */
function scopeFilters(request: SearchRequest, params: Params): string {
  const clauses: string[] = [];
  if (!request.allVersions) clauses.push('sc.version_rank = 1');
  if (request.orgs.length > 0) {
    const slot = params.add(request.orgs);
    clauses.push(`(sc.tenant_slug = ANY(${slot}::text[]) OR LOWER(sc.tenant_name) = ANY(${slot}::text[]))`);
  }
  if (request.projects.length > 0) {
    const slot = params.add(request.projects);
    clauses.push(`(sc.project_slug = ANY(${slot}::text[]) OR LOWER(sc.project_name) = ANY(${slot}::text[]))`);
  }
  for (const fragment of request.versions) {
    clauses.push(`sc.version_slug ILIKE ${params.add(`%${escapeLikePattern(fragment)}%`)} ESCAPE '\\'`);
  }
  if (request.formats.length > 0) {
    const exact = params.add(request.formats);
    const family = params.add(request.formats.map((f) => `${escapeLikePattern(f)}-%`));
    clauses.push(`(sc.source_format = ANY(${exact}::text[]) OR sc.source_format LIKE ANY(${family}::text[]))`);
  }
  if (request.paradigms.length > 0) {
    clauses.push(`sc.paradigm = ANY(${params.add(request.paradigms)}::text[])`);
  }
  if (request.tags.length > 0) {
    clauses.push(`EXISTS (SELECT 1 FROM apiome.version_tags vt
                    WHERE vt.version_id = sc.version_pk AND LOWER(vt.name) = ANY(${params.add(request.tags)}::text[]))`);
  }
  if (request.after) clauses.push(`sc.published_at >= ${params.add(request.after)}::date`);
  if (request.before) clauses.push(`sc.published_at < ${params.add(request.before)}::date`);
  return clauses.length > 0 ? clauses.join('\n      AND ') : 'TRUE';
}

/** The ORDER BY for the page, per sort mode. */
export function orderBySql(sort: SearchRequest['sort']): string {
  switch (sort) {
    case 'newest':
      return 'published_at DESC NULLS LAST, rank DESC, title ASC';
    case 'oldest':
      return 'published_at ASC NULLS LAST, rank DESC, title ASC';
    case 'name':
      return 'LOWER(name_key) ASC, rank DESC, published_at DESC NULLS LAST';
    case 'relevance':
    default:
      return 'rank DESC, published_at DESC NULLS LAST, title ASC';
  }
}

/**
 * Build the statement.
 *
 * @param request The resolved request (see `resolveSearchRequest`).
 * @returns The statement, or `null` when no member can run (e.g. `scope=schemas method:GET`).
 */
export function buildCatalogSearchSql(request: SearchRequest): SqlStatement | null {
  const params = new Params();
  const runnable = applicableKinds(request);
  if (runnable.length === 0 || !request.kinds.some((kind) => runnable.includes(kind))) return null;

  const members = runnable.map((kind) => MEMBERS[kind]({ request, params }));
  const kindsSlot = params.add(request.kinds);
  const perSlot = params.add(request.perPage);
  const offsetSlot = params.add((request.page - 1) * request.perPage);
  const capSlot = params.add(SEARCH_HIT_CAP);

  const text = `
    WITH scope AS (
      SELECT v.id AS version_pk,
             v.version_id AS version_slug,
             v.published_at,
             v.project_id,
             p.slug AS project_slug,
             p.name AS project_name,
             p.description AS project_description,
             t.id AS tenant_pk,
             t.slug AS tenant_slug,
             t.name AS tenant_name,
             t.description AS tenant_description,
             LOWER(TRIM(COALESCE(v.source_format, ''))) AS source_format,
             LOWER(TRIM(COALESCE(v.protocol, ''))) AS paradigm,
             ROW_NUMBER() OVER (PARTITION BY v.project_id
                                ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC) AS version_rank
      FROM apiome.versions v
      JOIN apiome.projects p ON p.id = v.project_id
      JOIN apiome.tenants t ON t.id = p.tenant_id
      WHERE ${PUBLIC_VERSION_GATES}
    ),
    sv AS (
      SELECT sc.* FROM scope sc
      WHERE ${scopeFilters(request, params)}
    ),
    hits_all AS (
      SELECT ${HIT_COLUMNS.join(', ')} FROM (
${members.join('\n      UNION ALL\n')}
      ) members
      LIMIT ${capSlot}
    ),
    hits AS (
      SELECT * FROM hits_all WHERE hit_type = ANY(${kindsSlot}::text[])
    ),
    page AS (
      SELECT h.*, ROW_NUMBER() OVER (ORDER BY ${orderBySql(request.sort)}) AS ord
      FROM hits h
      ORDER BY ${orderBySql(request.sort)}
      LIMIT ${perSlot} OFFSET ${offsetSlot}
    )
    SELECT
      (SELECT COUNT(*)::int FROM hits) AS total,
      (SELECT COUNT(*)::int FROM hits_all) AS total_all_kinds,
      COALESCE((SELECT json_agg(json_build_object('value', x.hit_type, 'count', x.c) ORDER BY x.c DESC, x.hit_type)
                FROM (SELECT hit_type, COUNT(*)::int AS c FROM hits_all GROUP BY 1) x), '[]'::json) AS kind_facets,
      COALESCE((SELECT json_agg(json_build_object('value', x.tenant_slug, 'label', x.tenant_name, 'count', x.c) ORDER BY x.c DESC, x.tenant_name)
                FROM (SELECT tenant_slug, tenant_name, COUNT(*)::int AS c FROM hits GROUP BY 1, 2) x), '[]'::json) AS org_facets,
      COALESCE((SELECT json_agg(json_build_object('value', x.method, 'count', x.c) ORDER BY x.c DESC, x.method)
                FROM (SELECT method, COUNT(*)::int AS c FROM hits WHERE method IS NOT NULL GROUP BY 1) x), '[]'::json) AS method_facets,
      COALESCE((SELECT json_agg(json_build_object('value', x.source_format, 'count', x.c) ORDER BY x.c DESC, x.source_format)
                FROM (SELECT source_format, COUNT(*)::int AS c FROM hits WHERE source_format IS NOT NULL GROUP BY 1) x), '[]'::json) AS format_facets,
      COALESCE((SELECT json_agg(json_build_object('value', x.paradigm, 'count', x.c) ORDER BY x.c DESC, x.paradigm)
                FROM (SELECT paradigm, COUNT(*)::int AS c FROM hits WHERE paradigm IS NOT NULL GROUP BY 1) x), '[]'::json) AS paradigm_facets,
      COALESCE((SELECT json_agg(json_build_object('tenant_slug', x.tenant_slug, 'tenant_name', x.tenant_name,
                                                  'project_slug', x.project_slug, 'project_name', x.project_name, 'count', x.c)
                                ORDER BY x.c DESC, x.project_name)
                FROM (SELECT tenant_slug, tenant_name, project_slug, project_name, COUNT(*)::int AS c
                      FROM hits WHERE project_slug IS NOT NULL
                      GROUP BY 1, 2, 3, 4 ORDER BY c DESC, project_name LIMIT 8) x), '[]'::json) AS project_facets,
      COALESCE((SELECT json_agg(to_jsonb(pg) - 'ord' ORDER BY pg.ord) FROM page pg), '[]'::json) AS rows
  `;

  return { text, values: params.values };
}
