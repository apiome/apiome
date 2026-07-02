import { Importer, ImportSourceKind, NormalizeOptions, NormalizeResult, NormalizedClass, NormalizedProperty } from './index';
import { applyNamingConventionToClasses } from '../../src/app/utils/naming-conventions';
import { extractDirectProperties } from '../../src/app/utils/openapi-schema-direct-properties';
import { getSmartClassName } from '../schema-context-naming';
import { collectReservedNameWarnings } from './reserved-names';

/** Build external type key from property data for type mapping (#757). Returns null for refs or missing type. */
export function getExternalTypeKey(data: any): string | null {
  if (!data || typeof data !== 'object' || data.$ref) return null;
  const t = data.type;
  if (!t || typeof t !== 'string') return null;
  const f = data.format;
  return f && typeof f === 'string' ? `${t}:${f}` : t;
}

/** Apply type mapping to a single property data object (recurses into items). Refs are not modified. */
function applyTypeMappingToData(data: any, typeMapping: Record<string, any>): any {
  if (!data || typeof data !== 'object') return data;
  if (data.$ref) return data;
  const next = { ...data };
  if (next.items && typeof next.items === 'object') {
    next.items = applyTypeMappingToData(next.items, typeMapping);
  }
  const key = getExternalTypeKey(next);
  if (key && typeMapping[key]) {
    const internal = typeMapping[key];
    const merged = typeof internal === 'object' && internal !== null ? { ...internal } : { type: internal };
    if (next.required !== undefined) merged.required = next.required;
    return merged;
  }
  return next;
}

/** Apply type mapping to a normalized property and its children. */
function applyTypeMappingToProperty(p: NormalizedProperty, typeMapping: Record<string, any>): NormalizedProperty {
  const data = applyTypeMappingToData(p.data, typeMapping);
  const children = p.children?.map((c) => applyTypeMappingToProperty(c, typeMapping));
  return { ...p, data, children };
}

/** Apply global default values to a property when it has no default (#758). Recurse into children and items. */
function applyDefaultValuesToProperty(p: NormalizedProperty, defaultValues: Record<string, any>): NormalizedProperty {
  if (!defaultValues || Object.keys(defaultValues).length === 0) return p;
  const data = p.data && typeof p.data === 'object' ? { ...p.data } : p.data;
  if (data && !data.$ref && data.default === undefined) {
    const key = getExternalTypeKey(data);
    if (key && key in defaultValues) {
      data.default = defaultValues[key];
    }
  }
  if (data?.items && typeof data.items === 'object' && !data.items.$ref && data.items.default === undefined) {
    const key = getExternalTypeKey(data.items);
    if (key && key in defaultValues) {
      data.items = { ...data.items, default: defaultValues[key] };
    }
  }
  const children = p.children?.map((c) => applyDefaultValuesToProperty(c, defaultValues));
  return { ...p, data, children };
}

/**
 * Generate a single example value for a property schema when it has no example (#761).
 * Used during import when generateExamples is true. Deterministic and does not resolve $ref.
 */
function generateExampleFromPropertyData(data: any): any {
  if (!data || typeof data !== 'object' || data.example !== undefined) return undefined;
  if (data.$ref) return undefined;

  if (Array.isArray(data.enum) && data.enum.length > 0) return data.enum[0];

  const t = data.type;
  if (t === 'string') {
    const f = data.format;
    if (f === 'date') return '2025-02-11';
    if (f === 'date-time') return '2025-02-11T12:00:00Z';
    if (f === 'time') return '12:00:00';
    if (f === 'uuid') return '123e4567-e89b-12d3-a456-426614174000';
    if (f === 'email') return 'user@example.com';
    if (f === 'uri' || f === 'uri-reference') return 'https://example.com';
    if (f === 'hostname') return 'example.com';
    if (data.pattern) return `string matching pattern: ${data.pattern}`;
    return data.description ? String(data.description).slice(0, 80) : 'example';
  }
  if (t === 'integer') {
    if (data.minimum !== undefined) return Math.ceil(Number(data.minimum));
    if (data.maximum !== undefined) return Math.floor(Number(data.maximum));
    return 42;
  }
  if (t === 'number') {
    if (data.minimum !== undefined) return Number(data.minimum) + 0.5;
    if (data.maximum !== undefined) return Number(data.maximum) - 0.5;
    return 42.5;
  }
  if (t === 'boolean') return true;
  if (t === 'array') {
    if (data.items && typeof data.items === 'object' && !data.items.$ref && data.items.example === undefined) {
      const itemExample = generateExampleFromPropertyData(data.items);
      if (itemExample !== undefined) return [itemExample];
    }
    return [];
  }
  if (t === 'object') return {};
  return undefined;
}

