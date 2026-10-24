/**
 * Members list + detail logic — HIVE-5.2 (#5305).
 *
 * Authority: `docs/mockups/workspace/members.html`, whose **Notes → Keeps (1:1)** list is
 * this ticket's acceptance criteria, and `docs/mockups/DESIGN.md` §5.3, §5.4, §8.
 *
 * Everything here is pure, for the same reason {@link ../tenants/tenantsModel} is: the screen
 * this replaces decided *inside JSX* who could be suspended, what a status pill said and
 * whether the invite button was allowed — so the seat rule the licence enforces and the seat
 * rule the button drew were two different sentences that happened to agree. Written as
 * functions of their inputs they can be held to agreeing, and `tests/members-model.test.ts`
 * holds them.
 *
 * The React that draws all this lives beside it: {@link ../members/MembersTable} for the
 * list, {@link ../members/MemberDetailDrawer} for one person, and the dialogs for the four
 * decisions.
 */

import {
  daysUntil,
  toMemberTwoFactorStatus,
  type MemberTwoFactorStatus,
} from '@lib/two-factor-policy';
import type { MyPermissions, RoleRecord } from '../access/accessApi';
import type { TenantLicensePlan, TenantLicenseSeats } from '@/app/ade/dashboard/tenants/licenseApi';
import {
  seatMeterAppearance,
  seatsExhausted,
  seatsUnlimited,
} from '@/app/ade/dashboard/tenants/licenseSeats';
import type { ComingNextItem } from '@/app/components/ui/ComingNext';
import type { FactsLineFact } from '@/app/components/ui/FactsLine';
import { METER_WARN_PERCENT, type MetricTone } from '@/app/components/ui/metrics/metricTiers';

// ---------------------------------------------------------------------------------------
// Records
// ---------------------------------------------------------------------------------------

/** A membership's lifecycle state (V121), as `GET /api/access/members` reports it. */
export type MemberStatus = 'active' | 'pending' | 'suspended';

/** The lifecycle states in the order the toolbar and the summary read them. */
export const MEMBER_STATUSES: readonly MemberStatus[] = ['active', 'pending', 'suspended'];

/**
 * One row of `GET /api/access/members`.
 *
 * The three fields beyond the membership itself were added by this ticket and each reads a
 * column that already existed (apiome-rest `Database.list_members`): `joined_at` is when the
 * membership row was written, `last_active` is the account's last sign-in, and
 * `two_factor_enabled` is the Better Auth flag. All three are nullable, because a pending
 * invitation has never signed in and an older row may predate the column.
 *
 * `member_since` is the row's `updated_at`, which moves with every status change — so it
 * answers "since when has the membership read like this", not "when did they join". Both are
 * carried because the drawer says both things.
 */
export interface MemberRecord {
  user_id: string;
  name: string;
  email: string;
  status: MemberStatus;
  /** `tenant_users.updated_at` — when the membership last changed. */
  member_since: string | null;
  /** `tenant_users.created_at` — when the membership was first written. */
  joined_at?: string | null;
  /** `users.last_login_at` — the account's last sign-in, or `null` if it never has. */
  last_active?: string | null;
  /** The Better Auth `twoFactorEnabled` flag. */
  two_factor_enabled?: boolean | null;
  /**
   * Compliance with the tenant's two-factor policy (TFA-1.3, #5657): `not_required` while the
   * policy is off; otherwise `enabled`, `grace` (before the deadline) or `overdue`. Absent from
   * older servers, which reads as `not_required`.
   */
  two_factor_status?: MemberTwoFactorStatus | null;
  /** The member's two-factor deadline (ISO-8601); `null` while the policy is off. */
  two_factor_due_at?: string | null;
  role_id: string | null;
  role_name: string | null;
  role_slug: string | null;
  is_admin: boolean;
}

// A role and the viewer's own grants are the Roles screen's records as much as this one's
// (HIVE-5.3, #5306), so they are declared beside the reads that return them and re-exported
// here — every members call site keeps importing them from this module.
export type { MyPermissions, RolePermissionCell, RoleRecord } from '../access/accessApi';

/** One row of the access ledger, as `GET /api/access/audit` returns it. */
export interface AccessAuditRecord {
  id: string;
  created_at: string;
  actor_id: string | null;
  actor_label: string | null;
  action: string;
  target: string | null;
  source: string | null;
}

