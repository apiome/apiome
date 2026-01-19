/**
 * Inline Schema Utilities
 *
 * Functions for managing inline schema properties and converting them to OpenAPI 3.1.0 format.
 * Inline schemas are stored as flat arrays with parent_id relationships for nesting.
 */

// =============================================================================
// TYPES
// =============================================================================

export interface InlineSchemaProperty {
  id: string;
  name: string;
  description?: string | null;
  data: Record<string, any>;
  parent_id: string | null;
}

// Schema type that supports primitives, objects, and arrays
export type SchemaType = 'object' | 'array' | 'string' | 'number' | 'integer' | 'boolean' | 'null';

export interface InlineSchema {
  type: SchemaType;
  description?: string;
  // For object type
  properties?: InlineSchemaProperty[];
  // For array type
  items?: {
    type?: SchemaType;
    $ref?: string;
    properties?: InlineSchemaProperty[];
  };
  // For references
  $ref?: string;
  // Composition patterns
  allOf?: any[];
  oneOf?: any[];
  anyOf?: any[];
  // String constraints
  format?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  // Number constraints
  minimum?: number;
  maximum?: number;
  // Enum values
  enum?: (string | number | boolean | null)[];
  // Default value
  default?: unknown;
}

export interface PropertyTreeNode extends InlineSchemaProperty {
  children: PropertyTreeNode[];
}

// =============================================================================
// PROPERTY TREE BUILDING
// =============================================================================

/**
 * Build a hierarchical tree structure from flat properties array
 * Uses parent_id to establish nesting relationships
 */
export function buildPropertyTreeFromInlineSchema(
  inlineSchema: InlineSchema | null
): PropertyTreeNode[] {
  if (!inlineSchema || !inlineSchema.properties || !Array.isArray(inlineSchema.properties) || inlineSchema.properties.length === 0) {
    return [];
  }

  const properties = inlineSchema.properties;
  const nodeMap = new Map<string, PropertyTreeNode>();
  const roots: PropertyTreeNode[] = [];

  // Create nodes for all properties
  for (const prop of properties) {
    nodeMap.set(prop.id, {
      ...prop,
      children: [],
    });
  }

  // Build tree structure
  for (const prop of properties) {
    const node = nodeMap.get(prop.id)!;
    if (prop.parent_id && nodeMap.has(prop.parent_id)) {
      nodeMap.get(prop.parent_id)!.children.push(node);
    } else {
      roots.push(node);
    }
  }

  // Sort children by name at each level
  const sortChildren = (nodes: PropertyTreeNode[]) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    for (const node of nodes) {
      if (node.children.length > 0) {
        sortChildren(node.children);
      }
    }
  };

  sortChildren(roots);
  return roots;
}

/**
 * Flatten a property tree back to array format
 * Preserves parent_id relationships
 */
export function flattenPropertyTree(tree: PropertyTreeNode[]): InlineSchemaProperty[] {
  const result: InlineSchemaProperty[] = [];

  const flatten = (nodes: PropertyTreeNode[]) => {
    for (const node of nodes) {
      result.push({
        id: node.id,
        name: node.name,
        description: node.description,
        data: node.data,
        parent_id: node.parent_id,
      });
      if (node.children.length > 0) {
        flatten(node.children);
      }
    }
  };

  flatten(tree);
  return result;
}

// =============================================================================
// PROPERTY ARRAY MANIPULATION
// =============================================================================

/**
 * Add a property to an inline schema properties array
 * Generates a new UUID and inserts at the appropriate location
 */
export function addPropertyToInlineSchemaArray(
  properties: InlineSchemaProperty[],
  propertyData: {
    name: string;
    description?: string;
    data: Record<string, any>;
  },
  parentId?: string | null
): { properties: InlineSchemaProperty[]; newProperty: InlineSchemaProperty } {
  const newProperty: InlineSchemaProperty = {
    id: crypto.randomUUID(),
    name: propertyData.name,
    description: propertyData.description || null,
    data: propertyData.data,
    parent_id: parentId || null,
  };

  return {
    properties: [...properties, newProperty],
    newProperty,
  };
}

/**
 * Update a property in an inline schema properties array
 */
export function updatePropertyInInlineSchemaArray(
  properties: InlineSchemaProperty[],
  propertyId: string,
  updates: Partial<Omit<InlineSchemaProperty, 'id'>>
): InlineSchemaProperty[] {
  return properties.map((prop) => {
    if (prop.id === propertyId) {
      return {
        ...prop,
        ...updates,
      };
    }
    return prop;
  });
}

/**
 * Delete a property from an inline schema properties array
 * Optionally cascade deletes to children
 */
