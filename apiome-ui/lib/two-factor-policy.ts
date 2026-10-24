/**
 * Tenant two-factor policy — TFA-1.3 (#5657). Client-safe types and the few pure rules apiome-ui
 * needs; the policy itself (deadline, compliance) is computed in SQL by apiome-rest
 * (`app/two_factor_policy.py`) and, for enforcement, by `lib/auth/two-factor-requirement-db.ts`.
 */

/** The grace period a tenant starts with. */
export const DEFAULT_TWO_FACTOR_GRACE_DAYS = 7;
/** The longest grace period REST accepts (the V316 check constraint). */
export const MAX_TWO_FACTOR_GRACE_DAYS = 90;

/** A member's compliance with the policy, as `GET /v1/access/{slug}/members` reports it. */
export type MemberTwoFactorStatus = 'not_required' | 'enabled' | 'grace' | 'overdue';

/** The tenant's policy, as `GET /v1/tenants/{slug}/two-factor-policy` returns it. */
export interface TwoFactorPolicy {
  /** Whether every member must turn on two-factor. */
  require_two_factor: boolean;
  /** Days a member without two-factor may keep working. */
  grace_days: number;
  /** When the requirement was last turned on (ISO-8601); `null` while off. */
  required_since: string | null;
  /** Active members by state; all zero while the policy is off. */
  compliance: { enabled: number; grace: number; overdue: number };
}

/** A change to the policy; omitted fields are left alone. */
export interface TwoFactorPolicyChange {
  require_two_factor?: boolean;
  grace_days?: number;
}

/**
 * Whether a value is a grace period REST accepts: a whole number of days, 0–90.
 *
 * @param value - The candidate.
 * @returns True when it is valid.
 */
export function isValidGraceDays(value: unknown): value is number {
  return (
    typeof value === 'number' &&
    Number.isInteger(value) &&
    value >= 0 &&
    value <= MAX_TWO_FACTOR_GRACE_DAYS
  );
}

/**
 * Whole days left before a deadline, rounded up so "due in a few hours" reads as one day.
 *
 * @param dueAt - The deadline (ISO-8601).
 * @param now - The current time (injectable for tests).
 * @returns Days left, `0` once the deadline has passed, `null` for an unreadable date.
 */
export function daysUntil(dueAt: string, now: Date = new Date()): number | null {
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) return null;
  return Math.max(0, Math.ceil((due - now.getTime()) / 86_400_000));
}

/**
 * Narrow an untrusted value to a {@link MemberTwoFactorStatus}.
 *
 * @param value - What REST sent (older servers send nothing).
 * @returns The status, or `not_required` for anything unrecognised.
 */
export function toMemberTwoFactorStatus(value: unknown): MemberTwoFactorStatus {
  return value === 'enabled' || value === 'grace' || value === 'overdue' ? value : 'not_required';
}

// ---------------------------------------------------------------------------------------------
// Enforcement: what the signed-in user owes
// ---------------------------------------------------------------------------------------------

/** One workspace that requires two-factor of a member who has not turned it on. */
export interface TwoFactorRequirementRow {
  /** The workspace's display name. */
  tenantName: string;
  /** The member's deadline in that workspace (ISO-8601). */
  dueAt: string;
}

/**
 * What the signed-in user owes across every workspace they are an active member of. Empty
 * `tenants` means nothing: two-factor is on, or no workspace requires it.
 */
export interface TwoFactorRequirement {
  /** Workspaces that require two-factor of this user, earliest deadline first. */
  tenants: TwoFactorRequirementRow[];
  /** The earliest deadline; `null` when nothing is owed. */
  dueAt: string | null;
  /** True once the earliest deadline has passed: the app is blocked until they enrol. */
  overdue: boolean;
}

/** Nothing owed. */
export const NO_TWO_FACTOR_REQUIREMENT: TwoFactorRequirement = Object.freeze({
  tenants: [],
  dueAt: null,
  overdue: false,
}) as TwoFactorRequirement;

/**
 * Fold the per-workspace deadlines into one requirement. Two-factor is per account, so the
 * earliest deadline is the one that matters — enrolling once satisfies every workspace.
 *
 * @param rows - One row per requiring workspace; unreadable dates are dropped.
 * @param now - The current time (injectable for tests).
 * @returns The requirement.
 */
export function summarizeTwoFactorRequirement(
  rows: readonly TwoFactorRequirementRow[],
  now: Date = new Date()
): TwoFactorRequirement {
  const tenants = rows
    .filter((row) => !Number.isNaN(Date.parse(row.dueAt)))
    .sort((a, b) => Date.parse(a.dueAt) - Date.parse(b.dueAt));
  if (tenants.length === 0) return NO_TWO_FACTOR_REQUIREMENT;
  const dueAt = tenants[0].dueAt;
  return { tenants, dueAt, overdue: Date.parse(dueAt) <= now.getTime() };
}

/**
 * The workspaces as one phrase: `Acme`, `Acme and Globex`, `Acme, Globex and 2 more`.
 *
 * @param tenants - The requiring workspaces, earliest deadline first.
 * @returns The phrase; `Your workspace` when the list is empty.
 */
export function requiringWorkspacesPhrase(tenants: readonly TwoFactorRequirementRow[]): string {
  const names = tenants.map((tenant) => tenant.tenantName);
  if (names.length === 0) return 'Your workspace';
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  return `${names[0]}, ${names[1]} and ${names.length - 2} more`;
}
