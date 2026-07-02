'use server';

/**
 * Transaction-aware database functions for imports.
 * These functions accept an optional client parameter to run within a transaction.
 */

import { getPlanBlockMessageForNewProject, getPlanBlockMessageForNewVersion } from './plan-entitlements';

const connectionPool = require('./db');

// Type for a Postgres client (from pool)
export type PoolClient = {
  query: (text: string, params?: any[]) => Promise<any>;
  release: () => void;
};

// Helper to standardize responses
const errorResponse = (error: string) => JSON.stringify({ success: false, error });
const successResponse = (data: any = {}) => JSON.stringify({ success: true, ...data });

// Get a new client from the pool for transaction use
export async function getTransactionClient(): Promise<PoolClient> {
  return connectionPool.connect();
}

// Begin a transaction
export async function beginTransaction(client: PoolClient): Promise<void> {
  await client.query('BEGIN');
}

// Commit a transaction
export async function commitTransaction(client: PoolClient): Promise<void> {
  await client.query('COMMIT');
}

// Rollback a transaction
export async function rollbackTransaction(client: PoolClient): Promise<void> {
  await client.query('ROLLBACK');
}

// Release client back to pool
export async function releaseClient(client: PoolClient): Promise<void> {
  client.release();
}

// Slug validation helper
function validateSlug(slug: string): string | null {
  if (!slug) return 'Slug is required';
  if (slug.length < 2) return 'Slug must be at least 2 characters';
  if (slug.length > 100) return 'Slug must be 100 characters or less';
  if (!/^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$/.test(slug)) {
    return 'Slug must start and end with a letter or number, and contain only lowercase letters, numbers, and hyphens';
  }
  if (/--/.test(slug)) return 'Slug cannot contain consecutive hyphens';
  return null;
}

/**
 * Create a project within a transaction
 */
