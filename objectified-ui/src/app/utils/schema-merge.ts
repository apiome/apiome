/**
 * Intelligent merge of schema properties and constraints (#588).
 * Supports additive merge (add new, keep existing) and override merge (imported wins; constraints merged strictly).
 * #593: Selective merge — per-property strategy via propertyMergeStrategies (schema key → property path → strategy).
 */

import type { NormalizedClass, NormalizedProperty } from '../../../lib/importers';

export type MergeStrategy = 'additive' | 'override';

/** How to merge array-valued schema fields (e.g. required, enum) when merging constraints (#595). */
export type ArrayMergeStrategy = 'append' | 'replace' | 'deduplicate';

/** Options for selective per-property merge (#593) and array merge (#595). */
export interface MergeOptions {
  /** Schema key (e.g. components/schemas key) for looking up per-property strategies. */
  schemaKey?: string;
  /** Per-property merge strategy: schema key → property path (dot for nested) → strategy. Missing = use default strategy. */
  propertyMergeStrategies?: Record<string, Record<string, MergeStrategy>>;
  /** How to merge array-valued fields (required, enum). Default: replace. */
  arrayMergeStrategy?: ArrayMergeStrategy;
}

/** Merge two arrays by strategy (#595). Uses stable stringify for dedupe key when possible. */
function mergeArrayByStrategy(
  existing: any[],
  imported: any[],
  strategy: ArrayMergeStrategy
): any[] {
  if (strategy === 'replace') return imported.length ? imported : existing;
  if (strategy === 'append') return [...existing, ...imported];
  // deduplicate: union, existing first then imported additions (by primitive or JSON string for objects)
  const seen = new Set<string>();
  const out: any[] = [];
  for (const v of existing) {
    const key = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(v);
    }
  }
  for (const v of imported) {
    const key = typeof v === 'object' && v !== null ? JSON.stringify(v) : String(v);
    if (!seen.has(key)) {
      seen.add(key);
      out.push(v);
    }
  }
  return out;
}

/**
 * Merge two JSON Schema constraint objects for the same property.
 * Takes the "stricter" constraint where applicable so the merged schema is valid for both inputs.
 * #595: arrayMergeStrategy controls how required and enum arrays are merged.
 */
