/**
 * OpenAPI Import Utilities
 *
 * Handles parsing and validation of OpenAPI specifications for import
 * into the Objectified platform
 */

import YAML from 'yaml';
import { convertSwaggerToOpenAPI, isSwagger2 } from './swagger-converter';
import { convertJsonSchemaToOpenAPI, isJsonSchema } from './jsonschema-converter';
import { convertGraphQLToOpenAPI, isGraphQL, isGraphQLIntrospection, convertGraphQLIntrospectionToOpenAPI } from './graphql-converter';

export interface ParsedProperty {
  name: string;
  data: any;
  description?: string;
  children?: ParsedProperty[]; // For nested properties
}

export interface ParsedClass {
  name: string;
  description?: string;
  properties: ParsedProperty[];
  selected: boolean;
  warnings: string[];
  isSupported: boolean;
  schema?: any; // Original schema structure (may include allOf/anyOf/oneOf)
}

export interface OpenAPIParseResult {
  success: boolean;
  classes: ParsedClass[];
  error?: string;
  warnings: string[];
  version?: string;
  title?: string;
  description?: string;
}

/**
 * Extracts all $ref references from a schema
 */
function extractReferences(obj: any, refs: Set<string> = new Set()): Set<string> {
  if (!obj || typeof obj !== 'object') return refs;

  if (obj.$ref && typeof obj.$ref === 'string') {
    // Extract the schema name from the $ref path
    const match = obj.$ref.match(/#\/components\/schemas\/(.+)/);
    if (match) {
      refs.add(match[1]);
    }
  }

  // Recursively check nested objects and arrays
  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      extractReferences(obj[key], refs);
    }
  }

  return refs;
}

/**
 * Finds unresolved $ref references in a schema
 */
function findUnresolvedReferences(schema: any, allSchemaNames: Set<string>): string[] {
  const refs = extractReferences(schema);
  const unresolved: string[] = [];

  for (const ref of refs) {
    if (!allSchemaNames.has(ref)) {
      unresolved.push(ref);
    }
  }

  return unresolved;
}

/**
 * Resolves a $ref reference to the actual schema object
 */
