/**
 * Public catalog analytics — pure presentation helpers (V2-MCP-32.1 / MCAT-18.1, #4645).
 *
 * The React-free layer over {@link McpPublicCatalogInsight}: it shapes the raw category / transport /
 * grade mixes into view rows with whole-number percentages, decides the empty state, and classifies a
 * grade into a display tone. Keeping this free of React lets the public `CatalogAnalyticsClient` stay a
 * thin renderer and lets the shaping be unit-tested directly (vitest), mirroring how the private
 * dashboard splits its `mcpCatalogInsightUi` parser from its panel.
 */

import type { McpPublicCatalogBucket, McpPublicCatalogInsight } from './types';

/** One breakdown row ready to render: its label, count, and share of the relevant total. */
export interface McpCatalogBucketView {
  label: string;
  count: number;
  /** Whole-number percentage of the supplied total (`0` when the total is zero — never NaN). */
  percent: number;
}

/** True when the public catalog holds no endpoints → the page shows its empty state, not tiles. */
export function mcpPublicCatalogIsEmpty(insight: McpPublicCatalogInsight): boolean {
  return insight.endpoint_count <= 0;
}

/** A count as a whole-number percentage of `total` (`0` when `total` is non-positive). */
export function mcpCatalogPercent(count: number, total: number): number {
  if (!total || total <= 0) return 0;
  return Math.round((count / total) * 100);
}

/**
 * Shape a composition breakdown into percentage-bearing view rows. `total` is the denominator the
 * shares are taken against (the endpoint count for category/transport; the scored count — i.e. the
 * sum of the grade buckets — for grade). When omitted, the sum of the buckets' own counts is used.
 * Order is preserved (the query already sorts each mix).
 */
export function mcpCatalogBucketViews(
  buckets: readonly McpPublicCatalogBucket[],
  total?: number,
): McpCatalogBucketView[] {
  const denom =
    total !== undefined ? total : buckets.reduce((sum, bucket) => sum + bucket.count, 0);
  return buckets.map((bucket) => ({
    label: bucket.label,
    count: bucket.count,
    percent: mcpCatalogPercent(bucket.count, denom),
  }));
}

/** The sum of a breakdown's counts — the natural denominator for that mix's percentages. */
export function mcpCatalogBucketTotal(buckets: readonly McpPublicCatalogBucket[]): number {
  return buckets.reduce((sum, bucket) => sum + bucket.count, 0);
}

/** A grade's display tone: A/B are good, C is ok, D-and-below (and anything else) poor. */
export type McpGradeTone = 'good' | 'ok' | 'poor';

/** Classify an A–F grade into its display tone (A/B → good, C → ok, else poor). */
export function mcpPublicGradeTone(grade: string): McpGradeTone {
  const g = grade.trim().toUpperCase().charAt(0);
  if (g === 'A' || g === 'B') return 'good';
  if (g === 'C') return 'ok';
  return 'poor';
}
