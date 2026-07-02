/**
 * OpenAPI Specification Generator Utilities
 *
 * Consolidates OpenAPI specification generation logic for reuse across
 * the application. Builds complete schemas from class definitions and their properties.
 * Uses Handlebars templates for flexible versioning support.
 */

import { renderTemplate } from './template-loader';
import { getOpenAPIVersionConfig, DEFAULT_OPENAPI_VERSION } from './openapi-versions';
import { extractClassNameFromRef, findReferencedClasses } from './openapi-schema-refs';

export { extractClassNameFromRef, findReferencedClasses };

/**
 * Builds property schema with nested children for object types
 * @param prop - The property to build schema for
 * @param allProperties - All properties to find children
 * @returns Property schema object with nested properties if applicable
 */
function buildPropertySchema(prop: any, allProperties: any[]): any {
  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : { ...prop.data };
  // Strip internal persistence fields from exported schema output.
  delete propData.id;
  delete propData.property_id;
  delete propData.class_id;
  delete propData.parent_id;

  // Preserve the property's own required flag (boolean) - this indicates if THIS property is required
  // It will be extracted by the caller and moved to the parent's required array
  const selfRequired = propData.required;

  // Use property description from database field (prop.description) if available
  // This takes precedence over any description in the data JSON
  if (prop.description) {
    propData.description = prop.description;
  } else if (propData.description === null || propData.description === undefined) {
    // If no description in database field and no description in data, try title as fallback
    if (propData.title) {
      propData.description = propData.title;
    } else {
      // Remove undefined/null description
      delete propData.description;
    }
  }

  // If this property has type "object" and no $ref, check for nested properties
  if (propData.type === 'object' && !propData.$ref) {
    // Find all child properties
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);

    if (children.length > 0) {
      // Build nested properties object
      const nestedProperties: any = {};
      const nestedRequired: string[] = [];

      children.forEach((child: any) => {
        const childSchema = buildPropertySchema(child, allProperties);

        // Handle required flag for nested properties
        if (childSchema.required === true) {
          nestedRequired.push(child.name);
          delete childSchema.required;
        }
        if (childSchema.required === false) {
          delete childSchema.required;
        }

        nestedProperties[child.name] = childSchema;
      });

      // Add nested properties to the object schema
      propData.properties = nestedProperties;

      if (nestedRequired.length > 0) {
        propData.required = nestedRequired;
      } else {
        // Remove required if it was an array from nested (don't keep empty array)
        if (Array.isArray(propData.required)) {
          delete propData.required;
        }
      }
    }
  }

  // If this property is an array of inline objects, ensure items is present and nest children under items
  if (propData.type === 'array') {
    const children = allProperties.filter((p: any) => p.parent_id === prop.id);

    // If children exist but items is missing, infer items as an inline object
    if (children.length > 0 && !propData.items) {
      propData.items = { type: 'object' };
    }

    if (propData.items && !propData.items.$ref && (propData.items.type === 'object' || children.length > 0)) {
      const nestedProperties: any = {};
      const nestedRequired: string[] = [];

      children.forEach((child: any) => {
        const childSchema = buildPropertySchema(child, allProperties);
        if (childSchema.required === true) {
          nestedRequired.push(child.name);
          delete childSchema.required;
        }
        if (childSchema.required === false) {
          delete childSchema.required;
        }
        nestedProperties[child.name] = childSchema;
      });

      // Ensure items is an object and attach nested properties
      propData.items = { ...(propData.items || {}), type: 'object', properties: nestedProperties };
      if (nestedRequired.length > 0) {
        propData.items.required = nestedRequired;
      } else if (propData.items.required !== undefined) {
        delete propData.items.required;
      }
    }
  }

  // Parent-level "this property is required" is read from prop.data in buildClassSchema.
  // Do not set boolean required on propData when required is already the inner object array.
  if (selfRequired === false && !Array.isArray(propData.required)) {
    propData.required = false;
  }

  return propData;
}

/**
 * Builds a JSON Schema from a class definition and its properties
 * @param classData - The class data including name, description, schema, and properties array
 * @returns A JSON Schema object representing the class
 */
