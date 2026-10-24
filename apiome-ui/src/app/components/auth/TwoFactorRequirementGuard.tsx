import type { ReactNode } from 'react';
import { getAuthSession } from '@lib/auth/server-session';
import { readTwoFactorRequirement } from '@lib/auth/two-factor-requirement';
import { NO_TWO_FACTOR_REQUIREMENT, type TwoFactorRequirement } from '@lib/two-factor-policy';
import { TwoFactorRequiredScreen } from './TwoFactorRequiredScreen';

/**
 * Route guard for workspaces that require two-factor (TFA-1.3, #5657).
 *
 * When a workspace the user is an active member of requires two-factor, they have not turned it
 * on, and their grace period there has ended, the guard renders {@link TwoFactorRequiredScreen}
 * *in place* of any `/ade` route — like `FirstTenantOnboardingGuard`, it swaps the content rather
 * than redirecting, so no deep link can route around it. Two-factor is per account, so the
 * earliest deadline across workspaces decides, and enrolling once satisfies them all.
 *
 * Renders `children` unchanged when there is no session, nothing is owed, the grace period is
 * still running (the grace notice in the layout reminds them), or the lookup fails (fail open —
 * a database blip must not lock everyone out; the next sign-in checks again).
 *
 * @param children The protected route content.
 * @returns The route, or the blocking enrolment screen.
 */
export default async function TwoFactorRequirementGuard({ children }: { children: ReactNode }) {
  const session = await getAuthSession();
  const user = session?.user as { user_id?: string; email?: string | null } | undefined;
  if (!user?.user_id) return <>{children}</>;

  let requirement: TwoFactorRequirement = NO_TWO_FACTOR_REQUIREMENT;
  try {
    requirement = await readTwoFactorRequirement(user.user_id);
  } catch (error) {
    console.error('[TwoFactorRequirementGuard] requirement lookup failed; rendering route:', error);
  }
  if (requirement.overdue) {
    return <TwoFactorRequiredScreen tenants={requirement.tenants} email={user.email ?? null} />;
  }
  return <>{children}</>;
}
