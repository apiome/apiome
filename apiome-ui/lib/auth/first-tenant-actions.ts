'use server';

import {
  createTenant,
  addUserToTenant,
  addTenantAdministrator,
  deleteTenant,
  provisionSampleProject,
} from '../db/admin-helper';
import { insertFreeTierEntitlements } from '../db/oauth-signup';
// Imported via the alias so the jest `auth/server-session` mock mapping
// applies (a relative `./server-session` would pull real next-auth into tests).
import { getAuthSession } from '@lib/auth/server-session';
import { getMembershipTenantIdsForUser } from './post-login-routing';
import { generateTenantSlug, validateTenantSlug } from './tenant-slug';

/** Outcome of {@link provisionFirstTenant}. */
export type ProvisionFirstTenantResult =
  | {
      success: true;
      /** The newly created tenant, ready to be activated in the session. */
      tenant: { id: string; name: string; slug: string };
    }
  | { success: false; error: string };

/**
 * Create the authenticated user's first tenant from the onboarding wizard
 * (OLO-4.1, #4205): tenant row, membership, administrator role, free-tier
 * entitlements, and the curated sample project.
 *
 * This reuses the provisioning helpers behind `completeOAuthSignup()` — the
 * codebase's single provisioning path until the atomic REST endpoint
 * `POST /v1/onboarding/first-tenant` (OLO-4.3, #4207) replaces both callers.
 * Unlike OAuth signup the user already exists, so failure compensation only
 * ever removes the just-created tenant, never the user.
 *
 * Misuse safeguards:
 * - The user id comes from the server session, never from the client.
 * - Users who already belong to a tenant are refused (the wizard is only
 *   prompted at zero memberships; a second tab or stale prompt cannot create
 *   extra tenants).
 * - Name/slug are re-validated server-side; slug uniqueness is enforced by
 *   `createTenant`.
 *
 * @param orgNameInput Organization display name entered in the wizard.
 * @param slugInput Optional slug; when blank one is derived from the name.
 * @returns The created tenant, or a human-readable error.
 */
export async function provisionFirstTenant(
  orgNameInput: string,
  slugInput: string
): Promise<ProvisionFirstTenantResult> {
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return { success: false, error: 'Your session has expired. Please sign in again.' };
  }

  const orgName = orgNameInput?.trim();
  if (!orgName) {
    return { success: false, error: 'Organization name is required' };
  }

  const slug = slugInput?.trim()
    ? slugInput.trim().toLowerCase()
    : generateTenantSlug(orgName);
  const slugError = validateTenantSlug(slug);
  if (slugError) {
    return { success: false, error: slugError };
  }

  // Refuse when the user already has a tenant. Fail open on lookup errors:
  // the guard is advisory and createTenant still enforces slug uniqueness.
  try {
    const memberships = await getMembershipTenantIdsForUser(userId);
    if (memberships.length > 0) {
      return {
        success: false,
        error: 'Your account already belongs to a tenant. Use "Check again" to continue to your dashboard.',
      };
    }
  } catch (error) {
    console.error('[provisionFirstTenant] membership pre-check failed; continuing:', error);
  }

  const tenantParsed = JSON.parse(await createTenant(orgName, '', slug, true));
  if (!tenantParsed.success || !tenantParsed.tenant?.id) {
    return { success: false, error: tenantParsed.error || 'Could not create organization' };
  }
  const tenantId: string = tenantParsed.tenant.id;

  const memberParsed = JSON.parse(await addUserToTenant(tenantId, userId));
  if (!memberParsed.success) {
    await deleteTenant(tenantId);
    return { success: false, error: memberParsed.error || 'Could not add you to the organization' };
  }

  const adminParsed = JSON.parse(await addTenantAdministrator(tenantId, userId));
  if (!adminParsed.success) {
    await deleteTenant(tenantId);
    return { success: false, error: adminParsed.error || 'Could not grant organization access' };
  }

  // Best-effort from here: the tenant and membership are committed and usable.
  // Entitlements are idempotent (ON CONFLICT DO NOTHING) and the sample
  // project reports failure via its JSON result — neither should undo a
  // working tenant.
  try {
    await insertFreeTierEntitlements(userId);
  } catch (error) {
    console.error('[provisionFirstTenant] free-tier entitlement seed failed:', error);
  }
  await provisionSampleProject(tenantId, userId);

  return { success: true, tenant: { id: tenantId, name: orgName, slug } };
}