// ---------------------------------------------------------------------------------------
// Identity
// ---------------------------------------------------------------------------------------

/**
 * How a member is named on screen.
 *
 * A pending invitation often has no display name yet — the account exists but has never been
 * filled in — so the address is the name, which is what the mockup's pending row draws.
 *
 * @param member The member.
 * @returns Their display name, falling back to their email address.
 */
export function memberDisplayName(member: Pick<MemberRecord, 'name' | 'email'>): string {
  return member.name?.trim() || member.email;
}

/**
 * Whether this row is an invitation rather than a member.
 *
 * @param member The member.
 * @returns True for a `pending` membership.
 */
export function isPendingInvite(member: Pick<MemberRecord, 'status'>): boolean {
  return member.status === 'pending';
}

/**
 * The status column's label.
 *
 * The strings are the shared vocabulary's own, capitalised — `Badge` resolves the *tone* from
 * the same word, so the pill's colour and its text can never describe different states.
 *
 * @param status The lifecycle state.
 * @returns `'Active'`, `'Pending'` or `'Suspended'`.
 */
export function memberStatusLabel(status: MemberStatus): string {
  return status.charAt(0).toUpperCase() + status.slice(1);
}

// ---------------------------------------------------------------------------------------
// Capability gates
// ---------------------------------------------------------------------------------------

/** What the viewer may do on this screen. */
export interface MemberCapabilities {
  /** Open the invite dialog. */
  canInvite: boolean;
  /** Change a role, suspend or reinstate. */
  canEdit: boolean;
  /** Offboard a member or cancel an invitation. */
  canDelete: boolean;
  /**
   * Reset a member's two-factor (TFA-1.2, #5656). Owners only — `is_admin` on `permissions/me`,
   * which is the owner-equivalent flag — and not a `members:*` grant: it reaches past the
   * workspace into the member's own account. apiome-rest enforces the same rule.
   */
  canResetTwoFactor: boolean;
}

/** No permissions at all — what the screen assumes until `permissions/me` answers. */
const NO_CAPABILITIES: MemberCapabilities = {
  canInvite: false,
  canEdit: false,
  canDelete: false,
  canResetTwoFactor: false,
};

/**
 * Read the viewer's gates off their effective permissions.
 *
 * Administrators hold everything; everyone else needs the matching `members:*` grant. The
 * mapping is the one the screen already used and the mockup's Keeps list quotes, moved out of
 * JSX so the table, the drawer and the dialogs cannot each decide it slightly differently.
 *
 * @param perms The `permissions/me` payload, or `null` before it resolves.
 * @returns The three gates; all closed while permissions are unknown.
 */
export function memberCapabilities(perms: MyPermissions | null | undefined): MemberCapabilities {
  if (!perms) return NO_CAPABILITIES;
  const has = (permission: string) => perms.is_admin || perms.permissions.includes(permission);
  return {
    canInvite: has('members:create'),
    canEdit: has('members:edit'),
    canDelete: has('members:delete'),
    canResetTwoFactor: perms.is_admin,
  };
}

/**
 * Whether a row is the viewer's own.
 *
 * @param member The row.
 * @param viewerId The session's user id, or `null` before the session resolves.
 * @returns True when they are the same person.
 */
export function isSelf(
  member: Pick<MemberRecord, 'user_id'>,
  viewerId: string | null | undefined
): boolean {
  return Boolean(viewerId) && member.user_id === viewerId;
}

/** What a single row offers, once the gates and the row itself are both taken into account. */
export interface MemberRowActions {
  /** The role select is live rather than a pill. */
  canChangeRole: boolean;
  /** Suspend or reinstate is offered. */
  canChangeStatus: boolean;
  /** Offboard (or, for an invitation, Cancel invite) is offered. */
  canOffboard: boolean;
  /** Re-issue the invitation is offered — pending rows only. */
  canResendInvite: boolean;
  /**
   * Reset two-factor is offered: an owner, looking at somebody else who is an active member with
   * two-factor on. Whether the member also belongs to another workspace — which is what makes
   * apiome-rest refuse — is not something this screen can know, so that refusal is shown when it
   * comes back.
   */
  canResetTwoFactor: boolean;
  /** Why the row's controls are inert, for a `title`; `null` when they are live. */
  disabledReason: string | null;
}

/** What the mockup's disabled own-row select says on hover. */
export const OWN_ROW_REASON = 'You cannot change your own membership';

