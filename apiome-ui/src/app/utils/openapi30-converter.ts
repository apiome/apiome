/**
 * OpenAPI 3.0.x to OpenAPI 3.1.x Converter
 *
 * Converts OpenAPI 3.0.x specifications to OpenAPI 3.1.x format
 * for compatibility with the Apiome import system.
 *
 * Key differences between OpenAPI 3.0 and 3.1:
 * - OpenAPI 3.1 aligns with JSON Schema 2020-12
 * - nullable: true is replaced with type arrays or anyOf
 * - exclusiveMinimum/Maximum changed from boolean to numeric
 * - example vs examples handling
 * - webhooks support added in 3.1
 */

/**
 * Result of an OpenAPI 3.0 to 3.1 conversion
 */
export interface OpenAPI30ConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/**
 * Check if a document is OpenAPI 3.0.x
 */
export function isOpenAPI30(doc: any): boolean {
  if (!doc || typeof doc !== 'object') {
    return false;
  }
  if (!doc.openapi || typeof doc.openapi !== 'string') {
    return false;
  }
  return doc.openapi.startsWith('3.0');
}

/**
 * Converts an OpenAPI 3.0.x specification to OpenAPI 3.1.x format
 *
 * @param openapi30Doc - The parsed OpenAPI 3.0.x document
 * @returns The converted OpenAPI 3.1.x document with conversion metadata
 */
