/**
 * Product and plan lifecycle in the UI — APX-1.4 (#6101).
 *
 * API products and their plans share one lifecycle (apiome-rest `app.api_lifecycle`):
 *
 * ```
 * draft ⇄ published → deprecated → retired
 *              ↑          │
 *              └──────────┘  reinstate
 * ```
 *
 * A deprecated plan blocks new subscriptions and carries a retirement date, a message and the plan
 * consumers move to; a deprecated record retires on or after its date. This module mirrors those
 * rules so the editors offer only the steps REST accepts, and converts the retirement date between a
 * date input (`2027-03-31`) and the wire (`2027-03-31T00:00:00Z`).
 */

export const LIFECYCLE_STATES = ['draft', 'published', 'deprecated', 'retired'] as const;
export type LifecycleState = (typeof LIFECYCLE_STATES)[number];

/** Where each state may go next (staying put is always allowed). */
const NEXT: Readonly<Record<LifecycleState, readonly LifecycleState[]>> = {
  draft: ['published'],
  published: ['draft', 'deprecated'],
  deprecated: ['published', 'retired'],
  retired: [],
};

/**
 * The states a record may be saved in: a new one starts as draft or published; a stored one stays
 * where it is or takes one lifecycle step.
 *
 * @param current - The stored state, or `null` for a record not created yet.
 * @returns The states, in lifecycle order.
 */
export function selectableStates(current: LifecycleState | null): LifecycleState[] {
  if (current === null) return ['draft', 'published'];
  const allowed = new Set<LifecycleState>([current, ...NEXT[current]]);
  return LIFECYCLE_STATES.filter((state) => allowed.has(state));
}

/** A calendar date as a date input holds it. */
const DATE_INPUT = /^\d{4}-\d{2}-\d{2}$/;

/**
 * A wire timestamp as a date input's value.
 *
 * @param iso - The timestamp (`2027-03-31T00:00:00+00:00`), or `null`.
 * @returns `2027-03-31`, or `''`.
 */
export function dateInputValue(iso: string | null | undefined): string {
  return iso ? iso.slice(0, 10) : '';
}

/**
 * A date input's value as the wire timestamp REST stores (midnight UTC).
 *
 * @param value - What the input holds.
 * @returns `2027-03-31T00:00:00Z`, or `null` when empty or not a date.
 */
export function retireAtFromInput(value: string): string | null {
  const trimmed = value.trim();
  return DATE_INPUT.test(trimmed) ? `${trimmed}T00:00:00Z` : null;
}

/**
 * Whether a deprecated record may retire now: it has no date, or the date has come.
 *
 * @param retireAt - The stored retirement date, or `null`.
 * @param now - The current time.
 * @returns True when retiring is allowed.
 */
export function canRetireNow(retireAt: string | null | undefined, now: Date = new Date()): boolean {
  if (!retireAt) return true;
  const when = Date.parse(retireAt);
  return Number.isNaN(when) || when <= now.getTime();
}

/**
 * How a retirement date reads: `Retires on 2027-03-31`, or a fallback.
 *
 * @param retireAt - The retirement date, or `null`.
 * @returns The sentence.
 */
export function retireText(retireAt: string | null | undefined): string {
  return retireAt ? `Retires on ${dateInputValue(retireAt)}` : 'No retirement date';
}
