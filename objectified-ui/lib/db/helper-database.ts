'use server';

const connectionPool = require('./db');

export interface ClassSchemaTable {
  class_schema_id: string;
  class_id: string;
  class_name: string;
  schema: Record<string, unknown>;
}

/**
 * Get class_schema rows for a version (tables), with class names.
 * Only returns rows for versions whose project belongs to the tenant.
 */
export async function getClassSchemasForVersion(
  versionId: string,
  tenantId: string
): Promise<ClassSchemaTable[]> {
  const result = await connectionPool.query(
    `SELECT cs.id AS class_schema_id, cs.class_id, c.name AS class_name, cs.schema
     FROM odb.class_schema cs
     JOIN odb.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE cs.version_id = $1`,
    [versionId, tenantId]
  );
  return result.rows.map((row: { class_schema_id: string; class_id: string; class_name: string; schema: unknown }) => ({
    class_schema_id: row.class_schema_id,
    class_id: row.class_id,
    class_name: row.class_name,
    schema: typeof row.schema === 'object' && row.schema !== null ? (row.schema as Record<string, unknown>) : {},
  }));
}

/**
 * Ensure class_schema_id belongs to a version in a project under the tenant.
 */
export async function assertClassSchemaTenantAccess(
  classSchemaId: string,
  tenantId: string
): Promise<boolean> {
  const result = await connectionPool.query(
    `SELECT 1 FROM odb.class_schema cs
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE cs.id = $1`,
    [classSchemaId, tenantId]
  );
  return (result.rowCount ?? 0) > 0;
}

/**
 * Count rows in data_snapshot for a class_schema and tenant.
 */
export async function getDataSnapshotCount(
  classSchemaId: string,
  tenantId: string
): Promise<number> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return 0;
  const result = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2`,
    [classSchemaId, tenantId]
  );
  return result.rows[0]?.cnt ?? 0;
}

export interface DataSnapshotRow {
  record_id: string;
  data: Record<string, unknown>;
  updated_at: string;
}

/**
 * Paginated list of data_snapshot rows for a class_schema and tenant.
 */
export async function getDataSnapshotPage(
  classSchemaId: string,
  tenantId: string,
  page: number,
  pageSize: number
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));

  const countResult = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2`,
    [classSchemaId, tenantId]
  );
  const total = countResult.rows[0]?.cnt ?? 0;

  const listResult = await connectionPool.query(
    `SELECT record_id, data, updated_at
     FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2
     ORDER BY updated_at DESC NULLS LAST, record_id
     LIMIT $3 OFFSET $4`,
    [classSchemaId, tenantId, limit, offset]
  );

  const rows: DataSnapshotRow[] = listResult.rows.map((row: { record_id: string; data: unknown; updated_at: string }) => ({
    record_id: row.record_id,
    data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
    updated_at: row.updated_at,
  }));

  return { rows, total };
}

/**
 * Simple text search on data_snapshot.data::text (ILIKE).
 * Minimal implementation for scaffolding.
 */
export async function searchDataSnapshot(
  classSchemaId: string,
  tenantId: string,
  q: string,
  page: number,
  pageSize: number
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));
  const pattern = `%${q.replace(/%/g, '\\%').replace(/_/g, '\\_')}%`;

  const countResult = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2 AND data::text ILIKE $3`,
    [classSchemaId, tenantId, pattern]
  );
  const total = countResult.rows[0]?.cnt ?? 0;

  const listResult = await connectionPool.query(
    `SELECT record_id, data, updated_at
     FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2 AND data::text ILIKE $3
     ORDER BY updated_at DESC NULLS LAST, record_id
     LIMIT $4 OFFSET $5`,
    [classSchemaId, tenantId, pattern, limit, offset]
  );

  const rows: DataSnapshotRow[] = listResult.rows.map((row: { record_id: string; data: unknown; updated_at: string }) => ({
    record_id: row.record_id,
    data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
    updated_at: row.updated_at,
  }));

  return { rows, total };
}