function resolveReference(ref: string, schemas: any): any {
  const match = ref.match(/#\/components\/schemas\/(.+)/);
  if (match && schemas[match[1]]) {
    return schemas[match[1]];
  }
  return null;
}

/**
 * Resolves allOf compositions by merging all schemas together
 */
function resolveAllOf(schema: any, schemas: any): any {
  if (!schema.allOf || !Array.isArray(schema.allOf)) {
    return schema;
  }

  const merged: any = {
    type: 'object',
    properties: {},
    required: []
  };

  // Preserve description from the parent schema if present
  if (schema.description) {
    merged.description = schema.description;
  }

  // Merge each schema in allOf
  for (const item of schema.allOf) {
    let itemSchema: any;

    // Resolve $ref if present
    if (item.$ref) {
      itemSchema = resolveReference(item.$ref, schemas);
      if (!itemSchema) {
        continue; // Skip unresolved references
      }
      // Recursively resolve allOf in referenced schema
      itemSchema = resolveAllOf(itemSchema, schemas);
    } else {
      itemSchema = item;
    }

    // Merge properties
    if (itemSchema.properties) {
      merged.properties = { ...merged.properties, ...itemSchema.properties };
    }

    // Merge required arrays
    if (itemSchema.required && Array.isArray(itemSchema.required)) {
      merged.required = [...merged.required, ...itemSchema.required];
    }

    // Merge type (prefer object if any schema specifies it)
    if (itemSchema.type) {
      merged.type = itemSchema.type;
    }

    // Use description from first schema that has one
    if (!merged.description && itemSchema.description) {
      merged.description = itemSchema.description;
    }
  }

  // Remove empty required array
  if (merged.required.length === 0) {
    delete merged.required;
  }

  return merged;
}

/**
 * Extracts only the properties directly defined in this schema (not from $ref)
 * For allOf schemas, returns only properties from inline object definitions
 */
function extractDirectProperties(schema: any): { properties: any; required: string[] } {
  const result = {
    properties: {},
    required: [] as string[]
  };

  // If schema has allOf, extract properties from inline objects only (not from $refs)
  if (schema.allOf && Array.isArray(schema.allOf)) {
    for (const item of schema.allOf) {
      // Skip $ref items - those are inherited
      if (item.$ref) {
        continue;
      }

      // Merge properties from inline definitions
      if (item.properties) {
        result.properties = { ...result.properties, ...item.properties };
      }

      // Merge required arrays
      if (item.required && Array.isArray(item.required)) {
        result.required = [...result.required, ...item.required];
      }
    }
    return result;
  }

  // For anyOf/oneOf, we can't really determine which properties are "direct"
  // so we'll include all properties if it's a simple schema
  if (schema.anyOf || schema.oneOf) {
    // Don't extract properties from composition schemas
    return result;
  }

  // Normal schema - return its properties
  return {
    properties: schema.properties || {},
    required: schema.required || []
  };
}

/**
 * Converts an OpenAPI schema property to a property data object with nested children
 */
function convertSchemaProperty(propName: string, propSchema: any, required: string[] = []): ParsedProperty {
  const data: any = { ...propSchema };

  // Remove description from data (it's stored separately)
  const description = data.description;
  delete data.description;

  // Handle required flag
  if (required.includes(propName)) {
    data.required = true;
  }

  const result: ParsedProperty = {
    name: propName,
    data,
    description
  };

  // Handle inline object properties with nested properties
  if (propSchema.type === 'object' && propSchema.properties) {
    const nestedRequired = propSchema.required || [];
    const children: ParsedProperty[] = [];

    // Remove properties and required from data (they'll be stored as children)
    delete data.properties;
    delete data.required;

    // Recursively convert nested properties
    for (const childName in propSchema.properties) {
      const childSchema = propSchema.properties[childName];
      children.push(convertSchemaProperty(childName, childSchema, nestedRequired));
    }

    result.children = children;
  }

  // Handle arrays of objects with inline properties
  if (propSchema.type === 'array' && propSchema.items?.type === 'object' && propSchema.items.properties) {
    const nestedRequired = propSchema.items.required || [];
    const children: ParsedProperty[] = [];

    // Remove properties and required from items in data
    const items = { ...propSchema.items };
    delete items.properties;
    delete items.required;
    data.items = items;

    // Recursively convert nested properties from items
    for (const childName in propSchema.items.properties) {
      const childSchema = propSchema.items.properties[childName];
      children.push(convertSchemaProperty(childName, childSchema, nestedRequired));
    }

    result.children = children;
  }

  return result;
}

/**
 * Parses an OpenAPI specification and extracts classes/schemas
 */
export function parseOpenAPISpec(specContent: string): OpenAPIParseResult {
  try {
    let spec: any;

    // Check if this is GraphQL SDL content first
    if (isGraphQL(specContent)) {
      const conversionResult = convertGraphQLToOpenAPI(specContent);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `GraphQL conversion failed: ${conversionResult.error}`
        };
      }

      // Use the converted spec
      spec = conversionResult.document;

      // Add conversion warnings to global warnings
      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from GraphQL Schema to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from GraphQL Schema to OpenAPI 3.1.x'];

      // Continue with the converted spec
      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Try to parse as JSON first, then YAML
    try {
      spec = JSON.parse(specContent);
    } catch {
      // If JSON parsing fails, try YAML
      spec = YAML.parse(specContent);
    }

    // Check for Swagger 2.x and convert if needed
    if (isSwagger2(spec)) {
      const conversionResult = convertSwaggerToOpenAPI(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `Swagger conversion failed: ${conversionResult.error}`
        };
      }

      // Use the converted spec
      spec = conversionResult.document;

      // Add conversion warnings to global warnings
      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from Swagger 2.x to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from Swagger 2.x to OpenAPI 3.1.x'];

      // Continue with the converted spec
      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Check for JSON Schema and convert if needed
    if (isJsonSchema(spec)) {
      const conversionResult = convertJsonSchemaToOpenAPI(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `JSON Schema conversion failed: ${conversionResult.error}`
        };
      }

      // Use the converted spec
      spec = conversionResult.document;

      // Add conversion warnings to global warnings
      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from JSON Schema to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from JSON Schema to OpenAPI 3.1.x'];

      // Continue with the converted spec
      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Check for GraphQL introspection result and convert if needed
    if (isGraphQLIntrospection(spec)) {
      const conversionResult = convertGraphQLIntrospectionToOpenAPI(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `GraphQL introspection conversion failed: ${conversionResult.error}`
        };
      }

      // Use the converted spec
      spec = conversionResult.document;

      // Add conversion warnings to global warnings
      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from GraphQL introspection to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from GraphQL introspection to OpenAPI 3.1.x'];

      // Continue with the converted spec
      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Validate OpenAPI version
    if (!spec.openapi || !spec.openapi.startsWith('3.')) {
      // Check if this might be GraphQL SDL that wasn't parsed yet
      // (This shouldn't normally happen as YAML.parse would fail on GraphQL SDL)
      return {
        success: false,
        classes: [],
        warnings: [],
        error: 'Only OpenAPI 3.x specifications are supported'
      };
    }

    return parseOpenAPISpecInternal(spec, []);
  } catch (error: any) {
    return {
      success: false,
      classes: [],
      warnings: [],
      error: `Failed to parse OpenAPI specification: ${error.message}`
    };
  }
}