/**
 * What one row lets the viewer do.
 *
 * The own-row rule is the one worth stating out loud: a person must not be able to demote or
 * remove themselves out of the tenant they are administering, and the screen this replaces
 * enforced that nowhere — an owner could offboard themselves and lose the workspace. The
 * mockup draws the same rule as a disabled select with a reason on hover, which is what
 * {@link OWN_ROW_REASON} is for.
 *
 * @param member The row.
 * @param options.capabilities The viewer's gates, from {@link memberCapabilities}.
 * @param options.viewerId The session's user id.
 * @returns Which of the row's four affordances are live, and why they are not.
 */
export function memberRowActions(
  member: MemberRecord,
  options: { capabilities: MemberCapabilities; viewerId: string | null | undefined }
): MemberRowActions {
  const own = isSelf(member, options.viewerId);
  const { canEdit, canDelete, canInvite, canResetTwoFactor } = options.capabilities;
  return {
    canResetTwoFactor:
      canResetTwoFactor && !own && member.status === 'active' && Boolean(member.two_factor_enabled),
    canChangeRole: canEdit && !own,
    canChangeStatus: canEdit && !own,
    canOffboard: canDelete && !own,
    canResendInvite: canInvite && isPendingInvite(member),
    disabledReason: own ? OWN_ROW_REASON : null,
  };
}

// ---------------------------------------------------------------------------------------
// The list
// ---------------------------------------------------------------------------------------

/** The toolbar's facets. `all` is the resting state, not a filter. */
export type MemberFacet = 'all' | 'active' | 'pending' | 'suspended' | 'admins' | 'needs2fa';

/**
 * The facets in the order the toolbar draws them. `needs2fa` (TFA-1.3) is drawn only while the
 * tenant requires two-factor — see {@link twoFactorPolicyActive}.
 */
export const MEMBER_FACETS: readonly MemberFacet[] = [
  'all',
  'active',
  'pending',
  'suspended',
  'admins',
  'needs2fa',
];

/** The chip labels, which the mockup fixes. */
export const MEMBER_FACET_LABELS: Readonly<Record<MemberFacet, string>> = {
  all: 'All',
  active: 'Active',
  pending: 'Pending',
  suspended: 'Suspended',
  admins: 'Admins',
  needs2fa: 'Needs two-factor',
};

/**
 * Whether a row belongs to a facet.
 *
 * @param member The row.
 * @param facet The facet being tested.
 * @returns True when the row would survive that chip.
 */
export function matchesMemberFacet(member: MemberRecord, facet: MemberFacet): boolean {
  if (facet === 'admins') return member.is_admin;
  if (facet === 'needs2fa') return memberNeedsTwoFactor(member);
  if (facet === 'all') return true;
  return member.status === facet;
}

/**
 * How many rows each chip would leave, for the faint count beside its label.
 *
 * Counted against the *search-filtered* rows rather than the whole list, so the numbers
 * describe what pressing the chip would actually do from here — the same rule
 * {@link ../tenants/tenantsModel.tenantFacetCounts} follows.
 *
 * @param members The rows the search box has already narrowed.
 * @returns A count per facet.
 */
export function memberFacetCounts(
  members: readonly MemberRecord[]
): Readonly<Record<MemberFacet, number>> {
  return {
    all: members.length,
    active: members.filter((member) => member.status === 'active').length,
    pending: members.filter((member) => member.status === 'pending').length,
    suspended: members.filter((member) => member.status === 'suspended').length,
    admins: members.filter((member) => member.is_admin).length,
    needs2fa: members.filter(memberNeedsTwoFactor).length,
  };
}

// ---------------------------------------------------------------------------------------
// Two-factor compliance (TFA-1.3, #5657)
// ---------------------------------------------------------------------------------------

/**
 * A member's compliance with the tenant's two-factor policy.
 *
 * @param member The row.
 * @returns The status REST computed; `not_required` when it sent none.
 */
export function memberTwoFactorStatus(member: MemberRecord): MemberTwoFactorStatus {
  return toMemberTwoFactorStatus(member.two_factor_status);
}

/**
 * Whether a member still has to turn on two-factor: the policy is on and they are in their grace
 * period or past it. A pending invitation or a suspended member is not counted — they cannot sign
 * in to comply, and REST's compliance totals count active members only.
 *
 * @param member The row.
 * @returns True for an active member in `grace` or `overdue`.
 */
