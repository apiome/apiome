/**
 * OpenAPI Paths Generator
 *
 * Generates OpenAPI 3.1.0 paths section from database records.
 * Handles request bodies with both class references and inline schemas,
 * parameters, and responses.
 */

import {
  buildSchemaFromInlineProperties,
  buildRequestBodyForOpenAPI,
  type InlineSchema,
} from './inline-schema-utils';

// =============================================================================
// TYPES
// =============================================================================

/** OpenAPI Security Requirement: maps scheme name to array of scope names (empty for non-OAuth schemes) */
export type SecurityRequirement = Record<string, string[]>;

export interface PathOperationDescription {
  id: string;
  summary?: string;
  description?: string;
  operationId?: string;
  tags?: string[];
  deprecated?: boolean;
  /** When true, hide this operation from Swagger/OpenAPI docs (x-private) */
  'x-private'?: boolean;
  x_private?: boolean;
  externalDocs?: {
    url: string;
    description?: string;
  };
  /** Operation-level security requirements (OpenAPI security array) */
  security?: SecurityRequirement[];
  /** Optional documentation for how security applies (emitted as x-security-description). */
  securityDescription?: string;
}

export interface PathParameter {
  id: string;
  name: string;
  in_location: 'path' | 'query' | 'header' | 'cookie';
  summary?: string;
  description?: string;
  data: Record<string, unknown>;
}

export interface ContentTypeInfo {
  id: string;
  media_type: string;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  encoding?: Record<string, unknown> | null;
  examples?: unknown[] | null;
}

export interface RequestBodyInfo {
  id: string;
  name: string;
  description?: string;
  required: boolean;
  content_types: ContentTypeInfo[];
}

export interface ResponseInfo {
  id: string;
  status_code: string;
  description?: string;
  data?: Record<string, unknown>;
  class_id?: string | null;
  class_name?: string | null;
  inline_schema?: InlineSchema | null;
  content_types?: ContentTypeInfo[]; // Multiple content types like request bodies
}

export interface OperationInfo {
  id: string;
  operation: string; // GET, POST, PUT, PATCH, DELETE, etc.
  description?: PathOperationDescription;
  parameters: PathParameter[];
  requestBody?: RequestBodyInfo | null;
  responses: ResponseInfo[];
}

export interface PathInfo {
  id: string;
  pathname: string;
  summary?: string;
  description?: string;
  operations: OperationInfo[];
}

export interface PathsGeneratorOptions {
  includeExamples?: boolean;
  includeDescriptions?: boolean;
  baseUrl?: string;
}

// =============================================================================
// PARAMETER GENERATION
// =============================================================================

/**
 * Build OpenAPI parameter object from database parameter record
 */
export function buildParameterForOpenAPI(param: PathParameter): Record<string, unknown> {
  const data = param.data || {};

  const result: Record<string, unknown> = {
    name: param.name,
    in: param.in_location,
  };

  // Add summary if present (OpenAPI 3.x parameter field)
  if (param.summary) {
    result.summary = param.summary;
  }
  // Add description if present
  if (param.description) {
    result.description = param.description;
  }

  // Extract required flag from data
  const isRequired = data.required === true || param.in_location === 'path';
  if (isRequired) {
    result.required = true;
  }

  // Inline JSON Schema mode (P-08): full Schema Object stored in data.inlineSchema
  if (data.schemaMode === 'inline' && data.inlineSchema && typeof data.inlineSchema === 'object') {
    result.schema = { ...(data.inlineSchema as Record<string, unknown>) };
    if (data.deprecated) {
      result.deprecated = true;
    }
    if (data.allowEmptyValue !== undefined) {
      result.allowEmptyValue = data.allowEmptyValue;
    }
    if (data.style) {
      result.style = data.style;
    }
    if (data.explode !== undefined) {
      result.explode = data.explode;
    }
    if (data.example !== undefined) {
      result.example = data.example;
    }
    if (data.examples !== undefined) {
      result.examples = data.examples;
    }
    return result;
  }

  // Build schema from data (excluding non-schema fields)
  const schemaData = { ...data };
  delete schemaData.required;
  delete schemaData.schemaMode;
  delete schemaData.inlineSchema;
  delete schemaData.propertyRef;

  // Handle deprecated
  if (schemaData.deprecated) {
    result.deprecated = true;
    delete schemaData.deprecated;
  }

  // Handle allowEmptyValue
  if (schemaData.allowEmptyValue !== undefined) {
    result.allowEmptyValue = schemaData.allowEmptyValue;
    delete schemaData.allowEmptyValue;
  }

  // Handle style and explode
  if (schemaData.style) {
    result.style = schemaData.style;
    delete schemaData.style;
  }
  if (schemaData.explode !== undefined) {
    result.explode = schemaData.explode;
    delete schemaData.explode;
  }

  // Handle example(s)
  if (schemaData.example !== undefined) {
    result.example = schemaData.example;
    delete schemaData.example;
  }
  if (schemaData.examples !== undefined) {
    result.examples = schemaData.examples;
    delete schemaData.examples;
  }

  // Build the schema
  if (Object.keys(schemaData).length > 0) {
    result.schema = schemaData;
  } else {
    // Default to string if no schema specified
    result.schema = { type: 'string' };
  }

  return result;
}

