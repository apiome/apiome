const connectionPool = require('./db');

/**
 * Batch: for each version id, return whether it has class_schema rows (tenant-scoped).
 */
export async function getVersionHasClassSchemaMap(
  versionIds: string[],
  tenantId: string
): Promise<Record<string, boolean>> {
  if (versionIds.length === 0) return {};
  const result = await connectionPool.query(
    `SELECT cs.version_id
     FROM apiome.class_schema cs
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE cs.version_id = ANY($1::uuid[])`,
    [versionIds, tenantId]
  );
  const withSchema = new Set(result.rows.map((r: { version_id: string }) => r.version_id));
  const map: Record<string, boolean> = {};
  for (const id of versionIds) {
    map[id] = withSchema.has(id);
  }
  return map;
}