export function memberNeedsTwoFactor(member: MemberRecord): boolean {
  const status = memberTwoFactorStatus(member);
  return member.status === 'active' && (status === 'grace' || status === 'overdue');
}

/**
 * Whether the tenant requires two-factor, as far as the rows say: any row carries a status other
 * than `not_required`. Decides whether the **Needs two-factor** chip is drawn.
 *
 * @param members Every member of the tenant.
 * @returns True when the policy is on.
 */
export function twoFactorPolicyActive(members: readonly MemberRecord[]): boolean {
  return members.some((member) => memberTwoFactorStatus(member) !== 'not_required');
}

/** What a row's two-factor compliance badge says. */
export interface MemberTwoFactorBadge {
  /** `danger` past the deadline, `warn` before it (Badge variants). */
  tone: 'danger' | 'warn';
  /** The badge text, e.g. `2FA overdue` or `2FA due in 3 days`. */
  label: string;
}

/**
 * The compliance badge a row carries, if any: only a member who still has to comply gets one.
 *
 * @param member The row.
 * @param now The current time (injectable for tests).
 * @returns The badge, or `null` when there is nothing to chase.
 */
export function memberTwoFactorBadge(member: MemberRecord, now: Date = new Date()): MemberTwoFactorBadge | null {
  if (!memberNeedsTwoFactor(member)) return null;
  if (memberTwoFactorStatus(member) === 'overdue') return { tone: 'danger', label: '2FA overdue' };
  const days = member.two_factor_due_at ? daysUntil(member.two_factor_due_at, now) : null;
  if (days === null) return { tone: 'warn', label: '2FA due' };
  return { tone: 'warn', label: `2FA due in ${days} ${days === 1 ? 'day' : 'days'}` };
}

/**
 * Narrow the list by the toolbar's search box: name or email, substring, folded case.
 *
 * The mockup's placeholder is "Filter by name or email…", and those are the two things a
 * reader has in hand when they come looking for one person.
 *
 * @param members Every member of the tenant.
 * @param query The search box's contents; blank or whitespace matches everything.
 * @returns The matching rows, in the order given.
 */
export function searchMembers(
  members: readonly MemberRecord[],
  query: string
): MemberRecord[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...members];
  return members.filter(
    (member) =>
      member.name.toLowerCase().includes(needle) || member.email.toLowerCase().includes(needle)
  );
}

/** The columns the table can be ordered by. */
export type MemberSortColumn = 'user' | 'status' | 'lastActive' | 'joined';

/** Where a member sits in the lifecycle order — active, then pending, then suspended. */
const STATUS_RANK: Readonly<Record<MemberStatus, number>> = {
  active: 0,
  pending: 1,
  suspended: 2,
};

/**
 * A timestamp as a sortable number, with "never" sorting last in both directions.
 *
 * A member who has never signed in has no last-active instant, and treating that as epoch
 * zero would file them among the most stale — which is a claim about them rather than an
 * admission that there is nothing to say. `NaN` cannot be ordered, so the comparator below
 * handles the absent case explicitly and this only has to parse.
 *
 * @param iso An ISO timestamp, or a nullish value for "never".
 * @returns Milliseconds since the epoch, or `null` when there is no instant.
 */
function timeValue(iso: string | null | undefined): number | null {
  if (!iso) return null;
  const ms = new Date(iso).getTime();
  return Number.isFinite(ms) ? ms : null;
}

/**
 * Compare two members on one column, ascending.
 *
 * @param a The first row.
 * @param b The second row.
 * @param column The column being ordered by.
 * @returns A negative number when `a` sorts first, positive when `b` does, 0 when tied.
 */
function compareMembers(a: MemberRecord, b: MemberRecord, column: MemberSortColumn): number {
  if (column === 'status') {
    return STATUS_RANK[a.status] - STATUS_RANK[b.status];
  }
  if (column === 'lastActive' || column === 'joined') {
    const left = timeValue(column === 'lastActive' ? a.last_active : a.joined_at);
    const right = timeValue(column === 'lastActive' ? b.last_active : b.joined_at);
    // "Never" is not early, it is absent: it goes to the end of an ascending sort and stays
    // at the end when the direction flips, because the comparator's caller only negates the
    // *ranked* result.
    if (left === null && right === null) return 0;
    if (left === null) return 1;
    if (right === null) return -1;
    return left - right;
  }
  return 0;
}

