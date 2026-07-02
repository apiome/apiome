/**
 * JSON Schema to OpenAPI 3.1.x Converter
 *
 * Converts JSON Schema documents to OpenAPI 3.1.x format
 * for compatibility with the Apiome import system.
 *
 * Supports:
 * - JSON Schema Draft-04, Draft-06, Draft-07, Draft 2019-09, Draft 2020-12
 * - Single schema files (converted to a single-schema OpenAPI spec)
 * - Multi-schema files with $defs/definitions
 * - $ref resolution within the document
 */

/**
 * Result of a JSON Schema to OpenAPI conversion
 */
export interface JsonSchemaConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/**
 * Supported JSON Schema draft versions
 */
const SUPPORTED_DRAFTS: Record<string, string> = {
  'http://json-schema.org/draft-04/schema#': 'draft-04',
  'http://json-schema.org/draft-04/schema': 'draft-04',
  'http://json-schema.org/draft-06/schema#': 'draft-06',
  'http://json-schema.org/draft-06/schema': 'draft-06',
  'http://json-schema.org/draft-07/schema#': 'draft-07',
  'http://json-schema.org/draft-07/schema': 'draft-07',
  'https://json-schema.org/draft/2019-09/schema': 'draft-2019-09',
  'https://json-schema.org/draft/2020-12/schema': 'draft-2020-12',
};

/**
 * Converts a JSON Schema document to OpenAPI 3.1.x format
 *
 * @param jsonSchemaDoc - The parsed JSON Schema document
 * @param filename - Optional filename to derive schema name from
 * @returns The converted OpenAPI 3.1.x document with conversion metadata
 */
export function convertJsonSchemaToOpenAPI(
  jsonSchemaDoc: any,
  filename?: string
): JsonSchemaConversionResult {
  const warnings: string[] = [];

  try {
    // Validate input
    if (!jsonSchemaDoc || typeof jsonSchemaDoc !== 'object') {
      return {
        success: false,
        document: null,
        error: 'Invalid JSON Schema document: expected an object',
        warnings: []
      };
    }

    // Detect schema version
    const schemaVersion = detectSchemaVersion(jsonSchemaDoc);
    if (schemaVersion) {
      warnings.push(`Detected JSON Schema ${schemaVersion}`);
    }

    // Create OpenAPI 3.1.0 base structure
    const openApiDoc: any = {
      openapi: '3.1.0',
      info: {
        title: extractTitle(jsonSchemaDoc, filename),
        version: '1.0.0',
        description: jsonSchemaDoc.description || 'Converted from JSON Schema'
      },
      components: {
        schemas: {}
      }
    };

    // Extract schemas from the document
    const schemas = extractSchemas(jsonSchemaDoc, filename, warnings);

    if (Object.keys(schemas).length === 0) {
      return {
        success: false,
        document: null,
        error: 'No schemas found in JSON Schema document',
        warnings
      };
    }

    // Convert each schema
    for (const [name, schema] of Object.entries(schemas)) {
      openApiDoc.components.schemas[name] = convertSchema(schema, warnings, name);
    }

    return {
      success: true,
      document: openApiDoc,
      warnings
    };
  } catch (error) {
    return {
      success: false,
      document: null,
      error: `Conversion failed: ${error instanceof Error ? error.message : String(error)}`,
      warnings
    };
  }
}

/**
 * Detect the JSON Schema draft version
 */
function detectSchemaVersion(doc: any): string | null {
  if (!doc.$schema) {
    return null;
  }

  const version = SUPPORTED_DRAFTS[doc.$schema];
  if (version) {
    return version;
  }

  // Try to extract version from unknown schema URLs
  if (doc.$schema.includes('draft-04')) return 'draft-04';
  if (doc.$schema.includes('draft-06')) return 'draft-06';
  if (doc.$schema.includes('draft-07')) return 'draft-07';
  if (doc.$schema.includes('2019-09')) return 'draft-2019-09';
  if (doc.$schema.includes('2020-12')) return 'draft-2020-12';

  return 'unknown';
}

/**
 * Extract a title from the schema or filename
 */
function extractTitle(doc: any, filename?: string): string {
  if (doc.title) {
    return doc.title;
  }

  if (filename) {
    // Remove extension and convert to title case
    const name = filename
      .replace(/\.(json|yaml|yml)$/i, '')
      .replace(/[-_]/g, ' ')
      .replace(/\b\w/g, c => c.toUpperCase());
    return name;
  }

  return 'JSON Schema';
}

