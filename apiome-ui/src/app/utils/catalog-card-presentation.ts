/**
 * Catalog presentation helpers (MFI-23.x).
 *
 * Small, pure derivations shared by the Catalog screen's card/table (MFI-23.3/23.4) and the catalog
 * item detail view (MFI-23.9): the avatar initials, a deterministic avatar gradient keyed off the
 * item id, and the short `cat_…` id shown under the name. Kept here (not inlined per-screen) so the
 * card and the detail header render an item identically.
 */

import { letterGradeFromOverallPercent } from './numeric-score-tier';

/** The avatar gradient palette; an item's id picks one deterministically. */
export const CATALOG_CARD_GRADIENTS = [
  'from-indigo-500 to-purple-500',
  'from-emerald-500 to-cyan-500',
  'from-amber-500 to-orange-500',
  'from-rose-500 to-pink-500',
  'from-purple-500 to-fuchsia-500',
  'from-sky-500 to-cyan-500',
] as const;

/** Up-to-two-letter initials for an avatar tile / creator chip, derived from a name. */
export function catalogCardInitials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (parts.length >= 2) return `${parts[0][0] ?? ''}${parts[1][0] ?? ''}`.toUpperCase();
  const w = parts[0] ?? '?';
  return w.slice(0, 2).toUpperCase();
}

/** A stable `from-…/to-…` gradient class for an item id (same id → same gradient). */
export function catalogCardGradientClass(itemId: string): string {
  let h = 0;
  for (let i = 0; i < itemId.length; i++) {
    h = (h + itemId.charCodeAt(i) * (i + 1)) % 1_000_000;
  }
  return CATALOG_CARD_GRADIENTS[h % CATALOG_CARD_GRADIENTS.length] ?? CATALOG_CARD_GRADIENTS[0];
}

/** A short, human-friendly id shown under the item name (a catalog item's id is a project id). */
export function formatShortCatalogId(id: string): string {
  const compact = id.replace(/-/g, '');
  return `cat_${compact.slice(0, 5)}`;
}

/**
 * The letter grade shown for a catalog item (MFI-24.4): its server-captured `qualityGrade` when
 * present, otherwise derived from the numeric `qualityScore` via the shared score→letter bands, or
 * `null` when neither is known. Feeds the table's {@link GradeChip} and keeps the Grade column
 * consistent with the `grade` sort (which orders on `qualityGrade`).
 */
export function catalogItemGrade(item: {
  qualityGrade?: string | null;
  qualityScore?: number | null;
}): string | null {
  if (item.qualityGrade && item.qualityGrade.trim()) return item.qualityGrade.trim();
  if (typeof item.qualityScore === 'number' && !Number.isNaN(item.qualityScore)) {
    return letterGradeFromOverallPercent(item.qualityScore);
  }
  return null;
}
