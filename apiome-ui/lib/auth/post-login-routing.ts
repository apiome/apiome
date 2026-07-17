/**
 * Post-login routing rules (OLO-3.3, #4201).
 *
 * Single contract for "where does an authenticated user land":
 *
 * - **Zero tenant memberships** → the first-tenant onboarding wizard (OLO-EPIC-4).
 *   The wizard is *prompted* via a route guard on the protected shell
 *   ({@link decidePostLoginRoute} returns `kind: 'onboarding'`), not navigated to —
 *   any requested `callbackUrl` is deliberately ignored so the user cannot deep-link
 *   past the prompt.
 * - **One or more memberships** → the last-active tenant when it is still a valid
 *   membership, otherwise the user's default tenant (first membership, sorted by
 *   tenant name — the same ordering the tenant switcher shows). The landing page is
 *   the requested `callbackUrl` when it passes the allowlist
 *   (`resolveCallbackUrl`, OLO-3.4), otherwise {@link DEFAULT_LOGIN_LANDING}.
 *
 * `decidePostLoginRoute` / `pickActiveTenantId` are pure so the contract is testable
 * without a database; the `…ForUser` variants wire them to the membership store.
 */
import { DEFAULT_LOGIN_LANDING, resolveCallbackUrl } from './cookie-options';

/** How the post-login destination should be treated by the caller. */
export type PostLoginRouteKind = 'onboarding' | 'dashboard';

/** Result of the post-login routing decision. */
export interface PostLoginRoute {
  /** `'onboarding'` when the first-tenant wizard must be prompted, else `'dashboard'`. */
  kind: PostLoginRouteKind;
  /** Path or allowlisted absolute URL the user should land on. */
  destination: string;
  /** Tenant that should be active after landing; `null` when the user has none. */
  activeTenantId: string | null;
}

/** Inputs to the pure routing decision. */
export interface PostLoginRouteInput {
  /** Tenant ids the user is a member of, default tenant first. */
  membershipTenantIds: readonly string[];
  /** Tenant that was active in the user's previous session, if any. */
  lastActiveTenantId?: string | null;
  /** Raw `callbackUrl` requested by the login flow, if any. */
  callbackUrl?: string | null;
}

/**
 * Pick the tenant that becomes active after login.
 *
 * @param membershipTenantIds Tenant ids the user belongs to, default tenant first.
 * @param lastActiveTenantId Tenant active in the previous session, if known.
 * @returns The last-active tenant when still a membership, else the first
 *   membership, else `null` for tenant-less users.
 */
export function pickActiveTenantId(
  membershipTenantIds: readonly string[],
  lastActiveTenantId?: string | null
): string | null {
  if (lastActiveTenantId && membershipTenantIds.includes(lastActiveTenantId)) {
    return lastActiveTenantId;
  }
  return membershipTenantIds[0] ?? null;
}

/**
 * Apply the post-login routing rules (see module doc for the contract).
 *
 * @param input Memberships, previous active tenant, and requested callback URL.
 * @returns The landing destination, its kind, and the tenant to activate.
 */
export function decidePostLoginRoute(input: PostLoginRouteInput): PostLoginRoute {
  const { membershipTenantIds, lastActiveTenantId, callbackUrl } = input;

  if (membershipTenantIds.length === 0) {
    // Zero-tenant users always meet the onboarding guard at the default landing;
    // honoring callbackUrl here would let a deep link route around the wizard.
    return { kind: 'onboarding', destination: DEFAULT_LOGIN_LANDING, activeTenantId: null };
  }

  return {
    kind: 'dashboard',
    destination: resolveCallbackUrl(callbackUrl),
    activeTenantId: pickActiveTenantId(membershipTenantIds, lastActiveTenantId),
  };
}

/**
 * Load the user's tenant memberships, default tenant first (sorted by tenant
 * name, matching the tenant switcher).
 *
 * The db helper is imported lazily so the pure rules above stay importable
 * without a database module in scope (e.g. in unit tests).
 *
 * @param userId The `apiome.users.id` of the authenticated user.
 * @returns Ordered tenant ids; empty when the user belongs to no tenant.
 */
export async function getMembershipTenantIdsForUser(userId: string): Promise<string[]> {
  const helper = await import('../db/helper');
  const rows: Array<{ id: string; name?: string | null }> = JSON.parse(
    await helper.getTenantsForUser(userId)
  );
  rows.sort((a, b) => (a.name ?? '').localeCompare(b.name ?? ''));
  return rows.map((row) => row.id);
}

/**
 * Resolve the tenant to activate for a fresh sign-in (used by the NextAuth JWT
 * callback to seed `current_tenant_id`).
 *
 * Fails open: a membership-store error yields the unvalidated candidate rather
 * than blocking the login.
 *
 * @param userId The authenticated user's id.
 * @param candidateTenantId Preferred tenant (e.g. `pending_tenant_id` from the
 *   signup one-time code, or a previous session's tenant), if any.
 * @returns The validated active tenant id, or `null` for tenant-less users.
 */
export async function resolveActiveTenantForLogin(
  userId: string,
  candidateTenantId?: string | null
): Promise<string | null> {
  try {
    const memberships = await getMembershipTenantIdsForUser(userId);
    return pickActiveTenantId(memberships, candidateTenantId);
  } catch (error) {
    console.error('[post-login-routing] membership lookup failed; using candidate tenant:', error);
    return candidateTenantId ?? null;
  }
}

/**
 * Full post-login routing decision for a user (memberships loaded from the db).
 *
 * Fails open to a member-style route on membership-store errors so a database
 * blip cannot trap every user in the onboarding prompt.
 *
 * @param userId The authenticated user's id.
 * @param options Previous active tenant and requested callback URL.
 * @returns The routing decision for this user.
 */
export async function resolvePostLoginRouteForUser(
  userId: string,
  options: { lastActiveTenantId?: string | null; callbackUrl?: string | null } = {}
): Promise<PostLoginRoute> {
  let membershipTenantIds: readonly string[];
  try {
    membershipTenantIds = await getMembershipTenantIdsForUser(userId);
  } catch (error) {
    console.error('[post-login-routing] membership lookup failed; routing to dashboard:', error);
    return {
      kind: 'dashboard',
      destination: resolveCallbackUrl(options.callbackUrl),
      activeTenantId: options.lastActiveTenantId ?? null,
    };
  }
  return decidePostLoginRoute({ ...options, membershipTenantIds });
}