/**
 * Order the list.
 *
 * User is the resting order and the mockup's default. Every other column breaks its ties by
 * display name so the order is total — two renders over the same data always agree, which a
 * sort on a status rank alone does not guarantee.
 *
 * Rows with no timestamp keep their place at the end whichever way the column points, so
 * flipping the direction never fills the top of the table with people about whom nothing is
 * known.
 *
 * @param members The rows to order.
 * @param sort The sorted column and direction, or `null` for the API's own order (by name).
 * @returns A new, sorted array; the input is left alone.
 */
export function sortMembers(
  members: readonly MemberRecord[],
  sort: { column: string; direction: 'asc' | 'desc' } | null | undefined
): MemberRecord[] {
  if (!sort) return [...members];
  const column = sort.column as MemberSortColumn;
  const factor = sort.direction === 'desc' ? -1 : 1;
  return [...members].sort((a, b) => {
    const missingA = isMissingFor(a, column);
    const missingB = isMissingFor(b, column);
    if (missingA !== missingB) return missingA ? 1 : -1;
    const ranked = compareMembers(a, b, column);
    if (ranked !== 0) return ranked * factor;
    return memberDisplayName(a).localeCompare(memberDisplayName(b)) * factor;
  });
}

/**
 * Whether a row has nothing to show in the sorted column.
 *
 * @param member The row.
 * @param column The column being ordered by.
 * @returns True when the cell would read `—`.
 */
function isMissingFor(member: MemberRecord, column: MemberSortColumn): boolean {
  if (column === 'lastActive') return timeValue(member.last_active) === null;
  if (column === 'joined') return timeValue(member.joined_at) === null;
  return false;
}

/** The counts the table foot prints ("6 people · 4 active · 1 pending · 1 suspended"). */
export interface MemberSummary {
  total: number;
  active: number;
  pending: number;
  suspended: number;
  admins: number;
}

/**
 * Count the list for the table foot and the page header.
 *
 * Counts the *unfiltered* list — the foot reports the tenant, not the current search.
 *
 * @param members Every member of the tenant.
 * @returns Totals per lifecycle state, plus how many administer the tenant.
 */
export function summariseMembers(members: readonly MemberRecord[]): MemberSummary {
  const counts = memberFacetCounts(members);
  return {
    total: counts.all,
    active: counts.active,
    pending: counts.pending,
    suspended: counts.suspended,
    admins: counts.admins,
  };
}

/**
 * The page header's sub-line: how many people, and how many are still invitations.
 *
 * Kept from the screen this replaces — "{n} members · {p} pending" — because the mockup's
 * Keeps list quotes it, with the pending clause omitted when there are none rather than
 * printed as "0 pending".
 *
 * @param summary The counts.
 * @returns e.g. `"5 members · 1 pending"`, or `"1 member"`.
 */
export function describeMemberCount(summary: MemberSummary): string {
  const people = `${summary.total} ${summary.total === 1 ? 'member' : 'members'}`;
  return summary.pending > 0 ? `${people} · ${summary.pending} pending` : people;
}

/**
 * The table foot's sentence, which enumerates every lifecycle state that has anyone in it.
 *
 * @param summary The counts.
 * @returns e.g. `"6 people · 4 active · 1 pending · 1 suspended"`, or `"No members"`.
 */
export function describeMemberBreakdown(summary: MemberSummary): string {
  if (summary.total === 0) return 'No members';
  const parts = [`${summary.total} ${summary.total === 1 ? 'person' : 'people'}`];
  for (const status of MEMBER_STATUSES) {
    const count = summary[status];
    if (count > 0) parts.push(`${count} ${status}`);
  }
  return parts.join(' · ');
}

// ---------------------------------------------------------------------------------------
// Seats
// ---------------------------------------------------------------------------------------

/** The `title` on the invite control once every seat is taken — quoted by the Keeps list. */
export const SEATS_EXHAUSTED_TITLE =
  'All member seats are in use — upgrade the plan to add more.';

/**
 * Whether inviting is refused because the licence has no seat left.
 *
 * A thin wrapper over the shared {@link ../tenants/licenseSeats.seatsExhausted} rather than a
 * second rule: it is the same condition apiome-rest enforces (OLO-5.3), and the point of
 * naming it here is that a `null` licence — the read failed, or the tenant predates the
 * backfill — must *not* read as at capacity. Refusing an invite because a best-effort call
 * failed would be the screen inventing a limit the licence never stated.
 *
 * @param seats Seat usage, or `null` when the licence could not be read.
 * @returns True only when a licence was read and it has no seat left.
 */
