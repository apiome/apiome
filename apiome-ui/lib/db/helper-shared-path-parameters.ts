'use server';

// Helper functions for shared path parameter management

const connectionPool = require('./db');

/**
 * Get all shared path parameters for a version (by path id)
 */
export async function getSharedPathParameters(versionPathId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_path_id,
      name,
      in_location,
      summary,
      description,
      data,
      created_at,
      updated_at
    FROM apiome.shared_path_parameter
    WHERE version_path_id = $1
    ORDER BY name ASC
  `;

  try {
    const result = await connectionPool.query(query, [versionPathId]);
    return JSON.stringify({ success: true, parameters: result.rows });
  } catch (error: any) {
    console.error('Error fetching shared path parameters:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a shared path parameter (or return existing if already exists)
 */
export async function createSharedPathParameter(
  versionPathId: string,
  name: string,
  inLocation: 'path' | 'query' | 'header' | 'cookie',
  summary?: string,
  description?: string,
  data?: Record<string, any>
): Promise<string> {
  const schemaData = data || { type: 'string', required: true };

  // Check if parameter already exists
  const checkQuery = `
    SELECT id, version_path_id, name, in_location, summary, description, data
    FROM apiome.shared_path_parameter
    WHERE version_path_id = $1 AND name = $2 AND in_location = $3
  `;

  try {
    const checkResult = await connectionPool.query(checkQuery, [versionPathId, name, inLocation]);

    if (checkResult.rows.length > 0) {
      // Return existing parameter
      return JSON.stringify({ success: true, parameter: checkResult.rows[0], existed: true });
    }

    // Create new parameter
    const insertQuery = `
      INSERT INTO apiome.shared_path_parameter 
      (version_path_id, name, in_location, summary, description, data)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING id, version_path_id, name, in_location, summary, description, data, created_at, updated_at
    `;

    const result = await connectionPool.query(insertQuery, [
      versionPathId,
      name,
      inLocation,
      summary || null,
      description || null,
      JSON.stringify(schemaData),
    ]);

    return JSON.stringify({ success: true, parameter: result.rows[0], existed: false });
  } catch (error: any) {
    console.error('Error creating shared path parameter:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Link a shared parameter to an operation
 */
export async function linkParameterToOperation(
  operationId: string,
  sharedParameterId: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    INSERT INTO apiome.path_operation_parameter_link 
    (path_operation_id, shared_path_parameter_id, metadata)
    VALUES ($1, $2, $3)
    ON CONFLICT (path_operation_id, shared_path_parameter_id) 
    DO UPDATE SET metadata = EXCLUDED.metadata
    RETURNING id, path_operation_id, shared_path_parameter_id, metadata
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      sharedParameterId,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify({ success: true, link: result.rows[0] });
  } catch (error: any) {
    console.error('Error linking parameter to operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Unlink a parameter from an operation
 */
export async function unlinkParameterFromOperation(
  operationId: string,
  sharedParameterId: string
): Promise<string> {
  const query = `
    DELETE FROM apiome.path_operation_parameter_link
    WHERE path_operation_id = $1 AND shared_path_parameter_id = $2
  `;

  try {
    await connectionPool.query(query, [operationId, sharedParameterId]);
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error unlinking parameter from operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get all parameters linked to an operation (with full shared parameter details)
 */
export async function getLinkedParametersForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      spp.id,
      spp.version_path_id,
      spp.name,
      spp.in_location,
      spp.summary,
      spp.description,
      spp.data,
      popl.metadata as link_metadata,
      popl.id as link_id,
      spp.created_at,
      spp.updated_at
    FROM apiome.shared_path_parameter spp
    INNER JOIN apiome.path_operation_parameter_link popl 
      ON spp.id = popl.shared_path_parameter_id
    WHERE popl.path_operation_id = $1
    ORDER BY 
      CASE spp.in_location
        WHEN 'path' THEN 1
        WHEN 'query' THEN 2
        WHEN 'header' THEN 3
        WHEN 'cookie' THEN 4
        ELSE 5
      END,
      spp.name ASC
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true, parameters: result.rows });
  } catch (error: any) {
    console.error('Error fetching linked parameters:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a shared path parameter
 */
export async function updateSharedPathParameter(
  parameterId: string,
  updates: {
    name?: string;
    inLocation?: 'path' | 'query' | 'header' | 'cookie';
    summary?: string;
    description?: string;
    data?: Record<string, any>;
  }
): Promise<string> {
  const setClauses: string[] = ['updated_at = CURRENT_TIMESTAMP'];
  const params: any[] = [parameterId];
  let paramIndex = 1;

  if (updates.name !== undefined) {
    setClauses.push(`name = $${++paramIndex}`);
    params.push(updates.name);
  }
  if (updates.inLocation !== undefined) {
    setClauses.push(`in_location = $${++paramIndex}`);
    params.push(updates.inLocation);
  }
  if (updates.summary !== undefined) {
    setClauses.push(`summary = $${++paramIndex}`);
    params.push(updates.summary);
  }
  if (updates.description !== undefined) {
    setClauses.push(`description = $${++paramIndex}`);
    params.push(updates.description);
  }
  if (updates.data !== undefined) {
    setClauses.push(`data = $${++paramIndex}`);
    params.push(JSON.stringify(updates.data));
  }

  const query = `
    UPDATE apiome.shared_path_parameter
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, version_path_id, name, in_location, summary, description, data, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Parameter not found' });
    }
    return JSON.stringify({ success: true, parameter: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating shared parameter:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a shared path parameter (only if not linked to any operations)
 */
export async function deleteSharedPathParameter(parameterId: string): Promise<string> {
  // Check if parameter is linked to any operations
  const checkQuery = `
    SELECT COUNT(*) as link_count 
    FROM apiome.path_operation_parameter_link 
    WHERE shared_path_parameter_id = $1
  `;

  try {
    const checkResult = await connectionPool.query(checkQuery, [parameterId]);
    const linkCount = parseInt(checkResult.rows[0].link_count);

    if (linkCount > 0) {
      return JSON.stringify({
        success: false,
        error: `Cannot delete parameter: it is linked to ${linkCount} operation(s)`
      });
    }

    const deleteQuery = 'DELETE FROM apiome.shared_path_parameter WHERE id = $1';
    await connectionPool.query(deleteQuery, [parameterId]);
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting shared parameter:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