export async function createProjectTx(
  client: PoolClient,
  tenantId: string,
  creatorId: string,
  name: string,
  description: string,
  slug: string,
  metadata?: any
): Promise<string> {
  try {
    if (!name?.trim()) return errorResponse('Project name is required');
    if (!slug?.trim()) return errorResponse('Project slug is required');
    const slugError = validateSlug(slug.trim());
    if (slugError) return errorResponse(slugError);

    const planErr = await getPlanBlockMessageForNewProject(creatorId, client);
    if (planErr) return errorResponse(planErr);

    const result = await client.query(
      `INSERT INTO apiome.projects (tenant_id, creator_id, name, description, slug, metadata) 
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
      [tenantId, creatorId, name.trim(), description?.trim() || null, slug.trim().toLowerCase(), metadata ? JSON.stringify(metadata) : '{}']
    );
    return successResponse({ project: result.rows[0] });
  } catch (error: any) {
    if (error.code === '23505') {
      return errorResponse(`A project with slug "${slug.trim().toLowerCase()}" already exists in this tenant`);
    }
    if (error.code === '23503') {
      // Foreign key constraint violation
      if (error.constraint === 'projects_tenant_id_fkey') {
        return errorResponse('Invalid tenant ID. The tenant may no longer exist or you may need to switch to a valid tenant.');
      }
      if (error.constraint === 'projects_creator_id_fkey') {
        return errorResponse('Invalid user ID. Please try logging out and back in.');
      }
      return errorResponse(`Database constraint error: ${error.detail || error.message}`);
    }
    return errorResponse(error.message);
  }
}

/**
 * When importing OpenAPI into an existing catalog project, persist enriched description
 * (fill-if-blank) and shallow-merge spec-derived metadata into `apiome.projects.metadata`.
 */
export async function mergeProjectImportOpenApiFieldsTx(
  client: PoolClient,
  projectId: string,
  opts: {
    descriptionFromSpec?: string | null;
    metadataPatch?: Record<string, unknown> | null;
  },
): Promise<string> {
  try {
    const row = await client.query(
      `SELECT description, metadata FROM apiome.projects WHERE id = $1 AND deleted_at IS NULL`,
      [projectId],
    );
    if (!row.rows?.length) {
      return errorResponse('Project not found');
    }

    const curDesc = row.rows[0].description as string | null | undefined;
    const rawMeta = row.rows[0].metadata;

    let metaObj: Record<string, unknown> = {};
    if (rawMeta != null) {
      if (typeof rawMeta === 'string') {
        try {
          const p = JSON.parse(rawMeta) as unknown;
          if (p !== null && typeof p === 'object' && !Array.isArray(p)) {
            metaObj = { ...(p as Record<string, unknown>) };
          }
        } catch {
          metaObj = {};
        }
      } else if (typeof rawMeta === 'object' && !Array.isArray(rawMeta)) {
        metaObj = { ...(rawMeta as Record<string, unknown>) };
      }
    }

    const patch =
      opts.metadataPatch !== undefined && opts.metadataPatch !== null && typeof opts.metadataPatch === 'object'
        ? opts.metadataPatch
        : {};
    const mergedMeta = { ...metaObj, ...patch };

    const incDesc = (opts.descriptionFromSpec ?? '').trim();
    const curDescTrim = typeof curDesc === 'string' ? curDesc.trim() : '';
    const nextDesc = incDesc !== '' && curDescTrim === '' ? incDesc : curDesc ?? null;

    await client.query(
      `UPDATE apiome.projects SET description = $1, metadata = $2::jsonb, updated_at = CURRENT_TIMESTAMP WHERE id = $3 AND deleted_at IS NULL`,
      [nextDesc === '' ? null : nextDesc, JSON.stringify(mergedMeta), projectId],
    );
    return successResponse({});
  } catch (error: any) {
    return errorResponse(error.message);
  }
}

/**
 * Create a version within a transaction
 */
export async function createVersionTx(
  client: PoolClient,
  projectId: string,
  creatorId: string,
  versionId: string,
  description: string,
  changeLog: string,
  opts?: { parentVersionUuid?: string | null; projectSlug?: string | null }
): Promise<string> {
  try {
    if (!versionId?.trim()) return errorResponse('Version ID is required');

    const planErr = await getPlanBlockMessageForNewVersion(creatorId, client);
    if (planErr) return errorResponse(planErr);

    const parentUuid = opts?.parentVersionUuid?.trim() || null;
    const result = parentUuid
      ? await client.query(
          `INSERT INTO apiome.versions (project_id, creator_id, version_id, description, change_log, parent_version_id) 
           VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
          [
            projectId,
            creatorId,
            versionId.trim(),
            description?.trim() || null,
            changeLog?.trim() || null,
            parentUuid,
          ]
        )
      : await client.query(
          `INSERT INTO apiome.versions (project_id, creator_id, version_id, description, change_log) 
           VALUES ($1, $2, $3, $4, $5) RETURNING *`,
          [projectId, creatorId, versionId.trim(), description?.trim() || null, changeLog?.trim() || null]
        );
    return successResponse({ version: result.rows[0] });
  } catch (error: any) {
    if (error.code === '23505') {
      const version = versionId.trim();
      const projectSlug = opts?.projectSlug?.trim();
      return errorResponse(
        projectSlug
          ? `A version with ID "${version}" already exists in project "${projectSlug}"`
          : `A version with ID "${version}" already exists in this project`
      );
    }
    return errorResponse(error.message);
  }
}

/**
 * Resolve an existing project's id by tenant + slug (case-insensitive, matching createProjectTx's
 * lowercasing). Used so importing a *new version of an existing API* (same project slug, different
 * version) reuses the project instead of failing on the unique-slug constraint — only a duplicate
 * project **and** version is a hard error.
 */