export function inviteBlockedBySeats(seats: TenantLicenseSeats | null | undefined): boolean {
  return Boolean(seats) && seatsExhausted(seats as TenantLicenseSeats);
}

/**
 * Seat usage as it would read *after* one more invitation.
 *
 * The invite dialog prints this so the consequence of pressing Send is visible before it is
 * pressed. Capped at the limit: the preview is a forecast of an allowed action, and an
 * invitation that would exceed the licence is refused rather than shown as "6 of 5".
 *
 * @param seats Current seat usage.
 * @returns The projected usage, with `used` never above `max` on a limited plan.
 */
export function seatsAfterInvite(seats: TenantLicenseSeats): TenantLicenseSeats {
  const used = seats.used + 1;
  if (seats.max < 0) return { used, max: seats.max };
  return { used: Math.min(used, seats.max), max: seats.max };
}

// ---------------------------------------------------------------------------------------
// The four decisions
// ---------------------------------------------------------------------------------------

/** The message an empty invite field produces — the screen's own wording, kept verbatim. */
export const INVITE_EMPTY_EMAIL_MESSAGE = 'Please enter an email address';

/**
 * Validate the invite dialog.
 *
 * Deliberately thin, for the reason {@link ../tenants/TenantMemberDialogs.AddMemberDialog}
 * gives: an empty field is refused here, and everything else — unknown address, already a
 * member, seats exhausted — is the API's answer, shown verbatim. A dialog that guesses at
 * those rules drifts from the server that enforces them.
 *
 * @param email The address as typed.
 * @returns The problem to show, or `null` when the draft is submittable.
 */
export function validateInvite(email: string): string | null {
  return email.trim() ? null : INVITE_EMPTY_EMAIL_MESSAGE;
}

/** What an offboard would cost the tenant, beyond the person themselves. */
export interface OffboardConsequence {
  /** They administer the tenant, so the elevated warning is owed. */
  isAdmin: boolean;
  /** How many administrators the tenant would have left. */
  adminsRemaining: number;
  /** They are an invitation rather than a member, so the copy is "Cancel invite". */
  isInvite: boolean;
}

/**
 * What offboarding this person would leave behind.
 *
 * The administrator count is the reason this is computed rather than read off the row: the
 * mockup's elevated variant says *"Removing them leaves 1 administrator (you)"*, and a
 * warning that cannot count is a warning that cannot be trusted. Counted over the whole
 * member list so the number is the tenant's, not the current filter's.
 *
 * @param member The person being offboarded.
 * @param members Every member of the tenant.
 * @returns Whether the elevated warning is owed, and what it should say.
 */
export function describeOffboard(
  member: MemberRecord,
  members: readonly MemberRecord[]
): OffboardConsequence {
  const admins = members.filter((entry) => entry.is_admin).length;
  return {
    isAdmin: member.is_admin,
    adminsRemaining: Math.max(0, admins - (member.is_admin ? 1 : 0)),
    isInvite: isPendingInvite(member),
  };
}

/**
 * The sentence under the elevated offboard warning.
 *
 * @param consequence What the offboard would cost, from {@link describeOffboard}.
 * @returns The count sentence, phrased for none / one / several.
 */
export function describeAdminsRemaining(consequence: OffboardConsequence): string {
  const { adminsRemaining } = consequence;
  if (adminsRemaining === 0) {
    return 'Removing them leaves this tenant with no administrator. Promote someone else first.';
  }
  const noun = adminsRemaining === 1 ? 'administrator' : 'administrators';
  return `Removing them leaves ${adminsRemaining} ${noun}. Consider transferring their work first.`;
}

/**
 * The lifecycle status a suspend/reinstate action would move a member to.
 *
 * @param member The member.
 * @returns `'active'` for a suspended member, `'suspended'` for anyone else.
 */
export function nextMemberStatus(member: Pick<MemberRecord, 'status'>): MemberStatus {
  return member.status === 'suspended' ? 'active' : 'suspended';
}

// ---------------------------------------------------------------------------------------
// Permissions, from the role
// ---------------------------------------------------------------------------------------