export function convertOpenAPI30ToOpenAPI31(openapi30Doc: any): OpenAPI30ConversionResult {
  const warnings: string[] = [];

  try {
    // Validate input
    if (!openapi30Doc || typeof openapi30Doc !== 'object') {
      return {
        success: false,
        document: null,
        error: 'Invalid OpenAPI document: expected an object',
        warnings: []
      };
    }

    if (!isOpenAPI30(openapi30Doc)) {
      return {
        success: false,
        document: null,
        error: `Invalid OpenAPI version: expected 3.0.x, got ${openapi30Doc.openapi}`,
        warnings: []
      };
    }

    // Deep clone the document to avoid mutating the original
    const openapi31Doc = JSON.parse(JSON.stringify(openapi30Doc));

    // Update version to 3.1.0
    openapi31Doc.openapi = '3.1.0';

    // Convert info object (mostly compatible)
    if (openapi31Doc.info) {
      openapi31Doc.info = convertInfo(openapi31Doc.info, warnings);
    }

    // Convert components/schemas
    if (openapi31Doc.components?.schemas) {
      openapi31Doc.components.schemas = convertSchemas(
        openapi31Doc.components.schemas,
        warnings
      );
    }

    // Convert parameters
    if (openapi31Doc.components?.parameters) {
      openapi31Doc.components.parameters = convertParameters(
        openapi31Doc.components.parameters,
        warnings
      );
    }

    // Convert request bodies
    if (openapi31Doc.components?.requestBodies) {
      openapi31Doc.components.requestBodies = convertRequestBodies(
        openapi31Doc.components.requestBodies,
        warnings
      );
    }

    // Convert responses
    if (openapi31Doc.components?.responses) {
      openapi31Doc.components.responses = convertResponses(
        openapi31Doc.components.responses,
        warnings
      );
    }

    // Convert headers
    if (openapi31Doc.components?.headers) {
      openapi31Doc.components.headers = convertHeaders(
        openapi31Doc.components.headers,
        warnings
      );
    }

    // Convert paths
    if (openapi31Doc.paths) {
      openapi31Doc.paths = convertPaths(openapi31Doc.paths, warnings);
    }

    return {
      success: true,
      document: openapi31Doc,
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
 * Convert info object
 */
function convertInfo(info: any, warnings: string[]): any {
  const convertedInfo = { ...info };

  // In OpenAPI 3.1, license.identifier is added as an alternative to license.url
  // No changes needed for basic compatibility

  return convertedInfo;
}

/**
 * Convert schemas object
 */
function convertSchemas(schemas: any, warnings: string[]): any {
  const convertedSchemas: any = {};

  for (const [name, schema] of Object.entries<any>(schemas)) {
    convertedSchemas[name] = convertSchema(schema, warnings, `schemas.${name}`);
  }

  return convertedSchemas;
}

/**
 * Convert a single schema from OpenAPI 3.0 to 3.1
 */
function convertSchema(schema: any, warnings: string[], path: string = ''): any {
  if (!schema || typeof schema !== 'object') {
    return schema;
  }

  // Handle $ref - don't process further
  if (schema.$ref) {
    return { ...schema };
  }

  const converted: any = { ...schema };

  // Convert nullable to type array or anyOf
  if (schema.nullable === true) {
    delete converted.nullable;

    if (schema.type) {
      // Simple case: convert type to array with null
      if (typeof schema.type === 'string') {
        converted.type = [schema.type, 'null'];
      } else if (Array.isArray(schema.type)) {
        converted.type = [...schema.type, 'null'];
      }
    } else if (schema.allOf || schema.oneOf || schema.anyOf) {
      // Complex case: wrap composition in anyOf with null. We must remove the
      // original composition keys from the top of `converted`, otherwise the
      // result is malformed (e.g. both `allOf` and `anyOf` at the same level).
      const nullSchema = { type: 'null' };
      if (schema.anyOf) {
        converted.anyOf = [...schema.anyOf, nullSchema];
      } else {
        const originalSchema: any = { ...converted };
        delete originalSchema.nullable;
        // The original composition is preserved inside the anyOf branch; remove
        // it from the top-level converted schema to avoid duplicating it.
        delete converted.allOf;
        delete converted.oneOf;
        delete converted.type;
        converted.anyOf = [originalSchema, nullSchema];
      }
    } else {
      // No type specified, add anyOf with null
      const originalSchema: any = { ...converted };
      delete originalSchema.nullable;
      delete originalSchema.anyOf;
      converted.anyOf = [originalSchema, { type: 'null' }];
    }

    if (path) {
      warnings.push(`Converted nullable property at ${path} to OpenAPI 3.1 format`);
    }
  }

  // Convert exclusiveMinimum/exclusiveMaximum from boolean to numeric
  if (typeof schema.exclusiveMinimum === 'boolean') {
    if (schema.exclusiveMinimum === true && schema.minimum !== undefined) {
      converted.exclusiveMinimum = schema.minimum;
      delete converted.minimum;
    } else {
      delete converted.exclusiveMinimum;
    }
    if (schema.exclusiveMinimum === true && schema.minimum === undefined) {
      if (path) {
        warnings.push(
          `exclusiveMinimum boolean at ${path} requires a minimum value to convert properly`
        );
      }
    }
  }

  if (typeof schema.exclusiveMaximum === 'boolean') {
    if (schema.exclusiveMaximum === true && schema.maximum !== undefined) {
      converted.exclusiveMaximum = schema.maximum;
      delete converted.maximum;
    } else {
      delete converted.exclusiveMaximum;
    }
    if (schema.exclusiveMaximum === true && schema.maximum === undefined) {
      if (path) {
        warnings.push(
          `exclusiveMaximum boolean at ${path} requires a maximum value to convert properly`
        );
      }
    }
  }

  // Convert example to examples if needed (OpenAPI 3.1 prefers examples object)
  // Keep example as-is for now, both are valid in 3.1

  // Recursively convert nested schemas
  if (converted.properties) {
    const convertedProperties: any = {};
    for (const [propName, propSchema] of Object.entries<any>(converted.properties)) {
      convertedProperties[propName] = convertSchema(
        propSchema,
        warnings,
        path ? `${path}.properties.${propName}` : `properties.${propName}`
      );
    }
    converted.properties = convertedProperties;
  }

  if (converted.items) {
    converted.items = convertSchema(
      converted.items,
      warnings,
      path ? `${path}.items` : 'items'
    );
  }

  if (converted.additionalProperties && typeof converted.additionalProperties === 'object') {
    converted.additionalProperties = convertSchema(
      converted.additionalProperties,
      warnings,
      path ? `${path}.additionalProperties` : 'additionalProperties'
    );
  }

  if (converted.allOf) {
    converted.allOf = converted.allOf.map((s: any, i: number) =>
      convertSchema(s, warnings, path ? `${path}.allOf[${i}]` : `allOf[${i}]`)
    );
  }

  if (converted.oneOf) {
    converted.oneOf = converted.oneOf.map((s: any, i: number) =>
      convertSchema(s, warnings, path ? `${path}.oneOf[${i}]` : `oneOf[${i}]`)
    );
  }

  if (converted.anyOf) {
    converted.anyOf = converted.anyOf.map((s: any, i: number) =>
      convertSchema(s, warnings, path ? `${path}.anyOf[${i}]` : `anyOf[${i}]`)
    );
  }

  if (converted.not) {
    converted.not = convertSchema(
      converted.not,
      warnings,
      path ? `${path}.not` : 'not'
    );
  }

  return converted;
}

/**
 * Convert parameters
 */
function convertParameters(parameters: any, warnings: string[]): any {
  const convertedParameters: any = {};

  for (const [name, parameter] of Object.entries<any>(parameters)) {
    convertedParameters[name] = convertParameter(parameter, warnings, `parameters.${name}`);
  }

  return convertedParameters;
}

/**
 * Convert a single parameter
 */
function convertParameter(parameter: any, warnings: string[], path: string): any {
  if (!parameter || typeof parameter !== 'object') {
    return parameter;
  }

  const converted = { ...parameter };

  // Convert schema
  if (converted.schema) {
    converted.schema = convertSchema(converted.schema, warnings, `${path}.schema`);
  }

  // Convert content schemas
  if (converted.content) {
    converted.content = convertContent(converted.content, warnings, `${path}.content`);
  }

  return converted;
}

/**
 * Convert request bodies
 */
function convertRequestBodies(requestBodies: any, warnings: string[]): any {
  const convertedRequestBodies: any = {};

  for (const [name, requestBody] of Object.entries<any>(requestBodies)) {
    convertedRequestBodies[name] = convertRequestBody(
      requestBody,
      warnings,
      `requestBodies.${name}`
    );
  }

  return convertedRequestBodies;
}

/**
 * Convert a single request body
 */
function convertRequestBody(requestBody: any, warnings: string[], path: string): any {
  if (!requestBody || typeof requestBody !== 'object') {
    return requestBody;
  }

  const converted = { ...requestBody };

  if (converted.content) {
    converted.content = convertContent(converted.content, warnings, `${path}.content`);
  }

  return converted;
}

/**
 * Convert responses
 */
function convertResponses(responses: any, warnings: string[]): any {
  const convertedResponses: any = {};

  for (const [name, response] of Object.entries<any>(responses)) {
    convertedResponses[name] = convertResponse(response, warnings, `responses.${name}`);
  }

  return convertedResponses;
}

/**
 * Convert a single response
 */
function convertResponse(response: any, warnings: string[], path: string): any {
  if (!response || typeof response !== 'object') {
    return response;
  }

  const converted = { ...response };

  if (converted.content) {
    converted.content = convertContent(converted.content, warnings, `${path}.content`);
  }

  if (converted.headers) {
    const convertedHeaders: any = {};
    for (const [headerName, header] of Object.entries<any>(converted.headers)) {
      convertedHeaders[headerName] = convertHeader(
        header,
        warnings,
        `${path}.headers.${headerName}`
      );
    }
    converted.headers = convertedHeaders;
  }

  return converted;
}

/**
 * Convert headers
 */
function convertHeaders(headers: any, warnings: string[]): any {
  const convertedHeaders: any = {};

  for (const [name, header] of Object.entries<any>(headers)) {
    convertedHeaders[name] = convertHeader(header, warnings, `headers.${name}`);
  }

  return convertedHeaders;
}

/**
 * Convert a single header
 */
function convertHeader(header: any, warnings: string[], path: string): any {
  if (!header || typeof header !== 'object') {
    return header;
  }

  const converted = { ...header };

  if (converted.schema) {
    converted.schema = convertSchema(converted.schema, warnings, `${path}.schema`);
  }

  if (converted.content) {
    converted.content = convertContent(converted.content, warnings, `${path}.content`);
  }

  return converted;
}

/**
 * Convert content object (used in request bodies and responses)
 */
function convertContent(content: any, warnings: string[], path: string): any {
  if (!content || typeof content !== 'object') {
    return content;
  }

  const convertedContent: any = {};

  for (const [mediaType, mediaTypeObject] of Object.entries<any>(content)) {
    const converted = { ...mediaTypeObject };

    if (converted.schema) {
      converted.schema = convertSchema(
        converted.schema,
        warnings,
        `${path}['${mediaType}'].schema`
      );
    }

    convertedContent[mediaType] = converted;
  }

  return convertedContent;
}

/**
 * Convert paths object
 */
function convertPaths(paths: any, warnings: string[]): any {
  const convertedPaths: any = {};

  for (const [pathName, pathItem] of Object.entries<any>(paths)) {
    convertedPaths[pathName] = convertPathItem(pathItem, warnings, `paths['${pathName}']`);
  }

  return convertedPaths;
}

/**
 * Convert a single path item
 */
function convertPathItem(pathItem: any, warnings: string[], path: string): any {
  if (!pathItem || typeof pathItem !== 'object') {
    return pathItem;
  }

  const converted = { ...pathItem };

  // Convert parameters
  if (converted.parameters) {
    converted.parameters = converted.parameters.map((param: any, i: number) =>
      convertParameter(param, warnings, `${path}.parameters[${i}]`)
    );
  }

  // Convert operations
  const operations = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch', 'trace'];
  for (const op of operations) {
    if (converted[op]) {
      converted[op] = convertOperation(converted[op], warnings, `${path}.${op}`);
    }
  }

  return converted;
}

/**
 * Convert a single operation
 */
function convertOperation(operation: any, warnings: string[], path: string): any {
  if (!operation || typeof operation !== 'object') {
    return operation;
  }

  const converted = { ...operation };

  // Convert parameters
  if (converted.parameters) {
    converted.parameters = converted.parameters.map((param: any, i: number) =>
      convertParameter(param, warnings, `${path}.parameters[${i}]`)
    );
  }

  // Convert request body
  if (converted.requestBody) {
    converted.requestBody = convertRequestBody(
      converted.requestBody,
      warnings,
      `${path}.requestBody`
    );
  }

  // Convert responses
  if (converted.responses) {
    const convertedResponses: any = {};
    for (const [statusCode, response] of Object.entries<any>(converted.responses)) {
      convertedResponses[statusCode] = convertResponse(
        response,
        warnings,
        `${path}.responses['${statusCode}']`
      );
    }
    converted.responses = convertedResponses;
  }

  return converted;
}

