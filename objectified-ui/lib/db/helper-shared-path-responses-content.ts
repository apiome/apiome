'use server';

/**
 * Helper functions for managing response body schemas (class references and inline schemas)
 * Mirrors the request body implementation for consistency
 */

// eslint-disable-next-line @typescript-eslint/no-require-imports
const connectionPool = require('./db');

import type { InlineSchema } from '../utils/inline-schema-utils';

// =============================================================================
// RESPONSE CONTENT TYPES
// =============================================================================

/**
 * Add a content type to a response
 */
export async function addResponseContentType(
  responseId: string,
  mediaType: string,
  classId?: string,
  inlineSchema?: InlineSchema,
  examples?: unknown[]
): Promise<string> {
  try {
    const query = `
      INSERT INTO odb.shared_path_response_content 
        (shared_path_response_id, media_type, class_id, inline_schema, examples)
      VALUES ($1, $2, $3, $4, $5)
      RETURNING id, shared_path_response_id, media_type, class_id, inline_schema, examples
    `;

    const result = await connectionPool.query(query, [
      responseId,
      mediaType,
      classId || null,
      inlineSchema ? JSON.stringify(inlineSchema) : null,
      examples ? JSON.stringify(examples) : null,
    ]);

    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: unknown) {
    console.error('Error adding response content type:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Update a response content type
 */
export async function updateResponseContentType(
  contentId: string,
  updates: {
    mediaType?: string;
    classId?: string | null;
    inlineSchema?: InlineSchema | null;
    examples?: unknown[] | null;
  }
): Promise<string> {
  try {
    const setParts: string[] = [];
    const values: unknown[] = [];
    let paramIndex = 1;

    if (updates.mediaType !== undefined) {
      setParts.push(`media_type = $${paramIndex++}`);
      values.push(updates.mediaType);
    }
    if (updates.classId !== undefined) {
      setParts.push(`class_id = $${paramIndex++}`);
      values.push(updates.classId);
    }
    if (updates.inlineSchema !== undefined) {
      setParts.push(`inline_schema = $${paramIndex++}`);
      values.push(updates.inlineSchema ? JSON.stringify(updates.inlineSchema) : null);
    }
    if (updates.examples !== undefined) {
      setParts.push(`examples = $${paramIndex++}`);
      values.push(updates.examples ? JSON.stringify(updates.examples) : null);
    }

    if (setParts.length === 0) {
      return JSON.stringify({ success: false, error: 'No updates provided' });
    }

    values.push(contentId);
    const query = `
      UPDATE odb.shared_path_response_content
      SET ${setParts.join(', ')}
      WHERE id = $${paramIndex}
      RETURNING id, shared_path_response_id, media_type, class_id, inline_schema, examples
    `;

    const result = await connectionPool.query(query, values);

    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    return JSON.stringify({ success: true, content: result.rows[0] });
  } catch (error: unknown) {
    console.error('Error updating response content type:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Delete a response content type
 */
export async function deleteResponseContentType(contentId: string): Promise<string> {
  try {
    const query = `DELETE FROM odb.shared_path_response_content WHERE id = $1`;
    await connectionPool.query(query, [contentId]);
    return JSON.stringify({ success: true });
  } catch (error: unknown) {
    console.error('Error deleting response content type:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Get all content types for a response
 */
export async function getResponseContentTypes(responseId: string): Promise<string> {
  try {
    const query = `
      SELECT 
        rc.id,
        rc.shared_path_response_id,
        rc.media_type,
        rc.class_id,
        c.name as class_name,
        rc.inline_schema,
        rc.examples
      FROM odb.shared_path_response_content rc
      LEFT JOIN odb.classes c ON rc.class_id = c.id
      WHERE rc.shared_path_response_id = $1
      ORDER BY rc.media_type
    `;

    const result = await connectionPool.query(query, [responseId]);
    return JSON.stringify({ success: true, contentTypes: result.rows });
  } catch (error: unknown) {
    console.error('Error getting response content types:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

// =============================================================================
// INLINE SCHEMA MANAGEMENT
// =============================================================================

/**
 * Convert a class reference to inline schema (copies all properties)
 */
export async function convertResponseClassToInlineSchema(contentId: string): Promise<string> {
  try {
    // Get the content type with its class reference
    const getQuery = `
      SELECT rc.class_id, c.name, c.description
      FROM odb.shared_path_response_content rc
      JOIN odb.classes c ON rc.class_id = c.id
      WHERE rc.id = $1
    `;
    const getResult = await connectionPool.query(getQuery, [contentId]);

    if (getResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found or has no class reference' });
    }

    const { class_id, name, description } = getResult.rows[0];

    // Get all properties for the class
    const propsQuery = `
      SELECT id, name, description, data, parent_id
      FROM odb.class_properties
      WHERE class_id = $1
      ORDER BY parent_id NULLS FIRST, name
    `;
    const propsResult = await connectionPool.query(propsQuery, [class_id]);

    // Build inline schema
    const inlineSchema: InlineSchema = {
      type: 'object',
      description: description || `Inline schema converted from ${name}`,
      properties: propsResult.rows.map((prop: Record<string, unknown>) => ({
        id: prop.id as string,
        name: prop.name as string,
        description: prop.description as string | undefined,
        data: typeof prop.data === 'string' ? JSON.parse(prop.data as string) : prop.data,
        parent_id: prop.parent_id as string | null,
      })),
    };

    // Update the content type to use inline schema instead of class reference
    const updateQuery = `
      UPDATE odb.shared_path_response_content
      SET class_id = NULL, inline_schema = $1
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(updateQuery, [JSON.stringify(inlineSchema), contentId]);

    return JSON.stringify({ success: true, inlineSchema });
  } catch (error: unknown) {
    console.error('Error converting class to inline schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Initialize an empty inline schema for a content type
 */
export async function initializeResponseInlineSchema(contentId: string): Promise<string> {
  try {
    const inlineSchema: InlineSchema = {
      type: 'object',
      properties: [],
    };

    const query = `
      UPDATE odb.shared_path_response_content
      SET class_id = NULL, inline_schema = $1
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(query, [JSON.stringify(inlineSchema), contentId]);

    return JSON.stringify({ success: true, inlineSchema });
  } catch (error: unknown) {
    console.error('Error initializing inline schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Set a primitive type schema for a content type (string, number, integer, boolean, null)
 */
export async function setResponsePrimitiveSchema(
  contentId: string,
  schemaType: 'string' | 'number' | 'integer' | 'boolean' | 'null',
  options?: {
    format?: string;
    description?: string;
    enum?: (string | number | boolean | null)[];
    default?: unknown;
  }
): Promise<string> {
  try {
    const primitiveSchema: Record<string, unknown> = {
      type: schemaType,
    };

    if (options?.format) {
      primitiveSchema.format = options.format;
    }
    if (options?.description) {
      primitiveSchema.description = options.description;
    }
    if (options?.enum && options.enum.length > 0) {
      primitiveSchema.enum = options.enum;
    }
    if (options?.default !== undefined) {
      primitiveSchema.default = options.default;
    }

    const query = `
      UPDATE odb.shared_path_response_content
      SET class_id = NULL, inline_schema = $1
      WHERE id = $2
      RETURNING id, inline_schema
    `;
    const result = await connectionPool.query(query, [JSON.stringify(primitiveSchema), contentId]);

    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    return JSON.stringify({ success: true, schema: primitiveSchema });
  } catch (error: unknown) {
    console.error('Error setting primitive schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Set an array type schema for a content type
 */
export async function setResponseArraySchema(
  contentId: string,
  itemType: 'string' | 'number' | 'integer' | 'boolean' | 'object',
  options?: {
    itemRef?: string; // For object items that reference a class
    description?: string;
  }
): Promise<string> {
  try {
    const arraySchema: Record<string, unknown> = {
      type: 'array',
      items: itemType === 'object' && options?.itemRef
        ? { $ref: `#/components/schemas/${options.itemRef}` }
        : { type: itemType },
    };

    if (options?.description) {
      arraySchema.description = options.description;
    }

    const query = `
      UPDATE odb.shared_path_response_content
      SET class_id = NULL, inline_schema = $1
      WHERE id = $2
      RETURNING id, inline_schema
    `;
    const result = await connectionPool.query(query, [JSON.stringify(arraySchema), contentId]);

    if (result.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    return JSON.stringify({ success: true, schema: arraySchema });
  } catch (error: unknown) {
    console.error('Error setting array schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Set a class reference for a content type (replacing inline schema if present)
 */
export async function setResponseContentTypeClassReference(
  contentId: string,
  classId: string
): Promise<string> {
  try {
    const query = `
      UPDATE odb.shared_path_response_content
      SET class_id = $1, inline_schema = NULL
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(query, [classId, contentId]);

    return JSON.stringify({ success: true });
  } catch (error: unknown) {
    console.error('Error setting class reference:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

// =============================================================================
// INLINE SCHEMA PROPERTY MANAGEMENT
// =============================================================================

/**
 * Add a property to an inline schema
 */
export async function addPropertyToResponseInlineSchema(
  contentId: string,
  property: {
    name: string;
    description?: string;
    data: Record<string, unknown>;
    parent_id?: string | null;
  }
): Promise<string> {
  try {
    // Get current inline schema
    const getQuery = `SELECT inline_schema FROM odb.shared_path_response_content WHERE id = $1`;
    const getResult = await connectionPool.query(getQuery, [contentId]);

    if (getResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    // Initialize inline schema if it doesn't exist
    let inlineSchema = getResult.rows[0].inline_schema;
    if (!inlineSchema) {
      inlineSchema = {
        type: 'object',
        properties: [],
      };
    }

    inlineSchema.properties = inlineSchema.properties || [];

    // Check for duplicate property name at the same level (same parent_id)
    const parentId = property.parent_id || null;
    const duplicateProperty = inlineSchema.properties.find(
      (p: { name: string; parent_id: string | null }) =>
        p.name === property.name && (p.parent_id || null) === parentId
    );

    if (duplicateProperty) {
      return JSON.stringify({
        success: false,
        error: `Property "${property.name}" already exists at this level`,
      });
    }

    // Add new property with generated ID
    const newProperty = {
      id: crypto.randomUUID(),
      name: property.name,
      description: property.description,
      data: property.data,
      parent_id: property.parent_id || null,
    };

    inlineSchema.properties.push(newProperty);

    // Update the schema
    const updateQuery = `
      UPDATE odb.shared_path_response_content
      SET inline_schema = $1
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(updateQuery, [JSON.stringify(inlineSchema), contentId]);

    return JSON.stringify({ success: true, property: newProperty });
  } catch (error: unknown) {
    console.error('Error adding property to inline schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Update a property in an inline schema
 */
export async function updateResponseInlineSchemaProperty(
  contentId: string,
  propertyId: string,
  updates: {
    name?: string;
    description?: string;
    data?: Record<string, unknown>;
  }
): Promise<string> {
  try {
    // Get current inline schema
    const getQuery = `SELECT inline_schema FROM odb.shared_path_response_content WHERE id = $1`;
    const getResult = await connectionPool.query(getQuery, [contentId]);

    if (getResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    const inlineSchema = getResult.rows[0].inline_schema;
    if (!inlineSchema || !inlineSchema.properties) {
      return JSON.stringify({ success: false, error: 'No inline schema exists' });
    }

    // Find and update the property
    const property = inlineSchema.properties.find((p: { id: string }) => p.id === propertyId);
    if (!property) {
      return JSON.stringify({ success: false, error: 'Property not found' });
    }

    if (updates.name !== undefined) property.name = updates.name;
    if (updates.description !== undefined) property.description = updates.description;
    if (updates.data !== undefined) property.data = updates.data;

    // Update the schema
    const updateQuery = `
      UPDATE odb.shared_path_response_content
      SET inline_schema = $1
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(updateQuery, [JSON.stringify(inlineSchema), contentId]);

    return JSON.stringify({ success: true, property });
  } catch (error: unknown) {
    console.error('Error updating property in inline schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}

/**
 * Delete a property from an inline schema
 */
export async function deleteResponseInlineSchemaProperty(
  contentId: string,
  propertyId: string,
  cascadeChildren = true
): Promise<string> {
  try {
    // Get current inline schema
    const getQuery = `SELECT inline_schema FROM odb.shared_path_response_content WHERE id = $1`;
    const getResult = await connectionPool.query(getQuery, [contentId]);

    if (getResult.rows.length === 0) {
      return JSON.stringify({ success: false, error: 'Content type not found' });
    }

    const inlineSchema = getResult.rows[0].inline_schema;
    if (!inlineSchema || !inlineSchema.properties) {
      return JSON.stringify({ success: false, error: 'No inline schema exists' });
    }

    // Remove the property and optionally its children
    if (cascadeChildren) {
      const toDelete = new Set<string>([propertyId]);
      let foundNew = true;
      while (foundNew) {
        foundNew = false;
        for (const prop of inlineSchema.properties) {
          if (prop.parent_id && toDelete.has(prop.parent_id) && !toDelete.has(prop.id)) {
            toDelete.add(prop.id);
            foundNew = true;
          }
        }
      }
      inlineSchema.properties = inlineSchema.properties.filter(
        (p: { id: string }) => !toDelete.has(p.id)
      );
    } else {
      inlineSchema.properties = inlineSchema.properties.filter(
        (p: { id: string }) => p.id !== propertyId
      );
    }

    // Update the schema
    const updateQuery = `
      UPDATE odb.shared_path_response_content
      SET inline_schema = $1
      WHERE id = $2
      RETURNING id
    `;
    await connectionPool.query(updateQuery, [JSON.stringify(inlineSchema), contentId]);

    return JSON.stringify({ success: true });
  } catch (error: unknown) {
    console.error('Error deleting property from inline schema:', error);
    const message = error instanceof Error ? error.message : 'Unknown error';
    return JSON.stringify({ success: false, error: message });
  }
}
