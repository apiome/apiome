const connectionPool = require('./db');

/**
 * Resolve whether a user/tenant is entitled to a named feature flag.
 * Precedence matches apiome-rest `tenant_has_feature_flag` (#3478):
 * user override → tenant override → license bundle → denied.
 */
export async function userHasFeatureFlag(
  userId: string,
  tenantId: string | null | undefined,
  flagName: string
): Promise<boolean> {
  const result = await connectionPool.query(
    `
    WITH ff AS (
      SELECT id, enabled FROM apiome.feature_flags WHERE name = $1
    )
    SELECT
      ff.enabled                          AS flag_enabled,
      uff.enabled                         AS user_override,
      tff.enabled                         AS tenant_override,
      (lff.feature_flag_id IS NOT NULL)   AS license_grant
    FROM ff
    LEFT JOIN apiome.user_feature_flags uff
           ON uff.feature_flag_id = ff.id AND uff.user_id = $2::uuid
    LEFT JOIN apiome.tenant_feature_flags tff
           ON tff.feature_flag_id = ff.id AND tff.tenant_id = $3::uuid
    LEFT JOIN apiome.user_entitlements ue
           ON ue.user_id = $2::uuid
    LEFT JOIN apiome.license_feature_flags lff
           ON lff.feature_flag_id = ff.id AND lff.license_id = ue.license_id
    LIMIT 1
    `,
    [flagName, userId, tenantId ?? null]
  );

  if (result.rowCount === 0) {
    return false;
  }

  return isEntitled(result.rows[0] as FlagRecord);
}

/**
 * Whether an administrator gave the user Suite Access (`users.suite_access`, V320), which shows the
 * Designer and Developer suites. A missing or deleted user has none.
 *
 * @param userId The user's id.
 * @returns True only when the switch is on for a live account.
 */
export async function userHasSuiteAccess(userId: string): Promise<boolean> {
  const result = await connectionPool.query(
    'SELECT suite_access FROM apiome.users WHERE id = $1 AND deleted_at IS NULL',
    [userId]
  );
  return Boolean(result.rows[0]?.suite_access);
}

/**
 * Feature flags the user may access (for commercial product gating).
 *
 * One statement for every candidate (DBP-1.6, #7189): each flag is resolved by the same lookup
 * {@link userHasFeatureFlag} runs, as a `LATERAL` subquery, so the precedence (user override →
 * tenant override → license bundle → denied) and the answer per flag are unchanged.
 *
 * @param userId The user's id.
 * @param tenantId The workspace, if any.
 * @param candidateNames The flags to check; defaults to every enabled flag.
 * @returns The entitled flag names, in candidate order (by name for the default list).
 */
export async function getEntitledFeatureFlagNames(
  userId: string,
  tenantId?: string | null,
  candidateNames?: string[]
): Promise<string[]> {
  const result = await connectionPool.query(
    `
    WITH candidates AS (
      SELECT name, ord
      FROM unnest(
        COALESCE($1::text[], ARRAY(SELECT name FROM apiome.feature_flags WHERE enabled = true ORDER BY name))
      ) WITH ORDINALITY AS c(name, ord)
    )
    SELECT candidates.name, r.flag_enabled, r.user_override, r.tenant_override, r.license_grant
    FROM candidates
    LEFT JOIN LATERAL (
      SELECT
        ff.enabled                          AS flag_enabled,
        uff.enabled                         AS user_override,
        tff.enabled                         AS tenant_override,
        (lff.feature_flag_id IS NOT NULL)   AS license_grant
      FROM apiome.feature_flags ff
      LEFT JOIN apiome.user_feature_flags uff
             ON uff.feature_flag_id = ff.id AND uff.user_id = $2::uuid
      LEFT JOIN apiome.tenant_feature_flags tff
             ON tff.feature_flag_id = ff.id AND tff.tenant_id = $3::uuid
      LEFT JOIN apiome.user_entitlements ue
             ON ue.user_id = $2::uuid
      LEFT JOIN apiome.license_feature_flags lff
             ON lff.feature_flag_id = ff.id AND lff.license_id = ue.license_id
      WHERE ff.name = candidates.name
      LIMIT 1
    ) r ON true
    ORDER BY candidates.ord
    `,
    [candidateNames ?? null, userId, tenantId ?? null]
  );
  return (result.rows as FlagRecord[]).filter(isEntitled).map((row) => row.name as string);
}

/** One flag's lookup row: the flag's switch and the three grants, in precedence order. */
type FlagRecord = {
  name?: string;
  flag_enabled: boolean | null;
  user_override: boolean | null;
  tenant_override: boolean | null;
  license_grant: boolean | null;
};

/**
 * Whether a lookup row grants the flag: user override → tenant override → license bundle → denied.
 *
 * @param record The row; a missing or disabled flag is denied.
 * @returns True when the user may use the flag.
 */
function isEntitled(record: FlagRecord): boolean {
  if (!record.flag_enabled) {
    return false;
  }
  if (record.user_override !== null && record.user_override !== undefined) {
    return Boolean(record.user_override);
  }
  if (record.tenant_override !== null && record.tenant_override !== undefined) {
    return Boolean(record.tenant_override);
  }
  return Boolean(record.license_grant);
}
