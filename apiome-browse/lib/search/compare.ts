/**
 * Compare from search and the version quick-switch on hits (BDX-2.6).
 *
 * With *All published* on, search shows the same operation once per version. Two pieces turn that
 * into a diff or a jump:
 *
 * - **Compare selection.** A visitor ticks *Compare* on two version / operation / schema hits of
 *   one project; a sticky bar links to `/tenant/{t}/{p}/compare?v1=<older>&v2=<newer>`.
 * - **Version quick-switch.** The version chip on a hit opens a menu of the project's other
 *   published versions, each linking to the same operation or schema anchor in that version when
 *   the item exists there (one lookup per page of results — {@link buildHitVersionsSql}).
 *
 * Everything here is pure (no React, no database) so the rules are unit-tested.
 */

import { operationAnchorId, schemaAnchorId, versionHref } from './anchors';
import type { CatalogSearchHit } from './hits';
import type { HitKind } from './kinds';
import type { SqlStatement } from './sql';

/** The hit kinds that can be ticked for compare and carry a version quick-switch menu. */
export const COMPARE_KINDS: readonly HitKind[] = ['version', 'operation', 'schema'];

/** How many hits a compare selection holds: a diff has two sides. */
export const COMPARE_MAX = 2;

/**
 * Whether a hit can be ticked for compare (and carries the version menu): a version, operation or
 * schema hit that names its project and version.
 *
 * @param hit A search hit.
 * @returns True for an eligible hit.
 */
export function isCompareEligible(hit: CatalogSearchHit): boolean {
  return COMPARE_KINDS.includes(hit.hit_type) && Boolean(hit.project_slug) && Boolean(hit.version_slug);
}

/** The outcome of a toggle: the next selection, and a message when the toggle was refused. */
export interface CompareToggleResult {
  selection: CatalogSearchHit[];
  /** Why the hit was not added; null when the toggle went through. */
  error: string | null;
}

/** The `tenant/project` key of a hit — two hits compare only when their keys match. */
function projectKey(hit: CatalogSearchHit): string {
  return `${hit.tenant_slug}/${hit.project_slug ?? ''}`;
}

/**
 * Tick or untick a hit for compare.
 *
 * A ticked hit is removed. An unticked hit is added unless that would break the rules, in which
 * case the selection is returned unchanged with a message for the visitor:
 *
 * - the hit is not a version, operation or schema hit of a known version;
 * - the selection already holds {@link COMPARE_MAX} hits;
 * - the selection holds a hit of a different project;
 * - the selection already holds a hit of the same version (a diff needs two versions).
 *
 * @param selection The current selection, in the order the hits were ticked.
 * @param hit The hit to toggle.
 * @returns The next selection and the refusal message, if any.
 */
export function toggleCompare(selection: readonly CatalogSearchHit[], hit: CatalogSearchHit): CompareToggleResult {
  if (selection.some((s) => s.hit_id === hit.hit_id)) {
    return { selection: selection.filter((s) => s.hit_id !== hit.hit_id), error: null };
  }
  if (!isCompareEligible(hit)) {
    return { selection: [...selection], error: 'Only version, operation and schema hits can be compared.' };
  }
  if (selection.length >= COMPARE_MAX) {
    return { selection: [...selection], error: 'Compare takes two hits — untick one first.' };
  }
  const other = selection[0];
  if (other && projectKey(other) !== projectKey(hit)) {
    return {
      selection: [...selection],
      error: `Compare works within one project — ${other.project_name ?? other.project_slug} is already selected.`,
    };
  }
  if (other && other.version_slug === hit.version_slug) {
    return { selection: [...selection], error: `Both hits are in v${hit.version_slug} — pick a hit from another version.` };
  }
  return { selection: [...selection, hit], error: null };
}

/**
 * Order two selected hits as the compare page reads them: the older version first (`v1`, the
 * base), the newer second (`v2`). Hits without a publish date keep the order they were ticked.
 *
 * @param selection Exactly two hits.
 * @returns `[older, newer]`.
 */
