/**
 * Class schema builder.
 *
 * Builds the JSON Schema of a class from its stored schema and its property rows. The AsyncAPI and
 * JSON Schema exports use it (`asyncapi-generator.ts`, `jsonschema.ts`).
 *
 * This module no longer generates OpenAPI documents. A revision's OpenAPI document is rendered by
 * apiome-rest alone and read through `utils/revision-document.ts` (COA-5.13, #7089).
 */

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
