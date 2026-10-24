'use server';

/**
 * The signed-in user's two-factor requirement (TFA-1.3, #5657), for the client-side grace notice.
 *
 * Session-bound: it answers for the caller's own account only, and fails open (nothing owed) on
 * any error — the blocking screen is the server guard's job, not this read's.
 */

import { NO_TWO_FACTOR_REQUIREMENT, type TwoFactorRequirement } from '../two-factor-policy';

/**
 * What the signed-in user owes.
 *
 * @returns The requirement; nothing owed when signed out, enrolled, or the read fails.
 */
export async function getMyTwoFactorRequirement(): Promise<TwoFactorRequirement> {
  try {
    const { getAuthSession } = await import('./server-session');
    const session = await getAuthSession();
    const userId = (session?.user as { user_id?: string } | undefined)?.user_id;
    if (!userId) return NO_TWO_FACTOR_REQUIREMENT;
    const { readTwoFactorRequirement } = await import('./two-factor-requirement');
    return await readTwoFactorRequirement(userId);
  } catch (error) {
    console.warn(
      '[auth] two-factor requirement read failed:',
      error instanceof Error ? error.name : 'unknown'
    );
    return NO_TWO_FACTOR_REQUIREMENT;
  }
}