/**
 * Extract all schemas from a JSON Schema document
 */
function extractSchemas(
  doc: any,
  filename?: string,
  warnings: string[] = []
): Record<string, any> {
  const schemas: Record<string, any> = {};

  // Check for $defs (JSON Schema 2019-09+)
  if (doc.$defs && typeof doc.$defs === 'object') {
    for (const [name, schema] of Object.entries(doc.$defs)) {
      schemas[name] = schema;
    }
  }

  // Check for definitions (JSON Schema draft-04 to draft-07)
  if (doc.definitions && typeof doc.definitions === 'object') {
    for (const [name, schema] of Object.entries(doc.definitions)) {
      schemas[name] = schema;
    }
  }

  // If the root document is itself a schema (has type or properties)
  if (isSchemaDefinition(doc)) {
    const rootName = extractRootSchemaName(doc, filename);
    // Create a copy without $schema, $defs, definitions
    const rootSchema = { ...doc };
    delete rootSchema.$schema;
    delete rootSchema.$defs;
    delete rootSchema.definitions;
    delete rootSchema.$id;
    schemas[rootName] = rootSchema;
  }

  // If no schemas found, treat the whole document as a schema (only if it has some content)
  if (Object.keys(schemas).length === 0) {
    // Check if the document has any meaningful content
    const hasContent = Object.keys(doc).some(key =>
      !['$schema', '$id', '$comment'].includes(key)
    );

    if (hasContent) {
      const rootName = extractRootSchemaName(doc, filename);
      schemas[rootName] = doc;
      warnings.push(`Treating entire document as schema "${rootName}"`);
    }
  }

  return schemas;
}

/**
 * Check if an object looks like a schema definition
 */
function isSchemaDefinition(obj: any): boolean {
  if (!obj || typeof obj !== 'object') return false;

  // Has explicit type
  if (obj.type) return true;

  // Has properties (implies object type)
  if (obj.properties) return true;

  // Has items (implies array type)
  if (obj.items) return true;

  // Has composition keywords
  if (obj.allOf || obj.anyOf || obj.oneOf) return true;

  // Has enum
  if (obj.enum) return true;

  // Has const
  if (obj.const !== undefined) return true;

  return false;
}

/**
 * Extract a name for the root schema
 */
function extractRootSchemaName(doc: any, filename?: string): string {
  // Use title if available
  if (doc.title) {
    return normalizeSchemaName(doc.title);
  }

  // Use $id if available
  if (doc.$id) {
    const idName = doc.$id.split('/').pop()?.replace(/\.json$/i, '');
    if (idName) {
      return normalizeSchemaName(idName);
    }
  }

  // Use filename
  if (filename) {
    const name = filename.replace(/\.(json|yaml|yml)$/i, '');
    return normalizeSchemaName(name);
  }

  return 'Root';
}

/**
 * Normalize a string to be a valid schema name (PascalCase)
 */
function normalizeSchemaName(name: string): string {
  return name
    .replace(/[-_\s]+(.)?/g, (_, c) => (c ? c.toUpperCase() : ''))
    .replace(/^./, c => c.toUpperCase())
    .replace(/[^a-zA-Z0-9]/g, '');
}

/**
 * Convert a single schema from JSON Schema to OpenAPI 3.1 format
 */