/** Apply generated example to a property when it has no example (#761). Recurse into children and items. */
function applyGenerateExamplesToProperty(p: NormalizedProperty): NormalizedProperty {
  const data = p.data && typeof p.data === 'object' ? { ...p.data } : p.data;
  if (data && !data.$ref && data.example === undefined) {
    const example = generateExampleFromPropertyData(data);
    if (example !== undefined) data.example = example;
  }
  if (data?.items && typeof data.items === 'object' && !data.items.$ref && data.items.example === undefined) {
    const itemExample = generateExampleFromPropertyData(data.items);
    if (itemExample !== undefined) data.items = { ...data.items, example: itemExample };
  }
  const children = p.children?.map((c) => applyGenerateExamplesToProperty(c));
  return { ...p, data, children };
}

/** Recursively collect external type keys from a property schema. */
function collectKeysFromProp(prop: any, keys: Set<string>): void {
  if (!prop || typeof prop !== 'object') return;
  if (prop.$ref) return;
  const key = getExternalTypeKey(prop);
  if (key) keys.add(key);
  if (prop.type === 'object' && prop.properties) {
    for (const child of Object.values(prop.properties)) collectKeysFromProp(child as any, keys);
  }
  if (prop.type === 'array' && prop.items) collectKeysFromProp(prop.items, keys);
}

/** Collect all external type keys present in the given document for selected schemas (#757). */
export function collectExternalTypeKeysFromDocument(document: any, selectedSchemas: string[]): string[] {
  const schemas = document?.components?.schemas || {};
  const selected = new Set(selectedSchemas);
  const keys = new Set<string>();
  for (const [schemaName, schema] of Object.entries<any>(schemas)) {
    if (!selected.has(schemaName)) continue;
    const { properties } = extractDirectProperties(schema);
    for (const prop of Object.values(properties)) collectKeysFromProp(prop, keys);
  }
  return Array.from(keys).sort();
}

