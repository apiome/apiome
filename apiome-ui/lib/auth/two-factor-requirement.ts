/**
 * Read what a user owes under their workspaces' two-factor policies (TFA-1.3, #5657).
 *
 * Server-only, and **not** a `'use server'` module: it takes a user id, so callers must have read
 * it from the signed session first (`FirstTenantOnboardingGuard`'s pattern).
 */

import { getTwoFactorRequirementRows } from '../db/two-factor-requirement';
import { summarizeTwoFactorRequirement, type TwoFactorRequirement } from '../two-factor-policy';

/**
 * The user's requirement, earliest deadline first.
 *
 * @param userId - The signed-in user's id.
 * @param now - The current time (injectable for tests).
 * @returns The requirement; throws when the database cannot be read (callers fail open).
 */
export async function readTwoFactorRequirement(
  userId: string,
  now: Date = new Date()
): Promise<TwoFactorRequirement> {
  return summarizeTwoFactorRequirement(await getTwoFactorRequirementRows(userId), now);
}
