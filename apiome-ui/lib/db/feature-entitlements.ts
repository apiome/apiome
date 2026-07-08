'use server';

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

  const record = result.rows[0];
  if (!record.flag_enabled) {
    return false;
  }
  if (record.user_override !== null) {
    return Boolean(record.user_override);
  }
  if (record.tenant_override !== null) {
    return Boolean(record.tenant_override);
  }
  return Boolean(record.license_grant);
}

/** Feature flags the user may access (for commercial product gating). */
export async function getEntitledFeatureFlagNames(
  userId: string,
  tenantId?: string | null,
  candidateNames?: string[]
): Promise<string[]> {
  const names =
    candidateNames ??
    (await connectionPool.query(
      `SELECT name FROM apiome.feature_flags WHERE enabled = true ORDER BY name`
    )).rows.map((row: { name: string }) => row.name);

  const entitled: string[] = [];
  for (const name of names) {
    if (await userHasFeatureFlag(userId, tenantId ?? null, name)) {
      entitled.push(name);
    }
  }
  return entitled;
}
