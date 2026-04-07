/**
 * Property-level diff between existing and imported JSON Schema objects (#298).
 * Uses the same direct-property extraction as import conflict detection.
 */

import { schemasDefinitionEqual } from './schema-definition-equal';
import { extractDirectProperties } from './property-conflict-detection';

export type SchemaPropertyDiffStatus = 'unchanged' | 'added' | 'removed' | 'modified';

export interface SchemaPropertyDiffRow {
  name: string;
  status: SchemaPropertyDiffStatus;
  existing?: unknown;
  imported?: unknown;
}

export interface SchemaPropertyDiffResult {
  rows: SchemaPropertyDiffRow[];
  addedCount: number;
  modifiedCount: number;
  removedCount: number;
}

/**
 * Compare flattened direct properties on both schemas.
 */
export function computeSchemaPropertyDiff(
  existingSchema: unknown,
  importedSchema: unknown
): SchemaPropertyDiffResult {
  const ex = extractDirectProperties(existingSchema);
  const im = extractDirectProperties(importedSchema);
  const allKeys = new Set([...Object.keys(ex), ...Object.keys(im)]);
  const sortedKeys = [...allKeys].sort((a, b) => a.localeCompare(b));
  const rows: SchemaPropertyDiffRow[] = [];
  let addedCount = 0;
  let modifiedCount = 0;
  let removedCount = 0;

  for (const name of sortedKeys) {
    const e = ex[name];
    const i = im[name];
    if (e === undefined && i !== undefined) {
      rows.push({ name, status: 'added', imported: i });
      addedCount += 1;
    } else if (e !== undefined && i === undefined) {
      rows.push({ name, status: 'removed', existing: e });
      removedCount += 1;
    } else if (e !== undefined && i !== undefined) {
      if (schemasDefinitionEqual(e, i)) {
        rows.push({ name, status: 'unchanged', existing: e, imported: i });
      } else {
        rows.push({ name, status: 'modified', existing: e, imported: i });
        modifiedCount += 1;
      }
    }
  }

  return { rows, addedCount, modifiedCount, removedCount };
}

export function schemaSnippet(value: unknown, maxLen = 720): string {
  if (value === undefined) return '';
  try {
    const s = JSON.stringify(value, null, 2);
    if (s.length <= maxLen) return s;
    return `${s.slice(0, maxLen)}\n…`;
  } catch {
    return String(value);
  }
}
