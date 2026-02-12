import { Importer, ImportSourceKind, NormalizeOptions, NormalizeResult, NormalizedClass, NormalizedProperty } from './index';
import { applyNamingConventionToClasses } from '../../src/app/utils/naming-conventions';
import { getSmartClassName } from '../schema-context-naming';

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

    const classNameMap = options.classNameMap;

    for (const [schemaName, originalSchema] of Object.entries<any>(schemas)) {
      if (!selected.has(schemaName)) continue;

      const { properties, required } = extractDirectProperties(originalSchema);
      const props: NormalizedProperty[] = [];
      for (const propName of Object.keys(properties)) {
        props.push(convertProperty(propName, properties[propName], required));
      }

      // Smart naming from schema context (#753): title / x-class-name / then schema key
      const baseName = classNameMap?.[schemaName] ?? getSmartClassName(schemaName, originalSchema);

      classes.push({
        name: baseName,
        originalSchemaKey: schemaName,
        description: originalSchema?.description ?? null,
        schema: originalSchema,
        properties: props
      });
    }

    if (classes.length === 0) warnings.push('No selected schemas to import.');

    // Apply naming convention enforcement (#581)
    const applyNaming = options.applyNamingConvention === true;
    let finalClasses = applyNaming
      ? applyNamingConventionToClasses(classes, {
          classNamingConvention: options.classNamingConvention ?? 'PascalCase',
          propertyNamingConvention: options.propertyNamingConvention ?? 'camelCase',
          applyNamingConvention: true,
        })
      : classes;

    // Apply prefix/suffix rules to class names (#755)
    const prefix = (options.classPrefix ?? '').trim();
    const suffix = (options.classSuffix ?? '').trim();
    if (prefix || suffix) {
      const nameToFinal = new Map<string, string>();
      for (const cls of finalClasses) {
        const finalName = prefix + cls.name + suffix;
        nameToFinal.set(cls.name, finalName);
        if (cls.originalSchemaKey && cls.originalSchemaKey !== cls.name) nameToFinal.set(cls.originalSchemaKey, finalName);
      }
      const updateRefs = (data: any): any => {
        if (!data || typeof data !== 'object') return data;
        const result = { ...data };
        if (typeof result.$ref === 'string') {
          const match = result.$ref.match(/#\/components\/schemas\/(.+)$/);
          if (match && nameToFinal.has(match[1])) {
            result.$ref = `#/components/schemas/${nameToFinal.get(match[1])}`;
          }
        }
        if (result.items && typeof result.items === 'object' && result.items.$ref) {
          const match = result.items.$ref.match(/#\/components\/schemas\/(.+)$/);
          if (match && nameToFinal.has(match[1])) {
            result.items = { ...result.items, $ref: `#/components/schemas/${nameToFinal.get(match[1])}` };
          }
        }
        return result;
      };
      const transformProp = (p: NormalizedProperty): NormalizedProperty => {
        const newData = p.data ? updateRefs(p.data) : p.data;
        const result: NormalizedProperty = { ...p, data: newData };
        if (p.children?.length) result.children = p.children.map(transformProp);
        return result;
      };
      finalClasses = finalClasses.map((cls) => ({
        ...cls,
        name: prefix + cls.name + suffix,
        properties: cls.properties?.map(transformProp) ?? cls.properties,
      }));
    }

    return { classes: finalClasses, warnings };
  }
};