// =============================================================================
// RESPONSE GENERATION
// =============================================================================

/**
 * Build OpenAPI response object from database response record
 */
export function buildResponseForOpenAPI(response: ResponseInfo): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  // Add description (required for OpenAPI)
  result.description = response.description || `${response.status_code} response`;

  // Check if response has multiple content types (like request bodies)
  if (response.content_types && response.content_types.length > 0) {
    const content: Record<string, unknown> = {};

    for (const contentType of response.content_types) {
      const mediaTypeObject: Record<string, unknown> = {};

      // Build schema from class reference or inline schema
      if (contentType.class_id && contentType.class_name) {
        mediaTypeObject.schema = {
          $ref: `#/components/schemas/${contentType.class_name}`,
        };
      } else if (contentType.inline_schema) {
        mediaTypeObject.schema = buildSchemaFromInlineProperties(contentType.inline_schema);
      }

      // Add examples
      if (contentType.examples && contentType.examples.length > 0) {
        if (contentType.examples.length === 1) {
          mediaTypeObject.example = (contentType.examples[0] as { value?: unknown }).value;
        } else {
          const examplesObj: Record<string, { summary?: string; value?: unknown }> = {};
          for (const ex of contentType.examples) {
            const example = ex as { name?: string; summary?: string; value?: unknown };
            if (example.name) {
              examplesObj[example.name] = {
                summary: example.summary,
                value: example.value,
              };
            }
          }
          mediaTypeObject.examples = examplesObj;
        }
      }

      content[contentType.media_type] = mediaTypeObject;
    }

    result.content = content;
  } else {
    // Fallback: Single content type or legacy format
    let schema: Record<string, unknown> | null = null;

    if (response.class_id && response.class_name) {
      // Reference to existing class
      schema = {
        $ref: `#/components/schemas/${response.class_name}`,
      };
    } else if (response.inline_schema) {
      // Inline schema
      schema = buildSchemaFromInlineProperties(response.inline_schema);
    } else if (response.data) {
      // Legacy data format - extract schema from it
      const data = response.data;
      if (data.content) {
        // Already has content structure
        result.content = data.content;
      } else if (data.schema) {
        schema = data.schema as Record<string, unknown>;
      } else if (data.$ref) {
        schema = { $ref: data.$ref as string };
      }
    }

    // Build content object if we have a schema and content wasn't already set
    if (schema && !result.content) {
      result.content = {
        'application/json': {
          schema,
        },
      };
    }
  }

  // Add headers if present in data
  if (response.data?.headers) {
    result.headers = response.data.headers;
  }

  // Add links if present in data
  if (response.data?.links) {
    result.links = response.data.links;
  }

  return result;
}

// =============================================================================
// OPERATION GENERATION
// =============================================================================

/**
 * Build OpenAPI operation object from database operation record
 */
