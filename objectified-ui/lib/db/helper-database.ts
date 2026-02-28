'use server';

const connectionPool = require('./db');
const crypto = require('crypto');

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
 * Return true if the version has at least one class_schema row (schema already frozen).
 * Only considers versions whose project belongs to the tenant.
 */
export async function versionHasClassSchema(versionId: string, tenantId: string): Promise<boolean> {
  const result = await connectionPool.query(
    `SELECT 1 FROM odb.class_schema cs
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE cs.version_id = $1
     LIMIT 1`,
    [versionId, tenantId]
  );
  return (result.rowCount ?? 0) > 0;
}

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
     FROM odb.class_schema cs
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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
 * Get a single class_schema row by id. Returns null if not found or tenant has no access.
 */
export async function getClassSchemaById(
  classSchemaId: string,
  tenantId: string
): Promise<ClassSchemaTable | null> {
  const result = await connectionPool.query(
    `SELECT cs.id AS class_schema_id, cs.class_id, c.name AS class_name, cs.schema
     FROM odb.class_schema cs
     JOIN odb.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE cs.id = $1`,
    [classSchemaId, tenantId]
  );
  if (result.rowCount === 0 || !result.rows[0]) return null;
  const row = result.rows[0] as { class_schema_id: string; class_id: string; class_name: string; schema: unknown };
  return {
    class_schema_id: row.class_schema_id,
    class_id: row.class_id,
    class_name: row.class_name,
    schema: typeof row.schema === 'object' && row.schema !== null ? (row.schema as Record<string, unknown>) : {},
  };
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

/**
 * Batch count rows in data_snapshot per class_schema_id for a tenant.
 * Only includes class_schema_ids that belong to versions in the tenant's projects.
 * Returns a map with an entry for each requested id (0 if no rows).
 */
export async function getDataSnapshotCounts(
  classSchemaIds: string[],
  tenantId: string
): Promise<Record<string, number>> {
  if (classSchemaIds.length === 0) return {};
  const result = await connectionPool.query(
    `SELECT ds.class_schema_id, COUNT(*)::int AS cnt
     FROM odb.data_snapshot ds
     JOIN odb.class_schema cs ON cs.id = ds.class_schema_id
     JOIN odb.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN odb.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
     WHERE ds.class_schema_id = ANY($1::uuid[]) AND ds.tenant_id = $2
     GROUP BY ds.class_schema_id`,
    [classSchemaIds, tenantId]
  );
  const map: Record<string, number> = {};
  for (const id of classSchemaIds) {
    map[id] = 0;
  }
  for (const row of result.rows as { class_schema_id: string; cnt: number }[]) {
    map[row.class_schema_id] = row.cnt;
  }
  return map;
}

export interface DataSnapshotRow {
  record_id: string;
  data: Record<string, unknown>;
  updated_at: string;
  created_at?: string;
  record_sequence?: number;
  last_action?: string;
}

/**
 * Allowed sort columns for snapshot list (maps to SQL expressions).
 * Data column is intentionally excluded.
 */
const SNAPSHOT_SORT_COLUMNS: Record<string, string> = {
  record_id: 'ds.record_id',
  created_at: 'dr_first.created_at',
  updated_at: 'ds.updated_at',
  record_sequence: 'dr_last.record_sequence',
  last_action: 'dr_last.action',
};

function buildSnapshotOrderBy(sortBy?: string | null, sortDir?: string | null): string {
  const dir = sortDir === 'asc' ? 'ASC' : 'DESC';
  const col = sortBy && SNAPSHOT_SORT_COLUMNS[sortBy] ? SNAPSHOT_SORT_COLUMNS[sortBy] : 'ds.updated_at';
  return `ORDER BY ${col} ${dir} NULLS LAST, ds.record_id`;
}

/**
 * Paginated list of data_snapshot rows for a class_schema and tenant.
 */
export async function getDataSnapshotPage(
  classSchemaId: string,
  tenantId: string,
  page: number,
  pageSize: number,
  sortBy?: string | null,
  sortDir?: string | null
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));
  const orderBy = buildSnapshotOrderBy(sortBy, sortDir);

  const countResult = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2`,
    [classSchemaId, tenantId]
  );
  const total = countResult.rows[0]?.cnt ?? 0;

  const listResult = await connectionPool.query(
    `SELECT ds.record_id, ds.data, ds.updated_at,
            dr_first.created_at,
            dr_last.record_sequence,
            dr_last.action AS last_action
     FROM odb.data_snapshot ds
     LEFT JOIN LATERAL (
       SELECT created_at FROM odb.data_record dr
       WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
       ORDER BY dr.record_sequence ASC LIMIT 1
     ) dr_first ON true
     LEFT JOIN LATERAL (
       SELECT record_sequence, action FROM odb.data_record dr
       WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
       ORDER BY dr.record_sequence DESC LIMIT 1
     ) dr_last ON true
     WHERE ds.class_schema_id = $1 AND ds.tenant_id = $2
     ${orderBy}
     LIMIT $3 OFFSET $4`,
    [classSchemaId, tenantId, limit, offset]
  );

  const rows: DataSnapshotRow[] = listResult.rows.map((row: {
    record_id: string;
    data: unknown;
    updated_at: string;
    created_at?: string;
    record_sequence?: number;
    last_action?: string;
  }) => ({
    record_id: row.record_id,
    data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
    updated_at: row.updated_at,
    created_at: row.created_at,
    record_sequence: row.record_sequence,
    last_action: row.last_action,
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
  pageSize: number,
  sortBy?: string | null,
  sortDir?: string | null
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));
  const pattern = `%${q.replace(/%/g, '\\%').replace(/_/g, '\\_')}%`;
  const orderBy = buildSnapshotOrderBy(sortBy, sortDir);

  const countResult = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM odb.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2 AND data::text ILIKE $3`,
    [classSchemaId, tenantId, pattern]
  );
  const total = countResult.rows[0]?.cnt ?? 0;

  const listResult = await connectionPool.query(
    `SELECT ds.record_id, ds.data, ds.updated_at,
            dr_first.created_at,
            dr_last.record_sequence,
            dr_last.action AS last_action
     FROM odb.data_snapshot ds
     LEFT JOIN LATERAL (
       SELECT created_at FROM odb.data_record dr
       WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
       ORDER BY dr.record_sequence ASC LIMIT 1
     ) dr_first ON true
     LEFT JOIN LATERAL (
       SELECT record_sequence, action FROM odb.data_record dr
       WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
       ORDER BY dr.record_sequence DESC LIMIT 1
     ) dr_last ON true
     WHERE ds.class_schema_id = $1 AND ds.tenant_id = $2 AND ds.data::text ILIKE $3
     ${orderBy}
     LIMIT $4 OFFSET $5`,
    [classSchemaId, tenantId, pattern, limit, offset]
  );

  const rows: DataSnapshotRow[] = listResult.rows.map((row: {
    record_id: string;
    data: unknown;
    updated_at: string;
    created_at?: string;
    record_sequence?: number;
    last_action?: string;
  }) => ({
    record_id: row.record_id,
    data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
    updated_at: row.updated_at,
    created_at: row.created_at,
    record_sequence: row.record_sequence,
    last_action: row.last_action,
  }));

  return { rows, total };
}

