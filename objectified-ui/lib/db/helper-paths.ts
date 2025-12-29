'use server';

const connectionPool = require('./db');

// Helper to standardize error responses
const errorResponse = (error: string) => JSON.stringify({ success: false, error });
const successResponse = (data: any = {}) => JSON.stringify({ success: true, ...data });

// ============================================================================
// API PATHS MANAGEMENT
// Functions for managing API paths (OpenAPI path items)
// ============================================================================

/**
 * Get all API paths for a version
 */
export async function getApiPathsForVersion(versionId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT * FROM odb.api_paths 
       WHERE version_id = $1 AND deleted_at IS NULL 
       ORDER BY sort_order ASC, path ASC`,
      [versionId]
    );
    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching API paths:', error);
    return JSON.stringify([]);
  }
}

/**
 * Get a single API path by ID
 */
export async function getApiPathById(pathId: string) {
  try {
    const result = await connectionPool.query(
      'SELECT * FROM odb.api_paths WHERE id = $1 AND deleted_at IS NULL',
      [pathId]
    );
    return JSON.stringify(result.rows[0] || null);
  } catch (error: any) {
    console.error('Error fetching API path:', error);
    return JSON.stringify(null);
  }
}

/**
 * Create a new API path
 */
export async function createApiPath(
  versionId: string,
  path: string,
  summary?: string,
  description?: string,
  servers?: any,
  parameters?: any,
  sortOrder?: number
) {
  try {
    if (!path?.trim()) {
      return errorResponse('Path cannot be empty');
    }

    // Check for duplicate path
    const existing = await connectionPool.query(
      'SELECT id FROM odb.api_paths WHERE version_id = $1 AND path = $2 AND deleted_at IS NULL',
      [versionId, path.trim()]
    );
    if (existing.rowCount > 0) {
      return errorResponse('A path with this pattern already exists in this version');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.api_paths 
       (version_id, path, summary, description, servers, parameters, sort_order) 
       VALUES ($1, $2, $3, $4, $5, $6, $7) 
       RETURNING *`,
      [
        versionId,
        path.trim(),
        summary?.trim() || null,
        description?.trim() || null,
        servers ? JSON.stringify(servers) : null,
        parameters ? JSON.stringify(parameters) : null,
        sortOrder || 0
      ]
    );
    return successResponse({ path: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating API path:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update an existing API path
 */
export async function updateApiPath(
  pathId: string,
  updates: {
    path?: string;
    summary?: string;
    description?: string;
    servers?: any;
    parameters?: any;
    sortOrder?: number;
    enabled?: boolean;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.path !== undefined) {
      if (!updates.path.trim()) {
        return errorResponse('Path cannot be empty');
      }
      fields.push(`path = $${paramIndex++}`);
      values.push(updates.path.trim());
    }
    if (updates.summary !== undefined) {
      fields.push(`summary = $${paramIndex++}`);
      values.push(updates.summary?.trim() || null);
    }
    if (updates.description !== undefined) {
      fields.push(`description = $${paramIndex++}`);
      values.push(updates.description?.trim() || null);
    }
    if (updates.servers !== undefined) {
      fields.push(`servers = $${paramIndex++}`);
      values.push(updates.servers ? JSON.stringify(updates.servers) : null);
    }
    if (updates.parameters !== undefined) {
      fields.push(`parameters = $${paramIndex++}`);
      values.push(updates.parameters ? JSON.stringify(updates.parameters) : null);
    }
    if (updates.sortOrder !== undefined) {
      fields.push(`sort_order = $${paramIndex++}`);
      values.push(updates.sortOrder);
    }
    if (updates.enabled !== undefined) {
      fields.push(`enabled = $${paramIndex++}`);
      values.push(updates.enabled);
    }

    if (fields.length === 0) {
      return errorResponse('No fields to update');
    }

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(pathId);

    const result = await connectionPool.query(
      `UPDATE odb.api_paths SET ${fields.join(', ')} WHERE id = $${paramIndex} AND deleted_at IS NULL RETURNING *`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('API path not found');
    }

    return successResponse({ path: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating API path:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete an API path (soft delete)
 */
export async function deleteApiPath(pathId: string) {
  try {
    const result = await connectionPool.query(
      'UPDATE odb.api_paths SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1 AND deleted_at IS NULL RETURNING id',
      [pathId]
    );
    if (result.rowCount === 0) {
      return errorResponse('API path not found');
    }
    return successResponse();
  } catch (error: any) {
    console.error('Error deleting API path:', error);
    return errorResponse(error.message);
  }
}

// ============================================================================
// PATH OPERATIONS MANAGEMENT
// Functions for managing HTTP operations on paths
// ============================================================================

/**
 * Get all operations for a path
 */
export async function getOperationsForPath(pathId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT * FROM odb.path_operations 
       WHERE path_id = $1 AND deleted_at IS NULL 
       ORDER BY 
         CASE method 
           WHEN 'get' THEN 1 
           WHEN 'post' THEN 2 
           WHEN 'put' THEN 3 
           WHEN 'patch' THEN 4 
           WHEN 'delete' THEN 5 
           WHEN 'options' THEN 6 
           WHEN 'head' THEN 7 
           WHEN 'trace' THEN 8 
         END`,
      [pathId]
    );
    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching path operations:', error);
    return JSON.stringify([]);
  }
}

/**
 * Get a single operation by ID
 */
export async function getOperationById(operationId: string) {
  try {
    const result = await connectionPool.query(
      'SELECT * FROM odb.path_operations WHERE id = $1 AND deleted_at IS NULL',
      [operationId]
    );
    return JSON.stringify(result.rows[0] || null);
  } catch (error: any) {
    console.error('Error fetching operation:', error);
    return JSON.stringify(null);
  }
}

/**
 * Create a new operation for a path
 */
export async function createPathOperation(
  pathId: string,
  method: string,
  operationId?: string,
  summary?: string,
  description?: string,
  externalDocs?: any,
  deprecated?: boolean,
  servers?: any
) {
  try {
    const validMethods = ['get', 'post', 'put', 'delete', 'patch', 'options', 'head', 'trace'];
    const normalizedMethod = method.toLowerCase();

    if (!validMethods.includes(normalizedMethod)) {
      return errorResponse('Invalid HTTP method');
    }

    // Check for duplicate method on this path
    const existing = await connectionPool.query(
      'SELECT id FROM odb.path_operations WHERE path_id = $1 AND method = $2 AND deleted_at IS NULL',
      [pathId, normalizedMethod]
    );
    if (existing.rowCount > 0) {
      return errorResponse('An operation with this method already exists for this path');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.path_operations 
       (path_id, method, operation_id, summary, description, external_docs, deprecated, servers) 
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8) 
       RETURNING *`,
      [
        pathId,
        normalizedMethod,
        operationId?.trim() || null,
        summary?.trim() || null,
        description?.trim() || null,
        externalDocs ? JSON.stringify(externalDocs) : null,
        deprecated || false,
        servers ? JSON.stringify(servers) : null
      ]
    );
    return successResponse({ operation: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating path operation:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update an existing operation
 */
export async function updatePathOperation(
  operationId: string,
  updates: {
    operationId?: string;
    summary?: string;
    description?: string;
    externalDocs?: any;
    deprecated?: boolean;
    deprecationMessage?: string;
    servers?: any;
    enabled?: boolean;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.operationId !== undefined) {
      fields.push(`operation_id = $${paramIndex++}`);
      values.push(updates.operationId?.trim() || null);
    }
    if (updates.summary !== undefined) {
      fields.push(`summary = $${paramIndex++}`);
      values.push(updates.summary?.trim() || null);
    }
    if (updates.description !== undefined) {
      fields.push(`description = $${paramIndex++}`);
      values.push(updates.description?.trim() || null);
    }
    if (updates.externalDocs !== undefined) {
      fields.push(`external_docs = $${paramIndex++}`);
      values.push(updates.externalDocs ? JSON.stringify(updates.externalDocs) : null);
    }
    if (updates.deprecated !== undefined) {
      fields.push(`deprecated = $${paramIndex++}`);
      values.push(updates.deprecated);
    }
    if (updates.deprecationMessage !== undefined) {
      fields.push(`deprecation_message = $${paramIndex++}`);
      values.push(updates.deprecationMessage?.trim() || null);
    }
    if (updates.servers !== undefined) {
      fields.push(`servers = $${paramIndex++}`);
      values.push(updates.servers ? JSON.stringify(updates.servers) : null);
    }
    if (updates.enabled !== undefined) {
      fields.push(`enabled = $${paramIndex++}`);
      values.push(updates.enabled);
    }

    if (fields.length === 0) {
      return errorResponse('No fields to update');
    }

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(operationId);

    const result = await connectionPool.query(
      `UPDATE odb.path_operations SET ${fields.join(', ')} WHERE id = $${paramIndex} AND deleted_at IS NULL RETURNING *`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('Operation not found');
    }

    return successResponse({ operation: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating operation:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete an operation (soft delete)
 */
export async function deletePathOperation(operationId: string) {
  try {
    const result = await connectionPool.query(
      'UPDATE odb.path_operations SET deleted_at = CURRENT_TIMESTAMP WHERE id = $1 AND deleted_at IS NULL RETURNING id',
      [operationId]
    );
    if (result.rowCount === 0) {
      return errorResponse('Operation not found');
    }
    return successResponse();
  } catch (error: any) {
    console.error('Error deleting operation:', error);
    return errorResponse(error.message);
  }
}

// ============================================================================
// OPERATION PARAMETERS MANAGEMENT
// Functions for managing operation parameters
// ============================================================================

/**
 * Get all parameters for an operation
 */
export async function getParametersForOperation(operationId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT * FROM odb.operation_parameters 
       WHERE operation_id = $1 
       ORDER BY location ASC, sort_order ASC, name ASC`,
      [operationId]
    );
    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching operation parameters:', error);
    return JSON.stringify([]);
  }
}

/**
 * Create a new parameter for an operation
 */
export async function createOperationParameter(
  operationId: string,
  name: string,
  location: string,
  description?: string,
  required?: boolean,
  deprecated?: boolean,
  schemaClassId?: string,
  schemaInline?: any,
  example?: any,
  sortOrder?: number
) {
  try {
    const validLocations = ['path', 'query', 'header', 'cookie'];
    if (!validLocations.includes(location.toLowerCase())) {
      return errorResponse('Invalid parameter location');
    }

    if (!name?.trim()) {
      return errorResponse('Parameter name cannot be empty');
    }

    // Check for duplicate parameter
    const existing = await connectionPool.query(
      'SELECT id FROM odb.operation_parameters WHERE operation_id = $1 AND name = $2 AND location = $3',
      [operationId, name.trim(), location.toLowerCase()]
    );
    if (existing.rowCount > 0) {
      return errorResponse('A parameter with this name and location already exists');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.operation_parameters 
       (operation_id, name, location, description, required, deprecated, schema_class_id, schema_inline, example, sort_order) 
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10) 
       RETURNING *`,
      [
        operationId,
        name.trim(),
        location.toLowerCase(),
        description?.trim() || null,
        required || false,
        deprecated || false,
        schemaClassId || null,
        schemaInline ? JSON.stringify(schemaInline) : null,
        example ? JSON.stringify(example) : null,
        sortOrder || 0
      ]
    );
    return successResponse({ parameter: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating operation parameter:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update an existing parameter
 */
export async function updateOperationParameter(
  parameterId: string,
  updates: {
    name?: string;
    description?: string;
    required?: boolean;
    deprecated?: boolean;
    schemaClassId?: string | null;
    schemaInline?: any;
    example?: any;
    sortOrder?: number;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.name !== undefined) {
      if (!updates.name.trim()) {
        return errorResponse('Parameter name cannot be empty');
      }
      fields.push(`name = $${paramIndex++}`);
      values.push(updates.name.trim());
    }
    if (updates.description !== undefined) {
      fields.push(`description = $${paramIndex++}`);
      values.push(updates.description?.trim() || null);
    }
    if (updates.required !== undefined) {
      fields.push(`required = $${paramIndex++}`);
      values.push(updates.required);
    }
    if (updates.deprecated !== undefined) {
      fields.push(`deprecated = $${paramIndex++}`);
      values.push(updates.deprecated);
    }
    if (updates.schemaClassId !== undefined) {
      fields.push(`schema_class_id = $${paramIndex++}`);
      values.push(updates.schemaClassId);
    }
    if (updates.schemaInline !== undefined) {
      fields.push(`schema_inline = $${paramIndex++}`);
      values.push(updates.schemaInline ? JSON.stringify(updates.schemaInline) : null);
    }
    if (updates.example !== undefined) {
      fields.push(`example = $${paramIndex++}`);
      values.push(updates.example ? JSON.stringify(updates.example) : null);
    }
    if (updates.sortOrder !== undefined) {
      fields.push(`sort_order = $${paramIndex++}`);
      values.push(updates.sortOrder);
    }

    if (fields.length === 0) {
      return errorResponse('No fields to update');
    }

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(parameterId);

    const result = await connectionPool.query(
      `UPDATE odb.operation_parameters SET ${fields.join(', ')} WHERE id = $${paramIndex} RETURNING *`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('Parameter not found');
    }

    return successResponse({ parameter: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating operation parameter:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a parameter
 */
export async function deleteOperationParameter(parameterId: string) {
  try {
    const result = await connectionPool.query(
      'DELETE FROM odb.operation_parameters WHERE id = $1 RETURNING id',
      [parameterId]
    );
    if (result.rowCount === 0) {
      return errorResponse('Parameter not found');
    }
    return successResponse();
  } catch (error: any) {
    console.error('Error deleting operation parameter:', error);
    return errorResponse(error.message);
  }
}

// ============================================================================
// OPERATION RESPONSES MANAGEMENT
// Functions for managing operation responses
// ============================================================================

/**
 * Get all responses for an operation
 */
export async function getResponsesForOperation(operationId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT * FROM odb.operation_responses 
       WHERE operation_id = $1 
       ORDER BY sort_order ASC, status_code ASC`,
      [operationId]
    );
    return JSON.stringify(result.rows);
  } catch (error: any) {
    console.error('Error fetching operation responses:', error);
    return JSON.stringify([]);
  }
}

/**
 * Create a new response for an operation
 */
export async function createOperationResponse(
  operationId: string,
  statusCode: string,
  description: string,
  headers?: any,
  content?: any,
  schemaClassId?: string,
  links?: any,
  sortOrder?: number
) {
  try {
    if (!statusCode?.trim()) {
      return errorResponse('Status code cannot be empty');
    }

    if (!description?.trim()) {
      return errorResponse('Response description cannot be empty');
    }

    // Check for duplicate status code
    const existing = await connectionPool.query(
      'SELECT id FROM odb.operation_responses WHERE operation_id = $1 AND status_code = $2',
      [operationId, statusCode.trim()]
    );
    if (existing.rowCount > 0) {
      return errorResponse('A response with this status code already exists');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.operation_responses 
       (operation_id, status_code, description, headers, content, schema_class_id, links, sort_order) 
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8) 
       RETURNING *`,
      [
        operationId,
        statusCode.trim(),
        description.trim(),
        headers ? JSON.stringify(headers) : null,
        content ? JSON.stringify(content) : null,
        schemaClassId || null,
        links ? JSON.stringify(links) : null,
        sortOrder || 0
      ]
    );
    return successResponse({ response: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating operation response:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update an existing response
 */
export async function updateOperationResponse(
  responseId: string,
  updates: {
    statusCode?: string;
    description?: string;
    headers?: any;
    content?: any;
    schemaClassId?: string | null;
    links?: any;
    sortOrder?: number;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.statusCode !== undefined) {
      if (!updates.statusCode.trim()) {
        return errorResponse('Status code cannot be empty');
      }
      fields.push(`status_code = $${paramIndex++}`);
      values.push(updates.statusCode.trim());
    }
    if (updates.description !== undefined) {
      if (!updates.description.trim()) {
        return errorResponse('Response description cannot be empty');
      }
      fields.push(`description = $${paramIndex++}`);
      values.push(updates.description.trim());
    }
    if (updates.headers !== undefined) {
      fields.push(`headers = $${paramIndex++}`);
      values.push(updates.headers ? JSON.stringify(updates.headers) : null);
    }
    if (updates.content !== undefined) {
      fields.push(`content = $${paramIndex++}`);
      values.push(updates.content ? JSON.stringify(updates.content) : null);
    }
    if (updates.schemaClassId !== undefined) {
      fields.push(`schema_class_id = $${paramIndex++}`);
      values.push(updates.schemaClassId);
    }
    if (updates.links !== undefined) {
      fields.push(`links = $${paramIndex++}`);
      values.push(updates.links ? JSON.stringify(updates.links) : null);
    }
    if (updates.sortOrder !== undefined) {
      fields.push(`sort_order = $${paramIndex++}`);
      values.push(updates.sortOrder);
    }

    if (fields.length === 0) {
      return errorResponse('No fields to update');
    }

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(responseId);

    const result = await connectionPool.query(
      `UPDATE odb.operation_responses SET ${fields.join(', ')} WHERE id = $${paramIndex} RETURNING *`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('Response not found');
    }

    return successResponse({ response: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating operation response:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a response
 */
export async function deleteOperationResponse(responseId: string) {
  try {
    const result = await connectionPool.query(
      'DELETE FROM odb.operation_responses WHERE id = $1 RETURNING id',
      [responseId]
    );
    if (result.rowCount === 0) {
      return errorResponse('Response not found');
    }
    return successResponse();
  } catch (error: any) {
    console.error('Error deleting operation response:', error);
    return errorResponse(error.message);
  }
}

// ============================================================================
// OPERATION REQUEST BODY MANAGEMENT
// Functions for managing operation request bodies
// ============================================================================

/**
 * Get request body for an operation
 */
export async function getRequestBodyForOperation(operationId: string) {
  try {
    const result = await connectionPool.query(
      `SELECT rb.*, 
              json_agg(
                json_build_object(
                  'id', rbc.id,
                  'content_type', rbc.content_type,
                  'schema_class_id', rbc.schema_class_id,
                  'schema_inline', rbc.schema_inline,
                  'example', rbc.example,
                  'examples', rbc.examples,
                  'encoding', rbc.encoding
                )
              ) FILTER (WHERE rbc.id IS NOT NULL) as content_types
       FROM odb.operation_request_bodies rb
       LEFT JOIN odb.operation_request_body_content rbc ON rb.id = rbc.request_body_id
       WHERE rb.operation_id = $1
       GROUP BY rb.id`,
      [operationId]
    );
    return JSON.stringify(result.rows[0] || null);
  } catch (error: any) {
    console.error('Error fetching request body:', error);
    return JSON.stringify(null);
  }
}

/**
 * Create a request body for an operation
 */
export async function createOperationRequestBody(
  operationId: string,
  description?: string,
  required?: boolean
) {
  try {
    // Check if request body already exists
    const existing = await connectionPool.query(
      'SELECT id FROM odb.operation_request_bodies WHERE operation_id = $1',
      [operationId]
    );
    if (existing.rowCount > 0) {
      return errorResponse('Request body already exists for this operation');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.operation_request_bodies 
       (operation_id, description, required) 
       VALUES ($1, $2, $3) 
       RETURNING *`,
      [operationId, description?.trim() || null, required || false]
    );
    return successResponse({ requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating request body:', error);
    return errorResponse(error.message);
  }
}

/**
 * Update a request body
 */
export async function updateOperationRequestBody(
  requestBodyId: string,
  updates: {
    description?: string;
    required?: boolean;
  }
) {
  try {
    const fields: string[] = [];
    const values: any[] = [];
    let paramIndex = 1;

    if (updates.description !== undefined) {
      fields.push(`description = $${paramIndex++}`);
      values.push(updates.description?.trim() || null);
    }
    if (updates.required !== undefined) {
      fields.push(`required = $${paramIndex++}`);
      values.push(updates.required);
    }

    if (fields.length === 0) {
      return errorResponse('No fields to update');
    }

    fields.push(`updated_at = CURRENT_TIMESTAMP`);
    values.push(requestBodyId);

    const result = await connectionPool.query(
      `UPDATE odb.operation_request_bodies SET ${fields.join(', ')} WHERE id = $${paramIndex} RETURNING *`,
      values
    );

    if (result.rowCount === 0) {
      return errorResponse('Request body not found');
    }

    return successResponse({ requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating request body:', error);
    return errorResponse(error.message);
  }
}

/**
 * Delete a request body
 */
export async function deleteOperationRequestBody(requestBodyId: string) {
  try {
    const result = await connectionPool.query(
      'DELETE FROM odb.operation_request_bodies WHERE id = $1 RETURNING id',
      [requestBodyId]
    );
    if (result.rowCount === 0) {
      return errorResponse('Request body not found');
    }
    return successResponse();
  } catch (error: any) {
    console.error('Error deleting request body:', error);
    return errorResponse(error.message);
  }
}

/**
 * Add content type to request body
 */
export async function addRequestBodyContentType(
  requestBodyId: string,
  contentType: string,
  schemaClassId?: string,
  schemaInline?: any,
  example?: any
) {
  try {
    if (!contentType?.trim()) {
      return errorResponse('Content type cannot be empty');
    }

    // Check for duplicate content type
    const existing = await connectionPool.query(
      'SELECT id FROM odb.operation_request_body_content WHERE request_body_id = $1 AND content_type = $2',
      [requestBodyId, contentType.trim()]
    );
    if (existing.rowCount > 0) {
      return errorResponse('This content type already exists for this request body');
    }

    const result = await connectionPool.query(
      `INSERT INTO odb.operation_request_body_content 
       (request_body_id, content_type, schema_class_id, schema_inline, example) 
       VALUES ($1, $2, $3, $4, $5) 
       RETURNING *`,
      [
        requestBodyId,
        contentType.trim(),
        schemaClassId || null,
        schemaInline ? JSON.stringify(schemaInline) : null,
        example ? JSON.stringify(example) : null
      ]
    );
    return successResponse({ content: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding request body content type:', error);
    return errorResponse(error.message);
  }
}

