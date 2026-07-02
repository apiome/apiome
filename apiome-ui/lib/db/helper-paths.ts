// Helper functions for path management in the database
'use server';

const connectionPool = require('./db');

/**
 * Get all paths for a specific version
 */
export async function getPathsForVersion(versionId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_id,
      pathname,
      metadata,
      created_at,
      updated_at
    FROM apiome.version_path
    WHERE version_id = $1
    ORDER BY pathname ASC
  `;

  try {
    const result = await connectionPool.query(query, [versionId]);
    return JSON.stringify(result.rows);
  } catch (error) {
    console.error('Error fetching paths for version:', error);
    throw error;
  }
}

/**
 * Create a new path for a version
 */
export async function createPath(
  versionId: string,
  pathname: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    INSERT INTO apiome.version_path (version_id, pathname, metadata)
    VALUES ($1, $2, $3)
    RETURNING id, version_id, pathname, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      versionId,
      pathname,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify(result.rows[0]);
  } catch (error) {
    console.error('Error creating path:', error);
    throw error;
  }
}

/**
 * Update an existing path
 */
export async function updatePath(
  pathId: string,
  pathname: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    UPDATE apiome.version_path
    SET 
      pathname = $2,
      metadata = $3,
      updated_at = CURRENT_TIMESTAMP
    WHERE id = $1
    RETURNING id, version_id, pathname, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      pathId,
      pathname,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify(result.rows[0]);
  } catch (error) {
    console.error('Error updating path:', error);
    throw error;
  }
}

/**
 * Delete a path
 */
export async function deletePath(pathId: string): Promise<void> {
  const query = `
    DELETE FROM apiome.version_path
    WHERE id = $1
  `;

  try {
    await connectionPool.query(query, [pathId]);
  } catch (error) {
    console.error('Error deleting path:', error);
    throw error;
  }
}

/**
 * Get a single path by ID
 */
export async function getPathById(pathId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_id,
      pathname,
      metadata,
      created_at,
      updated_at
    FROM apiome.version_path
    WHERE id = $1
  `;

  try {
    const result = await connectionPool.query(query, [pathId]);
    return JSON.stringify(result.rows[0]);
  } catch (error) {
    console.error('Error fetching path by ID:', error);
    throw error;
  }
}