function mergeConstraints(existing: any, imported: any, options?: MergeOptions): any {
  if (!existing || typeof existing !== 'object') return imported ?? {};
  if (!imported || typeof imported !== 'object') return existing;

  const arrayStrategy = options?.arrayMergeStrategy ?? 'replace';
  const result = { ...imported };

  // Type: keep imported; if different, prefer imported (override semantics for type)
  if (imported.type !== undefined) result.type = imported.type;

  // String constraints: stricter = larger minLength, smaller maxLength
  if (typeof existing.minLength === 'number' && typeof imported.minLength === 'number') {
    result.minLength = Math.max(existing.minLength, imported.minLength);
  } else if (imported.minLength !== undefined) result.minLength = imported.minLength;
  else if (existing.minLength !== undefined) result.minLength = existing.minLength;

  if (typeof existing.maxLength === 'number' && typeof imported.maxLength === 'number') {
    result.maxLength = Math.min(existing.maxLength, imported.maxLength);
  } else if (imported.maxLength !== undefined) result.maxLength = imported.maxLength;
  else if (existing.maxLength !== undefined) result.maxLength = existing.maxLength;

  // Numeric constraints: stricter = larger minimum, smaller maximum
  if (typeof existing.minimum === 'number' && typeof imported.minimum === 'number') {
    result.minimum = Math.max(existing.minimum, imported.minimum);
  } else if (imported.minimum !== undefined) result.minimum = imported.minimum;
  else if (existing.minimum !== undefined) result.minimum = existing.minimum;

  if (typeof existing.maximum === 'number' && typeof imported.maximum === 'number') {
    result.maximum = Math.min(existing.maximum, imported.maximum);
  } else if (imported.maximum !== undefined) result.maximum = imported.maximum;
  else if (existing.maximum !== undefined) result.maximum = existing.maximum;

  if (typeof existing.exclusiveMinimum === 'number' && typeof imported.exclusiveMinimum === 'number') {
    result.exclusiveMinimum = Math.max(existing.exclusiveMinimum, imported.exclusiveMinimum);
  } else if (imported.exclusiveMinimum !== undefined) result.exclusiveMinimum = imported.exclusiveMinimum;
  else if (existing.exclusiveMinimum !== undefined) result.exclusiveMinimum = existing.exclusiveMinimum;

  if (typeof existing.exclusiveMaximum === 'number' && typeof imported.exclusiveMaximum === 'number') {
    result.exclusiveMaximum = Math.min(existing.exclusiveMaximum, imported.exclusiveMaximum);
  } else if (imported.exclusiveMaximum !== undefined) result.exclusiveMaximum = imported.exclusiveMaximum;
  else if (existing.exclusiveMaximum !== undefined) result.exclusiveMaximum = existing.exclusiveMaximum;

  // Array constraints
  if (typeof existing.minItems === 'number' && typeof imported.minItems === 'number') {
    result.minItems = Math.max(existing.minItems, imported.minItems);
  } else if (imported.minItems !== undefined) result.minItems = imported.minItems;
  else if (existing.minItems !== undefined) result.minItems = existing.minItems;

  if (typeof existing.maxItems === 'number' && typeof imported.maxItems === 'number') {
    result.maxItems = Math.min(existing.maxItems, imported.maxItems);
  } else if (imported.maxItems !== undefined) result.maxItems = imported.maxItems;
  else if (existing.maxItems !== undefined) result.maxItems = existing.maxItems;

  // Pattern: keep imported for override; if additive we'd keep existing - handled by strategy
  if (imported.pattern !== undefined) result.pattern = imported.pattern;
  else if (existing.pattern !== undefined) result.pattern = existing.pattern;

  // Enum: merge by array strategy (#595)
  if (Array.isArray(existing.enum) && Array.isArray(imported.enum)) {
    result.enum = mergeArrayByStrategy(existing.enum, imported.enum, arrayStrategy);
  } else if (Array.isArray(imported.enum)) result.enum = imported.enum;
  else if (Array.isArray(existing.enum)) result.enum = existing.enum;

  // $ref: override uses imported
  if (imported.$ref !== undefined) result.$ref = imported.$ref;
  else if (existing.$ref !== undefined) result.$ref = existing.$ref;

  // items (array): deep merge if both are objects
  if (existing.items && imported.items && typeof existing.items === 'object' && typeof imported.items === 'object' && !Array.isArray(existing.items) && !Array.isArray(imported.items)) {
    result.items = mergeConstraints(existing.items, imported.items, options);
  } else if (imported.items !== undefined) result.items = imported.items;
  else if (existing.items !== undefined) result.items = existing.items;

  // #594 Deep merge: recursively merge nested object schema fields
  if (existing.properties && imported.properties && typeof existing.properties === 'object' && typeof imported.properties === 'object' && !Array.isArray(existing.properties) && !Array.isArray(imported.properties)) {
    const existingKeys = Object.keys(existing.properties);
    const importedKeys = Object.keys(imported.properties);
    const allKeys = new Set([...existingKeys, ...importedKeys]);
    result.properties = {} as any;
    for (const k of allKeys) {
      const e = existing.properties[k];
      const i = imported.properties[k];
      if (e != null && i != null && typeof e === 'object' && typeof i === 'object' && !Array.isArray(e) && !Array.isArray(i)) {
        result.properties[k] = mergeConstraints(e, i, options);
      } else if (i !== undefined) result.properties[k] = i;
      else result.properties[k] = e;
    }
  } else if (imported.properties !== undefined) result.properties = imported.properties;
  else if (existing.properties !== undefined) result.properties = existing.properties;

  if (existing.additionalProperties != null && imported.additionalProperties != null && typeof existing.additionalProperties === 'object' && typeof imported.additionalProperties === 'object' && !Array.isArray(existing.additionalProperties) && !Array.isArray(imported.additionalProperties)) {
    result.additionalProperties = mergeConstraints(existing.additionalProperties, imported.additionalProperties, options);
  } else if (imported.additionalProperties !== undefined) result.additionalProperties = imported.additionalProperties;
  else if (existing.additionalProperties !== undefined) result.additionalProperties = existing.additionalProperties;

  if (existing.patternProperties && imported.patternProperties && typeof existing.patternProperties === 'object' && typeof imported.patternProperties === 'object' && !Array.isArray(existing.patternProperties) && !Array.isArray(imported.patternProperties)) {
    const patternKeys = new Set([...Object.keys(existing.patternProperties), ...Object.keys(imported.patternProperties)]);
    result.patternProperties = {} as any;
    for (const k of patternKeys) {
      const e = (existing.patternProperties as any)[k];
      const i = (imported.patternProperties as any)[k];
      if (e != null && i != null && typeof e === 'object' && typeof i === 'object' && !Array.isArray(e) && !Array.isArray(i)) {
        result.patternProperties[k] = mergeConstraints(e, i, options);
      } else if (i !== undefined) result.patternProperties[k] = i;
      else result.patternProperties[k] = e;
    }
  } else if (imported.patternProperties !== undefined) result.patternProperties = imported.patternProperties;
  else if (existing.patternProperties !== undefined) result.patternProperties = existing.patternProperties;

  // required: merge by array strategy (#595)
  if (Array.isArray(existing.required) && Array.isArray(imported.required)) {
    result.required = mergeArrayByStrategy(existing.required, imported.required, arrayStrategy);
  } else if (imported.required !== undefined) result.required = imported.required;
  else if (existing.required !== undefined) result.required = existing.required;

  // description / title: prefer imported when overriding
  if (imported.description !== undefined) result.description = imported.description;
  else if (existing.description !== undefined) result.description = existing.description;
  if (imported.title !== undefined) result.title = imported.title;
  else if (existing.title !== undefined) result.title = existing.title;

  return result;
}

