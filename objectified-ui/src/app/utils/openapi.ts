/**
 * OpenAPI Specification Generator Utilities
 *
 * Consolidates OpenAPI specification generation logic for reuse across
 * the application. Builds complete schemas from class definitions and their properties.
 * Uses Handlebars templates for flexible versioning support.
 */

import { renderTemplate } from './template-loader';
import { getOpenAPIVersionConfig, DEFAULT_OPENAPI_VERSION } from './openapi-versions';

/**
 * Extracts class name from a JSON Schema $ref string
 * @param ref - The $ref string (e.g., "#/components/schemas/Person")
 * @returns The class name or null if not found
 */
export function extractClassNameFromRef(ref: string): string | null {
  if (!ref) return null;

  if (ref.includes('/')) {
    const parts = ref.split('/');
    return parts[parts.length - 1] || null;
  }
  return ref;
}

/**
 * Recursively finds all class names referenced in a schema object via $ref
 * @param obj - The schema object to search
 * @param refs - Set to accumulate found class names
 */
export function findReferencedClasses(obj: any, refs: Set<string>): void {
  if (!obj || typeof obj !== 'object') return;

  if (obj.$ref && typeof obj.$ref === 'string') {
    const className = extractClassNameFromRef(obj.$ref);
    if (className) refs.add(className);
  }

  for (const key in obj) {
    if (obj.hasOwnProperty(key)) {
      findReferencedClasses(obj[key], refs);
    }
  }
}

/**
 * Builds property schema with nested children for object types
 * @param prop - The property to build schema for
 * @param allProperties - All properties to find children
 * @returns Property schema object with nested properties if applicable
 */
function buildPropertySchema(prop: any, allProperties: any[]): any {
  const propData = typeof prop.data === 'string' ? JSON.parse(prop.data) : { ...prop.data };

  // Preserve the property's own required flag (boolean) - this indicates if THIS property is required
  // It will be extracted by the caller and moved to the parent's required array
  const selfRequired = propData.required;

  // Clean up description handling
  if (propData.description === null) {
    delete propData.description;
    if (propData.title) {
      propData.description = propData.title;
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

  // Restore the property's own required flag (boolean) for the caller to handle
  // This is separate from the nested required array which is for child properties
  if (selfRequired === true) {
    propData.required = true;
  } else if (selfRequired === false && !Array.isArray(propData.required)) {
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

      // Handle required flag - it belongs in the class schema's required array, not the property
      // Check for boolean true specifically (not truthy, as required could be an array for nested props)
      if (propSchema.required === true) {
        required.push(prop.name);
        delete propSchema.required;
      } else if (propSchema.required === false) {
        // If property data explicitly sets required=false, remove the field
        delete propSchema.required;
      }
      // Note: If propSchema.required is an array (from nested properties), keep it as-is

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
 * @returns OpenAPI spec as JSON string
 */
export async function generateOpenApiSpec(
  classes: any[],
  options?: {
    projectName?: string;
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
    description: options?.description || `Generated OpenAPI ${versionConfig.version} specification from Objectified Studio`
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


  // Prepare template data
  const templateData: any = {
    openapi: versionConfig.version,
    info,
    schemas
  };

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

  // Prepare template data
  const templateData: any = {
    openapi: versionConfig.version,
    info,
    schemas
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