export function buildClassSchema(classData: any): any {
  const schema = typeof classData.schema === 'string'
    ? JSON.parse(classData.schema)
    : (classData.schema || {});

  // Remove properties and required from schema to prevent overwriting
  // We build these from the class_properties table instead
  const { properties: _schemaProperties, required: _schemaRequired, ...schemaWithoutProperties } = schema;

  const properties: any = {};
  const required: string[] = [];

  if (classData.properties && classData.properties.length > 0) {
    // Only process top-level properties (those without parent_id)
    const topLevelProperties = classData.properties.filter((prop: any) => !prop.parent_id);

    topLevelProperties.forEach((prop: any) => {
      const propSchema = buildPropertySchema(prop, classData.properties);
      const raw =
        typeof prop.data === 'string' ? JSON.parse(prop.data || '{}') : { ...(prop.data || {}) };
      const requiredOnParent = raw.required === true;
      const booleanRequiredOnSchema =
        !Array.isArray(propSchema.required) && propSchema.required === true;

      if (requiredOnParent || booleanRequiredOnSchema) {
        required.push(prop.name);
      }
      if (booleanRequiredOnSchema) {
        delete propSchema.required;
      } else if (propSchema.required === false && !Array.isArray(propSchema.required)) {
        delete propSchema.required;
      }

      properties[prop.name] = propSchema;
    });
  }

  // Check if schema has composition keywords (allOf/anyOf/oneOf)
  const hasComposition = schemaWithoutProperties.allOf || schemaWithoutProperties.anyOf || schemaWithoutProperties.oneOf;

  let classSchema: any;

  if (hasComposition) {
    // Preserve composition structure
    // If we have properties from class_properties table, add them alongside the composition
    // This is valid OpenAPI - properties at the same level as allOf represent additional fields
    classSchema = {
      description: classData.description || undefined,
      ...schemaWithoutProperties
    };

    // Add properties if we have any defined in the class_properties table
    if (Object.keys(properties).length > 0) {
      classSchema.properties = properties;
      if (required.length > 0) {
        classSchema.required = required;
      }
    }
  } else {
    // Normal schema without compositions - build as usual
    classSchema = {
      type: 'object',
      description: classData.description || undefined,
      ...schemaWithoutProperties,
      properties,
      required: required.length > 0 ? required : undefined
    };
  }

  // Delete class properties if properties is empty
  if (classSchema.properties && Object.keys(classSchema.properties).length === 0) {
    delete classSchema.properties;
  }

  // Remove undefined values
  Object.keys(classSchema).forEach(key => {
    if (classSchema[key] === undefined) {
      delete classSchema[key];
    }
  });

  return classSchema;
}

/**
 * Generates a complete OpenAPI specification from all classes
 * @param classes - Array of class definitions
 * @param options - Optional metadata for the spec
 * @param paths - Optional paths object (OpenAPI paths section)
 * @returns OpenAPI spec as JSON string
 */
/** OpenAPI 3.1 components (optional sections for #424) */
export interface OpenAPIComponents {
  parameters?: Record<string, unknown>;
  requestBodies?: Record<string, unknown>;
  responses?: Record<string, unknown>;
  headers?: Record<string, unknown>;
  examples?: Record<string, unknown>;
  securitySchemes?: Record<string, unknown>;
  links?: Record<string, unknown>;
  callbacks?: Record<string, unknown>;
  pathItems?: Record<string, unknown>;
}