/**
 * Resolve effective merge strategy for a property (#593). Uses per-property override when present.
 */
function getPropertyStrategy(
  schemaKey: string | undefined,
  propertyPath: string,
  defaultStrategy: MergeStrategy,
  options: MergeOptions | undefined
): MergeStrategy {
  const perProp = options?.propertyMergeStrategies?.[schemaKey ?? ''];
  if (perProp && propertyPath in perProp) return perProp[propertyPath];
  return defaultStrategy;
}

/**
 * Merge two NormalizedProperty lists at one level.
 * - additive: existing first, then imported properties whose name is not in existing. Same name → keep existing.
 * - override: by name, imported wins; for same name merge constraints. Then add existing names not in imported.
 * #593: When options.propertyMergeStrategies is set, each property uses its per-property strategy (keyed by path).
 */
function mergePropertyLists(
  existingList: NormalizedProperty[],
  importedList: NormalizedProperty[],
  strategy: MergeStrategy,
  options?: MergeOptions,
  parentPath?: string
): NormalizedProperty[] {
  const byNameExisting = new Map<string, NormalizedProperty>();
  for (const p of existingList) byNameExisting.set(p.name, p);
  const byNameImported = new Map<string, NormalizedProperty>();
  for (const p of importedList) byNameImported.set(p.name, p);

  const allNames = new Set([...byNameExisting.keys(), ...byNameImported.keys()]);
  const result: NormalizedProperty[] = [];
  const schemaKey = options?.schemaKey;

  // Preserve order: existing first, then imported-only (additive order); when override, we still build by iterating names and push in stable order (existing order for existing names, then imported-only)
  const existingOrder = existingList.map((p) => p.name);
  const importedOnly = importedList.filter((p) => !byNameExisting.has(p.name)).map((p) => p.name);
  const orderedNames = [...existingOrder];
  for (const n of importedOnly) if (!orderedNames.includes(n)) orderedNames.push(n);

  for (const name of orderedNames) {
    const path = parentPath ? `${parentPath}.${name}` : name;
    const effectiveStrategy = getPropertyStrategy(schemaKey, path, strategy, options);
    const existingProp = byNameExisting.get(name);
    const importedProp = byNameImported.get(name);

    if (effectiveStrategy === 'additive') {
      if (existingProp) {
        // #594 Deep merge: recursively merge children when either side has them (treat missing as empty).
        let mergedChildren: NormalizedProperty[] | undefined;
        if (importedProp?.children?.length && existingProp.children?.length) {
          mergedChildren = mergePropertyLists(existingProp.children, importedProp.children, strategy, options, path);
        } else if (importedProp?.children?.length) {
          mergedChildren = mergePropertyLists([], importedProp.children, strategy, options, path);
        } else if (existingProp.children?.length) {
          mergedChildren = existingProp.children;
        }
        result.push(mergedChildren !== undefined ? { ...existingProp, children: mergedChildren } : existingProp);
      } else if (importedProp) {
        result.push(importedProp);
      }
      continue;
    }

    // override for this property
    if (importedProp) {
      if (existingProp) {
        const mergedData = mergeConstraints(existingProp.data, importedProp.data, options);
        const hasChildren = (existingProp.children?.length ?? 0) > 0 || (importedProp.children?.length ?? 0) > 0;
        const mergedChildren: NormalizedProperty[] | undefined = hasChildren
          ? mergePropertyLists(existingProp.children || [], importedProp.children || [], strategy, options, path)
          : undefined;
        result.push({
          name: importedProp.name,
          data: mergedData,
          description: importedProp.description ?? existingProp.description,
          children: mergedChildren?.length ? mergedChildren : undefined,
        });
      } else {
        result.push(importedProp);
      }
    } else if (existingProp) {
      result.push(existingProp);
    }
  }

  return result;
}

/**
 * Intelligently merge an existing class with an imported one (#588).
 * - additive: add new properties from imported, keep all existing; class metadata from imported (name, description) can be kept or overridden by imported - we keep existing name/description and add only new properties.
 * - override: imported wins for metadata; properties merged by name with constraint merge for same name.
 * #593: Optional options.propertyMergeStrategies for per-property strategy.
 */
export function mergeClasses(
  existing: NormalizedClass,
  imported: NormalizedClass,
  strategy: MergeStrategy,
  options?: MergeOptions
): NormalizedClass {
  const properties = mergePropertyLists(existing.properties || [], imported.properties || [], strategy, options);

  if (strategy === 'additive') {
    return {
      name: existing.name,
      originalSchemaKey: imported.originalSchemaKey ?? existing.originalSchemaKey,
      description: existing.description ?? imported.description,
      schema: existing.schema ?? imported.schema ?? { type: 'object' },
      properties,
    };
  }

  return {
    name: imported.name,
    originalSchemaKey: imported.originalSchemaKey ?? existing.originalSchemaKey,
    description: imported.description ?? existing.description,
    schema: imported.schema ?? existing.schema ?? { type: 'object' },
    properties,
  };
}