function convertSchema(schema: any, warnings: string[], context?: string): any {
  if (!schema || typeof schema !== 'object') {
    return schema;
  }

  // Handle boolean schemas (JSON Schema 2019-09+)
  if (typeof schema === 'boolean') {
    return schema ? {} : { not: {} };
  }

  const converted: any = { ...schema };

  // Convert $ref paths
  if (converted.$ref && typeof converted.$ref === 'string') {
    converted.$ref = convertRefPath(converted.$ref);
    return converted;
  }

  // Remove JSON Schema specific fields that don't apply to OpenAPI
  delete converted.$schema;
  delete converted.$id;
  delete converted.$comment;

  // Convert definitions to $defs style (OpenAPI 3.1 uses $defs internally)
  if (converted.definitions) {
    const newDefs: any = {};
    for (const [name, def] of Object.entries(converted.definitions)) {
      newDefs[name] = convertSchema(def, warnings, `${context}.definitions.${name}`);
    }
    delete converted.definitions;
    // Note: We don't add $defs here as they should be at the component level
  }

  // Convert $defs recursively
  if (converted.$defs) {
    const newDefs: any = {};
    for (const [name, def] of Object.entries(converted.$defs)) {
      newDefs[name] = convertSchema(def, warnings, `${context}.$defs.${name}`);
    }
    converted.$defs = newDefs;
  }

  // Convert properties recursively
  if (converted.properties) {
    const newProperties: any = {};
    for (const [propName, propSchema] of Object.entries<any>(converted.properties)) {
      newProperties[propName] = convertSchema(propSchema, warnings, `${context}.${propName}`);
    }
    converted.properties = newProperties;
  }

  // Convert items in array types
  if (converted.items) {
    if (Array.isArray(converted.items)) {
      // Tuple validation - convert to prefixItems (OpenAPI 3.1)
      converted.prefixItems = converted.items.map((item: any, index: number) =>
        convertSchema(item, warnings, `${context}.items[${index}]`)
      );
      delete converted.items;
    } else {
      converted.items = convertSchema(converted.items, warnings, `${context}.items`);
    }
  }

  // Convert additionalItems to items (for tuple validation)
  if (converted.additionalItems !== undefined && converted.prefixItems) {
    if (typeof converted.additionalItems === 'boolean') {
      if (!converted.additionalItems) {
        converted.items = false;
      }
    } else {
      converted.items = convertSchema(converted.additionalItems, warnings, `${context}.additionalItems`);
    }
    delete converted.additionalItems;
  }

  // Convert allOf/anyOf/oneOf schemas recursively
  for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
    if (converted[keyword] && Array.isArray(converted[keyword])) {
      converted[keyword] = converted[keyword].map((subSchema: any, index: number) =>
        convertSchema(subSchema, warnings, `${context}.${keyword}[${index}]`)
      );
    }
  }

  // Convert not schema
  if (converted.not) {
    converted.not = convertSchema(converted.not, warnings, `${context}.not`);
  }

  // Convert if/then/else schemas
  if (converted.if) {
    converted.if = convertSchema(converted.if, warnings, `${context}.if`);
  }
  if (converted.then) {
    converted.then = convertSchema(converted.then, warnings, `${context}.then`);
  }
  if (converted.else) {
    converted.else = convertSchema(converted.else, warnings, `${context}.else`);
  }

  // Convert additionalProperties
  if (converted.additionalProperties && typeof converted.additionalProperties === 'object') {
    converted.additionalProperties = convertSchema(
      converted.additionalProperties,
      warnings,
      `${context}.additionalProperties`
    );
  }

  // Convert patternProperties
  if (converted.patternProperties) {
    const newPatternProps: any = {};
    for (const [pattern, propSchema] of Object.entries<any>(converted.patternProperties)) {
      newPatternProps[pattern] = convertSchema(propSchema, warnings, `${context}.patternProperties.${pattern}`);
    }
    converted.patternProperties = newPatternProps;
  }

  // Convert propertyNames
  if (converted.propertyNames && typeof converted.propertyNames === 'object') {
    converted.propertyNames = convertSchema(
      converted.propertyNames,
      warnings,
      `${context}.propertyNames`
    );
  }

  // Convert contains
  if (converted.contains) {
    converted.contains = convertSchema(converted.contains, warnings, `${context}.contains`);
  }

  // Convert dependentSchemas (JSON Schema 2019-09+)
  if (converted.dependentSchemas) {
    const newDepSchemas: any = {};
    for (const [prop, depSchema] of Object.entries<any>(converted.dependentSchemas)) {
      newDepSchemas[prop] = convertSchema(depSchema, warnings, `${context}.dependentSchemas.${prop}`);
    }
    converted.dependentSchemas = newDepSchemas;
  }

  // Convert dependencies (draft-07 and earlier) to dependentSchemas/dependentRequired
  if (converted.dependencies) {
    const dependentSchemas: any = {};
    const dependentRequired: any = {};

    for (const [prop, dep] of Object.entries<any>(converted.dependencies)) {
      if (Array.isArray(dep)) {
        // Property dependency -> dependentRequired
        dependentRequired[prop] = dep;
      } else {
        // Schema dependency -> dependentSchemas
        dependentSchemas[prop] = convertSchema(dep, warnings, `${context}.dependencies.${prop}`);
      }
    }

    delete converted.dependencies;

    if (Object.keys(dependentSchemas).length > 0) {
      converted.dependentSchemas = dependentSchemas;
    }
    if (Object.keys(dependentRequired).length > 0) {
      converted.dependentRequired = dependentRequired;
    }
  }

  // Handle exclusiveMinimum/exclusiveMaximum (draft-04 format)
  // In draft-04, these are booleans; in draft-06+, they are numbers
  if (typeof converted.exclusiveMinimum === 'boolean') {
    if (converted.exclusiveMinimum && converted.minimum !== undefined) {
      converted.exclusiveMinimum = converted.minimum;
      delete converted.minimum;
    } else {
      delete converted.exclusiveMinimum;
    }
  }
  if (typeof converted.exclusiveMaximum === 'boolean') {
    if (converted.exclusiveMaximum && converted.maximum !== undefined) {
      converted.exclusiveMaximum = converted.maximum;
      delete converted.maximum;
    } else {
      delete converted.exclusiveMaximum;
    }
  }

  // Handle contentEncoding and contentMediaType (keep as-is, supported in OpenAPI 3.1)

  // Handle examples (convert to example if single value)
  if (converted.examples && Array.isArray(converted.examples) && converted.examples.length === 1) {
    converted.example = converted.examples[0];
    delete converted.examples;
  }

  return converted;
}