export async function getProjectIdBySlugTx(
  client: PoolClient,
  tenantId: string,
  slug: string
): Promise<string | null> {
  const normalized = slug?.trim().toLowerCase();
  if (!normalized) return null;
  const result = await client.query(
    `SELECT id FROM apiome.projects
     WHERE tenant_id = $1 AND slug = $2 AND deleted_at IS NULL
     LIMIT 1`,
    [tenantId, normalized]
  );
  const row = result.rows[0];
  return row?.id ? (row.id as string) : null;
}

/** Latest non-deleted revision (versions.id) for a project — used as parent for incremental catalog imports. */
export async function getLatestVersionUuidForProjectTx(
  client: PoolClient,
  projectId: string
): Promise<string | null> {
  const result = await client.query(
    `SELECT id FROM apiome.versions
     WHERE project_id = $1 AND deleted_at IS NULL
     ORDER BY created_at DESC NULLS LAST, id DESC
     LIMIT 1`,
    [projectId]
  );
  const row = result.rows[0];
  return row?.id ? (row.id as string) : null;
}

/** Existing revision row id (`versions.id`) for a catalog version line (`versions.version_id`). */
export async function getVersionUuidForCatalogVersionLineTx(
  client: PoolClient,
  projectId: string,
  catalogVersionId: string
): Promise<string | null> {
  const vid = catalogVersionId?.trim();
  if (!vid) return null;
  const result = await client.query(
    `SELECT id FROM apiome.versions
     WHERE project_id = $1 AND version_id = $2 AND deleted_at IS NULL
     LIMIT 1`,
    [projectId, vid]
  );
  const row = result.rows[0];
  return row?.id ? (row.id as string) : null;
}

/** Property library rows for reuse when importing another revision into the same project. */
export async function listProjectLibraryPropertiesTx(
  client: PoolClient,
  projectId: string
): Promise<Array<{ id: string; name: string; description: string | null; data: any }>> {
  const result = await client.query(
    `SELECT id, name, description, data
     FROM apiome.properties
     WHERE project_id = $1 AND deleted_at IS NULL`,
    [projectId]
  );
  return result.rows as Array<{ id: string; name: string; description: string | null; data: any }>;
}

/**
 * Create a property within a transaction
 */
export async function createPropertyTx(
  client: PoolClient,
  projectId: string,
  name: string,
  description: string | null,
  data: any
): Promise<string> {
  try {
    if (!name || name.trim().length === 0) {
      return errorResponse('Property name is required');
    }

    if (!data) {
      return errorResponse('Property data is required');
    }

    const result = await client.query(
      `INSERT INTO apiome.properties (project_id, name, description, data)
       VALUES ($1, $2, $3, $4)
       RETURNING *`,
      [projectId, name.trim(), description, JSON.stringify(data)]
    );

    return successResponse({ property: result.rows[0] });
  } catch (error: any) {
    // Handle unique constraint violation (duplicate name in same project)
    if (error.code === '23505') {
      return errorResponse('A property with this name already exists in this project');
    }
    return errorResponse(error.message);
  }
}

/**
 * Row to insert into apiome.properties. id is supplied by the caller so a whole batch of
 * library shapes can be written in one statement and the ids fed straight into the
 * class-property links without a second round-trip.
 */
export interface PropertyInsert {
  id: string;
  projectId: string;
  name: string;
  description: string | null;
  data: any;
}

const PROPERTIES_COLS = 5;
const PROPERTIES_INSERT_HEAD =
  'INSERT INTO apiome.properties (id, project_id, name, description, data) VALUES ';

function propertyValues(r: PropertyInsert): any[] {
  return [r.id, r.projectId, r.name.trim(), r.description, JSON.stringify(r.data)];
}

/**
 * Bulk-create project library properties in one (chunked) multi-row INSERT.
 *
 * #perf: replaces the per-shape N+1 round-trips in buildPropertyIdMapForImport. Same
 * shape as addPropertiesToClassBatchTx — savepoint-protected with a per-row fallback so
 * a single name collision is reported (and skipped) without aborting the whole batch.
 * Returns { inserted, failed: [{ name, error }] }.
 */
