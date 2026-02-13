/**
 * Intelligent merge of schema properties and constraints (#588).
 * Supports additive merge (add new, keep existing) and override merge (imported wins; constraints merged strictly).
 */

import type { NormalizedClass, NormalizedProperty } from '../../../lib/importers';

export type MergeStrategy = 'additive' | 'override';

/**
 * Merge two JSON Schema constraint objects for the same property.
 * Takes the "stricter" constraint where applicable so the merged schema is valid for both inputs.
 */
function mergeConstraints(existing: any, imported: any): any {
  if (!existing || typeof existing !== 'object') return imported ?? {};
  if (!imported || typeof imported !== 'object') return existing;

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

  // Enum: intersection so value is valid in both (if both present)
  if (Array.isArray(existing.enum) && Array.isArray(imported.enum)) {
    const set = new Set(imported.enum);
    result.enum = existing.enum.filter((v: any) => set.has(v));
    if (result.enum.length === 0) result.enum = imported.enum;
  } else if (Array.isArray(imported.enum)) result.enum = imported.enum;
  else if (Array.isArray(existing.enum)) result.enum = existing.enum;

  // $ref: override uses imported
  if (imported.$ref !== undefined) result.$ref = imported.$ref;
  else if (existing.$ref !== undefined) result.$ref = existing.$ref;

  // items (array): deep merge if both are objects
  if (existing.items && imported.items && typeof existing.items === 'object' && typeof imported.items === 'object' && !Array.isArray(existing.items) && !Array.isArray(imported.items)) {
    result.items = mergeConstraints(existing.items, imported.items);
  } else if (imported.items !== undefined) result.items = imported.items;
  else if (existing.items !== undefined) result.items = existing.items;

  // required: for override use imported; merged schema typically keeps both required sets
  if (imported.required !== undefined) result.required = imported.required;
  else if (existing.required !== undefined) result.required = existing.required;

  // description / title: prefer imported when overriding
  if (imported.description !== undefined) result.description = imported.description;
  else if (existing.description !== undefined) result.description = existing.description;
  if (imported.title !== undefined) result.title = imported.title;
  else if (existing.title !== undefined) result.title = existing.title;

  return result;
}

/**
 * Merge two NormalizedProperty lists at one level.
 * - additive: existing first, then imported properties whose name is not in existing. Same name → keep existing.
 * - override: by name, imported wins; for same name merge constraints. Then add existing names not in imported.
 */
function mergePropertyLists(
  existingList: NormalizedProperty[],
  importedList: NormalizedProperty[],
  strategy: MergeStrategy
): NormalizedProperty[] {
  const byNameExisting = new Map<string, NormalizedProperty>();
  for (const p of existingList) byNameExisting.set(p.name, p);
  const byNameImported = new Map<string, NormalizedProperty>();
  for (const p of importedList) byNameImported.set(p.name, p);

  const result: NormalizedProperty[] = [];
  const seen = new Set<string>();

  if (strategy === 'additive') {
    // Add all existing first
    for (const p of existingList) {
      seen.add(p.name);
      result.push(p);
    }
    // Add imported only if name not present
    for (const p of importedList) {
      if (seen.has(p.name)) continue;
      seen.add(p.name);
      result.push(p);
    }
    return result;
  }

  // override: for each name, take imported if present (with constraint merge), else existing
  for (const [name, importedProp] of byNameImported) {
    const existingProp = byNameExisting.get(name);
    if (existingProp) {
      const mergedData = mergeConstraints(existingProp.data, importedProp.data);
      const mergedChildren =
        (existingProp.children?.length || importedProp.children?.length) &&
        mergePropertyLists(existingProp.children || [], importedProp.children || [], strategy);
      result.push({
        name: importedProp.name,
        data: mergedData,
        description: importedProp.description ?? existingProp.description,
        children: mergedChildren?.length ? mergedChildren : undefined,
      });
    } else {
      result.push(importedProp);
    }
    seen.add(name);
  }
  for (const [name, existingProp] of byNameExisting) {
    if (seen.has(name)) continue;
    result.push(existingProp);
  }
  return result;
}

/**
 * Intelligently merge an existing class with an imported one (#588).
 * - additive: add new properties from imported, keep all existing; class metadata from imported (name, description) can be kept or overridden by imported - we keep existing name/description and add only new properties.
 * - override: imported wins for metadata; properties merged by name with constraint merge for same name.
 */
export function mergeClasses(
  existing: NormalizedClass,
  imported: NormalizedClass,
  strategy: MergeStrategy
): NormalizedClass {
  const properties = mergePropertyLists(existing.properties || [], imported.properties || [], strategy);

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
