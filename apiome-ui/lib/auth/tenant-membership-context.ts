'use server';

/**
 * Server action loading the tenant-switcher membership context (OLO-6.1, #4218).
 *
 * Calls the OLO-6.2 (#4219) enriched `GET /v1/tenants/me` — one round-trip per
 * page returning role + status + license per membership — and pairs it with the
 * OLO-5.3 tenant-cap gate so the header's "Create tenant" entry knows whether
 * another tenant is allowed before the user clicks.
 *
 * Misuse safeguards:
 * - The acting user always comes from the server session; the client passes
 *   nothing and can spoof nothing.
 * - REST failures fall back to the legacy direct-DB tenant listing (name-only
 *   rows) so the switcher degrades to its pre-OLO-6.1 rendering instead of
 *   disappearing.
 */

// Imported via the alias so the jest `auth/server-session` mock mapping applies.
import { getAuthSession } from '@lib/auth/server-session';
import { REST_API_BASE_URL, createRestAuthHeaders } from '../rest-auth';
import { getMaxTenantsForUser } from '../db/plan-entitlements';
import {
  DEFAULT_FREE_MAX_TENANTS,
  mapRestMembershipToRow,
  resolveCreateTenantGate,
  type CreateTenantGate,
  type RestTenantMembership,
  type TenantMembershipRow,
} from './tenant-membership-context-mapping';

/** Page size for `GET /v1/tenants/me` (its documented maximum). */
const MEMBERSHIPS_PAGE_LIMIT = 100;
/** Hard stop on pagination so a pathological `total` cannot loop forever. */
const MEMBERSHIPS_MAX_PAGES = 10;

/** Serializable membership context for the tenant switcher. */
export interface TenantMembershipContextPayload {
  /** Membership rows, enriched when the REST call succeeded. */
  tenants: TenantMembershipRow[];
  /** Tenants the user administers (legacy admin-badge fallback contract). */
  adminTenantIds: string[];
  /** Create-tenant gate; null when neither REST nor the DB could resolve it. */
  createTenant: CreateTenantGate | null;
}

/**
 * Fetch every membership page from the enriched `GET /v1/tenants/me`.
 *
 * @param headers Signed REST auth headers for the acting user.
 * @returns All membership items, in the endpoint's slug ordering.
 * @throws When any page request fails or returns a non-OK status.
 */
async function fetchAllMemberships(
  headers: Record<string, string>
): Promise<RestTenantMembership[]> {
  const items: RestTenantMembership[] = [];
  for (let page = 0; page < MEMBERSHIPS_MAX_PAGES; page += 1) {
    const offset = page * MEMBERSHIPS_PAGE_LIMIT;
    const response = await fetch(
      `${REST_API_BASE_URL}/tenants/me?limit=${MEMBERSHIPS_PAGE_LIMIT}&offset=${offset}`,
      { headers, cache: 'no-store' }
    );
    if (!response.ok) {
      throw new Error(`GET /v1/tenants/me failed with status ${response.status}`);
    }
    const body = (await response.json()) as { items?: RestTenantMembership[]; total?: number };
    items.push(...(body.items ?? []));
    const total = typeof body.total === 'number' ? body.total : items.length;
    if (items.length >= total || (body.items ?? []).length === 0) {
      break;
    }
  }
  return items;
}

/**
 * Legacy fallback listing straight from the database (pre-OLO-6.1 behavior):
 * name-only rows plus the administrator id set, no role/license enrichment.
 *
 * @param userId The acting user's id.
 * @returns Name-sorted rows and the admin tenant-id list.
 */
async function loadLegacyTenantRows(
  userId: string
): Promise<{ tenants: TenantMembershipRow[]; adminTenantIds: string[] }> {
  const helper = await import('../db/helper');
  const [tenantsJson, adminsJson] = await Promise.all([
    helper.getTenantsForUser(userId),
    helper.getTenantsAdministratedByUser(userId),
  ]);
  const tenants: TenantMembershipRow[] = (
    JSON.parse(tenantsJson) as Array<{ id: string; name: string }>
  ).map((row) => ({ id: row.id, name: row.name }));
  tenants.sort((a, b) => a.name.localeCompare(b.name));
  const adminTenantIds = (JSON.parse(adminsJson) as Array<{ tenant_id: string; user_id: string }>)
    .filter((row) => row.user_id === userId)
    .map((row) => row.tenant_id);
  return { tenants, adminTenantIds };
}

/**
 * Resolve the create-tenant gate for a user with `used` memberships.
 *
 * Fails soft: an entitlement lookup error yields the Free default so the gate
 * still renders (the REST transaction remains the real enforcer).
 *
 * @param userId The acting user's id.
 * @param used Tenants the user already belongs to.
 * @returns The gate, never null.
 */
async function resolveGateForUser(userId: string, used: number): Promise<CreateTenantGate> {
  let max = DEFAULT_FREE_MAX_TENANTS;
  try {
    max = await getMaxTenantsForUser(userId);
  } catch (error) {
    console.error('[tenant-membership-context] max_tenants lookup failed; using Free default:', error);
  }
  return resolveCreateTenantGate(used, max);
}

/**
 * Load the authenticated user's switcher context: enriched membership rows,
 * the admin-badge id list, and the create-tenant gate.
 *
 * @returns The membership context; empty rows when there is no session.
 */
export async function loadTenantMembershipContext(): Promise<TenantMembershipContextPayload> {
  const session = await getAuthSession();
  const user = session?.user as
    | { user_id?: string; email?: string | null; name?: string | null; current_tenant_id?: string }
    | undefined;
  if (!user?.user_id) {
    return { tenants: [], adminTenantIds: [], createTenant: null };
  }

  try {
    const items = await fetchAllMemberships(createRestAuthHeaders(user));
    const tenants = items.map(mapRestMembershipToRow);
    // The legacy admin badge maps to Owner-equivalence (a tenant_administrators
    // row reads as role 'owner' in the enriched listing).
    const adminTenantIds = tenants
      .filter((tenant) => tenant.role === 'owner')
      .map((tenant) => tenant.id);
    return {
      tenants,
      adminTenantIds,
      createTenant: await resolveGateForUser(user.user_id, tenants.length),
    };
  } catch (error) {
    console.error(
      '[tenant-membership-context] enriched membership fetch failed; falling back to DB listing:',
      error
    );
  }

  try {
    const { tenants, adminTenantIds } = await loadLegacyTenantRows(user.user_id);
    return {
      tenants,
      adminTenantIds,
      createTenant: await resolveGateForUser(user.user_id, tenants.length),
    };
  } catch (error) {
    console.error('[tenant-membership-context] fallback DB listing failed:', error);
    return { tenants: [], adminTenantIds: [], createTenant: null };
  }
}
