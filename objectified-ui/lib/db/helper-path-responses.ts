'use server';

// Helper functions for path response management

const connectionPool = require('./db');

/**
 * Get all responses for a path operation
 */
export async function getResponsesForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      path_operation_id,
      status_code,
      description,
      metadata,
      created_at,
      updated_at
    FROM odb.path_response
    WHERE path_operation_id = $1
    ORDER BY status_code ASC
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true, responses: result.rows });
  } catch (error: any) {
    console.error('Error fetching responses:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a path response
 */
export async function createPathResponse(
  operationId: string,
  statusCode: string,
  description?: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    INSERT INTO odb.path_response 
    (path_operation_id, status_code, description, metadata)
    VALUES ($1, $2, $3, $4)
    RETURNING id, path_operation_id, status_code, description, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      statusCode,
      description || null,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify({ success: true, response: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating response:', error);
    if (error.code === '23505') {
      return JSON.stringify({
        success: false,
        error: 'A response with this status code already exists for this operation'
      });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a path response
 */
export async function updatePathResponse(
  responseId: string,
  updates: {
    statusCode?: string;
    description?: string;
    metadata?: Record<string, any>;
  }
): Promise<string> {
  const setClauses: string[] = ['updated_at = CURRENT_TIMESTAMP'];
  const params: any[] = [responseId];
  let paramIndex = 1;

  if (updates.statusCode !== undefined) {
    setClauses.push(`status_code = $${++paramIndex}`);
    params.push(updates.statusCode);
  }
  if (updates.description !== undefined) {
    setClauses.push(`description = $${++paramIndex}`);
    params.push(updates.description);
  }
  if (updates.metadata !== undefined) {
    setClauses.push(`metadata = $${++paramIndex}`);
    params.push(JSON.stringify(updates.metadata));
  }

  const query = `
    UPDATE odb.path_response
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, path_operation_id, status_code, description, metadata, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Response not found' });
    }
    return JSON.stringify({ success: true, response: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating response:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a path response
 */
export async function deletePathResponse(responseId: string): Promise<string> {
  const query = 'DELETE FROM odb.path_response WHERE id = $1';

  try {
    const result = await connectionPool.query(query, [responseId]);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Response not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting response:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