const convertProperty = (propName: string, propSchema: any, required: string[] = []): NormalizedProperty => {
  // Tolerate malformed property schemas (null, boolean, primitives) so a single
  // bad property does not abort the import.
  const safeSchema: any = propSchema && typeof propSchema === 'object' ? propSchema : {};
  const data: any = { ...safeSchema };
  const description = data.description;
  delete data.description;

  const requiredList = Array.isArray(required) ? required.filter((r) => typeof r === 'string') : [];
  if (requiredList.includes(propName)) data.required = true;

  const result: NormalizedProperty = { name: propName, data, description };

  // Inline object
  if (safeSchema.type === 'object' && safeSchema.properties && typeof safeSchema.properties === 'object') {
    const nestedRequired = Array.isArray(safeSchema.required) ? safeSchema.required : [];
    const children: NormalizedProperty[] = [];
    const wasRequiredOnParent = data.required === true;
    delete data.properties;
    delete data.required;
    for (const childName of Object.keys(safeSchema.properties)) {
      children.push(convertProperty(childName, safeSchema.properties[childName], nestedRequired));
    }
    result.children = children;
    if (wasRequiredOnParent) {
      data.required = true;
    }
  }

  // Array of objects
  if (
    safeSchema.type === 'array' &&
    safeSchema.items && typeof safeSchema.items === 'object' &&
    safeSchema.items.type === 'object' &&
    safeSchema.items.properties && typeof safeSchema.items.properties === 'object'
  ) {
    const nestedRequired = Array.isArray(safeSchema.items.required) ? safeSchema.items.required : [];
    const children: NormalizedProperty[] = [];
    const items = { ...safeSchema.items };
    delete items.properties;
    delete items.required;
    data.items = items;
    for (const childName of Object.keys(safeSchema.items.properties)) {
      children.push(convertProperty(childName, safeSchema.items.properties[childName], nestedRequired));
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
    const schemaKeys = Object.keys(schemas);
    // Empty array is truthy in JS; REST/CLI send selected_schemas: [] by default meaning "no filter".
    const effectiveSelection =
      Array.isArray(options.selectedSchemas) && options.selectedSchemas.length > 0
        ? options.selectedSchemas
        : schemaKeys;
    const selected = new Set(effectiveSelection);

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

    // Required field override (#759): apply before naming so we key by original schema + property name
    const requiredOverrides = options.requiredOverrides;
    let classesAfterRequired = classes;
    if (requiredOverrides && Object.keys(requiredOverrides).length > 0) {
      classesAfterRequired = classes.map((cls) => {
        const schemaKey = cls.originalSchemaKey ?? cls.name;
        const overrides = requiredOverrides[schemaKey];
        if (!overrides || typeof overrides !== 'object') return cls;
        const newProps = (cls.properties ?? []).map((p) => {
          if (overrides[p.name] === undefined) return p;
          const data = p.data && typeof p.data === 'object' ? { ...p.data, required: Boolean(overrides[p.name]) } : p.data;
          return { ...p, data };
        });
        return { ...cls, properties: newProps };
      });
    }

    // Description override (#760): add or modify property descriptions during import
    const descriptionOverrides = options.descriptionOverrides;
    if (descriptionOverrides && Object.keys(descriptionOverrides).length > 0) {
      classesAfterRequired = classesAfterRequired.map((cls) => {
        const schemaKey = cls.originalSchemaKey ?? cls.name;
        const overrides = descriptionOverrides[schemaKey];
        if (!overrides || typeof overrides !== 'object') return cls;
        const newProps = (cls.properties ?? []).map((p) => {
          if (!(p.name in overrides)) return p;
          const desc = overrides[p.name];
          return { ...p, description: desc === '' ? undefined : desc };
        });
        return { ...cls, properties: newProps };
      });
    }

    // Apply naming convention enforcement (#581)
    const applyNaming = options.applyNamingConvention === true;
    let finalClasses = applyNaming
      ? applyNamingConventionToClasses(classesAfterRequired, {
          classNamingConvention: options.classNamingConvention ?? 'PascalCase',
          propertyNamingConvention: options.propertyNamingConvention ?? 'camelCase',
          applyNamingConvention: true,
        })
      : classesAfterRequired;

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

    // Reserved name detection (#756): warn on class and property names that conflict with keywords
    warnings.push(...collectReservedNameWarnings(finalClasses));

    // Type mapping (#757): map external types to internal types for imported properties
    const typeMapping = options.typeMapping;
    let classesOut =
      typeMapping && Object.keys(typeMapping).length > 0
        ? finalClasses.map((cls) => ({
            ...cls,
            properties: (cls.properties ?? []).map((p) => applyTypeMappingToProperty(p, typeMapping)),
          }))
        : finalClasses;

    // Default value assignment (#758): set global defaults for properties that have no default
    const defaultValues = options.defaultValues;
    if (defaultValues && Object.keys(defaultValues).length > 0) {
      classesOut = classesOut.map((cls) => ({
        ...cls,
        properties: (cls.properties ?? []).map((p) => applyDefaultValuesToProperty(p, defaultValues)),
      }));
    }

    // Example generation (#761): auto-generate example for properties that have no example
    if (options.generateExamples === true) {
      classesOut = classesOut.map((cls) => ({
        ...cls,
        properties: (cls.properties ?? []).map((p) => applyGenerateExamplesToProperty(p)),
      }));
    }

    return { classes: classesOut, warnings };
  }
};

