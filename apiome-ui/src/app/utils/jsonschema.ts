/**
 * JSON Schema Generator Utilities
 *
 * Generates JSON Schema (Draft 2020-12) documents from class definitions.
 * JSON Schema is a vocabulary that allows you to annotate and validate JSON documents.
 */

import { buildClassSchema } from './openapi';

/**
 * Converts OpenAPI-style $ref paths to JSON Schema $defs paths
 * OpenAPI uses: #/components/schemas/ClassName
 * JSON Schema uses: #/$defs/ClassName
 */
export function convertRefsToJsonSchema(obj: any): any {
  if (obj === null || obj === undefined) {
    return obj;
  }

  if (Array.isArray(obj)) {
    return obj.map(item => convertRefsToJsonSchema(item));
  }

  if (typeof obj === 'object') {
    const result: any = {};
    for (const key in obj) {
      if (obj.hasOwnProperty(key)) {
        if (key === '$ref' && typeof obj[key] === 'string') {
          // Convert OpenAPI-style refs to JSON Schema $defs refs
          // #/components/schemas/ClassName -> #/$defs/ClassName
          // #/definitions/ClassName -> #/$defs/ClassName (Swagger 2.0 style)
          let refPath = obj[key];
          if (refPath.startsWith('#/components/schemas/')) {
            refPath = refPath.replace('#/components/schemas/', '#/$defs/');
          } else if (refPath.startsWith('#/definitions/')) {
            refPath = refPath.replace('#/definitions/', '#/$defs/');
          }
          result[key] = refPath;
        } else {
          result[key] = convertRefsToJsonSchema(obj[key]);
        }
      }
    }
    return result;
  }

  return obj;
}

/**
 * Generates a JSON Schema document from class definitions
 * @param classes - Array of class data objects with properties
 * @param options - Optional metadata for the schema
 * @returns JSON Schema document as a JSON string
 */
export function generateJsonSchema(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    metadata?: {
      summary?: string;
      termsOfService?: string;
      contact?: {
        name?: string;
        url?: string;
        email?: string;
      };
      license?: {
        name?: string;
        identifier?: string;
        url?: string;
      };
    };
  }
): string {
  const definitions: any = {};

  // Build schema for each class using the same logic as OpenAPI
  // JSON Schema uses $defs instead of components/schemas for definitions
  classes.forEach((cls) => {
    // Build the schema and convert any $ref paths to JSON Schema format
    const classSchema = buildClassSchema(cls);
    definitions[cls.name] = convertRefsToJsonSchema(classSchema);
  });

  const jsonSchemaDoc: any = {
    $schema: 'https://json-schema.org/draft/2020-12/schema',
    $id: `https://example.com/${options?.projectName?.toLowerCase().replace(/\s+/g, '-') || 'schema'}.json`,
    title: options?.projectName || 'JSON Schema',
    description: options?.description || `Generated JSON Schema from Apiome Studio - Version ${options?.version || '1.0.0'}`,
    type: 'object',
    $defs: definitions
  };

  // Add project metadata to top level as x-metadata extension
  if (options?.metadata && Object.keys(options.metadata).length > 0) {
    jsonSchemaDoc['x-metadata'] = options.metadata;
  }

  return JSON.stringify(jsonSchemaDoc, null, 2);
}

