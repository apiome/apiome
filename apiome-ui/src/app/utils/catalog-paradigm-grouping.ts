/**
 * Group catalog cards by resolved paradigm for the Catalog list (MFI-24.2, #4082).
 *
 * The Catalog card view can be sectioned by API paradigm — a header (label + item count + divider)
 * per group, iterated in a **fixed** order that mirrors the multi-format-import mockup's `PARADIGM`
 * map: graph → rpc → event → rest → data-schema. This module is the pure, data-driven core behind
 * that view so the page component stays presentational and the grouping/ordering can be unit-tested
 * without rendering.
 *
 * Grouping resolves each item's raw `protocol` through {@link resolveCatalogProtocol} (the same
 * registry the pills use), so `data-schema`, `data_schema` and `dataschema` all land in one bucket.
 * Every item is placed: any item whose paradigm falls outside the fixed five (e.g. `agent`) or whose
 * protocol is absent/unrecognised is collected into a trailing **Other** group, so grouping never
 * silently drops a card. Empty paradigms are omitted, and input order is preserved within each group
 * (so an already-sorted list stays sorted inside its sections).
 */

import { resolveCatalogProtocol } from './catalog-format-registry';

/**
 * The paradigms rendered as sections, in fixed display order (mockup `PARADIGM`,
 * `multi-format-import/index.html:1369-1377`). Each value is a canonical `CatalogProtocol` id as
 * returned by {@link resolveCatalogProtocol}.
 */
export const CATALOG_PARADIGM_ORDER = ['graph', 'rpc', 'event', 'rest', 'dataschema'] as const;

/** The synthetic bucket id for items outside the fixed paradigm order (agent / unknown / absent). */
export const CATALOG_PARADIGM_OTHER_ID = 'other';

/** A single rendered paradigm section: its bucket id, display label, and the items within it. */
export interface CatalogParadigmGroup<T> {
  /** The resolved `CatalogProtocol` id, or {@link CATALOG_PARADIGM_OTHER_ID} for the trailing bucket. */
  id: string;
  /** The header label (the registry's protocol label, or `Other` for the trailing bucket). */
  label: string;
  /** The items in this section, in the same relative order they arrived in. */
  items: T[];
}

/** The minimal item shape the grouper needs — just the raw imported paradigm/protocol token. */
export interface CatalogParadigmItem {
  protocol?: string | null;
}

/**
 * Group catalog items by resolved paradigm into ordered sections.
 *
 * Items are bucketed by {@link resolveCatalogProtocol}; the fixed-order paradigms
 * ({@link CATALOG_PARADIGM_ORDER}) are emitted first, each only when it has at least one item, then a
 * single trailing **Other** section for everything else (unknown/absent/`agent`). Relative order is
 * preserved within every bucket, so a pre-sorted input keeps its order inside each section.
 *
 * @param items The (already filtered/sorted) catalog items to group.
 * @returns The non-empty sections, in fixed paradigm order with `Other` last. Empty input → `[]`.
 */
export function groupCatalogItemsByParadigm<T extends CatalogParadigmItem>(
  items: readonly T[],
): CatalogParadigmGroup<T>[] {
  const known = new Set<string>(CATALOG_PARADIGM_ORDER);
  const buckets = new Map<string, T[]>();
  const labels = new Map<string, string>();
  const other: T[] = [];

  for (const item of items) {
    const proto = resolveCatalogProtocol(item.protocol);
    if (proto && known.has(proto.id)) {
      let bucket = buckets.get(proto.id);
      if (!bucket) {
        bucket = [];
        buckets.set(proto.id, bucket);
        labels.set(proto.id, proto.label);
      }
      bucket.push(item);
    } else {
      other.push(item);
    }
  }

  const groups: CatalogParadigmGroup<T>[] = [];
  for (const id of CATALOG_PARADIGM_ORDER) {
    const bucket = buckets.get(id);
    if (bucket && bucket.length > 0) {
      groups.push({ id, label: labels.get(id) ?? id, items: bucket });
    }
  }
  if (other.length > 0) {
    groups.push({ id: CATALOG_PARADIGM_OTHER_ID, label: 'Other', items: other });
  }
  return groups;
}
