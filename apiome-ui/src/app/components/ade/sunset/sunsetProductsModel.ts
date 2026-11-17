/**
 * API products and plans on the sunset timeline — APX-1.4 (#6101).
 *
 * REST's sunset timeline answers `products` beside the version `entries`: every deprecated or
 * retired API product and plan, soonest retirement first. These are the rules the
 * {@link SunsetProductsTable} draws; the status words are the version table's
 * ({@link sunsetTimelineStatus}), so one legend covers both.
 */

import { productHref } from '@lib/api-products';

/** One deprecated or retired product or plan, as REST returns it. */
export interface SunsetProductEntry {
  kind: 'product' | 'plan';
  productSlug: string;
  productName: string;
  planSlug?: string | null;
  planName?: string | null;
  state: 'deprecated' | 'retired';
  deprecatedAt?: string | null;
  retireAt?: string | null;
  retiredAt?: string | null;
  /** `announced`, `imminent` or `past`. */
  timelineStatus: string;
  /** `deprecated`, `sunset_reached` or `retired`. */
  lifecyclePhase: string;
  deprecationMessage?: string | null;
  successorPlanSlug?: string | null;
  successorPlanName?: string | null;
}

/** How each lifecycle phase of a product or plan reads. */
export const PRODUCT_LIFECYCLE_LABEL: Readonly<Record<string, string>> = {
  deprecated: 'Deprecated (no new subscriptions)',
  sunset_reached: 'Retirement date passed — ready to retire',
  retired: 'Retired',
};

/**
 * The lifecycle wording for a product or plan row.
 *
 * @param phase - REST's `lifecyclePhase`.
 * @returns The label; an unknown phase reads as deprecated.
 */
export function productLifecycleLabel(phase: string | null | undefined): string {
  return PRODUCT_LIFECYCLE_LABEL[phase ?? ''] ?? PRODUCT_LIFECYCLE_LABEL.deprecated;
}

/**
 * A stable row id: the product, and the plan when there is one.
 *
 * @param entry - The row.
 * @returns `payments` or `payments/standard`.
 */
export function productRowId(entry: SunsetProductEntry): string {
  return entry.kind === 'plan' && entry.planSlug ? `${entry.productSlug}/${entry.planSlug}` : entry.productSlug;
}

/**
 * What the row names: the product, or `Payments · Standard` for a plan.
 *
 * @param entry - The row.
 * @returns The name.
 */
export function productRowName(entry: SunsetProductEntry): string {
  return entry.kind === 'plan' ? `${entry.productName} · ${entry.planName ?? entry.planSlug ?? ''}` : entry.productName;
}

/**
 * Where the row links: the product's editor (its Plans section holds the plan).
 *
 * @param entry - The row.
 * @returns The path.
 */
export function productRowHref(entry: SunsetProductEntry): string {
  return productHref(entry.productSlug);
}

/**
 * The retirement date as the table prints it: the calendar day (`2027-03-31`), else `null`.
 *
 * @param entry - The row.
 * @returns The day, or `null` when none is set.
 */
export function productRetireDay(entry: SunsetProductEntry): string | null {
  const when = entry.state === 'retired' ? entry.retiredAt ?? entry.retireAt : entry.retireAt;
  return when ? when.slice(0, 10) : null;
}