export function deletePropertyFromInlineSchemaArray(
  properties: InlineSchemaProperty[],
  propertyId: string,
  cascadeChildren: boolean = true
): InlineSchemaProperty[] {
  const propertiesToDelete = new Set<string>([propertyId]);

  if (cascadeChildren) {
    // Recursively find all descendants
    let foundMore = true;
    while (foundMore) {
      foundMore = false;
      for (const prop of properties) {
        if (prop.parent_id && propertiesToDelete.has(prop.parent_id) && !propertiesToDelete.has(prop.id)) {
          propertiesToDelete.add(prop.id);
          foundMore = true;
        }
      }
    }
  }

  return properties.filter((prop) => !propertiesToDelete.has(prop.id));
}

/**
 * Find a property by ID in the properties array
 */
export function findPropertyById(
  properties: InlineSchemaProperty[],
  propertyId: string
): InlineSchemaProperty | undefined {
  return properties.find((prop) => prop.id === propertyId);
}

/**
 * Get all children of a property
 */
export function getPropertyChildren(
  properties: InlineSchemaProperty[],
  parentId: string
): InlineSchemaProperty[] {
  return properties.filter((prop) => prop.parent_id === parentId);
}

// =============================================================================
// OPENAPI 3.1.0 EXPORT
// =============================================================================

/**
 * Build an OpenAPI 3.1.0 compliant JSON Schema from inline schema properties
 * Handles nested objects, arrays, $ref patterns, required fields, and all JSON Schema keywords
 *
 * CRITICAL: This function is essential for OpenAPI export of paths with inline request/response bodies
 */
export function buildSchemaFromInlineProperties(
  inlineSchema: InlineSchema | null
): Record<string, any> {
  if (!inlineSchema) {
    return { type: 'object' };
  }

  // Ensure properties is an array (handle legacy data where it might be an object)
  const properties = Array.isArray(inlineSchema.properties) ? inlineSchema.properties : [];
  const tree = buildPropertyTreeFromInlineSchema(inlineSchema);

  // Build the schema from the tree
  const schema = buildSchemaFromTree(tree, inlineSchema.description);

  // Preserve composition patterns if present
  if (inlineSchema.allOf) {
    schema.allOf = inlineSchema.allOf;
  }
  if (inlineSchema.oneOf) {
    schema.oneOf = inlineSchema.oneOf;
  }
  if (inlineSchema.anyOf) {
    schema.anyOf = inlineSchema.anyOf;
  }

  return schema;
}

/**
 * Build schema recursively from property tree
 */
function buildSchemaFromTree(
  nodes: PropertyTreeNode[],
  description?: string
): Record<string, any> {
  if (nodes.length === 0) {
    const schema: Record<string, any> = { type: 'object' };
    if (description) schema.description = description;
    return schema;
  }

  const properties: Record<string, any> = {};
  const required: string[] = [];

  for (const node of nodes) {
    const propSchema = buildPropertySchema(node);

    // Extract required flag and add to parent's required array
    if (propSchema.required === true) {
      required.push(node.name);
    }
    // Remove the required flag from the property schema (it belongs on the parent)
    delete propSchema.required;

    properties[node.name] = propSchema;
  }

  const schema: Record<string, any> = {
    type: 'object',
    properties,
  };

  if (description) {
    schema.description = description;
  }

  if (required.length > 0) {
    schema.required = required;
  }

  return schema;
}

/**
 * Build schema for a single property, handling nested children
 */
function buildPropertySchema(node: PropertyTreeNode): Record<string, any> {
  const data = node.data || {};
  const schema: Record<string, any> = { ...data };

  // Add description if present and not already in data
  if (node.description && !schema.description) {
    schema.description = node.description;
  }

  // Handle $ref - pass through unchanged
  if (schema.$ref) {
    return schema;
  }

  // Handle object type with children
  if (data.type === 'object' && node.children.length > 0) {
    const childProperties: Record<string, any> = {};
    const childRequired: string[] = [];

    for (const child of node.children) {
      const childSchema = buildPropertySchema(child);

      if (childSchema.required === true) {
        childRequired.push(child.name);
      }
      delete childSchema.required;

      childProperties[child.name] = childSchema;
    }

    schema.properties = childProperties;
    if (childRequired.length > 0) {
      schema.required = childRequired;
    }
  }

  // Handle array type with children (array of objects)
  if (data.type === 'array' && node.children.length > 0) {
    const itemProperties: Record<string, any> = {};
    const itemRequired: string[] = [];

    for (const child of node.children) {
      const childSchema = buildPropertySchema(child);

      if (childSchema.required === true) {
        itemRequired.push(child.name);
      }
      delete childSchema.required;

      itemProperties[child.name] = childSchema;
    }

    // If items already exists and has $ref, don't override
    if (!schema.items?.$ref) {
      schema.items = {
        type: 'object',
        properties: itemProperties,
      };
      if (itemRequired.length > 0) {
        schema.items.required = itemRequired;
      }
    }
  }

  return schema;
}

