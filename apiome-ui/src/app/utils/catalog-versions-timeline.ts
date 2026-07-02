/**
 * catalog-versions-timeline (MFI-25.7, #4092) — pure helpers for the inline version timeline and its
 * "tick any two revisions to diff" affordance in the catalog detail Versions tab.
 *
 * The catalog detail view lists a project's revisions newest-first and lets the reader tick **exactly
 * two** of them to open the existing versions-dashboard diff with both revisions preselected. All of
 * the selection maths and the deep-link construction live here (framework-free) so they can be unit
 * tested without rendering, and so the panel component stays a thin view over them.
 *
 * The diff deep-link matches the versions dashboard's existing compare handler
 * (`versions/page.tsx` `compareOpen=1&compareBase=&compareHead=`): `compareBase` is the **older**
 * revision and `compareHead` the **newer**, so the diff always reads old → new regardless of the
 * order the two checkboxes were ticked.
 */

/** The minimal revision shape the timeline needs (a subset of the versions API `Version`). */
export interface CatalogVersionRevision {
  /** Revision UUID — the value the diff deep-link compares on. */
  id: string;
  /** Semver-ish label, e.g. "1.0.0". */
  version_id: string;
  /** ISO timestamp the revision was created — drives newest-first ordering and diff base/head. */
  created_at: string;
  /** Short revision note (REST list payload). */
  shortMessage?: string | null;
  /** Legacy/detail note field, preferred over `shortMessage` when present. */
  description?: string | null;
  /** Whether the revision is published (drives a lock/published chip). */
  published?: boolean;
  /** Governance lifecycle (stable | beta | deprecated | archived). */
  lifecycle?: string | null;
  creator_name?: string | null;
  creator_email?: string | null;
}

/** A diff compares exactly two revisions. */
export const MAX_DIFF_SELECTION = 2;

/**
 * Sort revisions newest-first: by `created_at` descending, breaking ties on `version_id` with a
 * numeric-aware descending compare (so "1.10.0" sorts above "1.2.0"). Pure — returns a new array and
 * never mutates the input.
 */
export function sortRevisionsNewestFirst<T extends CatalogVersionRevision>(
  revisions: readonly T[],
): T[] {
  return [...revisions].sort((a, b) => {
    const ta = new Date(a.created_at).getTime();
    const tb = new Date(b.created_at).getTime();
    if (ta !== tb && !Number.isNaN(ta) && !Number.isNaN(tb)) return tb - ta;
    return b.version_id.localeCompare(a.version_id, undefined, { numeric: true });
  });
}

/**
 * Toggle a revision id in the diff selection:
 *   - already selected → remove it;
 *   - not selected and fewer than two selected → append it;
 *   - not selected and two already selected → unchanged (the selection is capped at two, so the UI
 *     disables the remaining checkboxes; this guards the logic even if that is bypassed).
 * Returns a new array and never mutates the input.
 */
export function toggleRevisionSelection(selected: readonly string[], id: string): string[] {
  if (selected.includes(id)) return selected.filter((s) => s !== id);
  if (selected.length >= MAX_DIFF_SELECTION) return [...selected];
  return [...selected, id];
}

/** Whether exactly two revisions are selected (i.e. "Diff" is available). */
export function canDiffRevisions(selected: readonly string[]): boolean {
  return selected.length === MAX_DIFF_SELECTION;
}

/** An ordered diff pair: the older revision (`base`) and the newer one (`head`). */
export interface OrderedRevisionPair<T extends CatalogVersionRevision = CatalogVersionRevision> {
  base: T;
  head: T;
}

/**
 * Resolve the two selected revisions into an old → new ordered pair. The older revision (by
 * `created_at`) becomes `base` and the newer `head`, so a diff always reads old → new no matter which
 * checkbox was ticked first; when the timestamps are equal or unparseable the ticked order is kept.
 *
 * Returns `null` unless the selection is exactly two distinct revisions that both resolve in
 * `revisions` — callers use that to gate the diff affordance.
 */
export function orderRevisionPairOldToNew<T extends CatalogVersionRevision>(
  selected: readonly string[],
  revisions: readonly T[],
): OrderedRevisionPair<T> | null {
  if (!canDiffRevisions(selected)) return null;
  const [firstId, secondId] = selected;
  if (firstId === secondId) return null;
  const first = revisions.find((r) => r.id === firstId);
  const second = revisions.find((r) => r.id === secondId);
  if (!first || !second) return null;

  const tFirst = new Date(first.created_at).getTime();
  const tSecond = new Date(second.created_at).getTime();
  // Older → base, newer → head. When timestamps are equal/unparseable, keep the ticked order.
  return !Number.isNaN(tFirst) && !Number.isNaN(tSecond) && tSecond < tFirst
    ? { base: second, head: first }
    : { base: first, head: second };
}

/**
 * Build the diff deep-link into the shared versions dashboard with both revisions preselected. The
 * older revision (by `created_at`) becomes `compareBase` and the newer `compareHead`, so the diff
 * reads old → new no matter which checkbox was ticked first.
 *
 * Returns `null` unless the selection is exactly two distinct revisions that both resolve in
 * `revisions` — callers use that to keep the "Open version history" fallback link honest.
 */
export function buildVersionDiffHref(
  projectId: string,
  selected: readonly string[],
  revisions: readonly CatalogVersionRevision[],
): string | null {
  if (!projectId) return null;
  const pair = orderRevisionPairOldToNew(selected, revisions);
  if (!pair) return null;

  const params = new URLSearchParams({
    projectId,
    compareOpen: '1',
    compareBase: pair.base.id,
    compareHead: pair.head.id,
  });
  return `/ade/dashboard/versions?${params.toString()}`;
}
