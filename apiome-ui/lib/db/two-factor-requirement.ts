/**
 * The database read behind two-factor enforcement (TFA-1.3, #5657; columns V316).
 *
 * Deliberately **not** a `'use server'` module: it takes a user id the caller has already read
 * from the signed session, so it must never become a client-callable server action. It is reached
 * through `FirstTenant…`-style server guards and `lib/auth/two-factor-requirement-actions.ts`.
 *
 * The deadline expression is apiome-rest's `DUE_AT_SQL` (`app/two_factor_policy.py`): the later of
 * the requirement being turned on and the member joining, plus the grace days.
 */

import type { TwoFactorRequirementRow } from '../two-factor-policy';

// `lib/db/db` is a CommonJS module (`module.exports = pool`), like every other lib/db consumer.
// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

/** The member's deadline, over `apiome.tenants tn` and `apiome.tenant_users tu`. */
export const TWO_FACTOR_DUE_AT_SQL =
  'GREATEST(tn.two_factor_required_since, tu.created_at) + make_interval(days => tn.two_factor_grace_days)';

/**
 * The workspaces that require two-factor of a user who has not turned it on.
 *
 * Only active memberships of live, enabled workspaces count: a pending invitation or a suspended
 * member is not asked to comply, and a user with two-factor on gets no rows at all.
 *
 * @param userId - The signed-in user's `apiome.users.id`.
 * @returns One row per requiring workspace (unsorted; see `summarizeTwoFactorRequirement`).
 */
export async function getTwoFactorRequirementRows(userId: string): Promise<TwoFactorRequirementRow[]> {
  const result = await connectionPool.query(
    `SELECT tn.name AS tenant_name, ${TWO_FACTOR_DUE_AT_SQL} AS due_at
       FROM apiome.tenant_users tu
       JOIN apiome.tenants tn ON tn.id = tu.tenant_id
       JOIN apiome.users u ON u.id = tu.user_id
      WHERE tu.user_id = $1
        AND tu.status = 'active'
        AND tn.deleted_at IS NULL
        AND tn.enabled
        AND tn.require_two_factor
        AND tn.two_factor_required_since IS NOT NULL
        AND u.deleted_at IS NULL
        AND NOT COALESCE(u."twoFactorEnabled", false)`,
    [userId]
  );
  return (result.rows as Array<{ tenant_name: string; due_at: Date | string }>).map((row) => ({
    tenantName: row.tenant_name,
    dueAt: new Date(row.due_at).toISOString(),
  }));
}
