/**
 * The result row shape and the pure helpers the results page needs for a row: where it links,
 * what it is called, how its kind is shown.
 */

import { operationAnchorId, schemaAnchorId, versionHref } from './anchors';
import { HIT_KIND_LABELS, type HitKind } from './kinds';

/** One search hit, as the SQL projects it. */
export interface CatalogSearchHit {
  hit_id: string;
  hit_type: HitKind;
  tenant_slug: string;
  tenant_name: string;
  project_slug: string | null;
  project_name: string | null;
  version_slug: string | null;
  published_at: string | null;
  title: string;
  snippet: string;
  subtitle: string | null;
  method: string | null;
  path: string | null;
  anchor_key: string | null;
  source_format: string | null;
  paradigm: string | null;
  rank: number;
  name_key: string;
}

/** One facet bucket. */
export interface FacetBucket {
  value: string;
  label?: string;
  count: number;
}

/** One "top project" bucket. */
export interface ProjectFacet {
  tenant_slug: string;
  tenant_name: string;
  project_slug: string;
  project_name: string;
  count: number;
}

/** The whole response of one search. */
export interface CatalogSearchResponse {
  total: number;
  /** Hits across every kind, before the tab/type narrowing — what the scope tabs count. */
  totalAllKinds: number;
  /** True when the corpus hit the cap and `total` is a floor, not a count. */
  truncated: boolean;
  page: number;
  perPage: number;
  pageCount: number;
  rows: CatalogSearchHit[];
  facets: {
    kinds: FacetBucket[];
    orgs: FacetBucket[];
    methods: FacetBucket[];
    formats: FacetBucket[];
    paradigms: FacetBucket[];
    projects: ProjectFacet[];
  };
  tookMs: number;
}

/** An empty response, for the landing state and for failures. */
export function emptySearchResponse(page = 1, perPage = 25): CatalogSearchResponse {
  return {
    total: 0,
    totalAllKinds: 0,
    truncated: false,
    page,
    perPage,
    pageCount: 0,
    rows: [],
    facets: { kinds: [], orgs: [], methods: [], formats: [], paradigms: [], projects: [] },
    tookMs: 0,
  };
}

/**
 * Where a hit links: the organization page, the project page, or the version page — at the
 * operation or schema anchor when the row has one.
 */
export function hitHref(hit: CatalogSearchHit): string {
  const tenant = encodeURIComponent(hit.tenant_slug);
  if (hit.hit_type === 'organization' || !hit.project_slug) return `/tenant/${tenant}`;
  const project = encodeURIComponent(hit.project_slug);
  if (hit.hit_type === 'project' || !hit.version_slug) return `/tenant/${tenant}/${project}`;
  let anchor: string | null = null;
  if (hit.hit_type === 'operation' && hit.method && hit.path) {
    anchor = operationAnchorId(hit.method, hit.path);
  } else if ((hit.hit_type === 'schema' || hit.hit_type === 'property') && hit.anchor_key) {
    anchor = schemaAnchorId(hit.anchor_key);
  }
  return versionHref(hit.tenant_slug, hit.project_slug, hit.version_slug, anchor);
}

/** The breadcrumb pieces for a hit: org, then project, then version when present. */
export function hitCrumbs(hit: CatalogSearchHit): { label: string; href: string }[] {
  const crumbs = [{ label: hit.tenant_name, href: `/tenant/${encodeURIComponent(hit.tenant_slug)}` }];
  if (hit.project_slug && hit.project_name) {
    crumbs.push({
      label: hit.project_name,
      href: `/tenant/${encodeURIComponent(hit.tenant_slug)}/${encodeURIComponent(hit.project_slug)}`,
    });
    if (hit.version_slug && hit.hit_type !== 'project') {
      crumbs.push({
        label: `v${hit.version_slug}`,
        href: versionHref(hit.tenant_slug, hit.project_slug, hit.version_slug),
      });
    }
  }
  return crumbs;
}

/** The kind label for a hit. */
export function hitKindLabel(kind: HitKind): string {
  return HIT_KIND_LABELS[kind]?.one ?? kind.replace(/_/g, ' ');
}

/** Group a page of rows by kind, preserving the page order within each group. */
export function groupHitsByKind(rows: readonly CatalogSearchHit[]): { kind: HitKind; rows: CatalogSearchHit[] }[] {
  const groups = new Map<HitKind, CatalogSearchHit[]>();
  for (const row of rows) {
    const list = groups.get(row.hit_type) ?? [];
    list.push(row);
    groups.set(row.hit_type, list);
  }
  return [...groups.entries()].map(([kind, list]) => ({ kind, rows: list }));
}