/**
 * Insert a new record: one data_record (action 'created', record_sequence 1) and one data_snapshot row.
 * Throws if tenant has no access to the class_schema.
 */
export async function insertDataRecord(
  classSchemaId: string,
  tenantId: string,
  data: Record<string, unknown>,
  createdBy?: string | null
): Promise<{ record_id: string }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) {
    throw new Error('Access denied to class schema');
  }
  const recordId = crypto.randomUUID();
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    await client.query(
      `INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
       VALUES ($1, $2, 'created', 1, $3::jsonb, $4, $5)`,
      [recordId, classSchemaId, JSON.stringify(data), tenantId, createdBy ?? null]
    );
    await client.query(
      `INSERT INTO odb.data_snapshot (record_id, class_schema_id, data, tenant_id)
       VALUES ($1, $2, $3::jsonb, $4)`,
      [recordId, classSchemaId, JSON.stringify(data), tenantId]
    );
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {});
    throw err;
  } finally {
    client.release();
  }
  return { record_id: recordId };
}

/**
 * Update an existing record: append data_record (action 'updated') and update data_snapshot.
 * Throws if tenant has no access or record not found.
 */
export async function updateDataRecord(
  recordId: string,
  classSchemaId: string,
  tenantId: string,
  data: Record<string, unknown>,
  updatedBy?: string | null
): Promise<void> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) {
    throw new Error('Access denied to class schema');
  }
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const seqResult = await client.query(
      `SELECT COALESCE(MAX(record_sequence), 0) + 1 AS next_seq
       FROM odb.data_record WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3`,
      [recordId, classSchemaId, tenantId]
    );
    const nextSeq = seqResult.rows[0]?.next_seq ?? 1;
    const updateSnapshotResult = await client.query(
      `UPDATE odb.data_snapshot
       SET data = $1::jsonb, updated_at = CURRENT_TIMESTAMP
       WHERE record_id = $2 AND class_schema_id = $3 AND tenant_id = $4`,
      [JSON.stringify(data), recordId, classSchemaId, tenantId]
    );
    if (updateSnapshotResult.rowCount === 0) {
      await client.query('ROLLBACK');
      throw new Error('Record not found');
    }
    await client.query(
      `INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
       VALUES ($1, $2, 'updated', $3, $4::jsonb, $5, $6)`,
      [recordId, classSchemaId, nextSeq, JSON.stringify(data), tenantId, updatedBy ?? null]
    );
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Delete a record: read current state from data_snapshot, append data_record with action 'deleted'
 * (same record_id, incremented record_sequence, data = snapshot so restore can use it), then remove the snapshot row.
 * Throws if tenant has no access or record not found.
 */