export async function createPropertiesBatchTx(
  client: PoolClient,
  rows: PropertyInsert[]
): Promise<string> {
  if (rows.length === 0) return successResponse({ inserted: 0, failed: [] });

  const CHUNK = 1000; // 1000 * 5 = 5000 params, far below the 65535 limit
  const SP = 'imp_props_lib_batch';

  try {
    await client.query(`SAVEPOINT ${SP}`);
  } catch (error: any) {
    return errorResponse(error.message);
  }

  try {
    let inserted = 0;
    for (let start = 0; start < rows.length; start += CHUNK) {
      const chunk = rows.slice(start, start + CHUNK);
      const params: any[] = [];
      const valueGroups = chunk.map((r, i) => {
        const b = i * PROPERTIES_COLS;
        params.push(...propertyValues(r));
        return `($${b + 1}, $${b + 2}, $${b + 3}, $${b + 4}, $${b + 5})`;
      });
      const result = await client.query(PROPERTIES_INSERT_HEAD + valueGroups.join(', '), params);
      inserted += result.rowCount ?? chunk.length;
    }
    await client.query(`RELEASE SAVEPOINT ${SP}`);
    return successResponse({ inserted, failed: [] });
  } catch (_batchError: any) {
    try {
      await client.query(`ROLLBACK TO SAVEPOINT ${SP}`);
      const failed: Array<{ name: string; error: string }> = [];
      let inserted = 0;
      const ROW_SP = 'imp_prop_lib_row';
      for (const r of rows) {
        await client.query(`SAVEPOINT ${ROW_SP}`);
        try {
          await client.query(`${PROPERTIES_INSERT_HEAD}($1, $2, $3, $4, $5)`, propertyValues(r));
          await client.query(`RELEASE SAVEPOINT ${ROW_SP}`);
          inserted++;
        } catch (rowError: any) {
          await client.query(`ROLLBACK TO SAVEPOINT ${ROW_SP}`);
          failed.push({
            name: r.name,
            error:
              rowError?.code === '23505'
                ? 'A property with this name already exists in this project'
                : rowError?.message || 'insert failed',
          });
        }
      }
      await client.query(`RELEASE SAVEPOINT ${SP}`);
      return successResponse({ inserted, failed });
    } catch (recoverError: any) {
      return errorResponse(recoverError.message);
    }
  }
}

/**
 * Create a class within a transaction
 */
export async function createClassTx(
  client: PoolClient,
  versionId: string,
  name: string,
  description: string | null,
  schema: any
): Promise<string> {
  try {
    if (!name || name.trim().length === 0) {
      return errorResponse('Class name is required');
    }

    if (!schema) {
      return errorResponse('Class schema is required');
    }

    const result = await client.query(
      `INSERT INTO apiome.classes (version_id, name, description, schema)
       VALUES ($1, $2, $3, $4)
       RETURNING *`,
      [versionId, name.trim(), description, JSON.stringify(schema)]
    );

    return successResponse({ class: result.rows[0] });
  } catch (error: any) {
    // Handle unique constraint violation (duplicate name in same version)
    if (error.code === '23505') {
      return errorResponse('A class with this name already exists in this version');
    }
    return errorResponse(error.message);
  }
}

/**
 * Add a property to a class within a transaction
 */
