/**
 * OpenAPI Import Utilities
 *
 * Handles parsing and validation of OpenAPI specifications for import
 * into the Apiome platform
 */

import YAML from 'yaml';
import { extractDirectProperties } from './openapi-schema-direct-properties';
import { convertSwaggerToOpenAPI, isSwagger2 } from './swagger-converter';
import { convertJsonSchemaToOpenAPI, isJsonSchema } from './jsonschema-converter';
import { convertGraphQLToOpenAPI, isGraphQL, isGraphQLIntrospection, convertGraphQLIntrospectionToOpenAPI } from './graphql-converter';
import { convertOpenAPI30ToOpenAPI31, isOpenAPI30 } from './openapi30-converter';
import { convertOpenAPI32ToOpenAPI31, isOpenAPI32 } from './openapi32-converter';
import { convertRAMLToOpenAPI, isRAML } from './raml-converter';
import { convertProtobufToOpenAPI, isProtobuf } from './protobuf-converter';
import { convertAvroToOpenAPI, isAvroSchemaObject } from './avro-converter';
import { convertThriftToOpenAPI, isThrift } from './thrift-converter';

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

/** Parsed OpenAPI path item: path pattern + operations (#425) */
export interface ParsedPath {
  path: string;
  summary?: string;
  description?: string;
  parameters?: Array<{ name: string; in: string; required?: boolean; description?: string; schema?: Record<string, unknown> }>;
  operations: ParsedOperation[];
}

/** Parsed OpenAPI operation (get, post, etc.) */
export interface ParsedOperation {
  method: string;
  operationId?: string;
  summary?: string;
  description?: string;
  tags?: string[];
  deprecated?: boolean;
  parameters: Array<{ name: string; in: string; required?: boolean; description?: string; schema?: Record<string, unknown> }>;
  requestBody?: {
    required?: boolean;
    description?: string;
    content: Record<string, { schema?: Record<string, unknown>; $ref?: string }>;
  };
  responses: Record<string, { description?: string; content?: Record<string, { schema?: Record<string, unknown>; $ref?: string }>; headers?: Record<string, unknown>; links?: Record<string, unknown> }>;
  security?: Record<string, string[]>;
}

/** Parsed OpenAPI security scheme (components.securitySchemes) */
export interface ParsedSecurityScheme {
  scheme_name: string;
  scheme_type: 'apiKey' | 'http' | 'oauth2' | 'openIdConnect' | 'mutualTLS';
  in_location?: 'header' | 'query' | 'cookie';
  param_name?: string;
  http_scheme?: string;
  description?: string;
  data?: Record<string, unknown>;
}

/** OpenAPI info object (title, version, description, etc.) */
export interface ParsedOpenAPIInfo {
  title?: string;
  version?: string;
  description?: string;
  termsOfService?: string;
  contact?: { name?: string; url?: string; email?: string };
  license?: { name: string; identifier?: string; url?: string };
}

/** OpenAPI server entry */
export interface ParsedOpenAPIServer {
  url: string;
  description?: string;
  variables?: Record<string, { default: string; enum?: string[]; description?: string }>;
}

