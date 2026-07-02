'use server';

// Helper functions for path parameter management

const connectionPool = require('./db');

/**
 * Get all parameters for a path operation
 */
export async function getParametersForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      path_operation_id,
      name,
      in_location,
      summary,
      description,
      metadata,
      data,
      created_at,
      updated_at
    FROM apiome.path_parameter
    WHERE path_operation_id = $1
    ORDER BY 
      CASE in_location
        WHEN 'path' THEN 1
        WHEN 'query' THEN 2
        WHEN 'header' THEN 3
        WHEN 'cookie' THEN 4
        ELSE 5
      END,
      name ASC
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true, parameters: result.rows });
  } catch (error: any) {
    console.error('Error fetching parameters:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a path parameter
 */
export async function createPathParameter(
  operationId: string,
  name: string,
  inLocation: 'path' | 'query' | 'header' | 'cookie',
  summary?: string,
  description?: string,
  metadata?: Record<string, any>,
  data?: Record<string, any>
): Promise<string> {
  // Default schema if not provided
  const schemaData = data || { type: 'string' };

  const query = `
    INSERT INTO apiome.path_parameter 
    (path_operation_id, name, in_location, summary, description, metadata, data)
    VALUES ($1, $2, $3, $4, $5, $6, $7)
    RETURNING id, path_operation_id, name, in_location, summary, description, metadata, data, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      name,
      inLocation,
      summary || null,
      description || null,
      metadata ? JSON.stringify(metadata) : null,
      JSON.stringify(schemaData),
    ]);
    return JSON.stringify({ success: true, parameter: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating parameter:', error);
    if (error.code === '23505') {
      return JSON.stringify({
        success: false,
        error: 'A parameter with this name and location already exists for this operation'
      });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a path parameter
 */
export async function updatePathParameter(
  parameterId: string,
  updates: {
    name?: string;
    inLocation?: 'path' | 'query' | 'header' | 'cookie';
    summary?: string;
    description?: string;
    metadata?: Record<string, any>;
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
  if (updates.metadata !== undefined) {
    setClauses.push(`metadata = $${++paramIndex}`);
    params.push(JSON.stringify(updates.metadata));
  }
  if (updates.data !== undefined) {
    setClauses.push(`data = $${++paramIndex}`);
    params.push(JSON.stringify(updates.data));
  }

  const query = `
    UPDATE apiome.path_parameter
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, path_operation_id, name, in_location, summary, description, metadata, data, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Parameter not found' });
    }
    return JSON.stringify({ success: true, parameter: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating parameter:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a path parameter
 */
export async function deletePathParameter(parameterId: string): Promise<string> {
  const query = 'DELETE FROM apiome.path_parameter WHERE id = $1';

  try {
    const result = await connectionPool.query(query, [parameterId]);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Parameter not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting parameter:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

