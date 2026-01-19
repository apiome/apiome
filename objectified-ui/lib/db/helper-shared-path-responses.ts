'use server';

// Helper functions for shared path response management

const connectionPool = require('./db');

/**
 * Get all shared responses for a version path
 */
export async function getSharedPathResponses(versionPathId: string): Promise<string> {
  const query = `
    SELECT 
      spr.id,
      spr.version_path_id,
      spr.status_code,
      spr.description,
      spr.data,
      spr.class_id,
      c.name as class_name,
      spr.inline_schema,
      spr.schema_mode,
      spr.created_at,
      spr.updated_at,
      COALESCE(
        json_agg(
          json_build_object(
            'id', rc.id,
            'media_type', rc.media_type,
            'class_id', rc.class_id,
            'class_name', rc_class.name,
            'inline_schema', rc.inline_schema,
            'examples', rc.examples
          )
        ) FILTER (WHERE rc.id IS NOT NULL),
        '[]'
      ) as content_types
    FROM odb.shared_path_response spr
    LEFT JOIN odb.classes c ON spr.class_id = c.id
    LEFT JOIN odb.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
    LEFT JOIN odb.classes rc_class ON rc.class_id = rc_class.id
    WHERE spr.version_path_id = $1
    GROUP BY spr.id, spr.version_path_id, spr.status_code, spr.description, spr.data,
             spr.class_id, c.name, spr.inline_schema, spr.schema_mode, spr.created_at, spr.updated_at
    ORDER BY spr.status_code ASC
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
 * Get linked responses for an operation with content types
 */
export async function getLinkedResponsesForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      spr.id,
      spr.version_path_id,
      spr.status_code,
      spr.description,
      spr.data,
      spr.class_id,
      c.name as class_name,
      spr.inline_schema,
      spr.schema_mode,
      spr.created_at,
      spr.updated_at,
      porl.metadata as link_metadata,
      COALESCE(
        json_agg(
          json_build_object(
            'id', rc.id,
            'media_type', rc.media_type,
            'class_id', rc.class_id,
            'class_name', rc_class.name,
            'inline_schema', rc.inline_schema,
            'examples', rc.examples
          )
        ) FILTER (WHERE rc.id IS NOT NULL),
        '[]'
      ) as content_types
    FROM odb.shared_path_response spr
    JOIN odb.path_operation_response_link porl ON spr.id = porl.shared_path_response_id
    LEFT JOIN odb.classes c ON spr.class_id = c.id
    LEFT JOIN odb.shared_path_response_content rc ON spr.id = rc.shared_path_response_id
    LEFT JOIN odb.classes rc_class ON rc.class_id = rc_class.id
    WHERE porl.path_operation_id = $1
    GROUP BY spr.id, spr.version_path_id, spr.status_code, spr.description, spr.data, 
             spr.class_id, c.name, spr.inline_schema, spr.schema_mode, spr.created_at, spr.updated_at, porl.metadata
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
    SELECT id, version_path_id, status_code, description, data, inline_schema, class_id, schema_mode, created_at, updated_at
    FROM odb.shared_path_response
    WHERE version_path_id = $1 AND status_code = $2
  `;

  try {
    const checkResult = await connectionPool.query(checkQuery, [versionPathId, statusCode]);

    if (checkResult.rows.length > 0) {
      return JSON.stringify({ success: true, response: checkResult.rows[0], existed: true });
    }

    // Determine schema_mode based on data
    let schemaMode = 'object'; // default
    if (data) {
      const dataType = data.type;
      if (dataType === 'array') {
        schemaMode = 'array';
      } else if (['string', 'number', 'integer', 'boolean', 'null'].includes(dataType)) {
        schemaMode = 'primitive';
      } else if (dataType === 'object' || data.properties) {
        schemaMode = 'object';
      }
    }

    // Create new response
    // The constraint requires at least one of: class_id, inline_schema, or data
    // If no data is provided, create with an empty inline schema
    const insertQuery = `
      INSERT INTO odb.shared_path_response 
      (version_path_id, status_code, description, data, inline_schema, schema_mode)
      VALUES ($1, $2, $3, $4, $5, $6)
      RETURNING id, version_path_id, status_code, description, data, inline_schema, class_id, schema_mode, created_at, updated_at
    `;

    // Use data if provided, otherwise use empty inline_schema to satisfy constraint
    const hasData = data && Object.keys(data).length > 0;
    const inlineSchema = hasData ? null : JSON.stringify({ type: 'object', properties: [] });

    const result = await connectionPool.query(insertQuery, [
      versionPathId,
      statusCode,
      description || null,
      hasData ? JSON.stringify(data) : null,
      inlineSchema,
      schemaMode,
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
    data?: Record<string, any> | null;
    inlineSchema?: Record<string, any> | null;
    schemaMode?: 'class' | 'object' | 'primitive' | 'array';
    classId?: string | null;
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
  if (updates.schemaMode !== undefined) {
    setClauses.push(`schema_mode = $${++paramIndex}`);
    params.push(updates.schemaMode);
  }
  if (updates.classId !== undefined) {
    setClauses.push(`class_id = $${++paramIndex}`);
    params.push(updates.classId);
  }
  if (updates.data !== undefined) {
    setClauses.push(`data = $${++paramIndex}::jsonb`);
    // For JSONB columns, PostgreSQL expects a JSON string
    // If data is null, we want to set it to NULL, otherwise stringify it
    let dataValue: string | null = null;
    if (updates.data !== null) {
      if (typeof updates.data === 'string') {
        // Already a string, use it directly (but validate it's valid JSON)
        try {
          JSON.parse(updates.data);
          dataValue = updates.data;
        } catch (e) {
          // Invalid JSON string, stringify the original object
          dataValue = JSON.stringify(updates.data);
        }
      } else {
        // Object, stringify it
        dataValue = JSON.stringify(updates.data);
      }
    }
    params.push(dataValue);
  }
  if (updates.inlineSchema !== undefined) {
    setClauses.push(`inline_schema = $${++paramIndex}::jsonb`);
    params.push(updates.inlineSchema ? JSON.stringify(updates.inlineSchema) : null);
  }

  const query = `
    UPDATE odb.shared_path_response
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, version_path_id, status_code, description, data, inline_schema, class_id, schema_mode, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Response not found' });
    }
    
    const response = result.rows[0];
    // Ensure data is properly parsed if it's a string
    if (response.data && typeof response.data === 'string') {
      try {
        response.data = JSON.parse(response.data);
      } catch (e) {
        // If it's already an object, leave it as is
      }
    }
    // Ensure inline_schema is properly parsed if it's a string
    if (response.inline_schema && typeof response.inline_schema === 'string') {
      try {
        response.inline_schema = JSON.parse(response.inline_schema);
      } catch (e) {
        // If it's already an object, leave it as is
      }
    }

    return JSON.stringify({ success: true, response });
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