/**
 * Internal function that parses an already-validated OpenAPI 3.x specification
 */
function parseOpenAPISpecInternal(spec: any, initialWarnings: string[]): OpenAPIParseResult {
  const globalWarnings: string[] = [...initialWarnings];

  // Extract components/schemas
  if (!spec.components || !spec.components.schemas) {
    return {
      success: false,
      classes: [],
      warnings: globalWarnings,
      error: 'No schemas found in OpenAPI specification'
    };
  }

  const schemas = spec.components.schemas;
  const classes: ParsedClass[] = [];

  // Get all schema names for reference validation
  const allSchemaNames = new Set(Object.keys(schemas));

  // Convert each schema to a class
  for (const schemaName in schemas) {
    const originalSchema = schemas[schemaName];
    const warnings: string[] = [];
    let isSupported = true;

    // Resolve allOf compositions for validation and reference checking
    const resolvedSchema = resolveAllOf(originalSchema, schemas);

    // Check for unresolved $ref references
    const unresolvedRefs = findUnresolvedReferences(resolvedSchema, allSchemaNames);
    if (unresolvedRefs.length > 0) {
      warnings.push(
        `References undefined schemas: ${unresolvedRefs.join(', ')}. ` +
        `These referenced schemas do not exist in the specification.`
      );
      isSupported = false;
    }

    // Extract ONLY direct properties (not inherited via $ref in allOf)
    // This prevents storing duplicate properties that come from parent schemas
    const { properties: directProperties, required: directRequired } = extractDirectProperties(originalSchema);

    const properties: ParsedProperty[] = [];

    // Convert only the direct properties for storage
    for (const propName in directProperties) {
      const propSchema = directProperties[propName];
      properties.push(convertSchemaProperty(propName, propSchema, directRequired));
    }

    classes.push({
      name: schemaName,
      description: originalSchema.description || resolvedSchema.description,
      properties,
      selected: isSupported, // Only select supported classes by default
      warnings,
      isSupported,
      schema: originalSchema // Preserve original schema with compositions
    });

    // Add to global warnings if unsupported
    if (!isSupported) {
      globalWarnings.push(`${schemaName}: ${warnings.join(' ')}`);
    }
  }

  const supportedClasses = classes.filter(c => c.isSupported);

  if (supportedClasses.length === 0) {
    return {
      success: false,
      classes: [],
      warnings: globalWarnings,
      error: 'No supported schemas found to import. All schemas have unresolved references.'
    };
  }

  return {
    success: true,
    classes,
    warnings: globalWarnings,
    version: spec.info?.version,
    title: spec.info?.title,
    description: spec.info?.description
  };
}

/**
 * Validates that imported classes don't have duplicate property names
 */
export function validateImportedClasses(classes: ParsedClass[]): { valid: boolean; errors: string[] } {
  const errors: string[] = [];

  for (const cls of classes) {
    if (!cls.selected) continue;

    const propNames = new Set<string>();
    for (const prop of cls.properties) {
      if (propNames.has(prop.name)) {
        errors.push(`Class "${cls.name}" has duplicate property: ${prop.name}`);
      }
      propNames.add(prop.name);
    }

    if (cls.properties.length === 0) {
      errors.push(`Class "${cls.name}" has no properties`);
    }
  }

  return {
    valid: errors.length === 0,
    errors
  };
}