/**
 * Convert a $ref path from JSON Schema format to OpenAPI format
 */
function convertRefPath(ref: string): string {
  // Already in OpenAPI format
  if (ref.startsWith('#/components/schemas/')) {
    return ref;
  }

  // Convert #/definitions/Name to #/components/schemas/Name
  if (ref.startsWith('#/definitions/')) {
    return ref.replace('#/definitions/', '#/components/schemas/');
  }

  // Convert #/$defs/Name to #/components/schemas/Name
  if (ref.startsWith('#/$defs/')) {
    return ref.replace('#/$defs/', '#/components/schemas/');
  }

  // Handle simple #/Name references
  if (ref.startsWith('#/') && !ref.includes('/definitions/') && !ref.includes('/$defs/')) {
    const parts = ref.split('/');
    if (parts.length === 2) {
      return `#/components/schemas/${parts[1]}`;
    }
  }

  // Handle external references (keep as-is for now, add warning)
  if (!ref.startsWith('#')) {
    // External reference - keep as-is but it may not resolve
    return ref;
  }

  return ref;
}

/**
 * Check if a document is a JSON Schema
 */
export function isJsonSchema(doc: any): boolean {
  if (!doc || typeof doc !== 'object') {
    return false;
  }

  // Has explicit $schema field
  if (doc.$schema && typeof doc.$schema === 'string') {
    return doc.$schema.includes('json-schema.org');
  }

  // Looks like a schema (has type, properties, etc.) but no openapi/swagger fields
  if (doc.openapi || doc.swagger || doc.asyncapi || doc.arazzo) {
    return false;
  }

  // Has schema-like structure
  return isSchemaDefinition(doc);
}

/**
 * Get the JSON Schema version from a document
 */
export function getJsonSchemaVersion(doc: any): string | null {
  if (!doc || !doc.$schema) {
    return null;
  }

  const version = detectSchemaVersion(doc);
  return version;
}

/**
 * Infer a schema type if not explicitly specified
 */
export function inferSchemaType(schema: any): string | null {
  if (schema.type) {
    return Array.isArray(schema.type) ? schema.type[0] : schema.type;
  }

  if (schema.properties || schema.additionalProperties || schema.patternProperties) {
    return 'object';
  }

  if (schema.items || schema.prefixItems || schema.contains) {
    return 'array';
  }

  if (schema.minimum !== undefined || schema.maximum !== undefined ||
      schema.exclusiveMinimum !== undefined || schema.exclusiveMaximum !== undefined ||
      schema.multipleOf !== undefined) {
    return 'number';
  }

  if (schema.minLength !== undefined || schema.maxLength !== undefined ||
      schema.pattern !== undefined || schema.format === 'email' ||
      schema.format === 'uri' || schema.format === 'date' ||
      schema.format === 'date-time') {
    return 'string';
  }

  return null;
}

