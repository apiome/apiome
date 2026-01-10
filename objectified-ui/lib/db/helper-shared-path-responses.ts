'use server';

// Helper functions for shared path response management

const connectionPool = require('./db');

/**
 * Get all shared responses for a version path
 */
export async function getSharedPathResponses(versionPathId: string): Promise<string> {
  const query = `
    SELECT 
      id,
      version_path_id,
      status_code,
      description,
      data,
      created_at,
      updated_at
    FROM odb.shared_path_response
    WHERE version_path_id = $1
    ORDER BY status_code ASC
  `;

  try {
    const result = await connectionPool.query(query, [versionPathId]);
    return JSON.stringify({ success: true, responses: result.rows });
  } catch (error: any) {
    console.error('Error fetching shared responses:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get linked responses for an operation
 */
export async function getLinkedResponsesForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      spr.id,
      spr.version_path_id,
      spr.status_code,
      spr.description,
      spr.data,
      spr.created_at,
      spr.updated_at,
      porl.metadata as link_metadata
    FROM odb.shared_path_response spr
    JOIN odb.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
    WHERE porl.path_operation_id = $1
    ORDER BY spr.status_code ASC
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true, responses: result.rows });
  } catch (error: any) {
    console.error('Error fetching linked responses:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a shared path response (or return existing if already exists)
 */
export async function createSharedPathResponse(
  versionPathId: string,
  statusCode: string,
  description?: string,
  data?: Record<string, any>
): Promise<string> {
  // Check if response already exists
  const checkQuery = `
    SELECT id, version_path_id, status_code, description, data, created_at, updated_at
    FROM odb.shared_path_response
    WHERE version_path_id = $1 AND status_code = $2
  `;

  try {
    const checkResult = await connectionPool.query(checkQuery, [versionPathId, statusCode]);

    if (checkResult.rows.length > 0) {
      return JSON.stringify({ success: true, response: checkResult.rows[0], existed: true });
    }

    // Create new response
    const insertQuery = `
      INSERT INTO odb.shared_path_response 
      (version_path_id, status_code, description, data)
      VALUES ($1, $2, $3, $4)
      RETURNING id, version_path_id, status_code, description, data, created_at, updated_at
    `;

    const result = await connectionPool.query(insertQuery, [
      versionPathId,
      statusCode,
      description || null,
      data ? JSON.stringify(data) : null,
    ]);

    return JSON.stringify({ success: true, response: result.rows[0], existed: false });
  } catch (error: any) {
    console.error('Error creating shared response:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Link a shared response to an operation
 */
export async function linkResponseToOperation(
  operationId: string,
  sharedResponseId: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    INSERT INTO odb.path_operation_response_link 
    (path_operation_id, shared_path_response_id, metadata)
    VALUES ($1, $2, $3)
    ON CONFLICT (path_operation_id, shared_path_response_id) 
    DO UPDATE SET metadata = EXCLUDED.metadata
    RETURNING id, path_operation_id, shared_path_response_id, metadata
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      sharedResponseId,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify({ success: true, link: result.rows[0] });
  } catch (error: any) {
    console.error('Error linking response to operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Unlink a response from an operation
 */
export async function unlinkResponseFromOperation(
  operationId: string,
  sharedResponseId: string
): Promise<string> {
  const query = `
    DELETE FROM odb.path_operation_response_link 
    WHERE path_operation_id = $1 AND shared_path_response_id = $2
  `;

  try {
    const result = await connectionPool.query(query, [operationId, sharedResponseId]);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Link not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error unlinking response from operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a shared path response
 */
export async function updateSharedPathResponse(
  responseId: string,
  updates: {
    statusCode?: string;
    description?: string;
    data?: Record<string, any>;
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
  if (updates.data !== undefined) {
    setClauses.push(`data = $${++paramIndex}`);
    params.push(JSON.stringify(updates.data));
  }

  const query = `
    UPDATE odb.shared_path_response
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, version_path_id, status_code, description, data, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Response not found' });
    }
    return JSON.stringify({ success: true, response: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating shared response:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a shared path response (only if not linked to any operations)
 */
export async function deleteSharedPathResponse(responseId: string): Promise<string> {
  // Check if response is linked to any operations
  const checkQuery = `
    SELECT COUNT(*) as link_count
    FROM odb.path_operation_response_link
    WHERE shared_path_response_id = $1
  `;

  try {
    const checkResult = await connectionPool.query(checkQuery, [responseId]);
    const linkCount = parseInt(checkResult.rows[0].link_count);

    if (linkCount > 0) {
      return JSON.stringify({
        success: false,
        error: `Cannot delete response: it is linked to ${linkCount} operation(s). Unlink it first.`
      });
    }

    const query = 'DELETE FROM odb.shared_path_response WHERE id = $1';
    const result = await connectionPool.query(query, [responseId]);

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Response not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting shared response:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