/** How many permission tags the drawer prints before it elides the rest. */
export const PERMISSION_PREVIEW_LIMIT = 12;

/** The `resource:action` tags a member holds, and how many were not printed. */
export interface PermissionPreview {
  /** The tags to draw, at most {@link PERMISSION_PREVIEW_LIMIT} of them. */
  shown: string[];
  /** How many more the role grants beyond those. */
  more: number;
  /** Everything the role grants, for the count sentence. */
  total: number;
}

/**
 * The permissions a member effectively holds, read off the role they are assigned.
 *
 * The tags are real rather than illustrative: `GET /api/access/roles` returns each role's
 * permission grid, so the drawer can name what the role actually grants instead of restating
 * the mockup's fixture. An administrator is reported as holding everything, which mirrors
 * what apiome-rest's `permissions/me` says about one — the tenant-admin plane is checked
 * before any grant is consulted.
 *
 * @param member The member.
 * @param roles Every role in the tenant.
 * @returns Sorted `resource:action` strings, split into a preview and a remainder.
 */
export function memberPermissionPreview(
  member: MemberRecord,
  roles: readonly RoleRecord[]
): PermissionPreview {
  const role = roles.find((entry) => entry.id === member.role_id);
  const labels = (role?.permissions ?? [])
    .map((cell) => `${cell.resource}:${cell.action}`)
    .sort((a, b) => a.localeCompare(b));
  return {
    shown: labels.slice(0, PERMISSION_PREVIEW_LIMIT),
    more: Math.max(0, labels.length - PERMISSION_PREVIEW_LIMIT),
    total: labels.length,
  };
}

// ---------------------------------------------------------------------------------------
// Recent activity, from the access ledger
// ---------------------------------------------------------------------------------------

/** How many ledger rows the drawer shows before it hands off to the audit page. */
export const ACTIVITY_PREVIEW_LIMIT = 5;

/**
 * The access-ledger rows that concern one member.
 *
 * A row concerns them when they *did* it (`actor_id`) or when it was done *to* them — the
 * ledger's `target` is written as a user id by the lifecycle routes and as an email address
 * by the invite route, so both spellings are matched rather than one being assumed.
 *
 * Deliberately a filter over rows the page already fetched rather than a per-member query:
 * the ledger has no by-subject endpoint, and inventing one here would pre-empt HIVE-5.5,
 * which owns the audit surface.
 *
 * @param rows The tenant's ledger, newest first.
 * @param member The member in question.
 * @param limit How many rows to keep; defaults to {@link ACTIVITY_PREVIEW_LIMIT}.
 * @returns The matching rows, newest first, capped.
 */
export function memberActivity(
  rows: readonly AccessAuditRecord[],
  member: Pick<MemberRecord, 'user_id' | 'email'>,
  limit: number = ACTIVITY_PREVIEW_LIMIT
): AccessAuditRecord[] {
  const email = member.email.trim().toLowerCase();
  return rows
    .filter(
      (row) =>
        row.actor_id === member.user_id ||
        row.target === member.user_id ||
        (row.target ?? '').trim().toLowerCase() === email
    )
    .slice(0, Math.max(0, limit));
}

// ---------------------------------------------------------------------------------------
// Time
// ---------------------------------------------------------------------------------------

/** What every date cell reads when there is no instant to print. */
export const NO_TIMESTAMP = '—';

/** Milliseconds in the units the relative phrasing steps through. */
const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;
const DAY_MS = 24 * HOUR_MS;

/**
 * A timestamp as an absolute date — "Jan 12, 2025".
 *
 * The zone is a parameter with no default so that a test can pin it; left unset the
 * platform's own zone applies, which is what a reader expects of a date about their own
 * workspace.
 *
 * @param iso An ISO timestamp, or a nullish value.
 * @param timeZone An IANA zone to format in; omit for the viewer's own.
 * @returns The formatted date, or {@link NO_TIMESTAMP} when there is no instant.
 */
export function formatMemberDate(
  iso: string | null | undefined,
  timeZone?: string
): string {
  const ms = timeValue(iso);
  if (ms === null) return NO_TIMESTAMP;
  return new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    timeZone,
  }).format(new Date(ms));
}