/**
 * Build a complete requestBody object for OpenAPI export
 * Handles multiple content types with either class $ref or inline schema
 */
export function buildRequestBodyForOpenAPI(
  requestBody: {
    description?: string;
    required?: boolean;
    content_types: Array<{
      media_type: string;
      class_id?: string;
      class_name?: string;
      inline_schema?: InlineSchema;
      encoding?: Record<string, any>;
      examples?: any[];
    }>;
  }
): Record<string, any> {
  const content: Record<string, any> = {};

  for (const contentType of requestBody.content_types) {
    const mediaTypeObject: Record<string, any> = {};

    // Build schema
    if (contentType.class_id && contentType.class_name) {
      // Reference to existing class
      mediaTypeObject.schema = {
        $ref: `#/components/schemas/${contentType.class_name}`,
      };
    } else if (contentType.inline_schema) {
      // Inline schema
      mediaTypeObject.schema = buildSchemaFromInlineProperties(contentType.inline_schema);
    }

    // Add encoding for multipart/form-data
    if (contentType.encoding && Object.keys(contentType.encoding).length > 0) {
      mediaTypeObject.encoding = contentType.encoding;
    }

    // Add examples
    if (contentType.examples && contentType.examples.length > 0) {
      if (contentType.examples.length === 1) {
        mediaTypeObject.example = contentType.examples[0].value;
      } else {
        mediaTypeObject.examples = {};
        for (const ex of contentType.examples) {
          mediaTypeObject.examples[ex.name] = {
            summary: ex.summary,
            value: ex.value,
          };
        }
      }
    }

    content[contentType.media_type] = mediaTypeObject;
  }

  const result: Record<string, any> = { content };

  if (requestBody.description) {
    result.description = requestBody.description;
  }

  if (requestBody.required !== undefined) {
    result.required = requestBody.required;
  }

  return result;
}

/**
 * Validate inline schema structure
 * Returns array of validation errors (empty if valid)
 */
export function validateInlineSchema(inlineSchema: InlineSchema): string[] {
  const errors: string[] = [];

  if (!inlineSchema) {
    errors.push('Inline schema is required');
    return errors;
  }

  if (inlineSchema.type !== 'object') {
    errors.push('Inline schema type must be "object"');
  }

  if (!Array.isArray(inlineSchema.properties)) {
    errors.push('Inline schema properties must be an array');
    return errors;
  }

  const propertyNames = new Map<string, Set<string>>(); // parent_id -> set of names

  for (const prop of inlineSchema.properties) {
    if (!prop.id) {
      errors.push(`Property missing required field: id`);
    }
    if (!prop.name) {
      errors.push(`Property missing required field: name`);
    }
    if (!prop.data) {
      errors.push(`Property "${prop.name}" missing required field: data`);
    }

    // Check for duplicate names at same level
    const parentKey = prop.parent_id || '__root__';
    if (!propertyNames.has(parentKey)) {
      propertyNames.set(parentKey, new Set());
    }
    const namesAtLevel = propertyNames.get(parentKey)!;
    if (namesAtLevel.has(prop.name)) {
      errors.push(`Duplicate property name "${prop.name}" at same level`);
    }
    namesAtLevel.add(prop.name);

    // Validate parent_id exists if set
    if (prop.parent_id) {
      const parentExists = inlineSchema.properties.some((p) => p.id === prop.parent_id);
      if (!parentExists) {
        errors.push(`Property "${prop.name}" references non-existent parent: ${prop.parent_id}`);
      }
    }
  }

  return errors;
}

// =============================================================================
// PROPERTY DRAG-DROP SUPPORT
// =============================================================================

/**
 * Clone a property from the property library or another class for use in inline schema
 * Generates a new UUID and removes class-specific fields
 */
export function clonePropertyForInlineSchema(
  sourceProperty: {
    name: string;
    description?: string;
    data: Record<string, any>;
  },
  parentId?: string | null
): InlineSchemaProperty {
  // Deep clone the data to avoid mutations
  const clonedData = JSON.parse(JSON.stringify(sourceProperty.data));

  return {
    id: crypto.randomUUID(),
    name: sourceProperty.name,
    description: sourceProperty.description || null,
    data: clonedData,
    parent_id: parentId || null,
  };
}

/**
 * Check if a property can accept children (is an object or array of objects)
 */
export function canPropertyAcceptChildren(propertyData: Record<string, any>): boolean {
  // Object type can have nested properties
  if (propertyData.type === 'object' && !propertyData.$ref) {
    return true;
  }

  // Array of objects can have nested properties (defines items schema)
  if (propertyData.type === 'array') {
    const items = propertyData.items;
    if (items && items.type === 'object' && !items.$ref) {
      return true;
    }
    // Array without items defined - can still accept children to define items
    if (!items) {
      return true;
    }
  }

  return false;
}