export interface OpenAPIParseResult {
  success: boolean;
  classes: ParsedClass[];
  error?: string;
  warnings: string[];
  version?: string;
  title?: string;
  description?: string;
  /** OpenAPI 3.1 paths (pathing) - #425 */
  paths?: ParsedPath[];
  /** OpenAPI 3.1 components.securitySchemes - #425 */
  securitySchemes?: ParsedSecurityScheme[];
  /** Full info object for import */
  info?: ParsedOpenAPIInfo;
  /** Servers array for import */
  servers?: ParsedOpenAPIServer[];
  /** Top-level tags */
  tags?: Array<{ name: string; description?: string }>;
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
 * Resolves allOf compositions by merging all schemas together.
 * Tracks visited $refs so circular allOf chains do not cause infinite recursion
 * (which previously surfaced as "Maximum call stack size exceeded" and aborted
 * the entire import).
 */
function resolveAllOf(schema: any, schemas: any, seen: Set<string> = new Set()): any {
  if (!schema || typeof schema !== 'object') return schema;
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
    if (!item || typeof item !== 'object') continue;
    let itemSchema: any;

    // Resolve $ref if present
    if (item.$ref) {
      if (seen.has(item.$ref)) {
        // Circular reference - skip to avoid infinite recursion
        continue;
      }
      itemSchema = resolveReference(item.$ref, schemas);
      if (!itemSchema) {
        continue; // Skip unresolved references
      }
      const nextSeen = new Set(seen);
      nextSeen.add(item.$ref);
      // Recursively resolve allOf in referenced schema
      itemSchema = resolveAllOf(itemSchema, schemas, nextSeen);
    } else {
      itemSchema = resolveAllOf(item, schemas, seen);
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

export { extractDirectProperties };

/**
 * Converts an OpenAPI schema property to a property data object with nested children.
 * Hardened to tolerate malformed inputs (null/non-object property schemas, non-array
 * `required`) so a single bad property does not abort the entire import.
 */
function convertSchemaProperty(propName: string, propSchema: any, required: string[] = []): ParsedProperty {
  // Defensive: tolerate null / non-object property schemas (some real-world specs
  // emit `properties: { foo: null }` or boolean schemas from JSON Schema 2020-12).
  const safeSchema: any = propSchema && typeof propSchema === 'object' ? propSchema : {};
  const data: any = { ...safeSchema };

  // Remove description from data (it's stored separately)
  const description = data.description;
  delete data.description;

  // Handle required flag — `required` from caller may be a non-array if the spec
  // is malformed; treat anything other than an array of strings as "no requireds".
  const requiredList = Array.isArray(required) ? required.filter((r) => typeof r === 'string') : [];
  if (requiredList.includes(propName)) {
    data.required = true;
  }

  const result: ParsedProperty = {
    name: propName,
    data,
    description
  };

  // Handle inline object properties with nested properties
  if (safeSchema.type === 'object' && safeSchema.properties && typeof safeSchema.properties === 'object') {
    const nestedRequired = Array.isArray(safeSchema.required) ? safeSchema.required : [];
    const children: ParsedProperty[] = [];

    // Remove properties and required from data (they'll be stored as children)
    delete data.properties;
    delete data.required;

    // Recursively convert nested properties
    for (const childName in safeSchema.properties) {
      const childSchema = safeSchema.properties[childName];
      children.push(convertSchemaProperty(childName, childSchema, nestedRequired));
    }

    result.children = children;
  }

  // Handle arrays of objects with inline properties
  if (
    safeSchema.type === 'array' &&
    safeSchema.items && typeof safeSchema.items === 'object' &&
    safeSchema.items.type === 'object' &&
    safeSchema.items.properties && typeof safeSchema.items.properties === 'object'
  ) {
    const nestedRequired = Array.isArray(safeSchema.items.required) ? safeSchema.items.required : [];
    const children: ParsedProperty[] = [];

    // Remove properties and required from items in data
    const items = { ...safeSchema.items };
    delete items.properties;
    delete items.required;
    data.items = items;

    // Recursively convert nested properties from items
    for (const childName in safeSchema.items.properties) {
      const childSchema = safeSchema.items.properties[childName];
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

    // Check GraphQL first so that schemas with enum/union/type are not misdetected as Protobuf or Thrift
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

      spec = conversionResult.document;

      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from GraphQL Schema to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from GraphQL Schema to OpenAPI 3.1.x'];

      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Check if this is Protobuf (.proto) content (#238)
    if (isProtobuf(specContent)) {
      const conversionResult = convertProtobufToOpenAPI(specContent);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `Protobuf conversion failed: ${conversionResult.error}`
        };
      }

      spec = conversionResult.document;

      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from Protocol Buffers to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from Protocol Buffers to OpenAPI 3.1.x'];

      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Thrift IDL (.thrift) — after GraphQL so enum/union-heavy GraphQL is not misdetected
    if (isThrift(specContent)) {
      const conversionResult = convertThriftToOpenAPI(specContent);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `Thrift conversion failed: ${conversionResult.error}`
        };
      }

      spec = conversionResult.document;

      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from Apache Thrift to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from Apache Thrift to OpenAPI 3.1.x'];

      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Try to parse as JSON first, then YAML
    try {
      spec = JSON.parse(specContent);
    } catch {
      // If JSON parsing fails, try YAML
      spec = YAML.parse(specContent);
    }

    // Check for Apache Avro (.avsc) and convert if needed (#239)
    if (isAvroSchemaObject(spec)) {
      const conversionResult = convertAvroToOpenAPI(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `Avro conversion failed: ${conversionResult.error}`
        };
      }

      spec = conversionResult.document;

      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from Apache Avro to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from Apache Avro to OpenAPI 3.1.x'];

      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Check for RAML and convert if needed (#237)
    if (isRAML(spec)) {
      const conversionResult = convertRAMLToOpenAPI(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `RAML conversion failed: ${conversionResult.error}`
        };
      }

      spec = conversionResult.document;

      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from RAML to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : ['Successfully converted from RAML to OpenAPI 3.1.x'];

      return parseOpenAPISpecInternal(spec, globalWarnings);
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

    // Check for OpenAPI 3.0.x and convert if needed
    if (isOpenAPI30(spec)) {
      const originalVersion = spec.openapi || '3.0';
      const conversionResult = convertOpenAPI30ToOpenAPI31(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `OpenAPI 3.0 conversion failed: ${conversionResult.error}`
        };
      }

      // Use the converted spec
      spec = conversionResult.document;

      // Add conversion warnings to global warnings
      const globalWarnings = conversionResult.warnings.length > 0
        ? [`Converted from OpenAPI ${originalVersion} to OpenAPI 3.1.x with ${conversionResult.warnings.length} conversion notes`]
        : [`Successfully converted from OpenAPI ${originalVersion} to OpenAPI 3.1.x`];

      // Continue with the converted spec
      return parseOpenAPISpecInternal(spec, globalWarnings);
    }

    // Check for OpenAPI 3.2.0 and normalize to 3.1.x if needed (OA2, #3499).
    // Runs after the OA1 routing decision (3.2.x is accepted) so 3.2-only constructs
    // are transformed/stashed rather than silently dropped by the 3.1 importer.
    if (isOpenAPI32(spec)) {
      const originalVersion = spec.openapi || '3.2.0';
      const conversionResult = convertOpenAPI32ToOpenAPI31(spec);

      if (!conversionResult.success) {
        return {
          success: false,
          classes: [],
          warnings: conversionResult.warnings,
          error: `OpenAPI 3.2 conversion failed: ${conversionResult.error}`
        };
      }

      // Use the normalized spec.
      spec = conversionResult.document;

      // Surface conversion notes plus any carried-forward 3.2-only constructs.
      const constructNotes = conversionResult.unsupportedConstructs.map(
        (c) => `${c.label}: ${c.description} (${c.count} occurrence${c.count === 1 ? '' : 's'})`
      );
      const globalWarnings = [
        `Normalized OpenAPI ${originalVersion} to OpenAPI 3.1.x for import`,
        ...conversionResult.warnings,
        ...constructNotes
      ];

      // Continue with the normalized spec.
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

    // Validate parsed spec is a plain object before reading properties on it
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) {
      return {
        success: false,
        classes: [],
        warnings: [],
        error: 'Invalid specification: expected an OpenAPI document object'
      };
    }

    // Validate OpenAPI version
    if (!spec.openapi || typeof spec.openapi !== 'string' || !spec.openapi.startsWith('3.')) {
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

/** Extract $ref schema name from reference string */
function getRefSchemaName(ref: string | undefined): string | null {
  if (!ref || typeof ref !== 'string') return null;
  const m = ref.match(/#\/components\/schemas\/(.+)/);
  return m ? m[1] : null;
}

/** Normalize OpenAPI schema for storage (inline or $ref) */
function normalizeContentSchema(mediaObj: any): { schema?: Record<string, unknown>; $ref?: string } | undefined {
  if (!mediaObj || typeof mediaObj !== 'object') return undefined;
  const s = mediaObj.schema;
  if (!s) return undefined;
  if (s.$ref) return { $ref: s.$ref };
  return { schema: s };
}

/**
 * Extract paths from OpenAPI spec.paths (OpenAPI 3.1 pathing - #425).
 * Exported for use by import-helper when importing OpenAPI via startImport.
 */
export function extractPaths(spec: any): ParsedPath[] {
  const pathObj = spec.paths;
  if (!pathObj || typeof pathObj !== 'object') return [];

  const methods = ['get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'];
  const result: ParsedPath[] = [];

  for (const path of Object.keys(pathObj)) {
    if (path.startsWith('/') === false) continue;
    const pathItem = pathObj[path];
    if (!pathItem || typeof pathItem !== 'object') continue;

    const pathParams = Array.isArray(pathItem.parameters)
      ? pathItem.parameters.map((p: any) => ({
          name: p.name || '',
          in: (p.in || 'query').toLowerCase(),
          required: p.required === true,
          description: p.description,
          schema: p.schema,
        }))
      : [];

    const operations: ParsedOperation[] = [];

    for (const method of methods) {
      const op = pathItem[method];
      if (!op || typeof op !== 'object') continue;

      const opParams = Array.isArray(op.parameters)
        ? op.parameters.map((p: any) => ({
            name: p.name || '',
            in: (p.in || 'query').toLowerCase(),
            required: p.required === true,
            description: p.description,
            schema: p.schema,
          }))
        : [];

      const allParams = [...pathParams];
      for (const p of opParams) {
        const existing = allParams.findIndex((x: { name: string; in: string }) => x.name === p.name && x.in === p.in);
        if (existing >= 0) allParams[existing] = p;
        else allParams.push(p);
      }

      let requestBody: ParsedOperation['requestBody'] | undefined;
      if (op.requestBody && typeof op.requestBody === 'object') {
        const content = op.requestBody.content;
        if (content && typeof content === 'object') {
          const contentMap: Record<string, { schema?: Record<string, unknown>; $ref?: string }> = {};
          for (const [mediaType, mediaObj] of Object.entries(content)) {
            const norm = normalizeContentSchema(mediaObj as any);
            if (norm) contentMap[mediaType] = norm;
          }
          if (Object.keys(contentMap).length > 0) {
            requestBody = {
              required: op.requestBody.required === true,
              description: op.requestBody.description,
              content: contentMap,
            };
          }
        }
      }

      const responses: ParsedOperation['responses'] = {};
      if (op.responses && typeof op.responses === 'object') {
        for (const [status, res] of Object.entries(op.responses)) {
          const r = res as any;
          if (!r || typeof r !== 'object') continue;
          const content: Record<string, { schema?: Record<string, unknown>; $ref?: string }> = {};
          if (r.content && typeof r.content === 'object') {
            for (const [mediaType, mediaObj] of Object.entries(r.content)) {
              const norm = normalizeContentSchema(mediaObj as any);
              if (norm) content[mediaType] = norm;
            }
          }
          responses[status] = {
            description: r.description,
            content: Object.keys(content).length > 0 ? content : undefined,
            headers: r.headers,
            links: r.links,
          };
        }
      }

      operations.push({
        method: method.toUpperCase(),
        operationId: op.operationId,
        summary: op.summary,
        description: op.description,
        tags: Array.isArray(op.tags) ? op.tags : undefined,
        deprecated: op.deprecated === true,
        parameters: allParams,
        requestBody,
        responses,
        security: op.security && op.security[0] && typeof op.security[0] === 'object' ? op.security[0] : undefined,
      });
    }

    if (operations.length > 0) {
      result.push({
        path,
        summary: pathItem.summary,
        description: pathItem.description,
        parameters: pathParams.length > 0 ? pathParams : undefined,
        operations,
      });
    }
  }

  return result;
}

/**
 * Extract security schemes from OpenAPI spec.components.securitySchemes (#425).
 * Exported for use by import-helper when importing OpenAPI via startImport.
 */
export function extractSecuritySchemes(spec: any): ParsedSecurityScheme[] {
  const schemes = spec.components?.securitySchemes;
  if (!schemes || typeof schemes !== 'object') return [];

  const result: ParsedSecurityScheme[] = [];

  for (const name of Object.keys(schemes)) {
    const def = schemes[name];
    if (!def || typeof def !== 'object') continue;

    const rawType = (def.type || (def.scheme ? 'http' : 'apiKey')).toString().toLowerCase();
    const schemeType: ParsedSecurityScheme['scheme_type'] =
      rawType === 'apikey' ? 'apiKey'
      : rawType === 'http' ? 'http'
      : rawType === 'oauth2' ? 'oauth2'
      : rawType === 'openidconnect' ? 'openIdConnect'
      : rawType === 'mutualtls' ? 'mutualTLS'
      : 'apiKey';

    const parsed: ParsedSecurityScheme = {
      scheme_name: name,
      scheme_type: schemeType,
      description: def.description,
    };

    if (schemeType === 'apiKey') {
      parsed.in_location = (def.in || 'header') as 'header' | 'query' | 'cookie';
      parsed.param_name = def.name || name;
    } else if (schemeType === 'http') {
      parsed.http_scheme = (def.scheme || 'bearer').toString().toLowerCase();
      parsed.data = {};
      if (def.bearerFormat) (parsed.data as any).bearerFormat = def.bearerFormat;
    } else if (schemeType === 'oauth2') {
      parsed.data = { flows: def.flows || {} };
    } else if (schemeType === 'openIdConnect') {
      parsed.data = { openIdConnectUrl: def.openIdConnectUrl || '' };
    } else if (schemeType === 'mutualTLS') {
      parsed.data = {};
    }

    result.push(parsed);
  }

  return result;
}

/**
 * Internal function that parses an already-validated OpenAPI 3.x specification
 * Supports full OpenAPI 3.1.0: schemas, paths, securitySchemes, info, servers, tags (#425)
 */
function parseOpenAPISpecInternal(spec: any, initialWarnings: string[]): OpenAPIParseResult {
  const globalWarnings: string[] = [...initialWarnings];

  const schemas = spec.components?.schemas;
  const hasSchemas = schemas && typeof schemas === 'object' && Object.keys(schemas).length > 0;
  const classes: ParsedClass[] = [];

  if (hasSchemas) {
    const allSchemaNames = new Set(Object.keys(schemas));

    for (const schemaName in schemas) {
      const originalSchema = schemas[schemaName];
      const warnings: string[] = [];
      let isSupported = true;
      let properties: ParsedProperty[] = [];
      let resolvedDescription: string | undefined;

      // Isolate per-schema parse work so a single malformed schema does not
      // abort the entire import (e.g. circular allOf, null property values).
      try {
        if (!originalSchema || typeof originalSchema !== 'object') {
          warnings.push('Schema is not an object; skipping.');
          isSupported = false;
        } else {
          const resolvedSchema = resolveAllOf(originalSchema, schemas);
          resolvedDescription = resolvedSchema?.description;
          const unresolvedRefs = findUnresolvedReferences(resolvedSchema, allSchemaNames);
          if (unresolvedRefs.length > 0) {
            warnings.push(
              `References undefined schemas: ${unresolvedRefs.join(', ')}. ` +
              `These referenced schemas do not exist in the specification.`
            );
            isSupported = false;
          }

          const { properties: directProperties, required: directRequired } = extractDirectProperties(originalSchema);
          for (const propName in directProperties) {
            const propSchema = directProperties[propName];
            properties.push(convertSchemaProperty(propName, propSchema, directRequired));
          }
        }
      } catch (err: any) {
        warnings.push(`Failed to parse schema: ${err?.message ?? String(err)}`);
        isSupported = false;
        properties = [];
      }

      classes.push({
        name: schemaName,
        description: (originalSchema && typeof originalSchema === 'object' ? originalSchema.description : undefined) || resolvedDescription,
        properties,
        selected: isSupported,
        warnings,
        isSupported,
        schema: originalSchema,
      });

      if (!isSupported) {
        globalWarnings.push(`${schemaName}: ${warnings.join(' ')}`);
      }
    }
  }

  const supportedClasses = classes.filter(c => c.isSupported);
  const hasPaths = spec.paths && typeof spec.paths === 'object' && Object.keys(spec.paths).length > 0;
  const paths = hasPaths ? extractPaths(spec) : [];
  const securitySchemes = extractSecuritySchemes(spec);
  const hasSecuritySchemes = securitySchemes.length > 0;

  const hasImportableContent = supportedClasses.length > 0 || paths.length > 0 || hasSecuritySchemes;
  if (!hasImportableContent) {
    return {
      success: false,
      classes,
      warnings: globalWarnings,
      error: hasSchemas
        ? 'No supported schemas found to import. All schemas have unresolved references.'
        : 'No schemas, paths, or security schemes found in OpenAPI specification.',
    };
  }

  const info: ParsedOpenAPIInfo | undefined = spec.info && typeof spec.info === 'object'
    ? {
        title: spec.info.title,
        version: spec.info.version,
        description: spec.info.description,
        termsOfService: spec.info.termsOfService,
        contact: spec.info.contact,
        license: spec.info.license,
      }
    : undefined;

  const servers: ParsedOpenAPIServer[] = Array.isArray(spec.servers)
    ? spec.servers.map((s: any) => ({
        url: s.url || '',
        description: s.description,
        variables: s.variables,
      })).filter((s: ParsedOpenAPIServer) => s.url)
    : [];

  const tags = Array.isArray(spec.tags)
    ? spec.tags.map((t: any) => ({ name: t.name || '', description: t.description }))
    : undefined;

  return {
    success: true,
    classes,
    warnings: globalWarnings,
    version: spec.info?.version,
    title: spec.info?.title,
    description: spec.info?.description,
    paths: paths.length > 0 ? paths : undefined,
    securitySchemes: securitySchemes.length > 0 ? securitySchemes : undefined,
    info,
    servers: servers.length > 0 ? servers : undefined,
    tags,
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