/**
 * A timestamp as a relative phrase — "2 minutes ago", "Yesterday", "Jan 12, 2025".
 *
 * The vocabulary is the mockup's, which is why this is not
 * {@link ../../../ade/dashboard/versions/version-history-dag.formatRelativeTime}: that one
 * abbreviates ("2m ago", "3h ago") for a dense revision graph, and a members table that says
 * "2m ago" beside a full date reads as two different clocks. Anything older than a week
 * becomes the absolute date, because "37 days ago" is arithmetic the reader has to undo.
 *
 * @param iso An ISO timestamp, or a nullish value.
 * @param now The instant to measure from; defaults to the current time.
 * @param timeZone An IANA zone for the absolute fallback; omit for the viewer's own.
 * @returns The phrase, or {@link NO_TIMESTAMP} when there is no instant.
 */
export function formatMemberRelative(
  iso: string | null | undefined,
  now: number = Date.now(),
  timeZone?: string
): string {
  const ms = timeValue(iso);
  if (ms === null) return NO_TIMESTAMP;
  const diff = now - ms;
  // A clock skew between the browser and the server can put a timestamp slightly in the
  // future; "in 3 seconds" would be a distraction about the wrong thing.
  if (diff < MINUTE_MS) return 'Just now';
  if (diff < HOUR_MS) {
    const minutes = Math.floor(diff / MINUTE_MS);
    return `${minutes} ${minutes === 1 ? 'minute' : 'minutes'} ago`;
  }
  if (diff < DAY_MS) {
    const hours = Math.floor(diff / HOUR_MS);
    return `${hours} ${hours === 1 ? 'hour' : 'hours'} ago`;
  }
  const days = Math.floor(diff / DAY_MS);
  if (days === 1) return 'Yesterday';
  if (days < 7) return `${days} days ago`;
  return formatMemberDate(iso, timeZone);
}

// ---------------------------------------------------------------------------------------
// The facts line and the "Coming next" line (HIVE-11.9, #5605)
// ---------------------------------------------------------------------------------------

/**
 * The page's one-line summary: members, then each lifecycle state, then seats.
 *
 * Replaces the seat-meter card. The seat fact is `formatSeatUsage` split into value and label
 * (`4 of 5` · `seats used`), so its numbers are the ones the meter printed. The plan name, which
 * the card carried as a badge, follows as a muted aside.
 *
 * @param summary Counts from {@link summariseMembers}.
 * @param seats Seat usage, or `null` when the licence could not be read (the seat fact is left out).
 * @param plan The tenant's plan, for the aside; omitted when unknown.
 * @returns The facts, in reading order.
 */
export function memberFacts(
  summary: MemberSummary,
  seats: TenantLicenseSeats | null | undefined,
  plan?: TenantLicensePlan | null
): FactsLineFact[] {
  const facts: FactsLineFact[] = [
    { id: 'members', value: summary.total, label: summary.total === 1 ? 'member' : 'members' },
    { id: 'active', value: summary.active, label: 'active' },
    { id: 'pending', value: summary.pending, label: 'pending' },
    { id: 'suspended', value: summary.suspended, label: 'suspended' },
  ];
  if (seats) {
    const noun = seats.used === 1 ? 'seat used' : 'seats used';
    const unlimited = seatsUnlimited(seats);
    facts.push({ id: 'seats', value: unlimited ? seats.used : `${seats.used} of ${seats.max}`, label: noun });
    if (unlimited) facts.push({ id: 'seats-unlimited', label: 'unlimited seats', muted: true });
  }
  if (plan?.name) facts.push({ id: 'plan', label: `${plan.name} plan`, muted: true });
  return facts;
}

/**
 * The thin seat bar under the facts line — drawn only once seats run short.
 *
 * @param seats Seat usage, or `null` when the licence could not be read.
 * @returns The bar's share and tone at or above the 80 % warn line on a limited plan, else `null`.
 */
export function memberSeatProgress(
  seats: TenantLicenseSeats | null | undefined
): { percent: number; tone: MetricTone } | null {
  if (!seats || seatsUnlimited(seats)) return null;
  const { percent, tone } = seatMeterAppearance(seats.used, seats.max);
  return percent >= METER_WARN_PERCENT ? { percent, tone } : null;
}

/** What the Members page announces as not shipped yet, in place of the old SSO/SCIM cards. */
export const MEMBERS_COMING_NEXT: readonly ComingNextItem[] = [
  { id: 'sso', label: 'SSO (OIDC/SAML)' },
  { id: 'scim', label: 'SCIM 2.0 provisioning' },
];
