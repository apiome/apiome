// Helper functions for path operation management in the database
'use server';

const connectionPool = require('./db');

/**
 * Get all operations for a specific path
 */
export async function getOperationsForPath(versionPathId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_path_id,
      operation,
      metadata,
      created_at,
      updated_at
    FROM apiome.path_operation
    WHERE version_path_id = $1
    ORDER BY 
      CASE operation
        WHEN 'GET' THEN 1
        WHEN 'POST' THEN 2
        WHEN 'PUT' THEN 3
        WHEN 'PATCH' THEN 4
        WHEN 'DELETE' THEN 5
        WHEN 'HEAD' THEN 6
        WHEN 'OPTIONS' THEN 7
        ELSE 8
      END
  `;

  try {
    const result = await connectionPool.query(query, [versionPathId]);
    return JSON.stringify(result.rows);
  } catch (error) {
    console.error('Error fetching operations for path:', error);
    throw error;
  }
}

/**
 * Create a new operation for a path
 * Also creates a path_operation_description with an auto-generated operationId
 */
export async function createOperation(
  versionPathId: string,
  operation: string,
  metadata?: Record<string, any>,
  pathPattern?: string // Optional path pattern for generating operationId
): Promise<string> {
  const operationQuery = `
    INSERT INTO apiome.path_operation (version_path_id, operation, metadata)
    VALUES ($1, $2, $3)
    RETURNING id, version_path_id, operation, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(operationQuery, [
      versionPathId,
      operation.toUpperCase(),
      metadata ? JSON.stringify(metadata) : null,
    ]);

    const createdOperation = result.rows[0];

    // Generate operationId based on method and path
    // e.g., GET /users/{id} -> getUsersById, POST /users -> createUsers
    const generatedOperationId = generateOperationId(operation.toUpperCase(), pathPattern);

    // Create the path_operation_description entry
    const descriptionQuery = `
      INSERT INTO apiome.path_operation_description (path_operation_id, operation_id)
      VALUES ($1, $2)
      ON CONFLICT (path_operation_id) DO NOTHING
    `;

    await connectionPool.query(descriptionQuery, [
      createdOperation.id,
      generatedOperationId,
    ]);

    return JSON.stringify(createdOperation);
  } catch (error) {
    console.error('Error creating operation:', error);
    throw error;
  }
}

/**
 * Generate an operationId based on HTTP method and path pattern
 * Examples:
 *   GET /users -> getUsers
 *   POST /users -> createUsers
 *   GET /users/{userId} -> getUsersById
 *   PUT /users/{userId} -> updateUsersById
 *   DELETE /users/{userId} -> deleteUsersById
 *   PATCH /users/{userId} -> patchUsersById
 */
function generateOperationId(method: string, pathPattern?: string): string {
  // Map HTTP methods to operation prefixes
  const methodPrefixes: Record<string, string> = {
    'GET': 'get',
    'POST': 'create',
    'PUT': 'update',
    'DELETE': 'delete',
    'PATCH': 'patch',
    'HEAD': 'head',
    'OPTIONS': 'options',
  };

  const prefix = methodPrefixes[method] || method.toLowerCase();

  if (!pathPattern) {
    return `${prefix}Resource`;
  }

  // Parse the path pattern
  // Remove leading slash and split by /
  const parts = pathPattern.replace(/^\//, '').split('/');

  // Convert path parts to camelCase
  // - Regular segments become capitalized words
  // - {param} segments become "ById" or "ByParamName"
  let hasPathParam = false;
  const nameParts: string[] = [];

  for (const part of parts) {
    if (part.startsWith('{') && part.endsWith('}')) {
      // This is a path parameter
      hasPathParam = true;
    } else if (part) {
      // Regular path segment - capitalize first letter
      nameParts.push(part.charAt(0).toUpperCase() + part.slice(1));
    }
  }

  const resourceName = nameParts.join('');
  const suffix = hasPathParam ? 'ById' : '';

  return `${prefix}${resourceName}${suffix}`;
}

/**
 * Update an existing operation
 */
export async function updateOperation(
  operationId: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    UPDATE apiome.path_operation
    SET 
      metadata = $2,
      updated_at = CURRENT_TIMESTAMP
    WHERE id = $1
    RETURNING id, version_path_id, operation, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify(result.rows[0]);
  } catch (error) {
    console.error('Error updating operation:', error);
    throw error;
  }
}

/**
 * Delete an operation
 */
export async function deleteOperation(operationId: string): Promise<void> {
  const query = `
    DELETE FROM apiome.path_operation
    WHERE id = $1
  `;

  try {
    await connectionPool.query(query, [operationId]);
  } catch (error) {
    console.error('Error deleting operation:', error);
    throw error;
  }
}

/**
 * Get a single operation by ID
 */
export async function getOperationById(operationId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_path_id,
      operation,
      metadata,
      created_at,
      updated_at
    FROM apiome.path_operation
    WHERE id = $1
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify(result.rows[0]);
  } catch (error) {
    console.error('Error fetching operation by ID:', error);
    throw error;
  }
}