export async function generateOpenApiSpec(
  classes: any[],
  options?: {
    projectName?: string;
    version?: string;
    description?: string;
    openapiVersion?: string;
    /** OpenAPI servers array (url, description) */
    servers?: Array<{ url: string; description?: string }>;
    /** OpenAPI top-level tags (name, description) */
    tags?: Array<{ name: string; description?: string }>;
    /** OpenAPI global security requirements */
    security?: Array<Record<string, string[]>>;
    /** OpenAPI external documentation */
    externalDocs?: { url: string; description?: string };
    /** Optional reusable components (#424) */
    components?: OpenAPIComponents;
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
  },
  paths?: Record<string, unknown>,
  securitySchemes?: Record<string, unknown>
): Promise<string> {
  const schemas: any = {};

  // Build schema for each class
  classes.forEach((cls) => {
    schemas[cls.name] = buildClassSchema(cls);
  });

  // Get OpenAPI version configuration
  const versionConfig = getOpenAPIVersionConfig(options?.openapiVersion);

  // Prepare info object with metadata
  const info: any = {
    title: options?.projectName || 'API Schema',
    version: options?.version || '1.0.0',
    description: options?.description || `Generated OpenAPI ${versionConfig.version} specification from Apiome Studio`
  };


  // Add optional metadata fields
  if (options?.metadata) {
    if (options.metadata.summary) {
      info.summary = options.metadata.summary;
    }
    if (options.metadata.termsOfService) {
      info.termsOfService = options.metadata.termsOfService;
    }
    if (options.metadata.contact && Object.keys(options.metadata.contact).length > 0) {
      info.contact = {};
      if (options.metadata.contact.name) info.contact.name = options.metadata.contact.name;
      if (options.metadata.contact.url) info.contact.url = options.metadata.contact.url;
      if (options.metadata.contact.email) info.contact.email = options.metadata.contact.email;
    }
    if (options.metadata.license && Object.keys(options.metadata.license).length > 0) {
      info.license = {};
      if (options.metadata.license.name) info.license.name = options.metadata.license.name;
      if (options.metadata.license.identifier) info.license.identifier = options.metadata.license.identifier;
      if (options.metadata.license.url) info.license.url = options.metadata.license.url;
    }
  }

  // Build full components object (#424: all OpenAPI 3.1 component sections)
  const components: Record<string, unknown> = {
    schemas,
  };
  if (securitySchemes && Object.keys(securitySchemes).length > 0) {
    components.securitySchemes = securitySchemes;
  }
  if (options?.components?.parameters && Object.keys(options.components.parameters).length > 0) {
    components.parameters = options.components.parameters;
  }
  if (options?.components?.requestBodies && Object.keys(options.components.requestBodies).length > 0) {
    components.requestBodies = options.components.requestBodies;
  }
  if (options?.components?.responses && Object.keys(options.components.responses).length > 0) {
    components.responses = options.components.responses;
  }
  if (options?.components?.headers && Object.keys(options.components.headers).length > 0) {
    components.headers = options.components.headers;
  }
  if (options?.components?.examples && Object.keys(options.components.examples).length > 0) {
    components.examples = options.components.examples;
  }
  if (options?.components?.links && Object.keys(options.components.links).length > 0) {
    components.links = options.components.links;
  }
  if (options?.components?.callbacks && Object.keys(options.components.callbacks).length > 0) {
    components.callbacks = options.components.callbacks;
  }
  if (options?.components?.pathItems && Object.keys(options.components.pathItems).length > 0) {
    components.pathItems = options.components.pathItems;
  }

  // Prepare template data
  const templateData: any = {
    openapi: versionConfig.version,
    info,
    components,
    paths: paths || {},  // Include paths in template data, default to empty object
    ...(options?.servers && options.servers.length > 0 ? { servers: options.servers } : {}),
    ...(options?.tags && options.tags.length > 0 ? { tags: options.tags } : {}),
    ...(options?.security && options.security.length > 0 ? { security: options.security } : {}),
    ...(options?.externalDocs ? { externalDocs: options.externalDocs } : {}),
  };

  console.log('[OpenAPI Generator] Template data paths count:', Object.keys(paths || {}).length);
  if (Object.keys(paths || {}).length > 0) {
    console.log('[OpenAPI Generator] Path keys:', Object.keys(paths || {}));
    console.log('[OpenAPI Generator] First path sample:', JSON.stringify(Object.values(paths || {})[0]).substring(0, 300));
  } else {
    console.warn('[OpenAPI Generator] WARNING: No paths provided to template!');
  }

  // Add project metadata to top level as x-metadata extension
  if (options?.metadata && Object.keys(options.metadata).length > 0) {
    templateData.xMetadata = options.metadata;
  }

  // Render using Handlebars template
  const rendered = await renderTemplate(versionConfig.templateFile, templateData);


  // Parse and re-stringify to ensure valid JSON and proper formatting
  try {
    const parsed = JSON.parse(rendered);
    return JSON.stringify(parsed, null, 2);
  } catch (error) {
    console.error('[OpenAPI] Failed to parse rendered template. Error:', error);
    console.error('[OpenAPI] Rendered output:', rendered);
    throw new Error(`Failed to parse rendered OpenAPI spec: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Generates an OpenAPI specification for a single class and its referenced dependencies
 * @param classData - The primary class to generate spec for
 * @param allClasses - All available classes (to resolve references)
 * @param options - Optional metadata for the spec
 * @returns OpenAPI spec as object
 */
export async function generateClassOpenApiSpec(
  classData: any,
  allClasses: any[],
  options?: {
    title?: string;
    version?: string;
    description?: string;
    openapiVersion?: string;
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
): Promise<any> {
  const referencedClasses = new Set<string>();

  // Find all referenced classes in the primary class
  const schema = typeof classData.schema === 'string'
    ? JSON.parse(classData.schema)
    : (classData.schema || {});

  findReferencedClasses(schema, referencedClasses);

  // Also check properties for references
  if (classData.properties && classData.properties.length > 0) {
    classData.properties.forEach((prop: any) => {
      const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
      findReferencedClasses(propData, referencedClasses);
    });
  }

  // Build schemas for the main class and all referenced classes
  const schemas: any = {
    [classData.name]: buildClassSchema(classData)
  };

  // Recursively resolve all transitive references
  const processedClasses = new Set<string>([classData.name]);
  const classesToProcess = Array.from(referencedClasses);

  while (classesToProcess.length > 0) {
    const className = classesToProcess.shift()!;

    if (processedClasses.has(className)) {
      continue; // Skip already processed classes
    }

    processedClasses.add(className);

    const referencedClassData = allClasses.find((cls: any) => cls.name === className);

    if (referencedClassData) {
      schemas[className] = buildClassSchema(referencedClassData);

      // Find references within this referenced class (transitive references)
      const transitiveRefs = new Set<string>();
      const refSchema = typeof referencedClassData.schema === 'string'
        ? JSON.parse(referencedClassData.schema)
        : (referencedClassData.schema || {});

      findReferencedClasses(refSchema, transitiveRefs);

      // Also check properties for references
      if (referencedClassData.properties && referencedClassData.properties.length > 0) {
        referencedClassData.properties.forEach((prop: any) => {
          const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : prop.data;
          findReferencedClasses(propData, transitiveRefs);
        });
      }

      // Add new references to the queue
      transitiveRefs.forEach(refClassName => {
        if (!processedClasses.has(refClassName) && !classesToProcess.includes(refClassName)) {
          classesToProcess.push(refClassName);
        }
      });
    } else {
      // Create placeholder for missing references
      schemas[className] = {
        type: 'object',
        description: `Referenced schema: ${className} (not loaded)`,
        properties: {}
      };
    }
  }

  // Get OpenAPI version configuration
  const versionConfig = getOpenAPIVersionConfig(options?.openapiVersion);

  // Prepare info object with metadata
  const info: any = {
    title: options?.title || `${classData.name} Schema`,
    version: options?.version || '1.0.0',
    description: options?.description || `OpenAPI ${versionConfig.version} schema definition`
  };

  // Add optional metadata fields
  if (options?.metadata) {
    if (options.metadata.summary) {
      info.summary = options.metadata.summary;
    }
    if (options.metadata.termsOfService) {
      info.termsOfService = options.metadata.termsOfService;
    }
    if (options.metadata.contact && Object.keys(options.metadata.contact).length > 0) {
      info.contact = {};
      if (options.metadata.contact.name) info.contact.name = options.metadata.contact.name;
      if (options.metadata.contact.url) info.contact.url = options.metadata.contact.url;
      if (options.metadata.contact.email) info.contact.email = options.metadata.contact.email;
    }
    if (options.metadata.license && Object.keys(options.metadata.license).length > 0) {
      info.license = {};
      if (options.metadata.license.name) info.license.name = options.metadata.license.name;
      if (options.metadata.license.identifier) info.license.identifier = options.metadata.license.identifier;
      if (options.metadata.license.url) info.license.url = options.metadata.license.url;
    }
  }

  // Prepare template data (use same components shape as generateOpenApiSpec #424)
  const templateData: any = {
    openapi: versionConfig.version,
    info,
    components: { schemas },
    paths: {}  // Include paths in template data, default to empty object
  };

  // Add project metadata to top level as x-metadata extension
  if (options?.metadata && Object.keys(options.metadata).length > 0) {
    templateData.xMetadata = options.metadata;
  }

  // Render using Handlebars template
  const rendered = await renderTemplate(versionConfig.templateFile, templateData);

  // Parse and return as object
  return JSON.parse(rendered);
}