export function buildOperationForOpenAPI(
  operation: OperationInfo,
  options: PathsGeneratorOptions = {}
): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  // Add operation metadata from description
  if (operation.description) {
    if (operation.description.summary) {
      result.summary = operation.description.summary;
    }
    if (options.includeDescriptions !== false && operation.description.description) {
      result.description = operation.description.description;
    }
    if (operation.description.operationId) {
      result.operationId = operation.description.operationId;
    }
    if (operation.description.tags && operation.description.tags.length > 0) {
      result.tags = operation.description.tags;
    }
    if (operation.description.deprecated) {
      result.deprecated = true;
    }
    if (operation.description.externalDocs) {
      result.externalDocs = operation.description.externalDocs;
    }
    // Add security requirements (OpenAPI Operation.security)
    if (operation.description.security && operation.description.security.length > 0) {
      result.security = operation.description.security;
    }
    // x-security-description: optional documentation for how security applies to this operation
    if (operation.description.securityDescription && operation.description.securityDescription.trim()) {
      result['x-security-description'] = operation.description.securityDescription.trim();
    }
    // x-private: hide from public docs (Swagger/OpenAPI doc generators may omit)
    if (operation.description['x-private'] === true) {
      result['x-private'] = true;
    }
  }

  // Add parameters
  if (operation.parameters && operation.parameters.length > 0) {
    result.parameters = operation.parameters.map(buildParameterForOpenAPI);
  }

  // Add request body (for POST, PUT, PATCH)
  if (operation.requestBody && ['POST', 'PUT', 'PATCH'].includes(operation.operation.toUpperCase())) {
    result.requestBody = buildRequestBodyForOpenAPI({
      description: operation.requestBody.description,
      required: operation.requestBody.required,
      content_types: operation.requestBody.content_types.map(ct => ({
        media_type: ct.media_type,
        class_id: ct.class_id || undefined,
        class_name: ct.class_name || undefined,
        inline_schema: ct.inline_schema || undefined,
        encoding: (ct.encoding as Record<string, unknown>) || undefined,
        examples: (ct.examples as unknown[]) || undefined,
      })),
    });
  }

  // Add responses
  const responses: Record<string, unknown> = {};
  if (operation.responses && operation.responses.length > 0) {
    for (const response of operation.responses) {
      responses[response.status_code] = buildResponseForOpenAPI(response);
    }
  } else {
    // Default response if none specified (OPTIONS: typical CORS preflight is 204 No Content)
    if (operation.operation.toUpperCase() === 'OPTIONS') {
      responses['204'] = {
        description: 'No Content',
      };
    } else {
      responses['200'] = {
        description: 'Successful response',
      };
    }
  }
  result.responses = responses;

  return result;
}

// =============================================================================
// PATH GENERATION
// =============================================================================

/**
 * Build OpenAPI path item object from database path record
 */
export function buildPathItemForOpenAPI(
  path: PathInfo,
  options: PathsGeneratorOptions = {}
): Record<string, unknown> {
  const result: Record<string, unknown> = {};

  // Add path-level summary and description
  if (path.summary) {
    result.summary = path.summary;
  }
  if (options.includeDescriptions !== false && path.description) {
    result.description = path.description;
  }

  // Add operations
  for (const operation of path.operations) {
    const method = operation.operation.toLowerCase();
    result[method] = buildOperationForOpenAPI(operation, options);
  }

  return result;
}

/**
 * Generate complete OpenAPI paths object from array of path records
 */
export function generatePathsForOpenAPI(
  paths: PathInfo[],
  options: PathsGeneratorOptions = {}
): Record<string, unknown> {
  console.log('[Paths Generator] Generating OpenAPI paths from', paths.length, 'path records');
  const result: Record<string, unknown> = {};

  for (const path of paths) {
    console.log('[Paths Generator] Building path:', path.pathname, 'with', path.operations.length, 'operations');

    if (path.operations.length === 0) {
      console.warn('[Paths Generator] WARNING: Path has no operations:', path.pathname);
      continue; // Skip paths with no operations
    }

    try {
      result[path.pathname] = buildPathItemForOpenAPI(path, options);
    } catch (error) {
      console.error('[Paths Generator] ERROR building path:', path.pathname, error);
      throw error;
    }
  }

  console.log('[Paths Generator] Generated', Object.keys(result).length, 'OpenAPI path entries');
  console.log('[Paths Generator] Result keys:', Object.keys(result));
  return result;
}

// =============================================================================
// FULL SPEC GENERATION
// =============================================================================

export interface OpenAPISpecOptions {
  title: string;
  version: string;
  description?: string;
  servers?: Array<{ url: string; description?: string }>;
  tags?: Array<{ name: string; description?: string }>;
  includeExamples?: boolean;
  includeDescriptions?: boolean;
}

/**
 * Generate a complete OpenAPI 3.1.0 specification with paths and schemas
 */
