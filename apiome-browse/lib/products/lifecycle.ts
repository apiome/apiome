/**
 * Product and plan lifecycle on an API's changelog — APX-1.4 (#6101).
 *
 * When an API belongs to a portal product that is deprecated, or that has a deprecated plan, its
 * changelog says so above the versions: what is going away, when, and what to move to. The rows
 * come from `PRODUCT_LIFECYCLE_FOR_PROJECT_SQL`; this module groups them per product and words the
 * sentences, so the page only renders.
 */

/** One row of `PRODUCT_LIFECYCLE_FOR_PROJECT_SQL`. */
export interface LifecycleRow {
  slug: string;
  name: string;
  state: string;
  retire_at: Date | string | null;
  deprecation_message: string | null;
  plan_slug: string | null;
  plan_name: string | null;
  plan_retire_at: Date | string | null;
  plan_deprecation_message: string | null;
  successor_name: string | null;
}

/** A deprecated plan of a product. */
export interface LifecyclePlanNotice {
  slug: string;
  name: string;
  /** `2027-03-31`, or null when no date is set. */
  retireOn: string | null;
  message: string | null;
  successorName: string | null;
}

/** What one product's notice says. */
export interface LifecycleNotice {
  productSlug: string;
  productName: string;
  /** True when the product itself is deprecated. */
  deprecated: boolean;
  retireOn: string | null;
  message: string | null;
  plans: LifecyclePlanNotice[];
}

/**
 * A timestamp as a calendar day (`2027-03-31`), deterministic for server rendering.
 *
 * @param value - A `Date`, an ISO string, or null.
 * @returns The day, or null.
 */
export function calendarDay(value: Date | string | null | undefined): string | null {
  if (!value) return null;
  const iso = value instanceof Date ? value.toISOString() : String(value);
  return /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : null;
}

/**
 * Group the rows into one notice per product, in row order.
 *
 * @param rows - The statement's rows.
 * @returns The notices.
 */
export function toLifecycleNotices(rows: readonly LifecycleRow[]): LifecycleNotice[] {
  const bySlug = new Map<string, LifecycleNotice>();
  for (const row of rows) {
    let notice = bySlug.get(row.slug);
    if (!notice) {
      notice = {
        productSlug: row.slug,
        productName: row.name,
        deprecated: row.state === 'deprecated',
        retireOn: calendarDay(row.retire_at),
        message: row.deprecation_message?.trim() || null,
        plans: [],
      };
      bySlug.set(row.slug, notice);
    }
    if (row.plan_slug && !notice.plans.some((plan) => plan.slug === row.plan_slug)) {
      notice.plans.push({
        slug: row.plan_slug,
        name: row.plan_name ?? row.plan_slug,
        retireOn: calendarDay(row.plan_retire_at),
        message: row.plan_deprecation_message?.trim() || null,
        successorName: row.successor_name ?? null,
      });
    }
  }
  return [...bySlug.values()];
}

/**
 * The product's own sentence, or null when only its plans are deprecated.
 *
 * @param notice - The notice.
 * @returns `Payments is deprecated and retires on 2027-06-30.`
 */
export function productSentence(notice: LifecycleNotice): string | null {
  if (!notice.deprecated) return null;
  return notice.retireOn
    ? `${notice.productName} is deprecated and retires on ${notice.retireOn}.`
    : `${notice.productName} is deprecated.`;
}

/**
 * One deprecated plan's sentence.
 *
 * @param plan - The plan.
 * @returns `The Standard plan is deprecated and retires on 2027-03-31. Move to Premium; your key keeps working.`
 */
export function planSentence(plan: LifecyclePlanNotice): string {
  const head = plan.retireOn
    ? `The ${plan.name} plan is deprecated and retires on ${plan.retireOn}.`
    : `The ${plan.name} plan is deprecated.`;
  const move = plan.successorName ? ` Move to ${plan.successorName}; your key keeps working.` : '';
  return `${head} It takes no new subscriptions.${move}`;
}
