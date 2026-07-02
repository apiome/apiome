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
     FROM apiome.class_schema cs
     JOIN apiome.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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
    `SELECT 1 FROM apiome.class_schema cs
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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

/**
 * Ensure class_schema_id belongs to a version in a project under the tenant.
 */
export async function assertClassSchemaTenantAccess(
  classSchemaId: string,
  tenantId: string
): Promise<boolean> {
  const result = await connectionPool.query(
    `SELECT 1 FROM apiome.class_schema cs
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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
     FROM apiome.class_schema cs
     JOIN apiome.classes c ON c.id = cs.class_id AND c.deleted_at IS NULL
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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
 * Get the current snapshot data for a single record (for edit form).
 * Returns null if not found or tenant has no access (e.g. record deleted).
 */
export async function getDataSnapshotByRecordId(
  recordId: string,
  classSchemaId: string,
  tenantId: string
): Promise<{ data: Record<string, unknown> } | null> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return null;

  const result = await connectionPool.query(
    `SELECT data FROM apiome.data_snapshot
     WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3`,
    [recordId, classSchemaId, tenantId]
  );
  if (result.rowCount === 0 || !result.rows[0]) return null;
  const row = result.rows[0] as { data: unknown };
  return {
    data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
  };
}

/**
 * Count rows in data_snapshot for a class_schema and tenant.
 * When includeDeleted is true, also counts records whose latest event is 'deleted' (no snapshot row).
 */
export async function getDataSnapshotCount(
  classSchemaId: string,
  tenantId: string,
  options?: { includeDeleted?: boolean }
): Promise<number> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return 0;
  const result = await connectionPool.query(
    `SELECT COUNT(*)::int AS cnt FROM apiome.data_snapshot
     WHERE class_schema_id = $1 AND tenant_id = $2`,
    [classSchemaId, tenantId]
  );
  let count = result.rows[0]?.cnt ?? 0;
  if (options?.includeDeleted) {
    const deletedResult = await connectionPool.query(
      `WITH dr_last AS (
         SELECT DISTINCT ON (record_id) record_id, action
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence DESC
       )
       SELECT COUNT(*)::int AS cnt FROM dr_last d
       WHERE d.action = 'deleted'
       AND NOT EXISTS (
         SELECT 1 FROM apiome.data_snapshot ds
         WHERE ds.record_id = d.record_id AND ds.class_schema_id = $1 AND ds.tenant_id = $2
       )`,
      [classSchemaId, tenantId]
    );
    count += deletedResult.rows[0]?.cnt ?? 0;
  }
  return count;
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
     FROM apiome.data_snapshot ds
     JOIN apiome.class_schema cs ON cs.id = ds.class_schema_id
     JOIN apiome.versions v ON v.id = cs.version_id AND v.deleted_at IS NULL
     JOIN apiome.projects p ON p.id = v.project_id AND p.tenant_id = $2 AND p.deleted_at IS NULL
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
 * When includeDeleted is true, appends rows for records whose latest event is 'deleted' (no snapshot row).
 */