export function orderForCompare(selection: readonly CatalogSearchHit[]): [CatalogSearchHit, CatalogSearchHit] {
  const [a, b] = selection;
  const ta = a.published_at ? Date.parse(a.published_at) : NaN;
  const tb = b.published_at ? Date.parse(b.published_at) : NaN;
  if (!Number.isNaN(ta) && !Number.isNaN(tb) && tb < ta) return [b, a];
  return [a, b];
}

/**
 * The compare page link for a full selection.
 *
 * @param selection The ticked hits.
 * @returns `/tenant/{t}/{p}/compare?v1=<older>&v2=<newer>`, or null until two hits of one project
 *   and two versions are ticked.
 */
export function compareHref(selection: readonly CatalogSearchHit[]): string | null {
  if (selection.length !== COMPARE_MAX) return null;
  const [older, newer] = orderForCompare(selection);
  if (projectKey(older) !== projectKey(newer) || !older.project_slug || !older.version_slug || !newer.version_slug) return null;
  if (older.version_slug === newer.version_slug) return null;
  const qs = new URLSearchParams({ v1: older.version_slug, v2: newer.version_slug });
  return `/tenant/${encodeURIComponent(older.tenant_slug)}/${encodeURIComponent(older.project_slug)}/compare?${qs.toString()}`;
}

/**
 * The sticky bar's button label: `Compare v1.0.0 → v2.0.0` for a full selection.
 *
 * @param selection The ticked hits.
 * @returns The label, or null until the selection is complete.
 */
export function compareLabel(selection: readonly CatalogSearchHit[]): string | null {
  if (!compareHref(selection)) return null;
  const [older, newer] = orderForCompare(selection);
  return `Compare v${older.version_slug} → v${newer.version_slug}`;
}

/* ----------------------------------------------------------------------------------------------- */
/* Version quick-switch                                                                            */
/* ----------------------------------------------------------------------------------------------- */

/** One published version of a hit's project, as the lookup returns it. */
export interface HitVersion {
  version_slug: string;
  published_at: string | null;
  /**
   * Whether the hit's operation (same method and path) or schema (same name) exists in this
   * version; null for version hits, which have no anchor.
   */
  has_anchor: boolean | null;
}

/**
 * The lookup result: every eligible hit on the page → its project's newest published versions,
 * newest first (at most {@link HIT_VERSIONS_CAP}).
 */
export type HitVersionsMap = Record<string, HitVersion[]>;

/** Every eligible hit on the page → how many published public versions its project has in all. */
export type HitVersionCounts = Record<string, number>;

/**
 * How many more versions a hit's menu could list than it does.
 *
 * @param versions The versions the lookup returned for the hit.
 * @param total The project's published public versions in all.
 * @returns The number not listed; 0 when the menu is complete.
 */
export function moreVersionsCount(versions: readonly HitVersion[] | undefined, total: number | undefined): number {
  return Math.max(0, (total ?? 0) - (versions?.length ?? 0));
}

/** One entry of a hit's version menu. */
export interface VersionMenuEntry {
  versionSlug: string;
  href: string;
  /** True when the link lands on the hit's operation or schema anchor in that version. */
  atAnchor: boolean;
  /** True when the hit is an operation or schema that does not exist in that version. */
  missing: boolean;
}

/**
 * The anchor a hit points at on its version page: `op-…` for an operation, `schema-…` for a
 * schema, null for a version hit.
 */
export function hitAnchor(hit: CatalogSearchHit): string | null {
  if (hit.hit_type === 'operation' && hit.method && hit.path) return operationAnchorId(hit.method, hit.path);
  if (hit.hit_type === 'schema' && hit.anchor_key) return schemaAnchorId(hit.anchor_key);
  return null;
}

/**
 * The version menu of a hit: its project's other published versions, newest first, each linking
 * to the same anchor when the operation or schema exists in that version and to the version page
 * otherwise.
 *
 * @param hit An eligible hit.
 * @param versions The project's published versions from the lookup (newest first).
 * @returns The menu entries, without the hit's own version; empty when there is nothing to switch to.
 */