export async function deleteDataRecord(
  recordId: string,
  classSchemaId: string,
  tenantId: string,
  deletedBy?: string | null
): Promise<void> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) {
    throw new Error('Access denied to class schema');
  }
  const client = await connectionPool.connect();
  try {
    await client.query('BEGIN');
    const snapshotResult = await client.query(
      `SELECT data FROM odb.data_snapshot
       WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3`,
      [recordId, classSchemaId, tenantId]
    );
    if (snapshotResult.rowCount === 0 || !snapshotResult.rows[0]) {
      await client.query('ROLLBACK');
      throw new Error('Record not found');
    }
    const currentData = snapshotResult.rows[0].data as Record<string, unknown>;
    const seqResult = await client.query(
      `SELECT COALESCE(MAX(record_sequence), 0) + 1 AS next_seq
       FROM odb.data_record WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3`,
      [recordId, classSchemaId, tenantId]
    );
    const nextSeq = seqResult.rows[0]?.next_seq ?? 1;
    await client.query(
      `INSERT INTO odb.data_record (record_id, class_schema_id, action, record_sequence, data, tenant_id, created_by)
       VALUES ($1, $2, 'deleted', $3, $4::jsonb, $5, $6)`,
      [recordId, classSchemaId, nextSeq, JSON.stringify(currentData), tenantId, deletedBy ?? null]
    );
    await client.query(
      `DELETE FROM odb.data_snapshot
       WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3`,
      [recordId, classSchemaId, tenantId]
    );
    await client.query('COMMIT');
  } catch (err) {
    await client.query('ROLLBACK').catch(() => {});
    throw err;
  } finally {
    client.release();
  }
}

/**
 * Update the embedding (and metadata) for a data_snapshot row.
 * Used after insert/update to store vectorization from Ollama.
 * If the pgvector extension is not installed (type "vector" does not exist), logs once and no-ops.
 */
let _vectorTypeMissingLogged = false;

export async function updateDataSnapshotEmbedding(
  recordId: string,
  embedding: number[],
  model: string
): Promise<void> {
  if (embedding.length === 0) return;
  // pgvector type lives in public; qualify so it resolves when search_path is e.g. only odb
  const vectorStr = '[' + embedding.join(',') + ']';
  try {
    await connectionPool.query(
      `UPDATE odb.data_snapshot
       SET embedding = $1::public.vector, embedding_model = $2, embedding_updated_at = CURRENT_TIMESTAMP
       WHERE record_id = $3`,
      [vectorStr, model, recordId]
    );
  } catch (err: unknown) {
    const code = (err as { code?: string }).code;
    const message = (err as { message?: string }).message ?? '';
    const isVectorTypeMissing = code === '42704' || /type\s+["']?vector["']?\s+does not exist/i.test(message);
    if (isVectorTypeMissing) {
      if (!_vectorTypeMissingLogged) {
        _vectorTypeMissingLogged = true;
        console.warn(
          '[updateDataSnapshotEmbedding] pgvector extension not available (type "vector" does not exist). ' +
            'Run migration 20260227-140000.sql (and ensure pgvector is installed). Embedding updates will be skipped.'
        );
      }
      return;
    }
    throw err;
  }
}
