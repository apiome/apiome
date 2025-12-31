'use server';

/**
 * Transaction-aware database functions for imports.
 * These functions accept an optional client parameter to run within a transaction.
 */

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

    const result = await client.query(
      `INSERT INTO odb.projects (tenant_id, creator_id, name, description, slug, metadata) 
       VALUES ($1, $2, $3, $4, $5, $6) RETURNING *`,
      [tenantId, creatorId, name.trim(), description?.trim() || null, slug.trim().toLowerCase(), metadata ? JSON.stringify(metadata) : '{}']
    );
    return successResponse({ project: result.rows[0] });
  } catch (error: any) {
    if (error.code === '23505') return errorResponse('A project with this slug already exists in this tenant');
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
  changeLog: string
): Promise<string> {
  try {
    if (!versionId?.trim()) return errorResponse('Version ID is required');

    const result = await client.query(
      `INSERT INTO odb.versions (project_id, creator_id, version_id, description, change_log) 
       VALUES ($1, $2, $3, $4, $5) RETURNING *`,
      [projectId, creatorId, versionId.trim(), description?.trim() || null, changeLog?.trim() || null]
    );
    return successResponse({ version: result.rows[0] });
  } catch (error: any) {
    if (error.code === '23505') return errorResponse('A version with this ID already exists in this project');
    return errorResponse(error.message);
  }
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
      `INSERT INTO odb.properties (project_id, name, description, data)
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
      `INSERT INTO odb.classes (version_id, name, description, schema)
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
      `INSERT INTO odb.class_properties (class_id, property_id, name, description, data, parent_id)
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
       FROM odb.classes
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
       FROM odb.class_properties cp
       LEFT JOIN odb.properties p ON cp.property_id = p.id
       WHERE cp.class_id = ANY($1)
       ORDER BY cp.class_id, cp.parent_id NULLS FIRST, cp.name ASC`,
      [classIds]
    );

    // Query 3: Get all tags for all classes in one query
    const tagsResult = await client.query(
      `SELECT ct.id, ct.class_id, ct.tag_id, ct.created_at,
              t.name as tag_name, t.color as tag_color, t.description as tag_description,
              t.project_id
       FROM odb.class_tags ct
       JOIN odb.tags t ON ct.tag_id = t.id
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