export async function addPropertyToClassTx(
  client: PoolClient,
  classId: string,
  propertyId: string | null,
  name: string,
  description: string | null,
  data: any,
  parentId: string | null = null
): Promise<string> {
  try {
    if (!name || name.trim().length === 0) {
      return errorResponse('Property name is required');
    }

    // Validate: either propertyId must be set, or data must contain $ref
    const hasRef = data && (data.$ref || (data.type === 'array' && data.items?.$ref));
    if (!propertyId && !hasRef) {
      return errorResponse('Property must have either a library reference (propertyId) or a schema $ref');
    }

    const result = await client.query(
      `INSERT INTO apiome.class_properties (class_id, property_id, name, description, data, parent_id)
       VALUES ($1, $2, $3, $4, $5, $6)
       RETURNING *`,
      [classId, propertyId, name.trim(), description, JSON.stringify(data), parentId]
    );

    return successResponse({ classProperty: result.rows[0] });
  } catch (error: any) {
    // Handle unique constraint violation (duplicate name in same class under same parent)
    if (error.code === '23505') {
      return errorResponse('A property with this name already exists in this class');
    }
    return errorResponse(error.message);
  }
}

/**
 * Row to insert into apiome.class_properties. The id is supplied by the caller so the
 * full property tree (including parent links) can be flattened and inserted in a
 * single multi-row statement instead of one round-trip per property.
 */
export interface ClassPropertyInsert {
  id: string;
  classId: string;
  propertyId: string | null;
  name: string;
  description: string | null;
  data: any;
  parentId: string | null;
}

const CLASS_PROPERTIES_COLS = 7;
const CLASS_PROPERTIES_INSERT_HEAD =
  'INSERT INTO apiome.class_properties (id, class_id, property_id, name, description, data, parent_id) VALUES ';

function classPropertyValues(r: ClassPropertyInsert): any[] {
  return [r.id, r.classId, r.propertyId, r.name.trim(), r.description, JSON.stringify(r.data), r.parentId];
}

/**
 * Bulk-insert class properties in one (chunked) multi-row INSERT.
 *
 * #perf: replaces the per-property N+1 round-trips in writeClassWithProperties. The
 * caller pre-assigns each row's UUID (the id column defaults to uuid_generate_v4()
 * but accepts a supplied value), so parent/child links are resolved client-side and
 * the whole tree goes to the DB in a single statement. Rows are chunked to stay well
 * under the Postgres 65535 bound-parameter limit (7 cols/row → ~9362 rows max).
 *
 * The batch runs inside a SAVEPOINT so a failure (e.g. a duplicate name) can be
 * recovered without poisoning the surrounding transaction. On failure it rolls back
 * and retries row-by-row (each in its own savepoint), so one bad property is skipped
 * while the rest still import — preserving the graceful-degradation contract (#733).
 * Returns { inserted, failed: [{ name, error }] }; `failed` is only populated when
 * the per-row fallback ran.
 */
export async function addPropertiesToClassBatchTx(
  client: PoolClient,
  rows: ClassPropertyInsert[]
): Promise<string> {
  if (rows.length === 0) return successResponse({ inserted: 0, failed: [] });

  const CHUNK = 1000; // 1000 * 7 = 7000 params, far below the 65535 limit
  const SP = 'imp_props_batch';

  try {
    await client.query(`SAVEPOINT ${SP}`);
  } catch (error: any) {
    // Not inside a transaction (shouldn't happen on the import paths) — surface it.
    return errorResponse(error.message);
  }

  // Fast path: chunked multi-row inserts.
  try {
    let inserted = 0;
    for (let start = 0; start < rows.length; start += CHUNK) {
      const chunk = rows.slice(start, start + CHUNK);
      const params: any[] = [];
      const valueGroups = chunk.map((r, i) => {
        const b = i * CLASS_PROPERTIES_COLS;
        params.push(...classPropertyValues(r));
        return `($${b + 1}, $${b + 2}, $${b + 3}, $${b + 4}, $${b + 5}, $${b + 6}, $${b + 7})`;
      });
      const result = await client.query(
        CLASS_PROPERTIES_INSERT_HEAD + valueGroups.join(', '),
        params
      );
      inserted += result.rowCount ?? chunk.length;
    }
    await client.query(`RELEASE SAVEPOINT ${SP}`);
    return successResponse({ inserted, failed: [] });
  } catch (_batchError: any) {
    // Recover the transaction and retry row-by-row so a single bad row doesn't drop the
    // whole class (graceful degradation). This path only runs on the rare failure case.
    try {
      await client.query(`ROLLBACK TO SAVEPOINT ${SP}`);
      const failed: Array<{ name: string; error: string }> = [];
      let inserted = 0;
      const ROW_SP = 'imp_prop_row';
      for (const r of rows) {
        await client.query(`SAVEPOINT ${ROW_SP}`);
        try {
          await client.query(
            `${CLASS_PROPERTIES_INSERT_HEAD}($1, $2, $3, $4, $5, $6, $7)`,
            classPropertyValues(r)
          );
          await client.query(`RELEASE SAVEPOINT ${ROW_SP}`);
          inserted++;
        } catch (rowError: any) {
          await client.query(`ROLLBACK TO SAVEPOINT ${ROW_SP}`);
          failed.push({
            name: r.name,
            error:
              rowError?.code === '23505'
                ? 'A property with this name already exists in this class'
                : rowError?.message || 'insert failed',
          });
        }
      }
      await client.query(`RELEASE SAVEPOINT ${SP}`);
      return successResponse({ inserted, failed });
    } catch (recoverError: any) {
      return errorResponse(recoverError.message);
    }
  }
}

