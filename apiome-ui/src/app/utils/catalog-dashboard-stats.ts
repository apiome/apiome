/**
 * Catalog stats-row metrics (MFI-24.1, #4081).
 *
 * The mockup opens the Catalog list with a four-card stats grid (`renderCatalog`,
 * `docs/planning/mockups/multi-format-import/index.html:1407-1422`); the implementation had
 * collapsed this into a single `headerSubtitle` string, dropping the formats-represented and
 * converted-to-OpenAPI metrics and the letter grade on average quality. This module recomputes
 * those four metrics from the already-fetched catalog list — no new API — so the page can render
 * the cards and the numbers can be unit-tested from a fixture list.
 *
 * The headline metrics describe the *live* catalog, so cataloged-items / active / disabled /
 * average-quality / formats are all computed over the non-deleted slice; toggling "Show deleted"
 * therefore does not move the headline numbers. The converted count likewise reflects live items on
 * a promotion path.
 */

import {
  letterGradeFromOverallPercent,
  getNumericScoreTier,
  type NumericScoreTierStyle,
} from './numeric-score-tier';
import { catalogFormatFamilyId, catalogFormatFamilyLabel } from './catalog-format-registry';

/** The minimal catalog-item shape the stats need — a subset of the page's `CatalogItem`. */
export interface CatalogStatsItem {
  enabled: boolean;
  deleted_at: string | null;
  qualityScore?: number | null;
  sourceFormat?: string | null;
  /** Truthy when the item has been converted to an OpenAPI project (MFI-23.11). */
  conversion?: unknown;
}

/** The four metrics rendered by the Catalog stats row (MFI-24.1). */
export interface CatalogStats {
  /** Non-deleted cataloged items — the headline count. */
  total: number;
  /** Non-deleted items that are enabled. */
  active: number;
  /** Non-deleted items that are disabled (present but not enabled). */
  disabled: number;
  /** Rounded mean quality score across scored non-deleted items, or null when none are scored. */
  avgScore: number | null;
  /** Letter grade for {@link avgScore} (A–F), or null when no items are scored. */
  avgGrade: 'A' | 'B' | 'C' | 'D' | 'F' | null;
  /** Tier style (colour band) for {@link avgScore}, or null when no items are scored. */
  avgTier: NumericScoreTierStyle | null;
  /** Distinct recognisable source formats across non-deleted items. */
  formatCount: number;
  /** Up to a handful of distinct format display labels, for the sample badge. */
  sampleFormats: string[];
  /** Non-deleted items that have been converted to an OpenAPI project. */
  converted: number;
}

/** How many distinct format labels the sample badge shows before eliding the rest. */
const SAMPLE_FORMAT_LIMIT = 4;

/**
 * Compute the Catalog stats-row metrics from the fetched item list.
 *
 * @param items The catalog list as fetched from `/api/catalog` (may include soft-deleted items
 *   when "Show deleted" is on; those are excluded from the headline metrics).
 * @returns The four metrics plus the sample-format labels and the average-quality tier style.
 */
export function computeCatalogStats(items: readonly CatalogStatsItem[]): CatalogStats {
  const live = items.filter((i) => !i.deleted_at);

  const active = live.filter((i) => i.enabled).length;
  const disabled = live.length - active;

  const scored = live
    .map((i) => i.qualityScore)
    .filter((x): x is number => typeof x === 'number' && Number.isFinite(x));
  const avgScore =
    scored.length > 0 ? Math.round(scored.reduce((a, b) => a + b, 0) / scored.length) : null;
  const avgGrade = avgScore != null ? letterGradeFromOverallPercent(avgScore) : null;
  const avgTier = avgScore != null ? getNumericScoreTier(avgScore) : null;

  // Distinct source formats, resolved to canonical labels so version variants (openapi30 vs
  // openapi31) collapse and unknown-but-present formats still count under their raw token.
  const formatLabels = new Map<string, string>();
  for (const item of live) {
    const raw = item.sourceFormat?.trim();
    if (!raw) continue;
    const familyId = catalogFormatFamilyId(raw);
    if (familyId) {
      if (!formatLabels.has(familyId)) formatLabels.set(familyId, catalogFormatFamilyLabel(familyId));
      continue;
    }
    const key = raw.toLowerCase();
    if (!formatLabels.has(key)) formatLabels.set(key, raw);
  }

  const converted = live.filter((i) => i.conversion != null).length;

  return {
    total: live.length,
    active,
    disabled,
    avgScore,
    avgGrade,
    avgTier,
    formatCount: formatLabels.size,
    sampleFormats: [...formatLabels.values()].slice(0, SAMPLE_FORMAT_LIMIT),
    converted,
  };
}
