/**
 * Swagger 2.x to OpenAPI 3.1.x Converter
 *
 * Converts Swagger 2.0 (OpenAPI 2.0) specifications to OpenAPI 3.1.x format
 * for compatibility with the Apiome import system.
 */

/**
 * Result of a Swagger to OpenAPI conversion
 */
export interface SwaggerConversionResult {
  success: boolean;
  document: any;
  error?: string;
  warnings: string[];
}

/**
 * Converts a Swagger 2.x specification to OpenAPI 3.1.x format
 *
 * @param swaggerDoc - The parsed Swagger 2.x document
 * @returns The converted OpenAPI 3.1.x document with conversion metadata
 */
export function convertSwaggerToOpenAPI(swaggerDoc: any): SwaggerConversionResult {
  const warnings: string[] = [];

  try {
    // Validate input
    if (!swaggerDoc || typeof swaggerDoc !== 'object') {
      return {
        success: false,
        document: null,
        error: 'Invalid Swagger document: expected an object',
        warnings: []
      };
    }

    if (!isSwagger2(swaggerDoc)) {
      const raw = swaggerDoc.swagger;
      return {
        success: false,
        document: null,
        error: `Invalid Swagger version: expected 2.x, got ${raw}`,
        warnings: []
      };
    }

    // Create OpenAPI 3.1.0 base structure
    const openApiDoc: any = {
      openapi: '3.1.0',
      info: convertInfo(swaggerDoc.info),
      components: {
        schemas: {}
      }
    };

    // Convert servers from host/basePath/schemes
    if (swaggerDoc.host || swaggerDoc.basePath) {
      openApiDoc.servers = convertServers(swaggerDoc);
    }

    // Convert security definitions to security schemes
    if (swaggerDoc.securityDefinitions) {
      openApiDoc.components.securitySchemes = convertSecurityDefinitions(
        swaggerDoc.securityDefinitions,
        warnings
      );
    }

    // Convert definitions to components/schemas
    if (swaggerDoc.definitions) {
      openApiDoc.components.schemas = convertDefinitions(swaggerDoc.definitions, warnings);
    }

    // Convert paths
    if (swaggerDoc.paths) {
      openApiDoc.paths = convertPaths(swaggerDoc.paths, swaggerDoc, warnings);
    }

    // Convert global security
    if (swaggerDoc.security) {
      openApiDoc.security = swaggerDoc.security;
    }

    // Convert tags
    if (swaggerDoc.tags) {
      openApiDoc.tags = swaggerDoc.tags;
    }

    // Convert external docs
    if (swaggerDoc.externalDocs) {
      openApiDoc.externalDocs = swaggerDoc.externalDocs;
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
 * Convert info object (mostly compatible, but add contact/license if missing)
 */
function convertInfo(info: any): any {
  if (!info) {
    return {
      title: 'Converted API',
      version: '1.0.0'
    };
  }

  return {
    title: info.title || 'Converted API',
    version: info.version || '1.0.0',
    description: info.description,
    termsOfService: info.termsOfService,
    contact: info.contact,
    license: info.license
  };
}

/**
 * Convert host/basePath/schemes to servers array
 */
function convertServers(swaggerDoc: any): any[] {
  const servers: any[] = [];
  const schemes = swaggerDoc.schemes || ['https'];
  const host = swaggerDoc.host || 'localhost';
  const basePath = swaggerDoc.basePath || '/';

  for (const scheme of schemes) {
    servers.push({
      url: `${scheme}://${host}${basePath}`,
      description: `${scheme.toUpperCase()} server`
    });
  }

  return servers;
}

/**
 * Convert security definitions to OpenAPI 3.x security schemes
 */
function convertSecurityDefinitions(securityDefs: any, warnings: string[]): any {
  const securitySchemes: any = {};

  for (const [name, def] of Object.entries<any>(securityDefs)) {
    switch (def.type) {
      case 'basic':
        securitySchemes[name] = {
          type: 'http',
          scheme: 'basic',
          description: def.description
        };
        break;

      case 'apiKey':
        securitySchemes[name] = {
          type: 'apiKey',
          name: def.name,
          in: def.in,
          description: def.description
        };
        break;

      case 'oauth2':
        securitySchemes[name] = convertOAuth2(def, warnings);
        break;

      default:
        warnings.push(`Unknown security type '${def.type}' for '${name}'`);
        securitySchemes[name] = {
          type: 'apiKey',
          name: name,
          in: 'header',
          description: def.description || 'Unknown security type'
        };
    }
  }

  return securitySchemes;
}

/**
 * Convert OAuth2 security definition
 */
function convertOAuth2(def: any, warnings: string[]): any {
  const oauth2: any = {
    type: 'oauth2',
    description: def.description,
    flows: {}
  };

  switch (def.flow) {
    case 'implicit':
      oauth2.flows.implicit = {
        authorizationUrl: def.authorizationUrl,
        scopes: def.scopes || {}
      };
      break;

    case 'password':
      oauth2.flows.password = {
        tokenUrl: def.tokenUrl,
        scopes: def.scopes || {}
      };
      break;

    case 'application':
      oauth2.flows.clientCredentials = {
        tokenUrl: def.tokenUrl,
        scopes: def.scopes || {}
      };
      break;

    case 'accessCode':
      oauth2.flows.authorizationCode = {
        authorizationUrl: def.authorizationUrl,
        tokenUrl: def.tokenUrl,
        scopes: def.scopes || {}
      };
      break;

    default:
      warnings.push(`Unknown OAuth2 flow '${def.flow}'`);
      // Default to implicit
      oauth2.flows.implicit = {
        authorizationUrl: def.authorizationUrl || 'https://example.com/oauth/authorize',
        scopes: def.scopes || {}
      };
  }

  return oauth2;
}

/**
 * Convert Swagger 2.x definitions to OpenAPI 3.1 schemas
 */
function convertDefinitions(definitions: any, warnings: string[]): any {
  const schemas: any = {};

  for (const [name, schema] of Object.entries<any>(definitions)) {
    schemas[name] = convertSchema(schema, warnings, name);
  }

  return schemas;
}

/**
 * Convert a single schema from Swagger 2.x to OpenAPI 3.1 format
 */
function convertSchema(schema: any, warnings: string[], context?: string): any {
  if (!schema || typeof schema !== 'object') {
    return schema;
  }

  const converted: any = { ...schema };

  // Convert $ref paths from #/definitions/ to #/components/schemas/
  if (converted.$ref && typeof converted.$ref === 'string') {
    converted.$ref = converted.$ref.replace(
      /^#\/definitions\//,
      '#/components/schemas/'
    );
    return converted;
  }

  // Convert x-nullable to nullable (Swagger 2.x extension to OpenAPI 3.0 style)
  // Then convert to type array for OpenAPI 3.1
  if (converted['x-nullable'] === true || converted.nullable === true) {
    delete converted['x-nullable'];
    delete converted.nullable;

    // OpenAPI 3.1 uses type array for nullable
    if (converted.type && converted.type !== 'null') {
      converted.type = [converted.type, 'null'];
    }
    warnings.push(`Converted nullable type at ${context || 'unknown'}`);
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
      converted.items = converted.items.map((item: any, index: number) =>
        convertSchema(item, warnings, `${context}.items[${index}]`)
      );
    } else {
      converted.items = convertSchema(converted.items, warnings, `${context}.items`);
    }
  }

  // Convert allOf/anyOf/oneOf schemas recursively
  for (const keyword of ['allOf', 'anyOf', 'oneOf']) {
    if (converted[keyword] && Array.isArray(converted[keyword])) {
      converted[keyword] = converted[keyword].map((subSchema: any, index: number) =>
        convertSchema(subSchema, warnings, `${context}.${keyword}[${index}]`)
      );
    }
  }

  // Convert additionalProperties
  if (converted.additionalProperties && typeof converted.additionalProperties === 'object') {
    converted.additionalProperties = convertSchema(
      converted.additionalProperties,
      warnings,
      `${context}.additionalProperties`
    );
  }

  // Handle discriminator (Swagger 2.x vs OpenAPI 3.x format difference)
  if (converted.discriminator && typeof converted.discriminator === 'string') {
    // Swagger 2.x uses discriminator as a string property name
    // OpenAPI 3.x uses an object with propertyName
    converted.discriminator = {
      propertyName: converted.discriminator
    };
  }

  // Convert file type to binary string format
  if (converted.type === 'file') {
    converted.type = 'string';
    converted.format = 'binary';
    warnings.push(`Converted 'file' type to 'string' with 'binary' format at ${context || 'unknown'}`);
  }

  // Remove Swagger 2.x specific extensions that don't apply to schemas
  delete converted['x-example']; // Use example instead

  return converted;
}

/** Resolve `#/parameters/<Name>` against `swaggerDoc.parameters`. */
function resolveSwaggerParameterRef(ref: string, swaggerDoc: any): any | null {
  const m = ref.match(/^#\/parameters\/(.+)$/);
  if (!m) return null;
  const key = m[1];
  const pool = swaggerDoc?.parameters;
  if (!pool || typeof pool !== 'object') return null;
  const resolved = pool[key];
  return resolved && typeof resolved === 'object' ? resolved : null;
}

/**
 * Expand `{ $ref: '#/parameters/...' }` entries (common in Swagger 2.0) so conversion
 * produces real OpenAPI parameter objects with `name`, `in`, and `schema`.
 */
function dereferenceSwaggerParameter(
  param: any,
  swaggerDoc: any,
  seen: Set<string> = new Set()
): any {
  if (!param || typeof param !== 'object') return param;
  const ref = param.$ref;
  if (typeof ref !== 'string') return param;
  if (seen.has(ref)) return param;
  const resolved = resolveSwaggerParameterRef(ref, swaggerDoc);
  if (!resolved) return param;
  const nextSeen = new Set(seen);
  nextSeen.add(ref);
  return dereferenceSwaggerParameter(resolved, swaggerDoc, nextSeen);
}

/**
 * Convert paths from Swagger 2.x to OpenAPI 3.x format
 */
function convertPaths(paths: any, swaggerDoc: any, warnings: string[]): any {
  const convertedPaths: any = {};

  for (const [path, pathItem] of Object.entries<any>(paths)) {
    convertedPaths[path] = convertPathItem(pathItem, swaggerDoc, warnings, path);
  }

  return convertedPaths;
}

/**
 * Convert a single path item
 */
function convertPathItem(pathItem: any, swaggerDoc: any, warnings: string[], pathContext: string): any {
  const converted: any = {};

  // Copy path-level parameters
  if (pathItem.parameters) {
    converted.parameters = pathItem.parameters.map((param: any) =>
      convertParameter(dereferenceSwaggerParameter(param, swaggerDoc), warnings, pathContext)
    );
  }

  // Convert each HTTP method
  const httpMethods = ['get', 'put', 'post', 'delete', 'options', 'head', 'patch'];

  for (const method of httpMethods) {
    if (pathItem[method]) {
      converted[method] = convertOperation(
        pathItem[method],
        swaggerDoc,
        warnings,
        `${pathContext}.${method}`
      );
    }
  }

  return converted;
}

/**
 * Convert a single operation (method)
 */
function convertOperation(operation: any, swaggerDoc: any, warnings: string[], context: string): any {
  const converted: any = {
    ...operation,
    responses: {}
  };

  // Convert parameters
  if (operation.parameters) {
    const { parameters, requestBody } = convertParameters(
      operation.parameters,
      operation.consumes || swaggerDoc.consumes,
      swaggerDoc,
      warnings,
      context
    );

    if (parameters.length > 0) {
      converted.parameters = parameters;
    } else {
      delete converted.parameters;
    }

    if (requestBody) {
      converted.requestBody = requestBody;
    }
  }

  // Convert responses
  if (operation.responses) {
    converted.responses = convertResponses(
      operation.responses,
      operation.produces || swaggerDoc.produces,
      warnings,
      context
    );
  }

  // Remove Swagger 2.x specific fields
  delete converted.consumes;
  delete converted.produces;
  delete converted.schemes;

  return converted;
}

/**
 * Convert parameters and extract body parameter to requestBody
 */
function convertParameters(
  parameters: any[],
  consumes: string[] | undefined,
  swaggerDoc: any,
  warnings: string[],
  context: string
): { parameters: any[]; requestBody: any | null } {
  const convertedParams: any[] = [];
  let requestBody: any = null;

  for (const raw of parameters) {
    const param = dereferenceSwaggerParameter(raw, swaggerDoc);
    if (param.in === 'body') {
      // Convert body parameter to requestBody
      requestBody = {
        description: param.description,
        required: param.required,
        content: {}
      };

      const contentTypes = consumes || ['application/json'];
      for (const contentType of contentTypes) {
        requestBody.content[contentType] = {
          schema: convertSchema(param.schema, warnings, `${context}.body`)
        };
      }
    } else if (param.in === 'formData') {
      // Convert formData to requestBody
      if (!requestBody) {
        requestBody = {
          content: {
            'application/x-www-form-urlencoded': {
              schema: {
                type: 'object',
                properties: {}
              }
            }
          }
        };
      }

      const schema = requestBody.content['application/x-www-form-urlencoded']?.schema;
      if (schema && schema.properties) {
        schema.properties[param.name] = convertFormDataParam(param);
        if (param.required) {
          schema.required = schema.required || [];
          schema.required.push(param.name);
        }
      }
    } else {
      // Regular parameter (path, query, header, cookie)
      convertedParams.push(convertParameter(param, warnings, context));
    }
  }

  return { parameters: convertedParams, requestBody };
}

/**
 * Convert a single parameter
 */
function convertParameter(param: any, warnings: string[], context: string): any {
  const converted: any = {
    name: param.name,
    in: param.in,
    description: param.description,
    required: param.required
  };

  // Convert schema for non-body parameters (in Swagger 2.x, these have type directly)
  if (param.type) {
    converted.schema = {
      type: param.type,
      format: param.format,
      enum: param.enum,
      default: param.default,
      minimum: param.minimum,
      maximum: param.maximum,
      minLength: param.minLength,
      maxLength: param.maxLength,
      pattern: param.pattern
    };

    // Handle array type
    if (param.type === 'array' && param.items) {
      converted.schema.items = convertSchema(param.items, warnings, `${context}.${param.name}.items`);
    }

    // Clean up undefined values
    Object.keys(converted.schema).forEach(key => {
      if (converted.schema[key] === undefined) {
        delete converted.schema[key];
      }
    });
  } else if (param.schema) {
    converted.schema = convertSchema(param.schema, warnings, `${context}.${param.name}`);
  }

  // Handle allowEmptyValue
  if (param.allowEmptyValue !== undefined) {
    converted.allowEmptyValue = param.allowEmptyValue;
  }

  // Handle style/explode (from collectionFormat)
  if (param.collectionFormat) {
    switch (param.collectionFormat) {
      case 'csv':
        converted.style = 'form';
        converted.explode = false;
        break;
      case 'ssv':
        converted.style = 'spaceDelimited';
        converted.explode = false;
        break;
      case 'tsv':
        warnings.push(`Tab-separated collection format not supported at ${context}.${param.name}`);
        converted.style = 'pipeDelimited';
        converted.explode = false;
        break;
      case 'pipes':
        converted.style = 'pipeDelimited';
        converted.explode = false;
        break;
      case 'multi':
        converted.style = 'form';
        converted.explode = true;
        break;
    }
  }

  return converted;
}

/**
 * Convert formData parameter to schema property
 */
function convertFormDataParam(param: any): any {
  const schema: any = {
    type: param.type === 'file' ? 'string' : param.type,
    description: param.description
  };

  if (param.type === 'file') {
    schema.format = 'binary';
  }

  if (param.format) schema.format = param.format;
  if (param.enum) schema.enum = param.enum;
  if (param.default !== undefined) schema.default = param.default;

  return schema;
}

/**
 * Convert responses from Swagger 2.x to OpenAPI 3.x format
 */
function convertResponses(
  responses: any,
  produces: string[] | undefined,
  warnings: string[],
  context: string
): any {
  const converted: any = {};

  for (const [statusCode, response] of Object.entries<any>(responses)) {
    converted[statusCode] = convertResponse(response, produces, warnings, `${context}.responses.${statusCode}`);
  }

  return converted;
}

/**
 * Convert a single response
 */
function convertResponse(
  response: any,
  produces: string[] | undefined,
  warnings: string[],
  context: string
): any {
  const converted: any = {
    description: response.description || 'No description'
  };

  // Convert schema to content
  if (response.schema) {
    converted.content = {};
    const contentTypes = produces || ['application/json'];

    for (const contentType of contentTypes) {
      converted.content[contentType] = {
        schema: convertSchema(response.schema, warnings, context)
      };
    }
  }

  // Convert headers
  if (response.headers) {
    converted.headers = {};
    for (const [headerName, headerDef] of Object.entries<any>(response.headers)) {
      converted.headers[headerName] = {
        description: headerDef.description,
        schema: {
          type: headerDef.type,
          format: headerDef.format
        }
      };
    }
  }

  // Convert examples
  if (response.examples) {
    if (!converted.content) {
      converted.content = {};
    }
    for (const [contentType, example] of Object.entries<any>(response.examples)) {
      if (!converted.content[contentType]) {
        converted.content[contentType] = {};
      }
      converted.content[contentType].example = example;
    }
  }

  return converted;
}

/**
 * Check if a document is a Swagger 2.x specification
 */
export function isSwagger2(doc: any): boolean {
  if (!doc || typeof doc !== 'object') {
    return false;
  }
  const v = doc.swagger;
  if (v == null) {
    return false;
  }
  if (typeof v === 'string') {
    return v.startsWith('2.');
  }
  if (typeof v === 'number' && Number.isFinite(v)) {
    return v >= 2 && v < 3;
  }
  return false;
}

/**
 * Get the Swagger version from a document
 */
export function getSwaggerVersion(doc: any): string | null {
  if (!doc || typeof doc !== 'object' || doc.swagger == null) {
    return null;
  }
  const v = doc.swagger;
  if (typeof v === 'string') {
    return v;
  }
  if (typeof v === 'number' && Number.isFinite(v)) {
    return String(v);
  }
  return null;
}