export function versionMenuEntries(hit: CatalogSearchHit, versions: readonly HitVersion[] | undefined): VersionMenuEntry[] {
  if (!versions || !isCompareEligible(hit)) return [];
  const anchor = hitAnchor(hit);
  const project = hit.project_slug as string;
  return versions
    .filter((v) => v.version_slug !== hit.version_slug)
    .map((v) => {
      const atAnchor = Boolean(anchor) && v.has_anchor === true;
      return {
        versionSlug: v.version_slug,
        href: versionHref(hit.tenant_slug, project, v.version_slug, atAnchor ? anchor : null),
        atAnchor,
        missing: Boolean(anchor) && v.has_anchor === false,
      };
    });
}

/** Versions a hit's menu lists with the page; the rest load when the visitor asks (DBP-1.27). */
export const HIT_VERSIONS_CAP = 20;

/** Most versions a hit's menu ever lists. */
export const HIT_VERSIONS_ALL_CAP = 500;

/**
 * The one statement behind the version menus of a page of results: for every eligible hit, its
 * project's newest published public versions (newest first), whether the hit's operation or schema
 * exists in each, and how many public versions the project has in all.
 *
 * Each hit's project is resolved through `apiome.browse_public_projects`, and only `limit` versions
 * per hit are read and probed (DBP-1.27, #7210) — the statement used to return every public version
 * of every hit's project, with an `EXISTS` probe for each.
 *
 * Parallel arrays bind the hits, so the statement has seven parameters whatever the page size.
 *
 * @param rows The page's rows; ineligible rows are skipped.
 * @param limit Most versions per hit.
 * @returns The statement, or null when no row is eligible. Each result row is
 *   `{ hit_id, version_count, versions: HitVersion[] }`.
 */
export function buildHitVersionsSql(
  rows: readonly CatalogSearchHit[],
  limit: number = HIT_VERSIONS_CAP
): SqlStatement | null {
  const eligible = rows.filter(isCompareEligible);
  if (eligible.length === 0) return null;
  const values: unknown[] = [
    eligible.map((h) => h.hit_id),
    eligible.map((h) => h.tenant_slug),
    eligible.map((h) => h.project_slug),
    eligible.map((h) => h.hit_type),
    eligible.map((h) => (h.hit_type === 'operation' ? (h.method ?? '').toUpperCase() : null)),
    eligible.map((h) => (h.hit_type === 'operation' ? h.path : h.hit_type === 'schema' ? h.anchor_key : null)),
    limit,
  ];
  const text = `
    WITH wanted AS (
      SELECT * FROM unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::text[], $6::text[])
        AS w(hit_id, tenant_slug, project_slug, hit_type, method, item_key)
    ),
    located AS (
      SELECT w.hit_id, w.hit_type, w.method, w.item_key, p.id AS project_id, b.version_count
      FROM wanted w
      JOIN apiome.tenants t ON t.slug = w.tenant_slug AND t.deleted_at IS NULL
      JOIN apiome.projects p ON p.tenant_id = t.id AND p.slug = w.project_slug AND p.deleted_at IS NULL
      JOIN apiome.browse_public_projects b ON b.project_id = p.id
    )
    SELECT w.hit_id, w.version_count,
           (SELECT json_agg(json_build_object(
                     'version_slug', pv.version_slug,
                     'published_at', pv.published_at,
                     'has_anchor', CASE
                       WHEN w.hit_type = 'operation' THEN EXISTS (
                         SELECT 1 FROM apiome.version_path vp
                         JOIN apiome.path_operation po ON po.version_path_id = vp.id
                         WHERE vp.version_id = pv.version_pk AND vp.pathname = w.item_key AND UPPER(po.operation) = w.method)
                       WHEN w.hit_type = 'schema' THEN EXISTS (
                         SELECT 1 FROM apiome.classes c
                         WHERE c.version_id = pv.version_pk AND c.deleted_at IS NULL AND c.name = w.item_key)
                       ELSE NULL END
                   ) ORDER BY pv.published_at DESC NULLS LAST, pv.created_at DESC)
              FROM (
                SELECT v.id AS version_pk, v.version_id AS version_slug, v.published_at, v.created_at
                FROM apiome.versions v
                WHERE v.project_id = w.project_id
                  AND v.published = true
                  AND v.visibility = 'public'
                  AND v.deleted_at IS NULL
                ORDER BY v.published_at DESC NULLS LAST, v.created_at DESC
                LIMIT $7
              ) pv) AS versions
    FROM located w`;
  return { text, values };
}
