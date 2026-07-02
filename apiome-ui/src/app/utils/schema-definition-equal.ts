/**
 * Compare two JSON/OpenAPI schema definitions for semantic equality (#582).
 * Used to detect "same name, different definition" during import:
 * only report duplicate_schema when the existing class has a different definition.
 */

const VOLATILE_KEYS = new Set(['$id', '$schema']);

/**
 * Recursively normalize an object for comparison: sort keys and strip volatile fields.
 * Keys starting with "x-" are stripped so extension differences don't cause false conflicts.
 */
function normalizeForCompare(value: unknown): unknown {
  if (value === null || value === undefined) return value;
  if (typeof value !== 'object') return value;
  if (Array.isArray(value)) return value.map(normalizeForCompare);

  const obj = value as Record<string, unknown>;
  const sorted: Record<string, unknown> = {};
  const keys = Object.keys(obj)
    .filter((k) => !VOLATILE_KEYS.has(k) && !k.startsWith('x-'))
    .sort();

  for (const k of keys) {
    sorted[k] = normalizeForCompare(obj[k]);
  }
  return sorted;
}

/**
 * Returns true if the two schema definitions are considered equal for duplicate detection.
 * Used when an imported schema has the same name as an existing class: if definitions
 * are equal, we do not report a conflict (same name, same definition).
 */
export function schemasDefinitionEqual(a: unknown, b: unknown): boolean {
  const na = normalizeForCompare(a);
  const nb = normalizeForCompare(b);
  return JSON.stringify(na) === JSON.stringify(nb);
}

/**
 * Returns true if the imported schema should be reported as a duplicate (same name, different definition).
 * Used by ClassImportDialog to set exists on each schema (#582).
 * - Name not in existing list → not a duplicate.
 * - Name in list but no existing definitions to compare → duplicate (conservative).
 * - Name in list, same definition → not a duplicate.
 * - Name in list, different definition → duplicate.
 */
export function isDuplicateSchema(
  importedName: string,
  importedSchema: unknown,
  existingClassNames: string[],
  existingClassSchemas?: Record<string, any>
): boolean {
  const existingNamesSet = new Set(existingClassNames.map((n) => n.toLowerCase()));
  const nameExists = existingNamesSet.has(importedName.toLowerCase());
  if (!nameExists) return false;
  const existingSchema = existingClassSchemas?.[importedName.toLowerCase()];
  return existingSchema == null || !schemasDefinitionEqual(importedSchema, existingSchema);
}
