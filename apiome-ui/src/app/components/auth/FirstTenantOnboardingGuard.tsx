import type { ReactNode } from 'react';
import { getAuthSession } from '@lib/auth/server-session';
import { getMembershipTenantIdsForUser } from '@lib/auth/post-login-routing';
import FirstTenantOnboardingWizard from './onboarding/FirstTenantOnboardingWizard';

/**
 * Route guard implementing the zero-tenant half of the post-login routing rules
 * (OLO-3.3, #4201): an authenticated user with zero tenant memberships is
 * prompted with the first-tenant onboarding wizard (OLO-4.1, #4205) *in place*
 * — the guard swaps the route content for {@link FirstTenantOnboardingWizard}
 * instead of navigating, so no deep link (callbackUrl or typed URL) can route
 * around it.
 *
 * Renders `children` unchanged when:
 * - there is no authenticated session (the client-side `AuthenticatedLayout`
 *   already redirects those visitors to `/login`), or
 * - the user has at least one tenant membership, or
 * - the membership lookup fails (fail open — a database blip must not lock
 *   every member out of the dashboard).
 *
 * @param children The protected route content to render for tenant members.
 */
export default async function FirstTenantOnboardingGuard({
  children,
}: {
  children: ReactNode;
}) {
  const session = await getAuthSession();
  const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
  if (!userId) {
    return <>{children}</>;
  }

  let membershipTenantIds: string[];
  try {
    membershipTenantIds = await getMembershipTenantIdsForUser(userId);
  } catch (error) {
    console.error('[FirstTenantOnboardingGuard] membership lookup failed; rendering route:', error);
    return <>{children}</>;
  }

  if (membershipTenantIds.length === 0) {
    return <FirstTenantOnboardingWizard />;
  }

  return <>{children}</>;
}