export async function getDataSnapshotPage(
  classSchemaId: string,
  tenantId: string,
  page: number,
  pageSize: number,
  sortBy?: string | null,
  sortDir?: string | null,
  options?: { includeDeleted?: boolean }
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));
  const orderBy = buildSnapshotOrderBy(sortBy, sortDir);

  if (!options?.includeDeleted) {
    const countResult = await connectionPool.query(
      `SELECT COUNT(*)::int AS cnt FROM apiome.data_snapshot
       WHERE class_schema_id = $1 AND tenant_id = $2`,
      [classSchemaId, tenantId]
    );
    const total = countResult.rows[0]?.cnt ?? 0;

    const listResult = await connectionPool.query(
      `SELECT ds.record_id, ds.data, ds.updated_at,
              dr_first.created_at,
              dr_last.record_sequence,
              dr_last.action AS last_action
       FROM apiome.data_snapshot ds
       LEFT JOIN LATERAL (
         SELECT created_at FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence ASC LIMIT 1
       ) dr_first ON true
       LEFT JOIN LATERAL (
         SELECT record_sequence, action FROM apiome.data_record dr
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

  // includeDeleted: union snapshot rows with deleted-only rows, then sort and paginate
  const safeSortCol = ['record_id', 'created_at', 'updated_at', 'record_sequence', 'last_action'].includes(
    sortBy ?? ''
  )
    ? sortBy!
    : 'updated_at';
  const dir = sortDir === 'asc' ? 'ASC' : 'DESC';
  const orderByUnified = `ORDER BY ${safeSortCol} ${dir} NULLS LAST, record_id`;

  const unionResult = await connectionPool.query(
    `WITH snapshot_rows AS (
       SELECT ds.record_id, ds.data, dr_first.created_at, ds.updated_at,
              dr_last.record_sequence, dr_last.action AS last_action
       FROM apiome.data_snapshot ds
       LEFT JOIN LATERAL (
         SELECT created_at FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence ASC LIMIT 1
       ) dr_first ON true
       LEFT JOIN LATERAL (
         SELECT record_sequence, action FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence DESC LIMIT 1
       ) dr_last ON true
       WHERE ds.class_schema_id = $1 AND ds.tenant_id = $2
     ),
     deleted_rows AS (
       SELECT d.record_id,
              COALESCE(d.data, '{}'::jsonb) AS data,
              f.created_at,
              d.created_at AS updated_at,
              d.record_sequence,
              d.action AS last_action
       FROM (
         SELECT DISTINCT ON (record_id) record_id, record_sequence, action, created_at, data
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence DESC
       ) d
       JOIN (
         SELECT DISTINCT ON (record_id) record_id, created_at
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence ASC
       ) f ON f.record_id = d.record_id
       WHERE d.action = 'deleted'
       AND NOT EXISTS (
         SELECT 1 FROM apiome.data_snapshot ds
         WHERE ds.record_id = d.record_id AND ds.class_schema_id = $1 AND ds.tenant_id = $2
       )
     ),
     combined AS (
       SELECT record_id, data, created_at, updated_at, record_sequence, last_action,
              updated_at AS sort_at FROM snapshot_rows
       UNION ALL
       SELECT record_id, data, created_at, updated_at, record_sequence, last_action,
              updated_at AS sort_at FROM deleted_rows
     )
     SELECT record_id, data, created_at, updated_at, record_sequence, last_action FROM combined
     ${orderByUnified}
     LIMIT $3 OFFSET $4`,
    [classSchemaId, tenantId, limit, offset]
  );

  const countResult = await connectionPool.query(
    `WITH snapshot_rows AS (
       SELECT ds.record_id FROM apiome.data_snapshot ds
       WHERE ds.class_schema_id = $1 AND ds.tenant_id = $2
     ),
     deleted_rows AS (
       SELECT d.record_id
       FROM (
         SELECT DISTINCT ON (record_id) record_id, action
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence DESC
       ) d
       WHERE d.action = 'deleted'
       AND NOT EXISTS (
         SELECT 1 FROM apiome.data_snapshot ds
         WHERE ds.record_id = d.record_id AND ds.class_schema_id = $1 AND ds.tenant_id = $2
       )
     )
     SELECT (SELECT COUNT(*) FROM snapshot_rows) + (SELECT COUNT(*) FROM deleted_rows) AS cnt`,
    [classSchemaId, tenantId]
  );
  const total = parseInt(String(countResult.rows[0]?.cnt ?? 0), 10);

  const rows: DataSnapshotRow[] = unionResult.rows.map((row: {
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
 * When includeDeleted is true, also includes records whose latest event is 'deleted' (no text filter on deleted).
 */
export async function searchDataSnapshot(
  classSchemaId: string,
  tenantId: string,
  q: string,
  page: number,
  pageSize: number,
  sortBy?: string | null,
  sortDir?: string | null,
  options?: { includeDeleted?: boolean }
): Promise<{ rows: DataSnapshotRow[]; total: number }> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return { rows: [], total: 0 };

  const offset = Math.max(0, page - 1) * Math.max(1, pageSize);
  const limit = Math.min(100, Math.max(1, pageSize));
  const pattern = `%${q.replace(/%/g, '\\%').replace(/_/g, '\\_')}%`;
  const orderBy = buildSnapshotOrderBy(sortBy, sortDir);

  if (!options?.includeDeleted) {
    const countResult = await connectionPool.query(
      `SELECT COUNT(*)::int AS cnt FROM apiome.data_snapshot
       WHERE class_schema_id = $1 AND tenant_id = $2 AND data::text ILIKE $3`,
      [classSchemaId, tenantId, pattern]
    );
    const total = countResult.rows[0]?.cnt ?? 0;

    const listResult = await connectionPool.query(
      `SELECT ds.record_id, ds.data, ds.updated_at,
              dr_first.created_at,
              dr_last.record_sequence,
              dr_last.action AS last_action
       FROM apiome.data_snapshot ds
       LEFT JOIN LATERAL (
         SELECT created_at FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence ASC LIMIT 1
       ) dr_first ON true
       LEFT JOIN LATERAL (
         SELECT record_sequence, action FROM apiome.data_record dr
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

  // includeDeleted: union (snapshot rows matching q) with (all deleted rows), then sort and paginate
  const safeSortCol = ['record_id', 'created_at', 'updated_at', 'record_sequence', 'last_action'].includes(
    sortBy ?? ''
  )
    ? sortBy!
    : 'updated_at';
  const dir = sortDir === 'asc' ? 'ASC' : 'DESC';
  const orderByUnified = `ORDER BY ${safeSortCol} ${dir} NULLS LAST, record_id`;

  const unionResult = await connectionPool.query(
    `WITH snapshot_rows AS (
       SELECT ds.record_id, ds.data, dr_first.created_at, ds.updated_at,
              dr_last.record_sequence, dr_last.action AS last_action
       FROM apiome.data_snapshot ds
       LEFT JOIN LATERAL (
         SELECT created_at FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence ASC LIMIT 1
       ) dr_first ON true
       LEFT JOIN LATERAL (
         SELECT record_sequence, action FROM apiome.data_record dr
         WHERE dr.record_id = ds.record_id AND dr.class_schema_id = ds.class_schema_id AND dr.tenant_id = ds.tenant_id
         ORDER BY dr.record_sequence DESC LIMIT 1
       ) dr_last ON true
       WHERE ds.class_schema_id = $1 AND ds.tenant_id = $2 AND ds.data::text ILIKE $3
     ),
     deleted_rows AS (
       SELECT d.record_id,
              COALESCE(d.data, '{}'::jsonb) AS data,
              f.created_at,
              d.created_at AS updated_at,
              d.record_sequence,
              d.action AS last_action
       FROM (
         SELECT DISTINCT ON (record_id) record_id, record_sequence, action, created_at, data
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence DESC
       ) d
       JOIN (
         SELECT DISTINCT ON (record_id) record_id, created_at
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence ASC
       ) f ON f.record_id = d.record_id
       WHERE d.action = 'deleted'
       AND NOT EXISTS (
         SELECT 1 FROM apiome.data_snapshot ds
         WHERE ds.record_id = d.record_id AND ds.class_schema_id = $1 AND ds.tenant_id = $2
       )
     ),
     combined AS (
       SELECT record_id, data, created_at, updated_at, record_sequence, last_action FROM snapshot_rows
       UNION ALL
       SELECT record_id, data, created_at, updated_at, record_sequence, last_action FROM deleted_rows
     )
     SELECT record_id, data, created_at, updated_at, record_sequence, last_action FROM combined
     ${orderByUnified}
     LIMIT $4 OFFSET $5`,
    [classSchemaId, tenantId, pattern, limit, offset]
  );

  const countResult = await connectionPool.query(
    `WITH snapshot_match AS (
       SELECT COUNT(*)::int AS cnt FROM apiome.data_snapshot
       WHERE class_schema_id = $1 AND tenant_id = $2 AND data::text ILIKE $3
     ),
     deleted_cnt AS (
       SELECT COUNT(*)::int AS cnt FROM (
         SELECT DISTINCT ON (record_id) record_id, action
         FROM apiome.data_record
         WHERE class_schema_id = $1 AND tenant_id = $2
         ORDER BY record_id, record_sequence DESC
       ) d
       WHERE d.action = 'deleted'
       AND NOT EXISTS (
         SELECT 1 FROM apiome.data_snapshot ds
         WHERE ds.record_id = d.record_id AND ds.class_schema_id = $1 AND ds.tenant_id = $2
       )
     )
     SELECT (SELECT cnt FROM snapshot_match) + COALESCE((SELECT cnt FROM deleted_cnt), 0) AS cnt`,
    [classSchemaId, tenantId, pattern]
  );
  const total = parseInt(String(countResult.rows[0]?.cnt ?? 0), 10);

  const rows: DataSnapshotRow[] = unionResult.rows.map((row: {
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

export interface RecordHistoryEvent {
  record_sequence: number;
  action: string;
  created_at: string;
  created_by: string | null;
  data: Record<string, unknown>;
}

/**
 * Full event history for a single record (data_record rows ordered by record_sequence).
 * Used by the record view dialog "Historical" tab.
 */
export async function getRecordHistory(
  recordId: string,
  classSchemaId: string,
  tenantId: string
): Promise<RecordHistoryEvent[]> {
  const hasAccess = await assertClassSchemaTenantAccess(classSchemaId, tenantId);
  if (!hasAccess) return [];

  const result = await connectionPool.query(
    `SELECT record_sequence, action, created_at, created_by, data
     FROM apiome.data_record
     WHERE record_id = $1 AND class_schema_id = $2 AND tenant_id = $3
     ORDER BY record_sequence ASC`,
    [recordId, classSchemaId, tenantId]
  );

  return (result.rows as { record_sequence: number; action: string; created_at: string; created_by: string | null; data: unknown }[]).map(
    (row) => ({
      record_sequence: row.record_sequence,
      action: row.action,
      created_at: row.created_at,
      created_by: row.created_by ?? null,
      data: typeof row.data === 'object' && row.data !== null ? (row.data as Record<string, unknown>) : {},
    })
  );
}

export interface MigrationRuleTemplateRow {
  id: string;
  name: string;
  description: string | null;
  category: string;
  rule_type: 'simple' | 'script' | 'sparkSql';
  rule_content: string;
  min_inputs: number;
  min_outputs: number;
  input_labels: string[] | null;
  sort_order: number;
}

/**
 * Get all migration rule templates for the migration UI (global, not tenant-scoped).
 */
export async function getMigrationRuleTemplates(): Promise<MigrationRuleTemplateRow[]> {
  const result = await connectionPool.query(
    `SELECT id, name, description, category, rule_type, rule_content, min_inputs, min_outputs, input_labels, sort_order
     FROM apiome.migration_rule_templates
     ORDER BY sort_order ASC, name ASC`
  );
  return (result.rows as { id: string; name: string; description: string | null; category: string; rule_type: string; rule_content: string; min_inputs: number; min_outputs: number; input_labels: unknown; sort_order: number }[]).map(
    (row) => ({
      id: row.id,
      name: row.name,
      description: row.description,
      category: row.category,
      rule_type: row.rule_type as 'simple' | 'script' | 'sparkSql',
      rule_content: row.rule_content,
      min_inputs: row.min_inputs,
      min_outputs: row.min_outputs,
      input_labels: Array.isArray(row.input_labels) ? (row.input_labels as string[]) : null,
      sort_order: row.sort_order,
    })
  );
}

