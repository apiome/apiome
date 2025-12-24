import { Importer, ImportSourceKind, NormalizeOptions, NormalizeResult, NormalizedClass, NormalizedProperty } from './index';

// Utility: extract direct properties and nested inline children similar to src/app/utils/openapi-import.ts
const extractDirectProperties = (schema: any): { properties: Record<string, any>; required: string[] } => {
  const result = { properties: {} as Record<string, any>, required: [] as string[] };
  if (!schema) return result;

  // First, always include top-level properties if they exist
  if (schema.properties) {
    Object.assign(result.properties, schema.properties);
  }
  if (Array.isArray(schema.required)) {
    result.required.push(...schema.required);
  }

  // Then also check allOf for additional inline properties (not $refs)
  if (schema.allOf && Array.isArray(schema.allOf)) {
    for (const item of schema.allOf) {
      // Skip $ref items - those are class references, not inline properties
      if (item.$ref) continue;
      // Skip if/then/else conditional rules - those don't define properties to import
      if (item.if !== undefined) continue;
      // Include inline properties from allOf items
      if (item.properties) Object.assign(result.properties, item.properties);
      if (Array.isArray(item.required)) result.required.push(...item.required);
    }
  }

  // For anyOf/oneOf without top-level properties, return empty (these are variant types)
  if ((schema.anyOf || schema.oneOf) && Object.keys(result.properties).length === 0) {
    return result;
  }

  return result;
};

const convertProperty = (propName: string, propSchema: any, required: string[] = []): NormalizedProperty => {
  const data: any = { ...propSchema };
  const description = data.description;
  delete data.description;

  if (required.includes(propName)) data.required = true;

  const result: NormalizedProperty = { name: propName, data, description };

  // Inline object
  if (propSchema.type === 'object' && propSchema.properties) {
    const nestedRequired = Array.isArray(propSchema.required) ? propSchema.required : [];
    const children: NormalizedProperty[] = [];
    delete data.properties;
    delete data.required;
    for (const childName of Object.keys(propSchema.properties)) {
      children.push(convertProperty(childName, propSchema.properties[childName], nestedRequired));
    }
    result.children = children;
  }

  // Array of objects
  if (propSchema.type === 'array' && propSchema.items?.type === 'object' && propSchema.items.properties) {
    const nestedRequired = Array.isArray(propSchema.items.required) ? propSchema.items.required : [];
    const children: NormalizedProperty[] = [];
    const items = { ...propSchema.items };
    delete items.properties;
    delete items.required;
    data.items = items;
    for (const childName of Object.keys(propSchema.items.properties)) {
      children.push(convertProperty(childName, propSchema.items.properties[childName], nestedRequired));
    }
    result.children = children;
  }

  return result;
};

export const openApiImporter: Importer = {
  kind: 'openapi' as ImportSourceKind,
  normalize({ document, options }: { document: any; options: NormalizeOptions }): NormalizeResult {
    const classes: NormalizedClass[] = [];
    const warnings: string[] = [];

    const schemas = document?.components?.schemas || {};
    const selected = new Set(options.selectedSchemas || Object.keys(schemas));

    for (const [schemaName, originalSchema] of Object.entries<any>(schemas)) {
      if (!selected.has(schemaName)) continue;

      const { properties, required } = extractDirectProperties(originalSchema);
      const props: NormalizedProperty[] = [];
      for (const propName of Object.keys(properties)) {
        props.push(convertProperty(propName, properties[propName], required));
      }

      classes.push({
        name: schemaName,
        description: originalSchema?.description ?? null,
        schema: originalSchema,
        properties: props
      });
    }

    if (classes.length === 0) warnings.push('No selected schemas to import.');

    return { classes, warnings };
  }
};