export function generateOpenAPISpecWithPaths(
  paths: PathInfo[],
  schemas: Record<string, unknown>,
  options: OpenAPISpecOptions
): Record<string, unknown> {
  const spec: Record<string, unknown> = {
    openapi: '3.1.0',
    info: {
      title: options.title,
      version: options.version,
    },
  };

  // Add description if provided
  if (options.description) {
    (spec.info as Record<string, unknown>).description = options.description;
  }

  // Add servers if provided
  if (options.servers && options.servers.length > 0) {
    spec.servers = options.servers;
  }

  // Add tags if provided
  if (options.tags && options.tags.length > 0) {
    spec.tags = options.tags;
  }

  // Generate paths
  spec.paths = generatePathsForOpenAPI(paths, {
    includeExamples: options.includeExamples,
    includeDescriptions: options.includeDescriptions,
  });

  // Add components/schemas
  if (schemas && Object.keys(schemas).length > 0) {
    spec.components = {
      schemas,
    };
  }

  return spec;
}

// =============================================================================
// DATA TRANSFORMATION HELPERS
// =============================================================================

/**
 * Parse inline_schema from database format (might be string or object)
 */
export function parseInlineSchema(data: unknown): InlineSchema | null {
  if (!data) return null;

  if (typeof data === 'string') {
    try {
      return JSON.parse(data) as InlineSchema;
    } catch {
      return null;
    }
  }

  return data as InlineSchema;
}

/**
 * Transform database content type record to ContentTypeInfo
 */
export function transformContentType(ct: Record<string, unknown>): ContentTypeInfo {
  return {
    id: ct.id as string,
    media_type: ct.media_type as string,
    class_id: ct.class_id as string | null,
    class_name: ct.class_name as string | null,
    inline_schema: parseInlineSchema(ct.inline_schema),
    encoding: ct.encoding ? (typeof ct.encoding === 'string' ? JSON.parse(ct.encoding) : ct.encoding) as Record<string, unknown> : null,
    examples: ct.examples ? (typeof ct.examples === 'string' ? JSON.parse(ct.examples) : ct.examples) as unknown[] : null,
  };
}

/**
 * Transform database request body record to RequestBodyInfo
 */
export function transformRequestBody(rb: Record<string, unknown>): RequestBodyInfo {
  const contentTypes = rb.content_types as unknown[];

  return {
    id: rb.id as string,
    name: rb.name as string,
    description: rb.description as string | undefined,
    required: rb.required as boolean,
    content_types: Array.isArray(contentTypes)
      ? contentTypes.map(ct => transformContentType(ct as Record<string, unknown>))
      : [],
  };
}

/**
 * Transform database response record to ResponseInfo
 */
export function transformResponse(response: Record<string, unknown>): ResponseInfo {
  return {
    id: response.id as string,
    status_code: response.status_code as string,
    description: response.description as string | undefined,
    data: response.data ? (typeof response.data === 'string' ? JSON.parse(response.data) : response.data) as Record<string, unknown> : undefined,
    class_id: response.class_id as string | null,
    class_name: response.class_name as string | null,
    inline_schema: parseInlineSchema(response.inline_schema),
  };
}

/**
 * Transform database parameter record to PathParameter
 */
export function transformParameter(param: Record<string, unknown>): PathParameter {
  return {
    id: param.id as string,
    name: param.name as string,
    in_location: param.in_location as 'path' | 'query' | 'header' | 'cookie',
    summary: param.summary as string | undefined,
    description: param.description as string | undefined,
    data: param.data ? (typeof param.data === 'string' ? JSON.parse(param.data) : param.data) as Record<string, unknown> : {},
  };
}

/**
 * Collect all class names referenced in paths (for generating minimal schemas)
 */
export function collectReferencedClassNames(paths: PathInfo[]): Set<string> {
  const classNames = new Set<string>();

  for (const path of paths) {
    for (const operation of path.operations) {
      // Check request body
      if (operation.requestBody?.content_types) {
        for (const ct of operation.requestBody.content_types) {
          if (ct.class_name) {
            classNames.add(ct.class_name);
          }
        }
      }

      // Check responses
      for (const response of operation.responses) {
        if (response.class_name) {
          classNames.add(response.class_name);
        }
        // Also check legacy data.$ref format
        if (response.data?.$ref) {
          const refPath = response.data.$ref as string;
          const match = refPath.match(/#\/components\/schemas\/(.+)/);
          if (match) {
            classNames.add(match[1]);
          }
        }
      }
    }
  }

  return classNames;
}
