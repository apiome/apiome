'use server';

// Helper functions for shared path request body management
// Request bodies can reference existing apiome.classes (class_id) or use inline schemas (inline_schema)

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

// =============================================================================
// SHARED REQUEST BODY CRUD
// =============================================================================

/**
 * Get all shared request bodies for a path
 * Includes content types with class names when class_id is set
 */
export async function getSharedPathRequestBodies(versionPathId: string): Promise<string> {
  const query = `
    SELECT 
      rb.id,
      rb.version_path_id,
      rb.name,
      rb.description,
      rb.required,
      rb.created_at,
      rb.updated_at,
      COALESCE(
        json_agg(
          json_build_object(
            'id', rbc.id,
            'media_type', rbc.media_type,
            'class_id', rbc.class_id,
            'class_name', c.name,
            'inline_schema', rbc.inline_schema,
            'encoding', rbc.encoding,
            'examples', rbc.examples
          )
        ) FILTER (WHERE rbc.id IS NOT NULL),
        '[]'
      ) as content_types
    FROM apiome.shared_path_request_body rb
    LEFT JOIN apiome.shared_path_request_body_content rbc 
      ON rb.id = rbc.shared_path_request_body_id
    LEFT JOIN apiome.classes c 
      ON rbc.class_id = c.id
    WHERE rb.version_path_id = $1
    GROUP BY rb.id
    ORDER BY rb.name ASC
  `;

  try {
    const result = await connectionPool.query(query, [versionPathId]);
    return JSON.stringify({ success: true, requestBodies: result.rows });
  } catch (error: any) {
    console.error('Error fetching shared path request bodies:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get a single shared request body by ID with full content type details
 */
export async function getSharedPathRequestBodyById(requestBodyId: string): Promise<string> {
  const query = `
    SELECT 
      rb.id,
      rb.version_path_id,
      rb.name,
      rb.description,
      rb.required,
      rb.created_at,
      rb.updated_at,
      COALESCE(
        json_agg(
          json_build_object(
            'id', rbc.id,
            'media_type', rbc.media_type,
            'class_id', rbc.class_id,
            'class_name', c.name,
            'inline_schema', rbc.inline_schema,
            'encoding', rbc.encoding,
            'examples', rbc.examples
          )
        ) FILTER (WHERE rbc.id IS NOT NULL),
        '[]'
      ) as content_types
    FROM apiome.shared_path_request_body rb
    LEFT JOIN apiome.shared_path_request_body_content rbc 
      ON rb.id = rbc.shared_path_request_body_id
    LEFT JOIN apiome.classes c 
      ON rbc.class_id = c.id
    WHERE rb.id = $1
    GROUP BY rb.id
  `;

  try {
    const result = await connectionPool.query(query, [requestBodyId]);
    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Request body not found' });
    }
    return JSON.stringify({ success: true, requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching shared path request body:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Create a shared request body
 */
export async function createSharedPathRequestBody(
  versionPathId: string,
  name: string,
  description?: string,
  required: boolean = true
): Promise<string> {
  const query = `
    INSERT INTO apiome.shared_path_request_body 
    (version_path_id, name, description, required)
    VALUES ($1, $2, $3, $4)
    RETURNING id, version_path_id, name, description, required, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, [
      versionPathId,
      name,
      description || null,
      required,
    ]);
    return JSON.stringify({ success: true, requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error creating shared path request body:', error);
    // Check for unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({
        success: false,
        error: `A request body named "${name}" already exists for this path`
      });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a shared request body
 */
export async function updateSharedPathRequestBody(
  requestBodyId: string,
  updates: {
    name?: string;
    description?: string;
    required?: boolean;
  }
): Promise<string> {
  const setClauses: string[] = ['updated_at = CURRENT_TIMESTAMP'];
  const params: any[] = [requestBodyId];
  let paramIndex = 1;

  if (updates.name !== undefined) {
    setClauses.push(`name = $${++paramIndex}`);
    params.push(updates.name);
  }
  if (updates.description !== undefined) {
    setClauses.push(`description = $${++paramIndex}`);
    params.push(updates.description);
  }
  if (updates.required !== undefined) {
    setClauses.push(`required = $${++paramIndex}`);
    params.push(updates.required);
  }

  const query = `
    UPDATE apiome.shared_path_request_body
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, version_path_id, name, description, required, created_at, updated_at
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Request body not found' });
    }
    return JSON.stringify({ success: true, requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating shared request body:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a shared request body (cascades to content types and links)
 */
export async function deleteSharedPathRequestBody(requestBodyId: string): Promise<string> {
  const query = 'DELETE FROM apiome.shared_path_request_body WHERE id = $1';

  try {
    const result = await connectionPool.query(query, [requestBodyId]);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Request body not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting shared request body:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// =============================================================================
// OPERATION LINK MANAGEMENT
// =============================================================================

/**
 * Link a request body to an operation
 * Note: Each operation can only have one request body (OpenAPI spec)
 */
export async function linkRequestBodyToOperation(
  operationId: string,
  requestBodyId: string,
  metadata?: Record<string, any>
): Promise<string> {
  const query = `
    INSERT INTO apiome.path_operation_request_body_link 
    (path_operation_id, shared_path_request_body_id, metadata)
    VALUES ($1, $2, $3)
    ON CONFLICT (path_operation_id) 
    DO UPDATE SET 
      shared_path_request_body_id = EXCLUDED.shared_path_request_body_id,
      metadata = EXCLUDED.metadata,
      updated_at = CURRENT_TIMESTAMP
    RETURNING id, path_operation_id, shared_path_request_body_id, metadata
  `;

  try {
    const result = await connectionPool.query(query, [
      operationId,
      requestBodyId,
      metadata ? JSON.stringify(metadata) : null,
    ]);
    return JSON.stringify({ success: true, link: result.rows[0] });
  } catch (error: any) {
    console.error('Error linking request body to operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Unlink a request body from an operation
 */
export async function unlinkRequestBodyFromOperation(operationId: string): Promise<string> {
  const query = `
    DELETE FROM apiome.path_operation_request_body_link
    WHERE path_operation_id = $1
  `;

  try {
    await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error unlinking request body from operation:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Lightweight existence check: returns true if the operation has any linked request body.
 * Uses SELECT 1 to avoid the heavy join/aggregate of getLinkedRequestBodyForOperation.
 */
export async function operationHasLinkedRequestBody(operationId: string): Promise<string> {
  const query = `
    SELECT 1
    FROM apiome.path_operation_request_body_link
    WHERE path_operation_id = $1
    LIMIT 1
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    return JSON.stringify({ success: true, linked: result.rows.length > 0 });
  } catch (error: any) {
    console.error('Error checking linked request body existence:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get the linked request body for an operation (with full details)
 */
export async function getLinkedRequestBodyForOperation(operationId: string): Promise<string> {
  const query = `
    SELECT 
      rb.id,
      rb.version_path_id,
      rb.name,
      rb.description,
      rb.required,
      link.metadata as link_metadata,
      link.id as link_id,
      rb.created_at,
      rb.updated_at,
      COALESCE(
        json_agg(
          json_build_object(
            'id', rbc.id,
            'media_type', rbc.media_type,
            'class_id', rbc.class_id,
            'class_name', c.name,
            'inline_schema', rbc.inline_schema,
            'encoding', rbc.encoding,
            'examples', rbc.examples
          )
        ) FILTER (WHERE rbc.id IS NOT NULL),
        '[]'
      ) as content_types
    FROM apiome.shared_path_request_body rb
    INNER JOIN apiome.path_operation_request_body_link link 
      ON rb.id = link.shared_path_request_body_id
    LEFT JOIN apiome.shared_path_request_body_content rbc 
      ON rb.id = rbc.shared_path_request_body_id
    LEFT JOIN apiome.classes c 
      ON rbc.class_id = c.id
    WHERE link.path_operation_id = $1
    GROUP BY rb.id, link.metadata, link.id
  `;

  try {
    const result = await connectionPool.query(query, [operationId]);
    if (result.rows.length === 0) {
      return JSON.stringify({ success: true, requestBody: null });
    }
    return JSON.stringify({ success: true, requestBody: result.rows[0] });
  } catch (error: any) {
    console.error('Error fetching linked request body:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Get all operations linked to a request body
 */
export async function getOperationsForRequestBody(requestBodyId: string): Promise<string> {
  const query = `
    SELECT 
      po.id,
      po.operation,
      vp.pathname,
      link.metadata as link_metadata,
      link.id as link_id
    FROM apiome.path_operation po
    INNER JOIN apiome.path_operation_request_body_link link 
      ON po.id = link.path_operation_id
    INNER JOIN apiome.version_path vp
      ON po.version_path_id = vp.id
    WHERE link.shared_path_request_body_id = $1
    ORDER BY po.operation
  `;

  try {
    const result = await connectionPool.query(query, [requestBodyId]);
    return JSON.stringify({ success: true, operations: result.rows });
  } catch (error: any) {
    console.error('Error fetching operations for request body:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// =============================================================================
// CONTENT TYPE MANAGEMENT
// =============================================================================

/**
 * Add a content type to a request body
 * Either classId or inlineSchema must be provided
 */
export async function addRequestBodyContentType(
  requestBodyId: string,
  mediaType: string,
  classId?: string,
  inlineSchema?: Record<string, any>,
  encoding?: Record<string, any>,
  examples?: any[]
): Promise<string> {
  // Validate that either classId or inlineSchema is provided
  if (!classId && !inlineSchema) {
    return JSON.stringify({
      success: false,
      error: 'Either classId or inlineSchema must be provided'
    });
  }

  const query = `
    INSERT INTO apiome.shared_path_request_body_content 
    (shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples)
    VALUES ($1, $2, $3, $4, $5, $6)
    RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples
  `;

  try {
    const result = await connectionPool.query(query, [
      requestBodyId,
      mediaType,
      classId || null,
      inlineSchema ? JSON.stringify(inlineSchema) : null,
      encoding ? JSON.stringify(encoding) : null,
      examples ? JSON.stringify(examples) : null,
    ]);
    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: any) {
    console.error('Error adding request body content type:', error);
    // Check for unique constraint violation
    if (error.code === '23505') {
      return JSON.stringify({
        success: false,
        error: `Content type "${mediaType}" already exists for this request body`
      });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a content type
 */
export async function updateRequestBodyContentType(
  contentId: string,
  updates: {
    mediaType?: string;
    classId?: string | null;
    inlineSchema?: Record<string, any> | null;
    encoding?: Record<string, any> | null;
    examples?: any[] | null;
  }
): Promise<string> {
  const setClauses: string[] = ['updated_at = CURRENT_TIMESTAMP'];
  const params: any[] = [contentId];
  let paramIndex = 1;

  if (updates.mediaType !== undefined) {
    setClauses.push(`media_type = $${++paramIndex}`);
    params.push(updates.mediaType);
  }
  if (updates.classId !== undefined) {
    setClauses.push(`class_id = $${++paramIndex}`);
    params.push(updates.classId);
  }
  if (updates.inlineSchema !== undefined) {
    setClauses.push(`inline_schema = $${++paramIndex}`);
    params.push(updates.inlineSchema ? JSON.stringify(updates.inlineSchema) : null);
  }
  if (updates.encoding !== undefined) {
    setClauses.push(`encoding = $${++paramIndex}`);
    params.push(updates.encoding ? JSON.stringify(updates.encoding) : null);
  }
  if (updates.examples !== undefined) {
    setClauses.push(`examples = $${++paramIndex}`);
    params.push(updates.examples ? JSON.stringify(updates.examples) : null);
  }

  const query = `
    UPDATE apiome.shared_path_request_body_content
    SET ${setClauses.join(', ')}
    WHERE id = $1
    RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples
  `;

  try {
    const result = await connectionPool.query(query, params);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }
    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: any) {
    console.error('Error updating request body content type:', error);
    if (error.code === '23505') {
      return JSON.stringify({
        success: false,
        error: 'A content type with this media type already exists for this request body',
      });
    }
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a content type
 */
export async function deleteRequestBodyContentType(contentId: string): Promise<string> {
  const query = 'DELETE FROM apiome.shared_path_request_body_content WHERE id = $1';

  try {
    const result = await connectionPool.query(query, [contentId]);
    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }
    return JSON.stringify({ success: true });
  } catch (error: any) {
    console.error('Error deleting request body content type:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// =============================================================================
// CLASS TO INLINE SCHEMA CONVERSION
// =============================================================================

/**
 * Convert a class reference to an inline schema
 * Copies all properties from apiome.class_properties into inline_schema.properties array
 * Sets class_id to NULL and populates inline_schema
 */
export async function convertClassToInlineSchema(contentId: string): Promise<string> {
  // First, get the content record with class_id
  const getContentQuery = `
    SELECT id, class_id, inline_schema
    FROM apiome.shared_path_request_body_content
    WHERE id = $1
  `;

  try {
    const contentResult = await connectionPool.query(getContentQuery, [contentId]);
    if (contentResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    const content = contentResult.rows[0];
    if (!content.class_id) {
      return JSON.stringify({
        success: false,
        error: 'Content type does not reference a class - already using inline schema'
      });
    }

    // Get the class details
    const getClassQuery = `
      SELECT id, name, description, schema
      FROM apiome.classes
      WHERE id = $1
    `;
    const classResult = await connectionPool.query(getClassQuery, [content.class_id]);
    if (classResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Referenced class not found' });
    }

    const classData = classResult.rows[0];

    // Get all properties for the class
    const getPropertiesQuery = `
      SELECT id, name, description, data, parent_id
      FROM apiome.class_properties
      WHERE class_id = $1
      ORDER BY name
    `;
    const propertiesResult = await connectionPool.query(getPropertiesQuery, [content.class_id]);

    // Build the inline schema with new UUIDs
    const uuidMapping: Record<string, string> = {}; // old_id -> new_id
    const properties = propertiesResult.rows.map((prop: any) => {
      const newId = crypto.randomUUID();
      uuidMapping[prop.id] = newId;
      return {
        id: newId,
        name: prop.name,
        description: prop.description,
        data: typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data,
        parent_id: null, // Will be updated in second pass
      };
    });

    // Second pass: update parent_id references
    properties.forEach((prop: any, index: number) => {
      const originalProp = propertiesResult.rows[index];
      if (originalProp.parent_id && uuidMapping[originalProp.parent_id]) {
        prop.parent_id = uuidMapping[originalProp.parent_id];
      }
    });

    // Parse class schema for additional metadata
    const classSchema = typeof classData.schema === 'string'
      ? JSON.parse(classData.schema)
      : (classData.schema || {});

    // Build the inline schema object
    const inlineSchema = {
      type: 'object',
      description: classData.description || undefined,
      properties: properties,
      // Preserve any composition patterns from the class schema
      ...(classSchema.allOf && { allOf: classSchema.allOf }),
      ...(classSchema.oneOf && { oneOf: classSchema.oneOf }),
      ...(classSchema.anyOf && { anyOf: classSchema.anyOf }),
    };

    // Update the content record: clear class_id, set inline_schema
    const updateQuery = `
      UPDATE apiome.shared_path_request_body_content
      SET class_id = NULL, inline_schema = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples
    `;

    const updateResult = await connectionPool.query(updateQuery, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);

    return JSON.stringify({
      success: true,
      content: updateResult.rows[0],
      message: `Converted ${properties.length} properties from class "${classData.name}" to inline schema`
    });
  } catch (error: any) {
    console.error('Error converting class to inline schema:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Copy class properties into a request body content type's inline schema (replace $ref or add to schema).
 * Sets class_id = NULL and populates inline_schema with copied properties.
 */
export async function copyClassPropertiesToRequestBodyContentType(
  contentId: string,
  classId: string
): Promise<string> {
  const getContentQuery = `
    SELECT id FROM apiome.shared_path_request_body_content WHERE id = $1
  `;
  const contentResult = await connectionPool.query(getContentQuery, [contentId]);
  if (contentResult.rows.length === 0) {
    return JSON.stringify({ success: false, error: 'Content type not found' });
  }

  const getClassQuery = `
    SELECT id, name, description FROM apiome.classes WHERE id = $1
  `;
  const classResult = await connectionPool.query(getClassQuery, [classId]);
  if (classResult.rows.length === 0) {
    return JSON.stringify({ success: false, error: 'Class not found' });
  }
  const classInfo = classResult.rows[0];

  const propsQuery = `
    SELECT id, name, description, data, parent_id
    FROM apiome.class_properties WHERE class_id = $1
    ORDER BY parent_id NULLS FIRST, name
  `;
  const propsResult = await connectionPool.query(propsQuery, [classId]);
  const idMap = new Map<string, string>();
  propsResult.rows.forEach((prop: any) => {
    idMap.set(prop.id, crypto.randomUUID());
  });

  const properties = propsResult.rows.map((prop: any) => {
    const newId = idMap.get(prop.id);
    const oldParentId = prop.parent_id;
    const newParentId = oldParentId && idMap.has(oldParentId) ? idMap.get(oldParentId) : null;
    return {
      id: newId,
      name: prop.name,
      description: prop.description || null,
      data: typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data,
      parent_id: newParentId || null,
    };
  });

  const inlineSchema = {
    type: 'object',
    description: classInfo.description || `Copied from class: ${classInfo.name}`,
    properties,
  };

  const updateQuery = `
    UPDATE apiome.shared_path_request_body_content
    SET class_id = NULL, inline_schema = $2, updated_at = CURRENT_TIMESTAMP
    WHERE id = $1
    RETURNING id, class_id, inline_schema
  `;
  try {
    const updateResult = await connectionPool.query(updateQuery, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);
    if (updateResult.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }
    return JSON.stringify({
      success: true,
      content: updateResult.rows[0],
      copiedProperties: properties.length,
      fromClass: classInfo.name,
    });
  } catch (error: any) {
    console.error('Error copying class properties to request body content:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

// =============================================================================
// INLINE SCHEMA PROPERTY MANAGEMENT
// =============================================================================

/**
 * Add a property to an inline schema
 */
export async function addPropertyToInlineSchema(
  contentId: string,
  propertyData: {
    name: string;
    description?: string;
    data: Record<string, any>;
  },
  parentId?: string
): Promise<string> {
  // Get current inline_schema and class_id (must be null to add properties – i.e. "copy" not "reference")
  const getQuery = `
    SELECT id, class_id, inline_schema
    FROM apiome.shared_path_request_body_content
    WHERE id = $1
  `;

  try {
    const result = await connectionPool.query(getQuery, [contentId]);
    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    const content = result.rows[0];
    if (content.class_id) {
      return JSON.stringify({
        success: false,
        error: 'Cannot add properties to class reference - convert to inline schema first'
      });
    }

    // Parse or initialize inline_schema
    let inlineSchema = content.inline_schema;
    if (typeof inlineSchema === 'string') {
      inlineSchema = JSON.parse(inlineSchema);
    }
    if (!inlineSchema) {
      inlineSchema = { type: 'object', properties: [] };
    }
    if (!Array.isArray(inlineSchema.properties)) {
      // Normalize: properties may be an object (OpenAPI-style) from import or legacy data
      if (inlineSchema.properties && typeof inlineSchema.properties === 'object') {
        inlineSchema.properties = Object.entries(inlineSchema.properties).map(([name, data]: [string, any]) => ({
          id: crypto.randomUUID(),
          name,
          description: data?.description ?? null,
          data: typeof data === 'object' && data !== null ? data : { type: 'string' },
          parent_id: null,
        }));
      } else {
        inlineSchema.properties = [];
      }
    }

    // Check for duplicate property name at the same level
    const existingProp = inlineSchema.properties.find(
      (p: any) => p.name === propertyData.name && p.parent_id === (parentId || null)
    );
    if (existingProp) {
      return JSON.stringify({
        success: false,
        error: `Property "${propertyData.name}" already exists at this level`
      });
    }

    // Create new property with UUID
    const newProperty = {
      id: crypto.randomUUID(),
      name: propertyData.name,
      description: propertyData.description || null,
      data: propertyData.data,
      parent_id: parentId || null,
    };

    inlineSchema.properties.push(newProperty);

    // Update the content record
    const updateQuery = `
      UPDATE apiome.shared_path_request_body_content
      SET inline_schema = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING id, inline_schema
    `;

    const updateResult = await connectionPool.query(updateQuery, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);

    return JSON.stringify({
      success: true,
      property: newProperty,
      inline_schema: updateResult.rows[0].inline_schema
    });
  } catch (error: any) {
    console.error('Error adding property to inline schema:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Update a property in an inline schema
 */
export async function updateInlineSchemaProperty(
  contentId: string,
  propertyId: string,
  updates: {
    name?: string;
    description?: string;
    data?: Record<string, any>;
  }
): Promise<string> {
  // Get current inline_schema
  const getQuery = `
    SELECT id, inline_schema
    FROM apiome.shared_path_request_body_content
    WHERE id = $1
  `;

  try {
    const result = await connectionPool.query(getQuery, [contentId]);
    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    let inlineSchema = result.rows[0].inline_schema;
    if (typeof inlineSchema === 'string') {
      inlineSchema = JSON.parse(inlineSchema);
    }
    if (!inlineSchema || !inlineSchema.properties) {
      return JSON.stringify({ success: false, error: 'No inline schema properties found' });
    }
    if (!Array.isArray(inlineSchema.properties)) {
      return JSON.stringify({
        success: false,
        error: 'Inline schema properties are in an unexpected format. Use "Add property" on the request body to normalize the schema first.',
      });
    }

    // Find and update the property
    const propertyIndex = inlineSchema.properties.findIndex((p: any) => p.id === propertyId);
    if (propertyIndex === -1) {
      return JSON.stringify({ success: false, error: 'Property not found' });
    }

    const property = inlineSchema.properties[propertyIndex];

    // Check for duplicate name if name is being changed
    if (updates.name && updates.name !== property.name) {
      const duplicate = inlineSchema.properties.find(
        (p: any) => p.name === updates.name && p.parent_id === property.parent_id && p.id !== propertyId
      );
      if (duplicate) {
        return JSON.stringify({
          success: false,
          error: `Property "${updates.name}" already exists at this level`
        });
      }
    }

    // Apply updates
    if (updates.name !== undefined) property.name = updates.name;
    if (updates.description !== undefined) property.description = updates.description;
    if (updates.data !== undefined) property.data = updates.data;

    inlineSchema.properties[propertyIndex] = property;

    // Update the content record
    const updateQuery = `
      UPDATE apiome.shared_path_request_body_content
      SET inline_schema = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING id, inline_schema
    `;

    const updateResult = await connectionPool.query(updateQuery, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);

    return JSON.stringify({
      success: true,
      property: property,
      inline_schema: updateResult.rows[0].inline_schema
    });
  } catch (error: any) {
    console.error('Error updating inline schema property:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Delete a property from an inline schema (with optional cascade to children)
 */
export async function deleteInlineSchemaProperty(
  contentId: string,
  propertyId: string,
  cascadeChildren: boolean = true
): Promise<string> {
  // Get current inline_schema
  const getQuery = `
    SELECT id, inline_schema
    FROM apiome.shared_path_request_body_content
    WHERE id = $1
  `;

  try {
    const result = await connectionPool.query(getQuery, [contentId]);
    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    let inlineSchema = result.rows[0].inline_schema;
    if (typeof inlineSchema === 'string') {
      inlineSchema = JSON.parse(inlineSchema);
    }
    if (!inlineSchema || !inlineSchema.properties) {
      return JSON.stringify({ success: false, error: 'No inline schema properties found' });
    }
    if (!Array.isArray(inlineSchema.properties)) {
      return JSON.stringify({
        success: false,
        error: 'Inline schema properties are in an unexpected format. Use "Add property" on the request body to normalize the schema first.',
      });
    }

    // Find all properties to delete (the target and optionally its children)
    const propertiesToDelete = new Set<string>([propertyId]);

    if (cascadeChildren) {
      // Recursively find all children
      let foundMore = true;
      while (foundMore) {
        foundMore = false;
        for (const prop of inlineSchema.properties) {
          if (prop.parent_id && propertiesToDelete.has(prop.parent_id) && !propertiesToDelete.has(prop.id)) {
            propertiesToDelete.add(prop.id);
            foundMore = true;
          }
        }
      }
    }

    // Remove properties
    const originalCount = inlineSchema.properties.length;
    inlineSchema.properties = inlineSchema.properties.filter(
      (p: any) => !propertiesToDelete.has(p.id)
    );
    const deletedCount = originalCount - inlineSchema.properties.length;

    if (deletedCount === 0) {
      return JSON.stringify({ success: false, error: 'Property not found' });
    }

    // Update the content record
    const updateQuery = `
      UPDATE apiome.shared_path_request_body_content
      SET inline_schema = $2, updated_at = CURRENT_TIMESTAMP
      WHERE id = $1
      RETURNING id, inline_schema
    `;

    const updateResult = await connectionPool.query(updateQuery, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);

    return JSON.stringify({
      success: true,
      deletedCount: deletedCount,
      inline_schema: updateResult.rows[0].inline_schema
    });
  } catch (error: any) {
    console.error('Error deleting inline schema property:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Initialize an empty inline schema for a content type
 * Useful when switching from class reference to inline mode
 */
export async function initializeInlineSchema(
  contentId: string,
  description?: string
): Promise<string> {
  const inlineSchema = {
    type: 'object',
    description: description || undefined,
    properties: [],
  };

  const query = `
    UPDATE apiome.shared_path_request_body_content
    SET class_id = NULL, inline_schema = $2, updated_at = CURRENT_TIMESTAMP
    WHERE id = $1
    RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples
  `;

  try {
    const result = await connectionPool.query(query, [
      contentId,
      JSON.stringify(inlineSchema),
    ]);

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: any) {
    console.error('Error initializing inline schema:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}

/**
 * Switch to class reference mode (clears inline schema)
 */
export async function setContentTypeClassReference(
  contentId: string,
  classId: string
): Promise<string> {
  const query = `
    UPDATE apiome.shared_path_request_body_content
    SET class_id = $2, inline_schema = NULL, updated_at = CURRENT_TIMESTAMP
    WHERE id = $1
    RETURNING id, shared_path_request_body_id, media_type, class_id, inline_schema, encoding, examples
  `;

  try {
    const result = await connectionPool.query(query, [contentId, classId]);

    if (result.rowCount === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: any) {
    console.error('Error setting class reference:', error);
    return JSON.stringify({ success: false, error: error.message });
  }
}