/**
 * Get classes with properties and tags for a version (for verification)
 */
export async function getClassesWithPropertiesAndTagsTx(
  client: PoolClient,
  versionId: string
): Promise<string> {
  try {
    // Query 1: Get all classes for the version
    const classesResult = await client.query(
      `SELECT id, version_id, name, description, schema, enabled, canvas_metadata, created_at, updated_at
       FROM apiome.classes
       WHERE version_id = $1 AND deleted_at IS NULL
       ORDER BY name ASC`,
      [versionId]
    );

    const classes = classesResult.rows;

    if (classes.length === 0) {
      return JSON.stringify([]);
    }

    const classIds = classes.map((c: any) => c.id);

    // Query 2: Get all properties for all classes in one query
    const propertiesResult = await client.query(
      `SELECT cp.id, cp.class_id, cp.property_id, cp.name, cp.description, cp.data, cp.parent_id,
              p.id as property_source_id, p.name as property_source_name
       FROM apiome.class_properties cp
       LEFT JOIN apiome.properties p ON cp.property_id = p.id
       WHERE cp.class_id = ANY($1)
       ORDER BY cp.class_id, cp.parent_id NULLS FIRST, cp.name ASC`,
      [classIds]
    );

    // Query 3: Get all tags for all classes in one query
    const tagsResult = await client.query(
      `SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
              t.name as tag_name, t.color as tag_color, t.description as tag_description,
              t.project_id
       FROM apiome.class_tags ct
       JOIN apiome.tags t ON ct.tag_id = t.id
       WHERE ct.class_id = ANY($1)
       ORDER BY ct.class_id, t.name ASC`,
      [classIds]
    );

    // Group properties by class_id
    const propertiesByClass = new Map<string, any[]>();
    for (const prop of propertiesResult.rows) {
      const classId = prop.class_id;
      if (!propertiesByClass.has(classId)) {
        propertiesByClass.set(classId, []);
      }
      propertiesByClass.get(classId)!.push(prop);
    }

    // Group tags by class_id
    const tagsByClass = new Map<string, any[]>();
    for (const tag of tagsResult.rows) {
      const classId = tag.class_id;
      if (!tagsByClass.has(classId)) {
        tagsByClass.set(classId, []);
      }
      tagsByClass.get(classId)!.push(tag);
    }

    // Combine classes with their properties and tags
    const classesWithData = classes.map((cls: any) => ({
      ...cls,
      properties: propertiesByClass.get(cls.id) || [],
      tags: tagsByClass.get(cls.id) || []
    }));

    return JSON.stringify(classesWithData);
  } catch (error: any) {
    console.error('Error bulk loading classes with properties and tags:', error);
    return JSON.stringify([]);
  }
}

